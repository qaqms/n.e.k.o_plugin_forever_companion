"""启动时 PluginStore 通电时序的回归测试（「重启后模拟开关复位」修复）。

复现的生产故障：宿主构造插件实例那一刻 effective config 尚未就位，SDK 把
PluginStore 建成 enabled=False；disabled 态下 get 静默返回 default、set 静默丢弃
（宿主 storage/store.py 的 `if not self.enabled` 早退）。而 startup() 原先第一行就
是 _load_state()（全部持久状态都在这里读），于是每次重启都"读到空"：总开关退回
[tide].enabled=false、锚点重新随机，且 shutdown 会把这份幻影状态整体回写，覆盖掉
上一次真实保存的开关/锚点/三本日记/相处统计。

本文件用 _GatedStore 复刻宿主的 enabled 门控，锁死两件事：
1. _load_state 之前必须先把 store 唤醒并读到真实值（开关与锚点重启不丢）；
2. 唤醒失败的那次启动标记为"载入不可信"，此后即便 store 中途通电，
   shutdown 也不得把幻影状态覆写回盘。

运行方式（插件目录内）：uv run python -m pytest tests -q
"""

import asyncio
import time


def run(coro):
    return asyncio.run(coro)


class _GatedStore:
    """复刻宿主 PluginStore 的 enabled 门控：未通电时读写一律静默空转。

    ok_cls 必须是插件 isinstance 用的那个 Ok（tests 里即 tm.Ok），否则载入路径
    会把每次读都当成"类型不对"而忽略——那就测不到门控本身了。
    never_wakes=True 模拟"整场启动都没通电"的病态窗口（用来验证覆写防线）。
    """

    def __init__(self, ok_cls, initial=None, *, enabled=True, never_wakes=False):
        self._ok = ok_cls
        self.data = dict(initial or {})
        self.enabled = enabled
        self._never_wakes = never_wakes
        self.set_calls = 0

    def wake(self):
        if not self._never_wakes:
            self.enabled = True

    async def get(self, key, default=None):
        if not self.enabled:
            return self._ok(None)
        return self._ok(self.data.get(key, default))

    async def set(self, key, value):
        self.set_calls += 1
        if not self.enabled:
            return self._ok(None)
        self.data[key] = value
        return self._ok(None)

    async def delete(self, key):
        self.set_calls += 1
        if not self.enabled:
            return self._ok(False)
        return self._ok(self.data.pop(key, None) is not None)


class _UngatedStore(_GatedStore):
    """完全没有 enabled 属性的 store（conftest.FakeStore 那一类实现）。

    用来验证 _store_ready 的 getattr(..., True) 回退：属性缺失时按"可用"处理，
    既不阻塞载入，也不会因为探测逻辑而误判成不可信。
    """

    def __init__(self, ok_cls, initial=None, **_ignored):
        super().__init__(ok_cls, initial)
        del self.enabled

    def wake(self):
        """覆盖父类：这类 store 没有门控，通电概念不成立（别把 enabled 属性造回来）。"""

    async def get(self, key, default=None):
        return self._ok(self.data.get(key, default))

    async def set(self, key, value):
        self.set_calls += 1
        self.data[key] = value
        return self._ok(None)


class _WakingConfig:
    """代理 config：dump() 先给 store 通电，复刻宿主"读配置→刷新 runtime config"链。

    这正是修复所依赖的机制——_ensure_store_ready 靠一次配置读取让宿主把
    store.enabled 翻上来。never_wakes 的 store 上 wake() 是空操作。
    """

    def __init__(self, inner, store):
        self._inner = inner
        self._store = store

    async def dump(self, timeout=5.0):
        self._store.wake()
        return await self._inner.dump(timeout=timeout)

    def __getattr__(self, name):
        return getattr(self._inner, name)


_PERSISTED_CYCLE = {
    "enabled": True,
    "anchor_date": "2026-08-01",
    "advance_days": 3,
    "phase_seen": "luteal",
    "params": {},
}


def _boot(tm, boot_factory, *, enabled=True, never_wakes=False, store_cls=None):
    """造一个"盘上已有开启状态"的插件：store 按门控注入，读配置即尝试通电。

    配置刻意与生产一致——[tide].enabled=false 且锚点为空、且与盘上分片取值不同：
    这样"从配置读到"与"从 store 读到"可以区分开，缺少修复时 _enabled 会退回
    fail-closed 的 false、锚点会被重新随机，测试就会红。
    """
    store = (store_cls or _GatedStore)(
        tm.Ok,
        {
            "lanlan_index": ["灵"],
            "cycle@灵": dict(_PERSISTED_CYCLE),
            "settings": {},
        },
        enabled=enabled,
        never_wakes=never_wakes,
    )
    p = boot_factory(
        tide_extra={"enabled": False, "anchor_date": ""},
        store=store,
        current_lanlan="灵",
    )
    p.config = _WakingConfig(p.config, store)
    return p, store


def test_startup_wakes_store_before_loading(tm, boot_factory):
    """store 建出来时是 disabled：startup 必须先唤醒再载入，开关与锚点原样回来。"""
    p, store = _boot(tm, boot_factory, enabled=False)

    result = run(p.startup())

    # 先断言用户可观察的结果（修复前这两条就会红），再断言内部标志
    shard = p._get_shard("灵")
    assert p._enabled(shard) is True, "重启后模拟开关必须保持开启，不能退回 fail-closed"
    assert shard.cycle["anchor_date"] == "2026-08-01", "锚点必须读回，不能重新随机"
    assert shard.cycle["advance_days"] == 3
    assert result.value["enabled"] is True
    assert p._state_trusted is True
    assert store.enabled is True, "startup 应通过一次配置读取把 store 唤醒"


def test_untrusted_load_never_overwrites_persisted_state(tm, boot_factory):
    """整场启动都没通电 → 载入不可信；即便 store 中途才醒，shutdown 也不得覆写盘上数据。"""
    p, store = _boot(tm, boot_factory, enabled=False, never_wakes=True)

    run(p.startup())

    store.enabled = True  # 会话中后期宿主才把配置推下来（正是生产里写能落盘的时段）
    before = dict(store.data["cycle@灵"])
    sets_before = store.set_calls
    result = run(p.shutdown())

    # 先断言可观察后果：修复前 startup 读空 + shutdown 整体回写，会把盘上的
    # enabled=True / 锚点覆写成幻影（enabled 缺失 + 重新随机的锚点）
    assert store.data["cycle@灵"] == before, "shutdown 把幻影状态覆写回了盘"
    assert store.set_calls == sets_before, "不可信载入的 shutdown 不应产生任何写入"
    assert result.value.get("saved") is False
    assert p._state_trusted is False, "读不到真实状态时必须标记为不可信"


def test_healthy_store_still_saves_on_shutdown(tm, boot_factory):
    """正常路径不受防线影响：通电的 store 照常回写，且不会被误判为不可信。"""
    p, store = _boot(tm, boot_factory)

    run(p.startup())
    assert p._state_trusted is True

    run(p.toggle())  # 关闭模拟
    assert p._enabled(p._get_shard("灵")) is False
    result = run(p.shutdown())

    assert result.value.get("saved") is not False
    assert store.data["cycle@灵"]["enabled"] is False, "可信会话的改动必须落盘"
    assert store.data["cycle@灵"]["anchor_date"] == "2026-08-01"


def test_probe_fails_fast_when_host_unreachable(tm, boot_factory):
    """读配置本身就失败：立刻降级，不做多轮重试（否则会把宿主拉起等到超时）。"""
    p, store = _boot(tm, boot_factory, enabled=False, never_wakes=True)

    async def boom(timeout=5.0):
        raise TimeoutError("host unreachable")

    p.config.dump = boom
    started = time.monotonic()
    assert run(p._ensure_store_ready()) is False
    # 一次都不睡：远小于"重试次数 × 间隔"的下界
    assert time.monotonic() - started < 0.1
    assert store.set_calls == 0


def test_ready_probe_treats_missing_enabled_attr_as_ready(tm, boot_factory):
    """无 enabled 属性的 store 实现（含 FakeStore）按可用处理，不阻塞载入。"""
    p, store = _boot(tm, boot_factory, store_cls=_UngatedStore)
    assert not hasattr(store, "enabled")

    assert run(p._ensure_store_ready()) is True
    run(p.startup())
    assert p._state_trusted is True
    assert p._enabled(p._get_shard("灵")) is True
