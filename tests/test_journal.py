"""个人日记（书页式）纯逻辑的单测（独立仓库可跑，不依赖宿主）。

覆盖：续写/翻页/写满自动翻页/页数淘汰、续写衔接句、邀请节奏判定、
旧版潮汐周记迁移、页眉统计。journal_write/journal_due 支持显式 now 注入，
不依赖系统时钟。运行方式：uv run python -m pytest tests -q
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forever_companion.core.journal import (  # noqa: E402
    assemble_journal_entry,
    has_journal_content,
    journal_due,
    journal_write,
    migrate_weekly_to_pages,
    page_header,
)

NOW = datetime(2026, 8, 29, 12, 0, 0, tzinfo=timezone.utc)


# ---------- 写入：续写 / 翻页 / 淘汰 ----------


def test_first_write_creates_page_one() -> None:
    pages, page_no, tail = journal_write([], "第一篇", False, now=NOW, affect=0.3)
    assert page_no == 1
    assert tail == ""
    assert pages[0]["page_no"] == 1
    assert pages[0]["started_at"] == NOW.isoformat(timespec="seconds")
    entry = pages[0]["entries"][0]
    assert entry["text"] == "第一篇"
    assert entry["affect"] == 0.3


def test_continue_appends_to_current_page() -> None:
    pages, page_no, tail = journal_write([], "第一段", False, now=NOW)
    later = NOW + timedelta(days=1)
    pages2, page_no2, tail2 = journal_write(pages, "第二段", False, now=later)
    assert page_no2 == 1  # 还在同一页
    assert "第一段" in tail2  # 续写衔接带出上次写的
    assert [e["text"] for e in pages2[0]["entries"]] == ["第一段", "第二段"]
    # 原 pages 不被 mutate
    assert len(pages[0]["entries"]) == 1


def test_new_page_flag_starts_fresh_page_with_previous_tail() -> None:
    pages, _, _ = journal_write([], "上一页的结尾", False, now=NOW)
    later = NOW + timedelta(days=3)
    pages2, page_no2, tail2 = journal_write(pages, "新的一页", True, now=later)
    assert page_no2 == 2
    # 翻页时衔接上一页最后一段（带落笔日期前缀）
    assert tail2.endswith("上一页的结尾")
    assert "写的）" in tail2
    assert pages2[1]["started_at"] == later.isoformat(timespec="seconds")


def test_full_page_auto_flips() -> None:
    pages: list[dict] = []
    for i in range(8):  # 页容量 8
        pages, _, _ = journal_write(pages, f"段{i}", False, now=NOW + timedelta(minutes=i))
    assert len(pages) == 1
    pages, page_no, _ = journal_write(pages, "第9段", False, now=NOW)
    assert page_no == 2  # 写满自动翻页
    assert [e["text"] for e in pages[0]["entries"]][-1] == "段7"


def test_page_cap_evicts_oldest() -> None:
    pages: list[dict] = []
    for i in range(60):  # 造 60 页（上限 52）
        pages, _, _ = journal_write(pages, f"页{i}", True, now=NOW + timedelta(days=i))
    assert len(pages) == 52
    assert pages[0]["page_no"] == 9  # 最旧的 8 页被淘汰
    assert pages[-1]["page_no"] == 60


def test_entry_text_truncated_to_cap() -> None:
    pages, _, _ = journal_write([], "长" * 2000, False, now=NOW)
    # 0.7.1 起结构化四字段拼装，单条上限放宽到 900
    assert len(pages[0]["entries"][0]["text"]) == 900


# ---------- 邀请节奏 ----------


def test_due_when_never_written() -> None:
    due, reason = journal_due([], now=NOW, interval_days=7)
    assert due is True and reason == "due"


def test_not_due_within_interval() -> None:
    pages, _, _ = journal_write([], "昨天写的", False, now=NOW - timedelta(days=1))
    due, reason = journal_due(pages, now=NOW, interval_days=7)
    assert due is False and reason == "recent_write"


def test_due_after_interval_even_without_new_pages() -> None:
    pages, _, _ = journal_write([], "八天前写的", False, now=NOW - timedelta(days=8))
    due, _ = journal_due(pages, now=NOW, interval_days=7)
    assert due is True


def test_continue_resets_cadence() -> None:
    # 首段写在 9 天前，但续写发生在 1 天前 → 节奏以"最近一次落笔"起算
    pages, _, _ = journal_write([], "九天前", False, now=NOW - timedelta(days=9))
    pages, _, _ = journal_write(pages, "昨天续写", False, now=NOW - timedelta(days=1))
    due, reason = journal_due(pages, now=NOW, interval_days=7)
    assert due is False and reason == "recent_write"


# ---------- 旧周记迁移 ----------


def test_migrate_weekly_records_to_pages() -> None:
    weekly = [
        {"ts": "2026-08-01T10:00:00+00:00", "summary": "第一周小结", "highlight": "那场雨"},
        {"ts": "2026-08-08T10:00:00+00:00", "summary": "第二周小结", "highlight": ""},
    ]
    pages = migrate_weekly_to_pages(weekly)
    assert len(pages) == 2
    assert pages[0]["page_no"] == 1
    assert pages[0]["legacy"] is True
    assert "第一周小结" in pages[0]["entries"][0]["text"]
    assert "那场雨" in pages[0]["entries"][0]["text"]
    # 无 highlight 的不拼那句
    assert "印象最深" not in pages[1]["entries"][0]["text"]


def test_migrate_empty_and_bad_data() -> None:
    assert migrate_weekly_to_pages([]) == []
    assert migrate_weekly_to_pages(["bad", {"summary": ""}, None]) == []


# ---------- 页眉统计 ----------


def test_page_header_stats() -> None:
    pages, _, _ = journal_write([], "a", False, now=NOW, affect=0.4)
    pages, _, _ = journal_write(pages, "b", False, now=NOW, affect=-0.2)
    header = page_header(pages[0])
    assert header["page_no"] == 1
    assert header["entry_count"] == 2
    assert header["mood_avg"] == 0.1
    assert header["last_ts"] == pages[0]["entries"][-1]["ts"]
    assert header["legacy"] is False


def test_page_header_without_affect_snapshots() -> None:
    header = page_header({"page_no": 3, "started_at": "t", "entries": [{"ts": "t", "text": "x"}]})
    assert header["mood_avg"] is None
    assert header["entry_count"] == 1


# ---------- 结构化字段拼装 ----------


def test_assemble_all_sections_labeled() -> None:
    text = assemble_journal_entry(
        events="他带我去了海边。", thoughts="我有点紧张。", feelings="喜欢多一点。", extra="下次想看日出。"
    )
    lines = text.splitlines()
    assert lines[0] == "【这段时间】他带我去了海边。"
    assert lines[1] == "【我在想】我有点紧张。"
    assert lines[2] == "【对他的感觉】喜欢多一点。"
    assert lines[3] == "【想说的】下次想看日出。"


def test_assemble_skips_empty_fields() -> None:
    text = assemble_journal_entry(thoughts="只想写心事。")
    assert text == "【我在想】只想写心事。"
    # 只写 extra：不加标题，尊重自由发挥
    assert assemble_journal_entry(extra="随手一句话") == "随手一句话"
    assert assemble_journal_entry() == ""


def test_assemble_truncates_each_field() -> None:
    text = assemble_journal_entry(events="长" * 500)
    # events 单字段截到 300
    assert len(text) == len("【这段时间】") + 300


def test_has_journal_content() -> None:
    assert has_journal_content("", "有内容", "", "") is True
    assert has_journal_content("   ", "", "", "") is False
    assert has_journal_content() is False


# ---------- 1.2.3：递邀双模式（手动 respond 当面递到 / 周期与冷却 read 静默） ----------

import asyncio  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def test_forced_invite_delivers_respond_then_cooldown_read(plugin_factory) -> None:
    """面板 force 首递走 respond（当场起轮她立刻收到）；10 分钟内再按回落 read 补递。"""
    p = plugin_factory()
    shard = run(p._ensure_shard("default"))
    invited, deliver = run(p._maybe_journal_invite("default", shard, force=True))
    assert (invited, deliver) == (True, "respond")
    push = p._pushed[-1]
    assert push["ai_behavior"] == "respond"
    assert push["visibility"] == []
    text = push["parts"][0]["text"]
    assert "[潮汐·日记邀请]" in text and "{MASTER_NAME}" in text
    assert push["coalesce_key"] == "forever_companion.journal_invite"
    assert push["metadata"]["deliver"] == "respond"
    assert p._journal_invite_pending(shard) is True, "递出即挂起，她落笔才解除"

    # 冷却窗口内（刚递出）：再 force 不重复起轮，改 read 补递
    invited2, deliver2 = run(p._maybe_journal_invite("default", shard, force=True))
    assert (invited2, deliver2) == (True, "read")
    assert p._pushed[-1]["ai_behavior"] == "read"
    assert "（内心状态提醒）" in p._pushed[-1]["parts"][0]["text"]

    # 手动把水位拨回 11 分钟前 → 冷却已过，又回到 respond 档
    shard.last_journal_invite_ts -= 11 * 60
    invited3, deliver3 = run(p._maybe_journal_invite("default", shard, force=True))
    assert (invited3, deliver3) == (True, "respond")


def test_periodic_invite_stays_read(plugin_factory) -> None:
    """tick 周期递邀保持 read：安静的生命节律不该起轮打扰。"""
    p = plugin_factory()
    run(p._ensure_shard("default"))
    invited, deliver = run(p._maybe_journal_invite("default", p._get_shard("default")))
    assert (invited, deliver) == (True, "read")
    assert p._pushed[-1]["ai_behavior"] == "read"


def test_invite_gated_by_switches(plugin_factory) -> None:
    """三道闸任一关闭都拒绝递邀（fail-closed 不破）。"""
    p = plugin_factory()
    shard = run(p._ensure_shard("default"))
    p._journal_cfg["enabled"] = False
    assert run(p._maybe_journal_invite("default", shard, force=True)) == (False, "")
    p._journal_cfg["enabled"] = True
    p._mood_cfg["enabled"] = False
    assert run(p._maybe_journal_invite("default", shard, force=True)) == (False, "")


def test_invite_journal_entry_reports_mode(plugin_factory) -> None:
    """面板入口三态 note：respond 当面递到 / 冷却内悄悄提醒。"""
    p = plugin_factory()
    run(p._ensure_shard("default"))
    res = run(p.invite_journal())
    v = res.value
    assert v["invited"] is True and v["mode"] == "respond"
    assert "当面" in v["note"]
    res2 = run(p.invite_journal())
    assert res2.value["mode"] == "read" and "悄悄" in res2.value["note"]
