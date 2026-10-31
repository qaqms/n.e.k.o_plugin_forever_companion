"""读取侧配置容错 / 监督锁不阻塞 / 本机 HTTP 绕过系统代理。"""

import asyncio
import http.server
import threading
import time

import pytest
from forever_companion.core.state import _cfg_int


def run(coro):
    return asyncio.run(coro)


# ---------- _cfg_int ----------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 3), ("", 3), ("3次", 3), ("abc", 3), (True, 3), ([1], 3), ("7", 7), (7.9, 7), (0, 1), (999, 50)],
)
def test_cfg_int_falls_back_and_clamps(raw, expected) -> None:
    assert _cfg_int({"k": raw}, "k", 3, lo=1, hi=50) == expected


def test_cfg_int_tolerates_non_dict_section() -> None:
    assert _cfg_int(None, "k", 5) == 5


# ---------- 手改配置写坏值：tick 链路不再抛异常 ----------


def test_bad_inject_interval_n_does_not_raise(plugin_factory) -> None:
    p = plugin_factory({"inject_mode": "interval_n", "inject_interval_n": "3次"})
    # 坏值回落默认 3：前两条不注入，第三条注入
    assert run(p._handle_new_user_message(1.0, "你好")) is False
    assert run(p._handle_new_user_message(2.0, "你好")) is False
    assert run(p._handle_new_user_message(3.0, "你好")) is True


def test_inject_interval_matches_snapshot_when_above_limit(plugin_factory) -> None:
    p = plugin_factory({"inject_mode": "interval_n", "inject_interval_n": 999})
    shard = p._current_shard()
    interval = p._settings_snapshot()["inject_interval_n"]
    assert interval == 50
    for _ in range(interval - 1):
        assert p._should_inject(shard, "hello") is False
    assert p._should_inject(shard, "hello") is True


@pytest.mark.parametrize("auto_derive", [True, False])
def test_bad_cycle_config_survives_refresh_snapshot_and_tick(plugin_factory, auto_derive) -> None:
    p = plugin_factory(
        {
            "anchor_date": "",
            "auto_derive": auto_derive,
            "cycle_length": "28days",
            "period_length": [],
            "ovulation_day": True,
            "ovulation_window": float("inf"),
        }
    )
    snapshot = p._settings_snapshot()
    assert {key: snapshot[key] for key in (
        "cycle_length", "period_length", "ovulation_day", "ovulation_window",
    )} == {
        "cycle_length": 28,
        "period_length": 5,
        "ovulation_day": 14,
        "ovulation_window": 3,
    }
    assert p._current_phase_state() is not None
    assert run(p.tick()).value["injected"] is False


def test_bad_shard_cycle_params_fall_back_to_global_settings(plugin_factory) -> None:
    p = plugin_factory(
        {"auto_derive": False, "cycle_length": 32, "period_length": 4, "ovulation_day": 18, "ovulation_window": 2}
    )
    shard = p._current_shard()
    shard.cycle["params"] = {
        "cycle_length": "bad",
        "period_length": None,
        "ovulation_day": True,
        "ovulation_window": float("nan"),
    }
    assert p._effective_cycle_settings(shard) == {
        "cycle_length": 32,
        "period_length": 4,
        "ovulation_day": 18,
        "ovulation_window": 2,
    }
    assert p._current_phase_state(shard) is not None


def test_settings_snapshot_tolerates_bad_values(plugin_factory) -> None:
    p = plugin_factory(
        {"inject_interval_n": "abc"},
        {"default_action_minutes": "十分钟", "open_action_timeout_minutes": "x"},
    )
    snap = p._settings_snapshot()
    assert snap["inject_interval_n"] == 3
    assert snap["default_action_minutes"] == 10
    assert snap["open_action_timeout_minutes"] == 20


def test_open_action_timeout_zero_still_means_off(plugin_factory) -> None:
    p = plugin_factory(None, {"open_action_timeout_minutes": 0})
    assert p._settings_snapshot()["open_action_timeout_minutes"] == 0


@pytest.mark.parametrize(
    ("raw", "displayed", "age_minutes", "expired"),
    [
        (None, 20, 19, False),
        (None, 20, 20, True),
        (True, 20, 2, False),
        ("bad", 20, 21, True),
        (float("inf"), 20, 21, True),
        (float("nan"), 20, 21, True),
        (2000, 1440, 1500, True),
        (0, 0, 2000, False),
        (-1, 0, 2000, False),
    ],
)
def test_open_action_timeout_execution_matches_snapshot(
    plugin_factory, monkeypatch, raw, displayed, age_minutes, expired
) -> None:
    p = plugin_factory(None, {"open_action_timeout_minutes": raw})
    monkeypatch.setattr(time, "time", lambda: 2_000_000_000.0)
    shard = p._current_shard()
    shard.mood.action = "seek_harbor"
    shard.mood.started_at = time.time() - age_minutes * 60
    assert p._settings_snapshot()["open_action_timeout_minutes"] == displayed
    result = run(p._fallback_open_action_if_due(shard))
    assert result == ("seek_harbor" if expired else "")
    assert shard.mood.action == ("" if expired else "seek_harbor")


def test_infinite_timeout_does_not_interrupt_supervision(plugin_factory, monkeypatch) -> None:
    p = plugin_factory(None, {"open_action_timeout_minutes": float("inf")})
    shard = p._current_shard()
    shard.mood.action = "seek_harbor"
    shard.mood.started_at = time.time()
    sync_calls = []

    async def sync():
        sync_calls.append(True)

    monkeypatch.setattr(p, "_maybe_sync_proactive_pause", sync)
    run(p._supervise_once())
    assert sync_calls == [True]
    assert not p._supervise_lock.locked()


# ---------- 监督锁：被占用时立即跳过，不阻塞事件循环 ----------


def test_supervise_skips_immediately_when_lock_held(plugin_factory) -> None:
    p = plugin_factory()
    assert p._supervise_lock.acquire(blocking=False)
    try:
        started = time.monotonic()
        run(p._supervise_once())
        assert time.monotonic() - started < 1.0
    finally:
        p._supervise_lock.release()
    # 锁释放后照常可再次进入
    run(p._supervise_once())
    assert not p._supervise_lock.locked()


# ---------- 本机 HTTP：不受系统代理环境变量影响 ----------


class _JsonHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib 约定
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - 签名须与基类一致
        pass


def test_proactive_http_bypasses_system_proxy(plugin_factory, monkeypatch) -> None:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _JsonHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # 指向一个不存在的代理：默认 urlopen 会转发给它而失败
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
            monkeypatch.setenv(name, "http://127.0.0.1:9")
        for name in ("NO_PROXY", "no_proxy"):
            monkeypatch.delenv(name, raising=False)
        p = plugin_factory()
        p._proactive_api_base_cache = f"http://127.0.0.1:{server.server_address[1]}"
        # conftest 在实例上桩掉了 _proactive_http，这里直接调类上的真实实现
        payload = run(type(p)._proactive_http(p, "GET", "/api/tools"))
        assert payload == {"ok": True}
    finally:
        server.shutdown()
        server.server_close()
