"""跨线程并发：宿主让入口/工具（命令循环）、tide_tick、diary_write_tick 各跑在自己的线程和
事件循环上（每个定时器一条线程、每趟 asyncio.run）。这里用真线程 + 各自的 asyncio.run 复现。

覆盖：主动搭话水位的串行化与停止时归还、分片首次创建/载入、成文在飞登记、时光日记写锁排队、
数据闸的等待与写者优先。
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def run(coro):
    return asyncio.run(coro)


class _SlowHost:
    """宿主 HTTP 桩：读开关要花 delay 秒，且返回的是"读完那一刻"的值（真实请求就是这样）。"""

    def __init__(self, master=True, delay=0.1, current="YUI"):
        self.master = master
        self.delay = delay
        self.current = current
        self.posts: list[bool] = []

    async def __call__(self, method, path, body=None, headers=None, timeout=4.0):
        if path == "/api/characters/current_catgirl":
            return {"current_catgirl": self.current}
        if path == "/api/characters":
            return {"猫娘": {self.current: {}}}
        if path == "/api/proactive/settings" and method == "GET":
            await asyncio.sleep(self.delay)
            return {"settings": {"proactiveChatEnabled": self.master}}
        if path == "/api/proactive/settings" and method == "POST":
            self.master = bool(body.get("proactiveChatEnabled"))
            self.posts.append(self.master)
            return {"success": True}
        return None


def _activate(p, lanlan="YUI", action="ebb_tide"):
    shard = run(p._ensure_shard(lanlan))
    shard.mood.action = action
    shard.mood.started_at = time.time()
    shard.mood.expires_at = time.time() + 3600
    return shard


# ---------- 主动搭话水位 ----------


def test_concurrent_pause_from_two_threads_keeps_original_master(plugin_factory_full) -> None:
    """后读开关的一方曾读到前一方刚写的 False，把它记成"用户原本就关着"，解除后再不打开。"""
    host = _SlowHost(master=True, delay=0.1)
    p = plugin_factory_full(http=host)
    _activate(p)

    def late_sync():
        time.sleep(0.05)  # 在第一路读开关的半途进来
        return run(p._maybe_sync_proactive_pause())

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, p._maybe_sync_proactive_pause())
        second = pool.submit(late_sync)
        first.result(timeout=5)
        second.result(timeout=5)

    assert p._proactive_state["prev"] == {"master": True}
    assert host.master is False
    # 解除后必须还原为开
    p._get_shard("YUI").mood.action = ""
    run(p._maybe_sync_proactive_pause())
    assert host.master is True
    assert p._proactive_state["prev"] is None


def test_reassert_cannot_reclose_after_resume(plugin_factory_full) -> None:
    """加固与恢复同锁：恢复刚写回 true、加固读到 true 又关掉，水位却已清空的死局。"""
    host = _SlowHost(master=False, delay=0.1)
    p = plugin_factory_full(http=host)
    p._proactive_state = {"prev": {"master": True}, "paused_by": []}  # 情绪刚解除，还在暂停中

    def late_resume():
        time.sleep(0.05)
        return run(p._maybe_sync_proactive_pause())

    with ThreadPoolExecutor(max_workers=2) as pool:
        reassert = pool.submit(run, p._reassert_proactive_off())
        resume = pool.submit(late_resume)
        reassert.result(timeout=5)
        resume.result(timeout=5)

    assert host.master is True
    assert p._proactive_state["prev"] is None


def test_shutdown_restores_paused_switch_and_tick_cannot_repause(plugin_factory_full) -> None:
    host = _SlowHost(master=True, delay=0)
    p = plugin_factory_full(http=host)
    _activate(p)
    run(p._maybe_sync_proactive_pause())
    assert host.master is False

    run(p.shutdown())
    assert host.master is True, "停用/卸载后再没人会替用户打开"
    assert p._proactive_state["prev"] is None
    assert p.store.data["proactive_state"]["prev"] is None
    # 宿主不等定时器线程退出：正在跑的一趟不能再把它关掉
    run(p.tick())
    run(p._maybe_sync_proactive_pause())
    assert host.master is True


def test_shutdown_leaves_switch_off_when_user_had_it_off(plugin_factory_full) -> None:
    host = _SlowHost(master=False, delay=0)
    p = plugin_factory_full(http=host)
    _activate(p)
    run(p._maybe_sync_proactive_pause())
    assert p._proactive_state["prev"] == {"master": False}
    run(p.shutdown())
    assert host.master is False
    assert True not in host.posts


def test_shutdown_restores_switch_even_while_backup_holds_gate(plugin_factory_full) -> None:
    host = _SlowHost(master=True, delay=0)
    p = plugin_factory_full(http=host)
    _activate(p)
    run(p._maybe_sync_proactive_pause())
    assert p._data_gate.enter(exclusive=True)
    try:
        res = run(p.shutdown())
    finally:
        p._data_gate.leave(exclusive=True)
    assert str(res.error) == "backup_busy"  # 数据照旧不在独占期间整体回写
    assert host.master is True


def test_shutdown_keeps_watermark_when_restore_fails(plugin_factory_full) -> None:
    host = _SlowHost(master=True, delay=0)
    p = plugin_factory_full(http=host)
    _activate(p)
    run(p._maybe_sync_proactive_pause())

    async def unreachable(*a, **k):
        return None

    p._proactive_http = unreachable
    run(p.shutdown())
    assert p._proactive_state["prev"] == {"master": True}, "没还上就留着水位，下次启动对账"


# ---------- 分片与写入 ----------


def test_concurrent_first_load_yields_one_shard(plugin_factory_full) -> None:
    p = plugin_factory_full(http=_SlowHost())
    reads: list[str] = []
    original = p.store.get

    async def slow_get(key):
        if key == "cycle@新角色":
            reads.append(key)
            await asyncio.sleep(0.05)
        return await original(key)

    p.store.get = slow_get
    barrier = threading.Barrier(2)

    def ensure():
        barrier.wait()
        return run(p._ensure_shard("新角色"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = (f.result(timeout=5) for f in [pool.submit(ensure), pool.submit(ensure)])
    assert a is b is p._shards["新角色"]
    assert reads == ["cycle@新角色"], "只载入一次：第二路等锁后复查到已载入"


def test_writer_claim_is_atomic_across_threads(plugin_factory_full) -> None:
    p = plugin_factory_full(http=_SlowHost())
    barrier = threading.Barrier(8)

    def claim():
        barrier.wait()
        return p._claim_writer(p._review_writing, "YUI")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [f.result(timeout=5) for f in [pool.submit(claim) for _ in range(8)]]
    assert results.count(True) == 1
    assert p._review_writing == {"YUI"}


def test_diary_update_waits_for_inflight_write(plugin_factory_full, monkeypatch) -> None:
    """她写手记恰好撞上一次碎片落盘：过去直接以 backup_busy 丢掉这条手记。"""
    from forever_companion.mixins.shards import ShardsMixin

    monkeypatch.setattr(ShardsMixin, "_DIARY_LOCK_WAIT_SEC", 3.0)
    p = plugin_factory_full(http=_SlowHost())
    shard = run(p._ensure_shard("YUI"))
    entered, release = threading.Event(), threading.Event()
    original = p.store.set

    async def slow_set(key, value):
        if key == "diary@YUI" and not release.is_set():
            entered.set()
            await asyncio.to_thread(release.wait, 3)
        return await original(key, value)

    p.store.set = slow_set
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(run, p._update_shard_diary("YUI", shard, lambda d: d.append({"ts": "a"})))
        assert entered.wait(2)
        threading.Timer(0.1, release.set).start()
        second = run(p._update_shard_diary("YUI", shard, lambda d: d.append({"ts": "b"})))
        first.result(timeout=5)
    assert not hasattr(second, "error")
    assert [item["ts"] for item in p.store.data["diary@YUI"]] == ["a", "b"]


# ---------- 数据闸 ----------


def test_gate_exclusive_waits_for_shared_and_blocks_newcomers() -> None:
    from forever_companion.services.data_guard import DataGate

    gate = DataGate()
    assert gate.enter()  # 一次在飞的面板轮询/定时器
    threading.Timer(0.15, gate.leave).start()

    async def scenario():
        waiter = asyncio.ensure_future(gate.acquire(exclusive=True, timeout=2.0))
        await asyncio.sleep(0.05)
        assert gate.waiting == 1
        assert not gate.enter(), "独占方排队时不再放新的共享方进门"
        assert await waiter
        assert gate.exclusive
        gate.leave(exclusive=True)
        assert gate.enter()

    run(scenario())
    assert gate.waiting == 0


def test_gate_exclusive_times_out_when_shared_never_leaves() -> None:
    from forever_companion.services.data_guard import DataGate

    gate = DataGate()
    assert gate.enter()
    assert run(gate.acquire(exclusive=True, timeout=0.1)) is False
    assert gate.waiting == 0 and not gate.exclusive
    assert gate.enter(), "超时退出后不能残留写者优先"


def test_backup_export_waits_out_a_short_shared_call(plugin_factory_full, monkeypatch) -> None:
    from forever_companion.services.data_guard import DataGate

    monkeypatch.setattr(DataGate, "EXCLUSIVE_WAIT_SEC", 3.0)
    p = plugin_factory_full(http=_SlowHost())
    assert p._data_gate.enter()
    threading.Timer(0.15, p._data_gate.leave).start()
    res = run(p.data_backup(op="export"))
    assert str(getattr(res, "error", "")) != "backup_busy"
    assert p._data_gate.active == 0 and not p._data_gate.exclusive
