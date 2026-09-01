"""相处统计（1.1.0）测试：纯逻辑（按天聚合/里程碑/热力图/月报/封卷/纪念日）
+ 主链路（喂入点/落盘/和好计数/入口/清零）。

依赖 tests/conftest.py 注入的宿主 SDK 桩与 ``tm`` / ``plugin_factory`` /
``plugin_factory_full`` fixture（不要 ``from conftest import ...``）。
"""

from __future__ import annotations

import asyncio

from forever_companion import stats as st


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 纯逻辑：stats.py —— 按天聚合
# ---------------------------------------------------------------------------

def test_record_turn_aggregates_per_day() -> None:
    stats = st.new_stats()
    stats = st.record_turn(stats, "2026-09-01", valence=0.5)
    stats = st.record_turn(stats, "2026-09-01", valence=-0.1)
    stats = st.record_turn(stats, "2026-09-02")
    day1 = stats["days"]["2026-09-01"]
    assert day1["turns"] == 2
    assert day1["v_n"] == 2
    assert abs(day1["v_sum"] - 0.4) < 1e-6
    assert stats["days"]["2026-09-02"]["turns"] == 1
    # first_seen 只写一次
    assert stats["first_seen"]
    # 返回新 dict（调用方赋值回 shard.stats），键集不共享底层引用
    grown = st.record_turn(stats, "2026-09-03")
    assert "2026-09-03" in grown["days"]
    assert grown["days"]["2026-09-01"]["turns"] == 2


def test_record_tone_and_mood_event_origins() -> None:
    stats = st.new_stats()
    stats = st.record_tone(stats, "2026-09-01", "happy")
    stats = st.record_tone(stats, "2026-09-01", "happy")
    stats = st.record_tone(stats, "2026-09-01", "sad")
    assert stats["days"]["2026-09-01"]["tone"] == {"happy": 2, "sad": 1}
    # 自主冷战计、命令演示不计
    stats = st.record_mood_event(stats, "2026-09-01", "ebb_tide", origin="self")
    stats = st.record_mood_event(stats, "2026-09-01", "ebb_tide", origin="user")
    stats = st.record_mood_event(stats, "2026-09-01", "spring_tide", origin="self")
    stats = st.record_mood_event(stats, "2026-09-01", "ripple", origin="self")
    day = stats["days"]["2026-09-01"]
    assert day["cold"] == 1  # user 演示不计
    assert day["warm"] == 1  # 满潮是开心时刻
    assert "ripple" not in (day.get("cold"), day.get("warm"))  # 涟漪两者都不算


def test_record_made_up_and_milestone() -> None:
    stats = st.new_stats()
    stats = st.record_made_up(stats, "2026-09-01")
    stats = st.record_made_up(stats, "2026-09-01")
    assert stats["days"]["2026-09-01"]["made_up"] == 2
    # 里程碑只记最早一次，不覆盖
    stats = st.record_milestone(stats, "first_diary")
    first = stats["milestones"]["first_diary"]
    stats = st.record_milestone(stats, "first_diary")
    assert stats["milestones"]["first_diary"] == first


def test_backfill_day_lights_up_without_overwriting() -> None:
    stats = st.new_stats()
    stats = st.backfill_day(stats, "2026-08-01")
    stats = st.backfill_day(stats, "2026-08-01")  # 幂等
    assert stats["days"]["2026-08-01"]["turns"] == 1
    assert stats["first_seen"]
    # 已有真实数据的天不被回填覆盖
    stats = st.record_turn(stats, "2026-08-02")
    stats = st.record_turn(stats, "2026-08-02")
    stats = st.backfill_day(stats, "2026-08-02")
    assert stats["days"]["2026-08-02"]["turns"] == 2


# ---------------------------------------------------------------------------
# 纯逻辑：派生视图
# ---------------------------------------------------------------------------

def _seed_stats():
    """三天连续 + 一天断档的种子数据。"""
    stats = st.new_stats()
    stats["first_seen"] = "2026-08-30T10:00:00+00:00"
    for day in ("2026-08-30", "2026-08-31", "2026-09-01"):
        stats = st.record_turn(stats, day)
        stats = st.record_turn(stats, day)
    stats = st.record_turn(stats, "2026-09-03")
    stats = st.record_tone(stats, "2026-09-01", "happy")
    return stats


def test_summary_and_streaks() -> None:
    stats = _seed_stats()
    summary = st.summary_payload(stats, "2026-09-03")
    assert summary["total_turns"] == 7
    assert summary["active_days"] == 4
    assert summary["longest_streak"] == 3
    # 今天（09-03）有聊天 → 当前连续 1
    assert summary["current_streak"] == 1
    # 昨天有聊今天没聊：当前连续从昨天延续
    summary2 = st.summary_payload(stats, "2026-09-02")
    assert summary2["current_streak"] == 3
    # 相伴天数 = 今天 − first_seen + 1
    assert summary["days_together"] == 5


def test_streaks_today_gap_tolerated() -> None:
    """深夜 00:01 不该把连续归零：今天没聊仍允许从昨天延续。"""
    stats = st.new_stats()
    stats["first_seen"] = "2026-09-01T10:00:00+00:00"
    stats = st.record_turn(stats, "2026-09-01")
    stats = st.record_turn(stats, "2026-09-02")
    _longest, current = st.streaks(stats, "2026-09-03")
    assert current == 2
    # 隔两天没聊才算断
    _longest2, current2 = st.streaks(stats, "2026-09-04")
    assert current2 == 0


def test_badges_payload_unlock_progression() -> None:
    stats = st.new_stats()
    stats["first_seen"] = "2026-09-01T10:00:00+00:00"
    badges = st.badges_payload(stats, "2026-09-07")  # 相伴第 7 天
    by_id = {b["id"]: b for b in badges}
    assert by_id["d7"]["unlocked"] is True
    assert by_id["d7"]["date"] == "2026-09-07"
    assert by_id["d30"]["unlocked"] is False
    assert by_id["first_diary"]["unlocked"] is False
    # 第一篇手记解锁
    stats = st.record_milestone(stats, "first_diary")
    badges = st.badges_payload(stats, "2026-09-07")
    by_id = {b["id"]: b for b in badges}
    assert by_id["first_diary"]["unlocked"] is True


def test_heatmap_payload_window_and_tone() -> None:
    stats = _seed_stats()
    heat = st.heatmap_payload(stats, "2026-09-03")
    # 窗口 = 最近 12 个月（含当月），末位是当月
    assert len(heat["months"]) == 12
    assert heat["months"][-1] == "2026-09"
    days = {d["date"]: d for d in heat["days"]}
    assert days["2026-08-30"]["turns"] == 2
    # 主导语气落在 09-01；今天（09-03）未过完不进热力图，明天才亮格
    assert days["2026-09-01"]["tone"] == "happy"
    assert "2026-09-03" not in days
    # 窗口起点之前的旧月份被裁掉
    heat_old = st.heatmap_payload(stats, "2026-09-03")
    earliest = heat_old["months"][0]
    assert all(d["date"] >= earliest for d in heat_old["days"])


def test_month_view_and_voice() -> None:
    stats = _seed_stats()
    stats = st.record_turn(stats, "2026-09-03")
    diary = [
        {"ts": "2026-09-01T12:00:00+00:00", "source": "self", "mood": "开心", "entry": "今天他陪了我很久。"},
        {"ts": "2026-09-02T12:00:00+00:00", "source": "self", "mood": "平静", "entry": "短"},
        {"ts": "2026-08-01T12:00:00+00:00", "source": "self", "mood": "旧", "entry": "上个月的长长长长长长长长长长记录"},
    ]
    month = st.month_view(stats, "2026-09", diary=diary)
    assert month["turns"] == 4  # 09-01×2 + 09-03×2
    assert month["active_days"] == 2
    assert month["busiest_day"] == "2026-09-01"
    assert month["sealed"] is False
    # 本月声音 = 当月最长手记
    assert month["voice"]["entry"] == "今天他陪了我很久。"


def test_seal_month_freezes_and_dedupes() -> None:
    stats = _seed_stats()
    # 封卷 8 月（返回新 dict，赋值回来）
    stats, months = st.seal_due_months(stats, "2026-09-01")
    assert "2026-08" in months
    frozen = stats["months"]["2026-08"]
    assert frozen["sealed"] is True
    assert frozen["turns"] == 4
    assert frozen["active_days"] == 2
    # 再跑一次幂等：不重复封卷
    stats2, months2 = st.seal_due_months(stats, "2026-09-02")
    assert months2 == []
    # 封卷后新增数据不影响历史月报（封卷值固定，当月即时视图才变化）
    grown = st.record_turn(stats, "2026-08-30")
    view = st.month_view(grown, "2026-08", diary=[])
    assert view["turns"] == 4
    assert view.get("sealed") is True


# ---------------------------------------------------------------------------
# 纯逻辑：纪念日
# ---------------------------------------------------------------------------

def test_anniversary_due_nodes_and_dedupe() -> None:
    stats = st.new_stats()
    stats["first_seen"] = "2026-08-02T10:00:00+00:00"
    # 09-01 = 相伴第 31 天，不是节点
    due, _ = st.anniversary_due(stats, "2026-09-01")
    assert due is False
    # 08-31 = 第 30 天 → 节点
    due, total = st.anniversary_due(stats, "2026-08-31")
    assert (due, total) == (True, 30)
    # 盖水位后同日不重复
    stats = st.mark_anniversary_pushed(stats, "2026-08-31")
    due, _ = st.anniversary_due(stats, "2026-08-31")
    assert due is False
    # 第二天恢复"未到节点"判定（非节点 total 恒 0）
    due, total = st.anniversary_due(stats, "2026-09-01")
    assert (due, total) == (False, 0)
    # 2027-08-01 = 第 365 天 → 节点
    due, total = st.anniversary_due(stats, "2027-08-01")
    assert (due, total) == (True, 365)


def test_next_anniversary() -> None:
    stats = st.new_stats()
    stats["first_seen"] = "2026-08-02T10:00:00+00:00"
    node, until = st.next_anniversary(stats, "2026-08-15")  # 第 14 天
    assert (node, until) == (30, 16)
    node, until = st.next_anniversary(stats, "2026-08-31")  # 第 30 天（当天）
    assert (node, until) == (30, 0)


# ---------------------------------------------------------------------------
# 主链路：埋点 / 落盘 / 入口
# ---------------------------------------------------------------------------

def test_handle_new_user_message_feeds_stats(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._get_shard("default")
    run(p._handle_new_user_message(1000.0, "你好", "default"))
    assert shard.stats.get("days")
    assert sum(b.get("turns", 0) for b in shard.stats["days"].values()) == 1
    # 落盘：stats@<角色> 已写入
    saved = run(p.store.get("stats@default"))
    assert saved.value.get("days")
    # 重复时间戳不重复计数
    run(p._handle_new_user_message(999.0, "旧消息", "default"))
    assert sum(b.get("turns", 0) for b in shard.stats["days"].values()) == 1


def test_mood_action_feeds_stats_and_made_up(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._get_shard("default")
    # 自主冷战 → cold +1；命令演示 → 不计
    run(p._apply_mood_action(action="ebb_tide", minutes=10, reason="气", timed=True, lanlan="default"))
    run(p._apply_mood_action(action="ebb_tide", minutes=10, reason="演示", timed=True, lanlan="default", origin="user"))
    day = list(shard.stats["days"].values())[0]
    assert day["cold"] == 1
    # 她主动转晴（rising_tide 工具路径）→ made_up +1
    shard.mood.action = "ebb_tide"
    run(p.tool_feeling_better(reason="哄好了", _ctx={"lanlan_name": "default"}))
    day = list(shard.stats["days"].values())[0]
    assert day["made_up"] == 1


def test_first_diary_milestone_via_tool(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._get_shard("default")
    run(p.tool_write_diary(entry="今天有点开心。", mood="开心", _ctx={"lanlan_name": "default"}))
    assert shard.stats["milestones"]["first_diary"]
    # 第二篇不覆盖第一篇的时间
    first = shard.stats["milestones"]["first_diary"]
    run(p.tool_write_diary(entry="又写一篇。", mood="平静", _ctx={"lanlan_name": "default"}))
    assert shard.stats["milestones"]["first_diary"] == first


def test_dashboard_carries_stats_summary(plugin_factory) -> None:
    p = plugin_factory()
    run(p._handle_new_user_message(1000.0, "你好", "default"))
    view = run(p.dashboard())
    summary = view["stats_summary"]["summary"]
    assert summary["total_turns"] == 1
    assert isinstance(view["stats_summary"]["badges"], list)


def test_get_stats_entry_returns_heatmap_and_month(plugin_factory) -> None:
    p = plugin_factory()
    run(p._handle_new_user_message(1000.0, "你好", "default"))
    res = run(p.get_stats(month=""))
    payload = res.value if hasattr(res, "value") else res
    # 信封结构齐全（1000.0 时间戳折算成 1970 日期，早于 12 个月窗口会被裁掉——
    # 但 month_available 仍列出该月）
    assert payload["heatmap"]["months"]
    assert isinstance(payload["heatmap"]["days"], list)
    assert payload["month_available"] == ["1970-01"]
    # 显式指定月份：返回该月即时视图
    res2 = run(p.get_stats(month="1970-01"))
    payload2 = res2.value if hasattr(res2, "value") else res2
    assert payload2["month"]["month"] == "1970-01"
    assert payload2["month"]["turns"] == 1


def test_clear_stats_entry(plugin_factory) -> None:
    p = plugin_factory()
    run(p._handle_new_user_message(1000.0, "你好", "default"))
    shard = p._get_shard("default")
    assert shard.stats.get("days")
    res = run(p.clear_stats())
    assert shard.stats == {"backfilled": True}
    saved = run(p.store.get("stats@default"))
    assert saved.value == {"backfilled": True}
    _ = res


def test_anniversary_push_respects_switch_and_dedupe(plugin_factory) -> None:
    """纪念日注入：节点当天推送一次 + 水位去重 + 开关关闭即静默。

    _maybe_anniversary_push 里的"今天"来自 _stats_today（真实时钟、本地时区），
    而 days_together 用 first_seen 的 **UTC 日期** 减本地今日。故把 first_seen 锚到
    「本地今天 − 29 天」的 UTC 正午，使今天恒为第 30 天，与真实日期和时区无关。
    """
    from datetime import date, datetime, timedelta, timezone

    p = plugin_factory()
    shard = p._get_shard("default")
    today = date.fromisoformat(p._stats_today())
    fs = datetime.combine(today - timedelta(days=29), datetime.min.time(), tzinfo=timezone.utc)
    fs = fs.replace(hour=12)
    shard.stats["first_seen"] = fs.isoformat()

    # 推送成功：一条 read 轻语 + 水位盖戳
    pushed = run(p._maybe_anniversary_push("default", shard))
    assert pushed is True
    assert len(p._pushed) == 1
    assert p._pushed[0]["ai_behavior"] == "read"
    assert "30" in p._pushed[0]["parts"][0]["text"]
    assert shard.stats["anniversary"]["last_pushed"] == p._stats_today()
    # 同日去重
    pushed2 = run(p._maybe_anniversary_push("default", shard))
    assert pushed2 is False
    assert len(p._pushed) == 1

    # 开关关闭（[stats].anniversary_inject = false）：不再推送
    p._stats_cfg = {"anniversary_inject": False}
    shard.stats["anniversary"] = {}
    pushed3 = run(p._maybe_anniversary_push("default", shard))
    assert pushed3 is False
    assert len(p._pushed) == 1


def test_seal_stats_months_via_tick_guard(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._get_shard("default")
    run(p._handle_new_user_message(1000.0, "你好", "default"))
    # 手动把数据挪到上个月再封卷
    days = shard.stats.get("days") or {}
    if days:
        only_day = list(days.keys())[0]
        del days[only_day]
        days["2020-01-15"] = {"turns": 3, "v_sum": 0.0, "v_n": 0, "tone": {}, "cold": 0, "made_up": 0, "warm": 0}
        shard.stats["days"] = days
        sealed = run(p._seal_stats_months("default", shard))
        assert "2020-01" in sealed
        assert shard.stats["months"]["2020-01"]["sealed"] is True
