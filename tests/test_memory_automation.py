"""Automatic lifecycle uses synthetic diaries, a fake model and an isolated Store."""

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from forever_companion.core import backup, memory
from forever_companion.core.fragments import parse_fragment_response
from forever_companion.mixins import senses

NOW = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


def record(index=0, quote="Coffee", *, pending=False):
    stamp = (NOW - timedelta(days=2, seconds=index)).isoformat()
    parsed = {"kind": "like", "quote": quote}
    return {"ts": stamp, "source": "auto", "kind": "like", "quote": quote, "status": "active",
            "memory": {**memory.new_metadata(parsed, stamp), "pending": pending}}


def conflict():
    old, new = record(1), record(0, "Tea")
    old["memory"].update(pending=True, conflicts_with=new["ts"])
    new["memory"].update(pending=True, conflicts_with=old["ts"])
    return [old, new]


def resolve(diary, *, proof="I prefer Tea now", target=2, existing=None):
    parsed = {"relation": "resolve", "target": target, "quote": proof, "resolution_quote": proof, "confidence": 0.99}
    fresh = record(-100, proof)
    fresh["ts"] = NOW.isoformat()
    fresh["memory"] = memory.new_metadata({"kind": "like", "quote": proof}, fresh["ts"])
    memory.apply_capture(diary, copy.deepcopy(diary) if existing is None else existing, parsed, fresh, user_text=proof)
    return fresh


def prepare(factory, monkeypatch, records=None):
    clock = [NOW]
    monkeypatch.setattr(memory, "_now_utc", lambda: clock[0])
    monkeypatch.setattr(senses, "_now_utc", lambda: clock[0])
    plugin = factory(current_lanlan="Alice", store_initial={
        "lanlan_index": ["Alice", "Other"], "diary@Alice": records or [record(), record(1, "Tea")],
        "diary@Other": [record(2, "Other role")],
    })
    plugin._fragments_cfg.update(slot="summary", daily_limit=60)
    shard = plugin._get_shard("Alice")
    shard.last_memory_turn_marker = "old"
    shard.last_recent_marker = "new"
    shard.last_recent_turn = ("Coffee", "Context")
    calls = []

    async def endpoint(*_args, **_kwargs):
        return {"model": "fake"}, "summary", {}

    async def chat(*args, **kwargs):
        calls.append((args, kwargs))
        return '{"findings": []}'

    plugin._resolve_channel_endpoint = endpoint
    plugin._channel_chat = chat
    return plugin, shard, calls, clock


def test_legacy_migration_grants_full_grace_without_fabricating_confirmation():
    original = {"ts": "2000-01-01", "source": "auto", "kind": "like", "quote": "Coffee", "status": "active"}
    item = copy.deepcopy(original)
    assert memory.maintain_memories([item], NOW) == 1
    assert {key: value for key, value in item.items() if key != "memory"} == original
    assert item["memory"]["aging_started_at"] == NOW.isoformat()
    assert "last_confirmed_at" not in item["memory"]
    assert memory.memory_state(item, NOW) == "active"
    assert memory.memory_state(item, NOW + timedelta(days=179)) == "active"
    assert memory.memory_state(item, NOW + timedelta(days=180)) == "dormant"
    after = copy.deepcopy(item)
    assert memory.maintain_memories([item], NOW + timedelta(days=180)) == 0
    assert item == after


@pytest.mark.parametrize("flags", [{"paused": True}, {"pinned": True}, {"correction": "Tea"}, {"archived": True}])
def test_legacy_migration_preserves_manual_choices(flags):
    item = {"source": "auto", "kind": "like", "ts": "2000-01-01", "quote": "Coffee", "memory": flags.copy()}
    memory.maintain_memories([item], NOW)
    assert all(item["memory"][key] == value for key, value in flags.items())
    assert item["memory"]["confirmations"] == 1


def test_legacy_migration_recovers_invalid_clock_without_changing_raw_confirmation():
    item = {"source": "auto", "kind": "like", "ts": "2000-01-01", "quote": "Coffee",
            "memory": {"last_confirmed_at": "invalid"}}
    assert memory.maintain_memories([item], NOW) == 1
    assert item["memory"]["last_confirmed_at"] == "invalid"
    assert memory.memory_state(item, NOW + timedelta(days=181)) == "dormant"


@pytest.mark.parametrize(("kind", "horizon"), [("like", 180), ("important", 90)])
def test_runtime_migration_persists_recent_and_archive_clock_across_restart(
    plugin_factory_full, monkeypatch, kind, horizon,
):
    records = [{"ts": f"2000-01-01T00:{index // 60:02}:{index % 60:02}+00:00",
                "source": "auto", "kind": kind, "quote": f"Original {index}", "status": "active"}
               for index in range(130)]
    originals = copy.deepcopy(records)
    plugin, shard, calls, clock = prepare(plugin_factory_full, monkeypatch, records)
    other_before = copy.deepcopy(plugin.store.data["diary@Other"])
    plugin._fragments_cfg["daily_limit"] = 0
    shard.last_recent_marker, shard.last_recent_turn = "", None
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert calls == [] and plugin._pushed == []
    assert len(memory.diary_partition(shard.diary, "archive")) == 10
    assert plugin.store.data["diary@Alice"] == shard.diary
    assert plugin.store.data["diary@Other"] == other_before
    for original, item in zip(originals, shard.diary, strict=True):
        assert {key: value for key, value in item.items() if key != "memory"} == original
        assert item["memory"]["aging_started_at"] == NOW.isoformat()
        assert "last_confirmed_at" not in item["memory"]
        assert memory.memory_state(item, NOW) == "active"

    clock[0] += timedelta(days=30)
    restarted = plugin_factory_full(current_lanlan="Alice", store_initial=copy.deepcopy(plugin.store.data))
    restored = restarted._get_shard("Alice")
    assert not run(restarted._maybe_maintain_memories("Alice", restored))
    assert restored.diary == shard.diary
    for item in restored.diary:
        assert memory.memory_state(item, NOW + timedelta(days=horizon, seconds=-1)) == "active"
        assert memory.memory_state(item, NOW + timedelta(days=horizon)) == "dormant"
    assert restarted.store.data["diary@Alice"] == restored.diary


def test_failed_legacy_migration_only_starts_clock_after_successful_retry(plugin_factory_full, monkeypatch, tm):
    records = [{"ts": "2000-01-01", "source": "auto", "kind": "like", "quote": "Original"}]
    plugin, shard, calls, clock = prepare(plugin_factory_full, monkeypatch, records)
    shard.last_recent_marker, shard.last_recent_turn = "", None
    original_set = plugin.store.set

    async def fail(*_args):
        return tm.Err(tm.SdkError("disk full"))

    plugin.store.set = fail
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert shard.diary == plugin.store.data["diary@Alice"] == records
    assert shard.last_memory_maintenance_ts == 0
    assert not shard.diary_save_lock.locked() and not shard.memory_maintenance_lock.locked()
    clock[0] += timedelta(hours=1)
    plugin.store.set = original_set
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert shard.diary[0]["memory"]["aging_started_at"] == clock[0].isoformat()
    assert plugin.store.data["diary@Alice"] == shard.diary
    assert calls == []


def test_migration_skips_self_demo_future_schema_and_does_not_erase_boundaries():
    items = [
        {"source": "self", "entry": "Diary"},
        {"source": "auto", "demo": True, "quote": "Example"},
        {"source": "auto", "memory": {"schema": 2}},
        {"source": "auto", "ts": "2000-01-01", "kind": "overstep", "quote": "Hurtful event"},
    ]
    before = copy.deepcopy(items)
    assert memory.maintain_memories(items, NOW) == 1
    assert items[:3] == before[:3]
    assert memory.memory_state(items[3], NOW + timedelta(days=3000)) == "active"


def test_conflict_resolution_replaces_both_sides_without_pinning_or_losing_originals():
    diary = conflict()
    originals = [(item["ts"], item["quote"]) for item in diary]
    fresh = resolve(diary)
    assert [memory.memory_state(item, NOW) for item in diary] == ["superseded", "superseded", "active"]
    assert [(item["ts"], item["quote"]) for item in diary[:2]] == originals
    assert memory.recall_memories(diary, now=NOW) == [fresh]
    assert not fresh["memory"].get("pinned")
    assert fresh["memory"]["confirmations"] == 1


@pytest.mark.parametrize("proof", ["OK", "yes", "I prefer Tea now?", "我现在喜欢茶？"])
def test_short_or_questioning_answers_do_not_resolve_conflicts(proof):
    diary = conflict()
    before = copy.deepcopy(diary)
    fresh = resolve(diary, proof=proof)
    assert diary[:2] == before
    assert memory.memory_state(fresh, NOW) == "pending"


@pytest.mark.parametrize("flag", ["pinned", "paused", "correction"])
def test_automatic_resolution_respects_manual_protection_on_either_side(flag):
    diary = conflict()
    diary[0]["memory"][flag] = "User correction" if flag == "correction" else True
    before = copy.deepcopy(diary)
    fresh = resolve(diary)
    assert diary[:2] == before
    assert memory.memory_state(fresh, NOW) == "pending"


def test_missing_or_edited_partner_prevents_partial_conflict_resolution():
    for changed in (False, True):
        diary = conflict()
        snapshot = copy.deepcopy(diary)
        if changed:
            diary[0]["memory"]["updated_at"] = NOW.isoformat()
        else:
            snapshot.pop(0)
        before = copy.deepcopy(diary)
        fresh = resolve(diary, existing=snapshot, target=2 if changed else 1)
        assert diary[:2] == before
        assert memory.memory_state(fresh, NOW) == "pending"


def test_resolution_handles_prior_updates_and_keeps_links_for_manual_reversal():
    diary = conflict()
    history = record(3, "Before Coffee")
    history["status"] = "superseded"
    diary[0]["supersedes"] = history["ts"]
    diary.insert(0, history)
    fresh = resolve(diary, existing=copy.deepcopy(diary[1:]), target=2)
    assert memory.memory_state(fresh, NOW) == "active"
    assert history["status"] == "superseded"
    assert diary[1]["memory"]["conflicts_with"] == diary[2]["ts"]
    memory.manage_memory(diary, diary[1], "confirm", now=NOW + timedelta(seconds=1))
    assert memory.memory_state(fresh, NOW) == "pending"
    assert memory.recall_memories(diary, now=NOW) == [diary[1]]


def test_low_confidence_resolution_stays_pending_even_with_a_source_quote():
    diary = conflict()
    fresh = record(-1, "I prefer Tea now")
    before = copy.deepcopy(diary)
    memory.apply_capture(diary, copy.deepcopy(diary),
                         {"relation": "resolve", "target": 2, "confidence": 0.7,
                          "quote": fresh["quote"], "resolution_quote": fresh["quote"]},
                         fresh, user_text=fresh["quote"])
    assert diary[:2] == before and memory.memory_state(fresh, NOW) == "pending"


def test_hallucinated_resolution_quote_is_never_accepted():
    diary = conflict()
    before = copy.deepcopy(diary)
    fresh = record(-1, "Tea")
    memory.apply_capture(diary, copy.deepcopy(diary),
                         {"relation": "resolve", "target": 2, "quote": "Tea", "resolution_quote": "I prefer Tea"},
                         fresh, user_text="Maybe later")
    assert diary[:2] == before
    assert memory.memory_state(fresh, NOW) == "pending"


def test_resolution_keeps_conditions_and_hurtful_history_protected():
    for mode in ("condition", "overstep"):
        diary = conflict()
        if mode == "condition":
            diary[0]["memory"]["condition"] = "at night"
        else:
            diary[0]["kind"] = "overstep"
        before = copy.deepcopy(diary)
        resolve(diary)
        assert diary[:2] == before


def test_supersede_cannot_bypass_pending_resolution_evidence():
    diary = conflict()
    before = copy.deepcopy(diary)
    fresh = record(-1, "Tea")
    memory.apply_capture(diary, copy.deepcopy(diary), {"relation": "supersede", "target": 2}, fresh)
    assert diary[:2] == before
    assert memory.memory_state(fresh, NOW) == "pending"


def test_pending_temporary_memory_expires_instead_of_waiting_forever():
    item = record(pending=True)
    item["memory"].update(type="temporary", valid_until=NOW.isoformat())
    assert memory.memory_state(item, NOW) == "expired"
    assert memory.recall_memories([item], query="Coffee", now=NOW) == []


@pytest.mark.parametrize(("text", "days"), [
    ("明天不喝咖啡", 1), ("后天不喝咖啡", 2), ("No Coffee tomorrow", 1),
    ("No Coffee the day after tomorrow", 2), ("今天先不喝咖啡", 0),
])
def test_temporary_relative_dates_are_grounded_in_local_calendar(text, days):
    local = NOW.astimezone(timezone(timedelta(hours=8)))
    meta = memory.new_metadata({"kind": "like", "memory_type": "temporary"}, NOW.isoformat(),
                               user_text=text, local_now=local)
    assert meta["valid_through"] == (local + timedelta(days=days)).date().isoformat()
    end = local.replace(hour=0, minute=0, second=0) + timedelta(days=days + 1)
    assert meta["valid_until"] == end.isoformat(timespec="seconds")


@pytest.mark.parametrize("text", [
    "今天喜欢咖啡，明天不一定", "Coffee tomorrow or the day after tomorrow",
    "某天再喝咖啡", "大后天不喝咖啡",
])
def test_ambiguous_or_unsupported_relative_dates_stay_pending(text):
    meta = memory.new_metadata({"kind": "like", "memory_type": "temporary"}, NOW.isoformat(), user_text=text)
    assert meta["pending"] and "valid_until" not in meta


def test_pending_candidates_and_resolution_proof_survive_prompt_parsing():
    diary = conflict()
    diary.extend(record(index + 20, "Unrelated") for index in range(20))
    selected = memory.extraction_candidates(diary, "Tea")
    assert all(item in selected for item in diary[:2])
    assert len(selected) <= 10
    parsed = parse_fragment_response(json.dumps({
        "capture": True, "confidence": 0.9, "kind": "like", "quote": "Tea",
        "relation": "resolve", "target": "2", "resolution_quote": "I prefer Tea now",
    }))
    assert parsed["target"] == 2 and parsed["resolution_quote"] == "I prefer Tea now"


def test_automatic_review_rotates_archive_and_cooldown_survives_restart(plugin_factory_full, monkeypatch):
    records = [record(index, f"Topic {index}") for index in range(140)]
    plugin, shard, calls, clock = prepare(plugin_factory_full, monkeypatch, records)
    assert run(plugin._maybe_maintain_memories("Alice", shard))
    assert len(calls) == 1
    reviewed = [item for item in shard.diary if item["memory"].get("review_attempted_at")]
    assert reviewed == shard.diary[:20]
    assert all(item in memory.diary_partition(shard.diary, "archive") for item in reviewed)
    restarted = plugin_factory_full(current_lanlan="Alice", store_initial=copy.deepcopy(plugin.store.data))
    restarted._channel_chat = plugin._channel_chat
    other = restarted._get_shard("Alice")
    other.last_memory_turn_marker = "before-restart"
    other.last_recent_marker, other.last_recent_turn = "after-restart", ("Coffee", "")
    assert not run(restarted._maybe_maintain_memories("Alice", other))
    assert len(calls) == 1
    clock[0] += timedelta(days=1, seconds=1)
    shard.last_recent_marker = "next-day"
    assert run(plugin._maybe_maintain_memories("Alice", shard))
    assert len(calls) == 2
    assert all(item["memory"].get("review_attempted_at") for item in shard.diary[:40])
    assert plugin.store.data["diary@Other"][0]["quote"] == "Other role"


def test_idle_and_startup_never_request_model_or_ask_questions(plugin_factory_full, monkeypatch):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)
    shard.last_memory_turn_marker = ""
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert calls == [] and plugin._pushed == []


@pytest.mark.parametrize("failure", [None, "not JSON"])
def test_failed_automatic_reviews_keep_persistent_cooldown(plugin_factory_full, monkeypatch, failure):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)

    async def fail(*_args, **_kwargs):
        calls.append(1)
        return failure

    plugin._channel_chat = fail
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    shard.last_recent_marker = "next-message"
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert len(calls) == 1
    assert plugin.store.data["diary@Alice"][0]["memory"]["review_attempted_at"] == NOW.isoformat()


def test_automatic_review_stale_reply_cannot_change_user_edits(plugin_factory_full, monkeypatch):
    plugin, shard, _, _ = prepare(plugin_factory_full, monkeypatch)

    async def edit(*_args, **_kwargs):
        shard.diary[0]["memory"]["correction"] = "User correction"
        return '{"findings": [{"index": 2, "issue": "stale", "reason": "Old reply"}]}'

    plugin._channel_chat = edit
    assert run(plugin._maybe_maintain_memories("Alice", shard))
    assert shard.diary[0]["memory"]["correction"] == "User correction"
    assert "suggestion" not in shard.diary[0]["memory"]


def test_automatic_review_applies_suggestions_without_guessing_fact_validity(plugin_factory_full, monkeypatch):
    plugin, shard, _, _ = prepare(plugin_factory_full, monkeypatch)

    async def finding(*_args, **_kwargs):
        return '{"findings": [{"index": 1, "issue": "stale", "reason": "Needs clarification"}]}'

    plugin._channel_chat = finding
    assert run(plugin._maybe_maintain_memories("Alice", shard))
    item = shard.diary[-1]
    assert item["memory"]["suggestion"]["issue"] == "stale"
    assert memory.memory_state(item, NOW) == "active" and item["quote"] == "Tea"


@pytest.mark.parametrize("gate", ["disabled", "untrusted", "fragments_off", "budget", "unavailable"])
def test_automatic_review_respects_switches_store_and_budget(plugin_factory_full, monkeypatch, gate):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)
    if gate == "disabled":
        shard.cycle["enabled"] = False
    elif gate == "untrusted":
        plugin._state_trusted = False
    elif gate == "fragments_off":
        plugin._fragments_cfg["enabled"] = False
    elif gate == "budget":
        plugin._fragments_cfg["daily_limit"] = 0
    else:
        async def unavailable(*_args, **_kwargs):
            return None, "agent", {}
        plugin._resolve_channel_endpoint = unavailable
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert calls == []


def test_agent_pacing_defers_review_without_losing_pending_turn(plugin_factory_full, monkeypatch):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)
    plugin._agent_tier_gate = lambda *_args: "pace"
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert calls == [] and shard.last_memory_turn_marker == "old"
    plugin._agent_tier_gate = lambda *_args: ""
    assert run(plugin._maybe_maintain_memories("Alice", shard))
    assert len(calls) == 1


def test_delayed_review_does_not_spend_after_conversation_window(plugin_factory_full, monkeypatch):
    plugin, shard, calls, clock = prepare(plugin_factory_full, monkeypatch)
    plugin._agent_tier_gate = lambda *_args: "pace"
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    clock[0] += timedelta(minutes=16)
    plugin._agent_tier_gate = lambda *_args: ""
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert calls == [] and shard.last_memory_turn_marker == shard.last_recent_marker


def test_automatic_review_store_failure_rolls_back_before_request(plugin_factory_full, monkeypatch, tm):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)
    original = copy.deepcopy(shard.diary)

    async def fail(*_args):
        return tm.Err(tm.SdkError("disk full"))

    plugin.store.set = fail
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert shard.diary == original and calls == []
    assert not shard.memory_maintenance_lock.locked()


def test_overlapping_maintenance_never_spends_twice(plugin_factory_full, monkeypatch):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        async def waiting(*_args, **_kwargs):
            calls.append(1)
            entered.set()
            await release.wait()
            return '{"findings": []}'

        plugin._channel_chat = waiting
        first = asyncio.create_task(plugin._maybe_maintain_memories("Alice", shard))
        await entered.wait()
        assert not await plugin._maybe_maintain_memories("Alice", shard)
        release.set()
        assert await first

    run(scenario())
    assert calls == [1] and not shard.memory_maintenance_lock.locked()


def test_clarification_is_relevant_directed_bounded_and_persistent(plugin_factory_full, monkeypatch):
    plugin, shard, calls, clock = prepare(plugin_factory_full, monkeypatch, [record(pending=True)])
    run(plugin._maybe_clarify_memory("Alice", shard, "Coffee", clock[0]))
    assert len(plugin._pushed) == 1 and calls == []
    assert plugin._pushed[0]["target_lanlan"] == "Alice"
    assert plugin._pushed[0]["ai_behavior"] == "read"
    restarted = plugin_factory_full(current_lanlan="Alice", store_initial=copy.deepcopy(plugin.store.data))
    restarted._resolve_channel_endpoint = plugin._resolve_channel_endpoint
    other = restarted._get_shard("Alice")
    run(restarted._maybe_clarify_memory("Alice", other, "Coffee", clock[0] + timedelta(days=1)))
    assert restarted._pushed == []
    run(restarted._maybe_clarify_memory("Alice", other, "Coffee", clock[0] + timedelta(days=7)))
    assert len(restarted._pushed) == 1
    run(restarted._maybe_clarify_memory("Alice", other, "Coffee", clock[0] + timedelta(days=14)))
    assert len(restarted._pushed) == 1
    assert other.diary[0]["memory"]["clarification_count"] == 2
    assert memory.memory_state(other.diary[0], NOW) == "pending"
    assert other.diary[0]["memory"]["confirmations"] == 1


@pytest.mark.parametrize("mode", ["unrelated", "pinned", "paused", "overstep", "negative_mood", "switched"])
def test_clarification_does_not_interrupt_or_override_user_choices(plugin_factory_full, monkeypatch, mode):
    plugin, shard, _, _ = prepare(plugin_factory_full, monkeypatch, [record(pending=True)])
    text = "Coffee"
    if mode == "unrelated":
        text = "Weather"
    elif mode in {"pinned", "paused"}:
        shard.diary[0]["memory"][mode] = True
    elif mode == "overstep":
        shard.diary[0]["kind"] = "overstep"
    elif mode == "negative_mood":
        import time
        shard.mood.action = "storm_surge"
        shard.mood.started_at = time.time()
        shard.mood.expires_at = time.time() + 600
    else:
        async def switched():
            return "Other"
        plugin._resolve_current_lanlan = switched
    before = copy.deepcopy(shard.diary)
    run(plugin._maybe_clarify_memory("Alice", shard, text, NOW))
    assert plugin._pushed == [] and shard.diary == before


def test_new_policy_metadata_roundtrips_backup_and_rejects_invalid_types():
    item = {"ts": "2000-01-01", "source": "auto", "kind": "like", "quote": "Coffee"}
    memory.maintain_memories([item], NOW)
    item["memory"].update(clarification_count=1, clarification_at=NOW.isoformat(), review_attempted_at=NOW.isoformat())
    records = {"lanlan_index": ["Alice"], "diary@Alice": [item], "gallery_index": {"items": []}}
    content, _ = backup.make_archive(records, "1.4.7")
    restored, _ = backup.read_archive(content)
    assert restored == records
    for field, value in [("aging_started_at", 123), ("review_attempted_at", []), ("clarification_count", 3),
                         ("clarification_at", False), ("clarification_count", True)]:
        changed = copy.deepcopy(records)
        changed["diary@Alice"][0]["memory"][field] = value
        with pytest.raises(backup.BackupError):
            backup.make_archive(changed, "1.4.7")


@pytest.mark.parametrize("gate", ["daily_limit", "agent_budget", "unavailable", "fused"])
def test_clarification_waits_until_an_answer_can_be_processed(plugin_factory_full, monkeypatch, gate):
    plugin, shard, calls, _ = prepare(plugin_factory_full, monkeypatch, [record(pending=True)])
    if gate == "daily_limit":
        plugin._fragments_cfg["daily_limit"] = 0
    elif gate == "agent_budget":
        plugin._agent_tier_gate = lambda *_args, **_kwargs: senses._CHANNEL_BUDGET_REASON
    elif gate == "unavailable":
        async def unavailable(*_args, **_kwargs):
            return None, "summary", {}
        plugin._resolve_channel_endpoint = unavailable
    else:
        plugin._channel_break_open = lambda *_args: True
    run(plugin._maybe_clarify_memory("Alice", shard, "Coffee", NOW))
    assert plugin._pushed == [] and calls == []
    assert "clarification_at" not in shard.diary[0]["memory"]


def test_manual_undo_cannot_reset_automatic_cooldowns_or_aging():
    item = record()
    memory.manage_memory([item], item, "pin", now=NOW)
    operations = {
        "aging_started_at": NOW.isoformat(), "clarification_at": NOW.isoformat(),
        "clarification_count": 1, "review_attempted_at": NOW.isoformat(),
    }
    item["memory"].update(operations)
    memory.manage_memory([item], item, "undo", now=NOW + timedelta(seconds=1))
    assert all(item["memory"][field] == value for field, value in operations.items())
    assert not item["memory"].get("pinned")


def test_dialogue_answer_resolves_conflict_through_real_capture_and_persists(plugin_factory_full, monkeypatch):
    plugin, shard, _, _ = prepare(plugin_factory_full, monkeypatch, conflict())
    text = "I prefer Tea now"
    async def poll(*_args, **_kwargs):
        shard.last_recent_marker = "answer"
        shard.last_recent_turn = (text, "Understood")
        return shard.last_recent_turn

    async def answer(*_args, **_kwargs):
        return json.dumps({
            "capture": True, "kind": "like", "quote": text, "confidence": 0.99,
            "relation": "resolve", "target": 1, "resolution_quote": text,
        })

    shard.last_fragment_marker = "asked"
    plugin._poll_recent_turns = poll
    plugin._channel_chat = answer
    assert run(plugin._maybe_capture_fragments("Alice", shard))
    assert len(shard.diary) == 3
    assert [memory.memory_state(item, NOW) for item in shard.diary] == ["superseded", "superseded", "active"]
    assert not run(plugin._maybe_maintain_memories("Alice", shard))
    assert plugin._pushed == []
    restarted = plugin_factory_full(current_lanlan="Alice", store_initial=copy.deepcopy(plugin.store.data))
    restored = restarted._get_shard("Alice")
    assert memory.recall_memories(restored.diary, now=NOW)[0]["quote"] == text
    assert restored.diary == shard.diary
