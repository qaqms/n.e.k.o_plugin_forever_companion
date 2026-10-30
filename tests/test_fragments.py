"""时光日记·自动碎片的单测（独立仓库可跑，不依赖宿主）。

覆盖：提取 prompt 组装、模型回复解析（容错/钳制/坏数据）、碎片记录截断、
检索过滤（类型/关键词/来源/上限）、吵架轻语判定，以及主链路
_maybe_capture_fragments 的基线/水位/落盘/轻语集成行为。

依赖 tests/conftest.py 注入的宿主 SDK 桩与 ``plugin_factory`` / ``tm`` fixture。
运行方式（插件目录内）：uv run python -m pytest tests -q
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from forever_companion.core.fragments import (  # noqa: E402
    build_fragment_prompt,
    build_review_prompt,
    fragment_record,
    parse_fragment_response,
    parse_review_response,
    recall_fragments,
    should_nudge_fight,
)
from forever_companion.core.state import _CYCLE_FRAG_DAY  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# ---------- prompt 组装 ----------


def test_prompt_contains_user_text_and_context() -> None:
    prompt = build_fragment_prompt("我最喜欢你做的饭", "真的吗嘿嘿")
    assert "我最喜欢你做的饭" in prompt
    assert "真的吗嘿嘿" in prompt  # 她的回复作为语境拼入


def test_prompt_without_her_reply_has_no_empty_context() -> None:
    prompt = build_fragment_prompt("今天好累", "")
    # 拼接的语境段不出现（prompt 模板说明文字里那句不算）
    assert "（猫娘当时的回复：" not in prompt


def test_prompt_lists_existing_memories_with_numbers() -> None:
    existing = [
        {"kind": "like", "quote": "我最喜欢下雨天"},
        {"kind": "dislike", "quote": "别在我忙的时候打扰我"},
    ]
    prompt = build_fragment_prompt("咖啡戒了", "", existing)
    assert "[1] [like] 我最喜欢下雨天" in prompt
    assert "[2] [dislike] 别在我忙的时候打扰我" in prompt
    # 顺序：已有记忆清单在"主人的话"之前（先看账本，再判这句）
    assert prompt.index("已有记忆") < prompt.index("主人的话：")


def test_prompt_without_existing_says_none() -> None:
    """空日记必须明写（无），不能让模型对着空标题自己猜有没有记忆。"""
    assert "已有记忆：（无）" in build_fragment_prompt("今天好累", "")
    assert "已有记忆：（无）" in build_fragment_prompt("今天好累", "", [])


# ---------- 回复解析 ----------


def test_parse_valid_capture_with_surrounding_text() -> None:
    raw = '好的，这是结果：{"capture": true, "kind": "like", "quote": "我最喜欢你做的饭", "note": "他说最喜欢她做的饭", "confidence": 0.9} 以上。'
    parsed = parse_fragment_response(raw)
    assert parsed == {
        "capture": True,
        "kind": "like",
        "quote": "我最喜欢你做的饭",
        "note": "他说最喜欢她做的饭",
        "confidence": 0.9,
        # 关系字段缺省：旧格式回复（没有 relation）按 new、target 归 0
        "relation": "new",
        "target": 0,
    }


def test_parse_capture_false_is_passthrough() -> None:
    parsed = parse_fragment_response('{"capture": false, "confidence": 0.3}')
    assert parsed == {"capture": False, "confidence": 0.3}
    # capture 缺省按 False（宁可漏记不可错记）
    assert parse_fragment_response('{"confidence": 0.5}')["capture"] is False


def test_parse_bad_json_and_bad_kind_return_none() -> None:
    assert parse_fragment_response("完全不是 JSON") is None
    assert parse_fragment_response("") is None
    assert parse_fragment_response('{"capture": true, "kind": "hate", "quote": "x"}') is None
    # 缺 quote 无从对证
    assert parse_fragment_response('{"capture": true, "kind": "like"}') is None


def test_parse_confidence_clamped() -> None:
    parsed = parse_fragment_response(
        '{"capture": true, "kind": "overstep", "quote": "滚开", "confidence": 5}'
    )
    assert parsed["confidence"] == 1.0
    bad = parse_fragment_response(
        '{"capture": true, "kind": "overstep", "quote": "滚开", "confidence": "abc"}'
    )
    assert bad["confidence"] == 0.0


# ---------- 关系字段（写入后治理）----------

_BASE_CAPTURE = '"capture": true, "kind": "like", "quote": "x", "confidence": 0.9'


def test_parse_relation_variants() -> None:
    assert parse_fragment_response("{" + _BASE_CAPTURE + ', "relation": "new"}')["relation"] == "new"
    dup = parse_fragment_response("{" + _BASE_CAPTURE + ', "relation": "duplicate"}')
    assert dup["relation"] == "duplicate"
    # duplicate 不需要编号
    assert dup["target"] == 0
    sup = parse_fragment_response(
        "{" + _BASE_CAPTURE + ', "relation": "supersede", "target": 2}'
    )
    assert sup["relation"] == "supersede"
    assert sup["target"] == 2


def test_parse_relation_invalid_falls_back_new() -> None:
    """关系字段乱写不该丢掉主体内容：一律按 new（宁可多记一条，也不错删旧记忆）。"""
    for bad in ('"replace"', '"Superseded"', '"NEW "', "1", "null", "true"):
        parsed = parse_fragment_response("{" + _BASE_CAPTURE + ', "relation": ' + bad + "}")
        assert parsed is not None, bad
        assert parsed["relation"] == "new", bad


def test_parse_supersede_with_bad_target_yields_zero() -> None:
    """target 类型坏 → 归 0，越界判定交给调用方（那里才知道已有记忆有几条）。"""
    parsed = parse_fragment_response(
        "{" + _BASE_CAPTURE + ', "relation": "supersede", "target": "abc"}'
    )
    assert parsed["relation"] == "supersede"
    assert parsed["target"] == 0


def test_parse_capture_false_has_no_relation_fields() -> None:
    """不值得记时只回 capture/confidence，不虚构关系字段。"""
    assert parse_fragment_response('{"capture": false, "confidence": 0.2}') == {
        "capture": False,
        "confidence": 0.2,
    }


# ---------- 记录构建 ----------


def test_fragment_record_truncates() -> None:
    record = fragment_record(
        "2026-08-29T10:00:00+00:00",
        "menstrual",
        {"kind": "overstep", "quote": "滚" * 100, "note": "骂" * 100, "confidence": 0.8},
    )
    assert record["source"] == "auto"
    assert record["phase"] == "menstrual"
    # 截断上限 60（state.py _FRAGMENT_QUOTE_MAX_CHARS/_FRAGMENT_NOTE_MAX_CHARS）
    assert len(record["quote"]) == 60
    assert len(record["note"]) == 60
    assert record["confidence"] == 0.8


# ---------- 检索 ----------


def _seed_diary() -> list[dict]:
    return [
        {"ts": "1", "source": "self", "mood": "委屈", "entry": "他凶我"},
        {"ts": "2", "source": "auto", "kind": "like", "quote": "最喜欢你做的饭", "note": "喜好"},
        {"ts": "3", "source": "auto", "kind": "overstep", "quote": "滚开 别烦我", "note": "骂人"},
        {"ts": "4", "source": "auto", "kind": "like", "quote": "喜欢安静", "note": "喜好"},
    ]


def test_recall_only_auto_source_newest_first() -> None:
    hits = recall_fragments(_seed_diary())
    assert [h["ts"] for h in hits] == ["4", "3", "2"]


def test_recall_kind_and_query_filters() -> None:
    hits = recall_fragments(_seed_diary(), kind="like")
    assert [h["ts"] for h in hits] == ["4", "2"]
    hits = recall_fragments(_seed_diary(), query="滚开")
    assert [h["ts"] for h in hits] == ["3"]
    # 关键词大小写不敏感
    assert [h["ts"] for h in recall_fragments(_seed_diary(), query="LIKE")] == []


def test_recall_limit_clamped() -> None:
    diary = [
        {"ts": str(i), "source": "auto", "kind": "important", "quote": f"q{i}", "note": ""}
        for i in range(40)
    ]
    assert len(recall_fragments(diary, limit=5)) == 5
    # limit 钳制到 30
    assert len(recall_fragments(diary, limit=999)) == 30


# ---------- 生命周期状态（status，写入后治理）----------


def test_fragment_record_starts_active() -> None:
    """新落盘的碎片一律是现行事实。"""
    record = fragment_record(
        "2026-10-24T10:00:00+00:00",
        "follicular",
        {"kind": "like", "quote": "喜欢下雨", "note": "", "confidence": 0.8},
    )
    assert record["status"] == "active"


def test_recall_skips_superseded_records() -> None:
    """被后来记录取代的旧条不再当作现状递给她（例：先说喜欢咖啡、后来心悸戒了）。"""
    diary = [
        {"ts": "1", "source": "auto", "kind": "like", "quote": "最喜欢咖啡", "note": "",
         "status": "active"},
        {"ts": "2", "source": "auto", "kind": "like", "quote": "咖啡戒了，心悸", "note": "",
         "status": "superseded"},
    ]
    assert [h["ts"] for h in recall_fragments(diary)] == ["1"]
    # kind 过滤路径同样跳过硬删条（不能靠 kind 兜底）
    assert [h["ts"] for h in recall_fragments(diary, kind="like")] == ["1"]


def test_recall_legacy_records_without_status_still_returned() -> None:
    """1.4.2 及之前的存量碎片没有 status 字段，必须照常翻得到（零迁移）。"""
    diary = [{"ts": "1", "source": "auto", "kind": "overstep", "quote": "滚开"}]
    assert [h["ts"] for h in recall_fragments(diary)] == ["1"]
    # 显式 None / 空串同样按 active 处理（坏数据宽容，不静默吞掉记忆）
    for bad in (None, ""):
        diary[0]["status"] = bad
        assert [h["ts"] for h in recall_fragments(diary)] == ["1"]


# ---------- 记忆自检（mood_review_memory）纯函数 ----------


def test_build_review_prompt_lists_items() -> None:
    items = [
        {"kind": "like", "quote": "最喜欢咖啡"},
        {"kind": "dislike", "quote": "咖啡戒了"},
    ]
    prompt = build_review_prompt(items)
    assert "[1] [like] 最喜欢咖啡" in prompt
    assert "[2] [dislike] 咖啡戒了" in prompt


def test_build_review_prompt_empty_says_none() -> None:
    assert "（无）" in build_review_prompt([])


def test_parse_review_response_ok() -> None:
    raw = '{"findings": [{"index": 2, "issue": "Conflict", "reason": "矛盾"}]}'
    # issue 大小写归一
    assert parse_review_response(raw) == [
        {"index": 2, "issue": "conflict", "reason": "矛盾"}
    ]


def test_parse_review_response_empty_is_valid() -> None:
    """findings 为空数组是"真的没问题"，必须与解析失败（None）严格区分。"""
    assert parse_review_response('{"findings": []}') == []


def test_parse_review_response_bad_shape_returns_none() -> None:
    assert parse_review_response("完全不是 JSON") is None
    assert parse_review_response('{"findings": "none"}') is None
    assert parse_review_response('{"other": []}') is None


def test_parse_review_response_drops_bad_entries() -> None:
    """单条坏数据只丢那一条，不作废整次自检。"""
    raw = (
        '{"findings": ['
        '{"index": 1, "issue": "stale", "reason": "a"},'
        '{"index": 0, "issue": "stale", "reason": "b"},'
        '{"index": 2, "issue": "weird", "reason": "c"},'
        '{"index": "x", "issue": "stale", "reason": "d"},'
        '{"issue": "stale", "reason": "e"}'
        "]}"
    )
    assert parse_review_response(raw) == [{"index": 1, "issue": "stale", "reason": "a"}]


# ---------- 吵架轻语判定 ----------


def test_nudge_only_for_heavy_actions_and_nudge_kinds() -> None:
    pause = frozenset({"ebb_tide", "storm_surge"})
    record = {"kind": "overstep"}
    assert should_nudge_fight(record, "storm_surge", pause) is True
    # 正面动作不轻语
    assert should_nudge_fight(record, "warm_current", pause) is False
    # 喜好类碎片不轻语
    assert should_nudge_fight({"kind": "like"}, "storm_surge", pause) is False
    # 无动作生效不轻语
    assert should_nudge_fight(record, "", pause) is False


# ---------- 主链路集成 ----------


def _setup_capture(p, reply_json: str, marker: str = "2:new") -> None:
    """给插件实例挂上碎片捕获的最小桩：recent 轮次、槽位解析、直连回复。"""
    shard = p._current_shard()

    async def fake_poll(shard_, *, lanlan="", peek=False, advance=True):
        shard_.last_recent_marker = marker
        return ("我最喜欢你做的饭", "真的吗嘿嘿")

    p._poll_recent_turns = fake_poll
    p._resolve_tone_slot = lambda cfg, slot, _seen=frozenset(): {
        "model": "m", "api_key": "k", "base_url": "http://x"
    }
    p._post_chat_completion = lambda *a, **k: reply_json
    return shard


def test_capture_baseline_first_run_does_not_analyze(plugin_factory) -> None:
    p = plugin_factory()
    shard = _setup_capture(p, '{"capture": true, "kind": "like", "quote": "喜欢", "confidence": 0.9}')
    # 首趟：基线未建立，只记水位不落碎片
    assert run(p._maybe_capture_fragments("default", shard)) is False
    assert shard.last_fragment_marker == "2:new"
    assert shard.diary == []


def test_capture_appends_fragment_and_persists(plugin_factory, tm) -> None:
    p = plugin_factory()
    shard = _setup_capture(p, '{"capture": true, "kind": "like", "quote": "最喜欢你做的饭", "confidence": 0.9}')
    shard.last_fragment_marker = "1:old"  # 基线已建立，本轮 marker 变化 → 分析
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 1
    record = shard.diary[0]
    assert record["source"] == "auto"
    assert record["kind"] == "like"
    assert record["quote"] == "最喜欢你做的饭"
    # 落盘到当前角色的 diary key
    assert p.store.data[tm._diary_key("default")][-1]["source"] == "auto"


def test_capture_below_confidence_drops(plugin_factory) -> None:
    p = plugin_factory()
    shard = _setup_capture(p, '{"capture": true, "kind": "like", "quote": "x", "confidence": 0.2}')
    shard.last_fragment_marker = "1:old"
    assert run(p._maybe_capture_fragments("default", shard)) is False
    assert shard.diary == []


def test_capture_nudge_during_fight(plugin_factory) -> None:
    p = plugin_factory()
    shard = _setup_capture(
        p,
        '{"capture": true, "kind": "overstep", "quote": "滚开 别烦我", "note": "凶我", "confidence": 0.9}',
    )
    shard.last_fragment_marker = "1:old"
    # 情绪风暴生效中（非限时校验：expires_at=0 视为不校验到期）
    shard.mood.action = "storm_surge"
    shard.mood.started_at = time.time()
    shard.mood.expires_at = time.time() + 600
    assert run(p._maybe_capture_fragments("default", shard)) is True
    pushes = [item for item in p._pushed if "fragment_nudge" in str(item.get("coalesce_key"))]
    assert len(pushes) == 1
    assert "滚开 别烦我" in pushes[0]["parts"][0]["text"]


def test_capture_no_nudge_when_calm(plugin_factory) -> None:
    p = plugin_factory()
    shard = _setup_capture(
        p,
        '{"capture": true, "kind": "overstep", "quote": "滚开", "confidence": 0.9}',
    )
    shard.last_fragment_marker = "1:old"
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert shard.diary  # 碎片照记
    assert p._pushed == []  # 但平静期不轻语


def test_capture_dormant_when_slot_unresolved(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._current_shard()

    async def fake_poll(shard_, *, lanlan="", peek=False, advance=True):
        shard_.last_recent_marker = "2:new"
        return ("话", "回")

    p._poll_recent_turns = fake_poll
    p._resolve_tone_slot = lambda cfg, slot, _seen=frozenset(): None  # 槽位未配模型
    shard.last_fragment_marker = "1:old"
    assert run(p._maybe_capture_fragments("default", shard)) is False
    assert shard.diary == []
    # 水位已推进：同一轮不会被反复重试
    assert shard.last_fragment_marker == "2:new"


# ---------- 碎片日限（[fragments].daily_limit）----------


def _reset_capture_gates(shard) -> None:
    """让下一次 _maybe_capture_fragments 必定走到模型调用：清掉间隔与水位两道门。"""
    shard.last_fragment_analysis_ts = 0.0
    shard.last_fragment_marker = "1:old"  # 与 fake_poll 写回的 "2:new" 不同 → 判为新轮


def test_capture_stops_at_daily_limit(plugin_factory) -> None:
    """日限是独立于 agent 档总账的上限：槽位切到付费档后仍能兜住次数。"""
    p = plugin_factory()
    # slot 钉非 agent：日限要兜的正是"切到付费槽后 agent 档双闸双双失效"这个场景
    p._fragments_cfg.update({"daily_limit": 2, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(
        p, '{"capture": true, "kind": "like", "quote": "喜欢", "confidence": 0.9}'
    )
    for _ in range(2):
        _reset_capture_gates(shard)
        assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 2

    calls: list[int] = []
    p._post_chat_completion = lambda *a, **k: calls.append(1) or "{}"
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is False
    # 超限时一次请求都不发：闸门在端点解析与通道调用之前
    assert calls == []
    assert len(shard.diary) == 2
    # 水位已推进：不会每 10 秒拿同一个 marker 空转到次日
    assert shard.last_fragment_marker == "2:new"


def test_capture_daily_limit_resets_next_day(plugin_factory) -> None:
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 1, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(
        p, '{"capture": true, "kind": "like", "quote": "喜欢", "confidence": 0.9}'
    )
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is True
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is False

    # 把计数日期推成过去：day_counter_used 对"不是今天"的账一律按 0 算
    shard.cycle[_CYCLE_FRAG_DAY] = "2020-01-01"
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 2


def test_capture_bad_json_does_not_fuse_channel(plugin_factory) -> None:
    """契约 1：模型输出格式坏（解析出 None）不得计入通道熔断。

    熔断账只记"请求层面失败"（_channel_chat 返回 None）。模型答了散文属于输出
    质量问题，计进去会让两次坏回复永久熔掉一条本来通畅的通道（解除条件只有
    改配置或重启）。
    """
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 10, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(p, "完全不是 JSON")
    for _ in range(3):  # 连撞 3 次坏输出，已越过熔断阈值 2
        _reset_capture_gates(shard)
        assert run(p._maybe_capture_fragments("default", shard)) is False
    assert p._channel_break == {}

    # 换一条合法输出：立刻恢复正常（若被误熔断，这一拍会直接丢弃、不调模型）
    p._post_chat_completion = lambda *a, **k: (
        '{"capture": true, "kind": "like", "quote": "喜欢", "confidence": 0.9}'
    )
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 1


# ---------- 面板旋钮：daily_limit 可调（1.5.0）----------


def test_update_settings_fragments_daily_limit_roundtrip(plugin_factory_full) -> None:
    """面板写入的日限要真落进 [fragments] 覆盖层，且读取口读回同一个数。

    读（_fragments_daily_limit）与写（update_settings）是两条独立代码路径，
    这里同时钉住两边：只改一边就会让面板显示与真实闸门不一致。
    """
    from forever_companion import Ok

    p = plugin_factory_full()
    run(p.startup())
    res = run(p.update_settings(fragments_daily_limit=12))
    assert isinstance(res, Ok)
    assert res.value["fragments_daily_limit"] == 12
    assert (p._settings_override.get("fragments") or {}).get("daily_limit") == 12
    assert p._fragments_daily_limit() == 12


def test_update_settings_fragments_daily_limit_keeps_zero(plugin_factory_full) -> None:
    """0 是合法值（今天一次都不分析 = 等价关闭捕获），不得被当空值回落出厂 60。

    这是"用户临时静音"的唯一入口，回落成 60 等于把静音悄悄解除了。
    """
    p = plugin_factory_full()
    run(p.startup())
    res = run(p.update_settings(fragments_daily_limit=0))
    assert res.value["fragments_daily_limit"] == 0
    assert p._fragments_daily_limit() == 0


def test_update_settings_fragments_daily_limit_clamps_to_bounds(plugin_factory_full) -> None:
    """越界钳到 0~500：与 _fragments_daily_limit() 的钳制同一把尺子。

    为什么不像 agent 预算那样拒收：这条闸保的是用户自己的花费，钳制后行为可预期
    （面板马上读回边界值），不会出现"填了 9999 却既不报错也不生效"的静默态。
    """
    p = plugin_factory_full()
    run(p.startup())
    assert run(p.update_settings(fragments_daily_limit=9999)).value["fragments_daily_limit"] == 500
    assert run(p.update_settings(fragments_daily_limit=-5)).value["fragments_daily_limit"] == 0
    assert p._fragments_daily_limit() == 0


def test_update_settings_fragments_daily_limit_rejects_non_number(plugin_factory_full) -> None:
    """非数值（只可能从 API 直调进来）回稳定码，不进 settings 覆盖层。"""
    from forever_companion import Err

    p = plugin_factory_full()
    run(p.startup())
    before = dict(p._settings_override.get("fragments") or {})
    res = run(p.update_settings(fragments_daily_limit="很多"))
    assert isinstance(res, Err)
    assert str(res.error) == "invalid_fragments_daily_limit"
    assert dict(p._settings_override.get("fragments") or {}) == before


# ---------- 写入后治理：判重与取代 ----------


def test_capture_duplicate_skips_new_record(plugin_factory) -> None:
    """模型判"同一结论又提一遍"→ 不新增条目：时间线与配额都不该被重复占。"""
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 10, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(
        p,
        '{"capture": true, "kind": "like", "quote": "最喜欢下雨天", "confidence": 0.9,'
        ' "relation": "duplicate"}',
    )
    shard.diary = [
        {"ts": "old-ts", "source": "auto", "kind": "like", "quote": "最喜欢下雨天",
         "status": "active"},
    ]
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is False
    assert len(shard.diary) == 1


def test_capture_supersede_marks_old_record(plugin_factory) -> None:
    """判"更新了某条"→ 新增一条、旧条转 superseded、新条记下 supersedes 指向。"""
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 10, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(
        p,
        '{"capture": true, "kind": "dislike", "quote": "咖啡戒了，心悸", "confidence": 0.9,'
        ' "relation": "supersede", "target": 1}',
    )
    shard.diary = [
        {"ts": "old-ts", "source": "auto", "kind": "like", "quote": "最喜欢咖啡",
         "status": "active"},
    ]
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 2
    old, new = shard.diary
    assert old["status"] == "superseded"   # 旧条只改状态
    assert old["quote"] == "最喜欢咖啡"     # 内容原样保留，可追溯
    assert new["status"] == "active"
    assert new["supersedes"] == "old-ts"
    # 检索只翻得到现行那条
    assert run(p.tool_recall_fragments()).value["found"] == 1


def test_capture_supersede_out_of_range_keeps_old_active(plugin_factory) -> None:
    """编号越界按 new：宁可多记一条，也不能因模型回了坏编号就标废一条正确记忆。"""
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 10, "min_interval_sec": 0, "slot": "summary"})
    shard = _setup_capture(
        p,
        '{"capture": true, "kind": "like", "quote": "新的一句", "confidence": 0.9,'
        ' "relation": "supersede", "target": 9}',
    )
    shard.diary = [
        {"ts": "old-ts", "source": "auto", "kind": "like", "quote": "旧的一句",
         "status": "active"},
    ]
    _reset_capture_gates(shard)
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert shard.diary[0]["status"] == "active"    # 旧条不受影响
    assert "supersedes" not in shard.diary[1]      # 新条不带指向


# ---------- 工具层 ----------


def test_tool_recall_fragments_returns_hits(plugin_factory) -> None:
    p = plugin_factory()
    shard = p._current_shard()
    shard.diary = _seed_diary()
    result = run(p.tool_recall_fragments(kind="overstep"))
    assert result.value["found"] == 1
    assert result.value["items"][0]["quote"] == "滚开 别烦我"


def _setup_review(p, reply_json: str, items: list[dict] | None = None):
    """给实例挂上自检所需的最小桩：碎片数据、槽位解析、直连回复。"""
    p._fragments_cfg["slot"] = "summary"  # 非 agent 槽：避开日预算与 300 秒地板
    shard = p._current_shard()
    shard.diary = items if items is not None else [
        {"ts": "t1", "source": "auto", "kind": "like", "quote": "最喜欢咖啡",
         "status": "active"},
        {"ts": "t2", "source": "auto", "kind": "dislike", "quote": "咖啡戒了",
         "status": "active"},
    ]
    p._resolve_tone_slot = lambda cfg, slot, _seen=frozenset(): {
        "model": "m", "api_key": "k", "base_url": "http://x"
    }
    p._post_chat_completion = lambda *a, **k: reply_json
    return shard


def test_tool_check_suggests_without_touching_data(plugin_factory) -> None:
    """自检只产出建议，一条数据都不许改（'不替她做决定'的代码化）。"""
    p = plugin_factory()
    shard = _setup_review(
        p,
        '{"findings": [{"index": 1, "issue": "conflict", "reason": "第1条说戒了，第2条说喜欢"}]}',
    )
    result = run(p.tool_check_memory())
    assert result.value["checked"] == 2
    findings = result.value["findings"]
    assert len(findings) == 1
    # 编号 1 = recall_fragments 的第一条 = 时间最新那条（t2）
    assert findings[0]["ts"] == "t2"
    assert findings[0]["issue"] == "conflict"
    # 数据原样：条数、状态、内容都没变
    assert len(shard.diary) == 2
    assert [item["status"] for item in shard.diary] == ["active", "active"]


def test_tool_check_needs_two_items(plugin_factory) -> None:
    """少于两条可比对时直接回空，连一次模型都不调。"""
    p = plugin_factory()
    _setup_review(p, "不该被调用", items=[
        {"ts": "t1", "source": "auto", "kind": "like", "quote": "只有一条",
         "status": "active"},
    ])
    calls: list[int] = []
    p._post_chat_completion = lambda *a, **k: calls.append(1) or "{}"
    result = run(p.tool_check_memory())
    assert result.value["checked"] == 1
    assert result.value["findings"] == []
    assert calls == []


def test_tool_check_throttled(plugin_factory) -> None:
    """30 分钟内重复调用被拒：她可以反复想，但不能反复花配额。"""
    p = plugin_factory()
    _setup_review(p, '{"findings": []}')
    assert not hasattr(run(p.tool_check_memory()), "error")
    assert hasattr(run(p.tool_check_memory()), "error")


def test_tool_check_bad_response_keeps_retryable(plugin_factory) -> None:
    """解析失败不占节流位：这次等于没发生，她可以立刻再试。"""
    p = plugin_factory()
    shard = _setup_review(p, "完全不是 JSON")
    assert hasattr(run(p.tool_check_memory()), "error")
    assert shard.last_fragment_review_ts == 0.0


def test_tool_check_drops_out_of_range_index(plugin_factory) -> None:
    """编号越界只丢那一条建议，不影响同一批里其他发现。"""
    p = plugin_factory()
    _setup_review(
        p,
        '{"findings": [{"index": 9, "issue": "stale", "reason": "越界"},'
        ' {"index": 1, "issue": "duplicate", "reason": "重复"}]}',
    )
    result = run(p.tool_check_memory())
    assert len(result.value["findings"]) == 1
    # 编号 1 指向时间最新那条（t2）
    assert result.value["findings"][0]["ts"] == "t2"


def test_tool_check_respects_daily_budget(plugin_factory) -> None:
    """agent 槽走满日预算时，自检也要被挡住（它与碎片提取共用同一本账）。"""
    p = plugin_factory()
    shard = _setup_review(p, '{"findings": []}')
    p._fragments_cfg["slot"] = "agent"
    shard.cycle["agent_budget_date"] = str(p._today_str())
    shard.cycle["agent_budget_used"] = p._agent_tier_budget()
    assert hasattr(run(p.tool_check_memory()), "error")


def test_tool_check_failures_do_not_fuse_fragment_capture(plugin_factory) -> None:
    p = plugin_factory()
    shard = _setup_review(p, "")
    calls = []

    async def failed_chat(*args, **kwargs):
        calls.append(1)
        return None

    p._channel_chat = failed_chat
    for _ in range(3):
        assert hasattr(run(p.tool_check_memory()), "error")
    assert len(calls) == 2
    assert "default|memory_review" in p._channel_break
    assert "default|fragments" not in p._channel_break

    _setup_capture(p, "")
    _reset_capture_gates(shard)

    async def capture_chat(*args, **kwargs):
        return '{"capture": true, "kind": "like", "quote": "喜欢", "confidence": 0.9}'

    p._channel_chat = capture_chat
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert "default|memory_review" in p._channel_break


def test_tool_check_success_does_not_clear_fragment_breaker(plugin_factory) -> None:
    p = plugin_factory()
    _setup_review(p, '{"findings": []}')
    entry = {"route": "direct|summary", "fails": 2}
    p._channel_break["default|fragments"] = dict(entry)
    assert not hasattr(run(p.tool_check_memory()), "error")
    assert p._channel_break["default|fragments"] == entry


def test_tool_write_journal_returns_tail_without_mirror(plugin_factory) -> None:
    p = plugin_factory()
    first = run(p.tool_write_journal(events="第一篇日记，这几天很开心。"))
    assert first.value["saved"] is True
    assert first.value["page"] == 1
    assert first.value["recent_context"] == ""
    second = run(p.tool_write_journal(thoughts="接着写今天的事。"))
    assert second.value["page"] == 1
    assert "第一篇日记" in second.value["recent_context"]  # 续写衔接（带日期前缀）
    # 个人日记不镜像 read 推送（只给用户看）
    assert p._pushed == []


def test_tool_write_journal_structured_fields_assemble(plugin_factory) -> None:
    p = plugin_factory()
    result = run(p.tool_write_journal(
        events="他带我去了海边。", thoughts="我有点紧张。", feelings="喜欢多一点。", extra="下次想去看日出。",
    ))
    text = p._current_shard().journal[0]["entries"][0]["text"]
    assert result.value["saved"] is True
    assert "【这段时间】他带我去了海边。" in text
    assert "【我在想】我有点紧张。" in text
    assert "【对他的感觉】喜欢多一点。" in text
    assert "【想说的】下次想去看日出。" in text


def test_tool_write_journal_rejects_all_empty(plugin_factory) -> None:
    p = plugin_factory()
    result = run(p.tool_write_journal(new_page=True))
    assert hasattr(result, "error")


def test_tool_mood_disabled_rejects(plugin_factory) -> None:
    p = plugin_factory(mood_extra={"enabled": False})
    result = run(p.tool_recall_fragments())
    assert hasattr(result, "error")
    result2 = run(p.tool_write_journal(events="x"))
    assert hasattr(result2, "error")


# ---------- 与语气感知的水位隔离（1.5.1：真机翻车回归）----------


def test_capture_still_gets_turn_after_tone_advanced_watermark(plugin_factory) -> None:
    """语气感知先把轮次水位推到最新后，碎片仍必须拿到这一轮。

    真机现场（1.5.0 实测）：tick 里语气感知排在碎片之前，且每轮通过门控就写
    ``shard.last_turn_marker``；碎片原先用 ``advance=False`` 轮询，而那道判定比的
    正是同一个 ``last_turn_marker``——于是碎片后跑永远判"没有新轮"，一条都不落，
    全程连 dormant 日志都没有。修法是改用 ``peek=True``（只读最新一轮、不参与水位
    判定），新旧由碎片自己的 ``last_fragment_marker`` 判。

    用真实 `_poll_recent_turns` + 假 recent_file 响应驱动，不 stub 轮询本身，
    否则这个坑会被桩挡掉（本文件其余集成用例都是 stub 的）。
    """
    p = plugin_factory()
    p._fragments_cfg.update({"daily_limit": 10, "min_interval_sec": 0, "slot": "summary"})
    shard = p._current_shard()
    p._resolve_tone_slot = lambda cfg, slot, _seen=frozenset(): {
        "model": "m", "api_key": "k", "base_url": "http://x",
    }
    p._post_chat_completion = lambda *a, **k: (
        '{"capture": true, "kind": "like", "quote": "喜欢下雨天", "confidence": 0.9}'
    )
    holder = {"turn": "我最近总在下雨天出门"}

    async def fake_recent_http(method, path, **kwargs):
        if "/api/memory/recent_file" not in str(path):
            return None
        return {"content": [
            {"type": "human", "data": {"content": holder["turn"]}},
            {"type": "ai", "data": {"content": "记住啦"}},
        ]}

    p._emotion_sense._http = fake_recent_http

    # 首趟只建基线（不分析历史）
    assert run(p._maybe_capture_fragments("default", shard)) is False
    assert shard.diary == []

    # 新的一轮出现，语气感知先跑——它把 last_turn_marker 推到最新（真机每轮如此）
    holder["turn"] = "我其实更喜欢晴天"
    run(p._poll_recent_turns(shard, lanlan="default", advance=True))
    assert shard.last_turn_marker == shard.last_recent_marker

    # 碎片后跑：仍必须拿到这一轮（旧实现这里恒为 False）
    shard.last_fragment_analysis_ts = 0.0
    assert run(p._maybe_capture_fragments("default", shard)) is True
    assert len(shard.diary) == 1
    assert shard.diary[0]["quote"] == "喜欢下雨天"
