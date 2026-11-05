"""Memory policy, persistence and archive regressions without a live host."""

import asyncio
import copy
from datetime import datetime, timedelta, timezone

import pytest
from forever_companion.core import backup
from forever_companion.core.memory import (
    MemoryPolicyError,
    apply_capture,
    diary_partition,
    extraction_candidates,
    manage_memory,
    memory_state,
    metadata,
    new_metadata,
    recall_memories,
    reinforce,
)

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def run(coroutine):
    return asyncio.run(coroutine)


def record(index=0, *, days=0, kind="like", memory_type="preference", quote="Coffee"):
    stamp = (NOW - timedelta(days=days, seconds=index)).isoformat()
    parsed = {"kind": kind, "quote": quote, "memory_type": memory_type}
    return {"ts": stamp, "source": "auto", "status": "active", "kind": kind,
            "quote": quote, "note": "Original note", "memory": new_metadata(parsed, stamp)}


def plugin_with(factory, records):
    return factory(current_lanlan="Alice", store_initial={
        "lanlan_index": ["Alice", "Other"], "diary@Alice": copy.deepcopy(records),
        "diary@Other": [{"ts": "other", "entry": "Other role"}],
    })


@pytest.mark.parametrize("size", [0, 1, 120, 121, 300])
def test_capacity_partition_preserves_every_record_in_original_order(size):
    diary = [record(index=i) for i in range(size)]
    original = copy.deepcopy(diary)
    recent, archive = diary_partition(diary), diary_partition(diary, "archive")
    assert len(recent) == min(120, size)
    assert len(archive) == max(0, size - 120)
    assert archive + recent == diary
    assert diary == original


def test_archive_roundtrip_and_restore_does_not_rewrite_event_dates(plugin_factory_full):
    records = [{"ts": f"old-{i}", "source": "self", "entry": str(i)} for i in range(130)]
    plugin = plugin_with(plugin_factory_full, records)
    shard = plugin._get_shard("Alice")
    run(plugin._save_shard_diary("Alice", shard))
    assert plugin.store.data["diary@Alice"] == records
    dashboard = run(plugin.dashboard())
    assert dashboard["diary_total"] == 120 and dashboard["diary_archive_total"] == 10
    archived = run(plugin.get_diary(scope="archive", limit=50)).value
    assert [row["ts"] for row in archived["items"]] == [f"old-{i}" for i in reversed(range(10))]
    assert all(row["in_archive"] for row in archived["items"])
    assert not archived["has_more"]
    result = run(plugin.delete_diary_item(ts="old-0", action="unarchive", expected_lanlan="Alice"))
    assert result.value["removed"] == 0
    assert shard.diary[0]["ts"] == "old-0"
    assert shard.diary[0]["entry"] == "0"
    assert shard.diary[0] in diary_partition(shard.diary)
    restarted = plugin_with(plugin_factory_full, plugin.store.data["diary@Alice"])
    assert restarted._get_shard("Alice").diary == shard.diary


@pytest.mark.parametrize("action", ["pin", "pause", "archive", "correct", "classify", "expire"])
def test_manual_changes_preserve_raw_text_and_can_be_undone(action):
    item = record()
    original = copy.deepcopy(item)
    text = {"correct": "Tea, not coffee", "classify": "temporary", "expire": "2026-11-05"}.get(action, "")
    manage_memory([item], item, action, text=text, now=NOW)
    assert item["quote"] == original["quote"] and item["note"] == original["note"]
    assert metadata(item)["undo"]
    manage_memory([item], item, "undo", now=NOW + timedelta(seconds=1))
    assert memory_state(item, NOW) == memory_state(original, NOW)
    assert {k: v for k, v in metadata(item).items() if k not in {"history", "undo", "updated_at"}} == {
        k: v for k, v in original["memory"].items() if k != "updated_at"
    }
    assert metadata(item)["updated_at"] == (NOW + timedelta(seconds=1)).isoformat()


def test_confirmation_resolves_conflict_and_undo_restores_both_sides():
    old, new = record(days=1), record(quote="Tea")
    new["memory"].update({"pending": True, "conflicts_with": old["ts"]})
    old["memory"].update({"pending": True, "conflicts_with": new["ts"]})
    before = copy.deepcopy([old, new])
    manage_memory([old, new], new, "confirm", now=NOW)
    assert memory_state(new, NOW) == "active"
    assert memory_state(old, NOW) == "pending"
    manage_memory([old, new], new, "undo", now=NOW + timedelta(seconds=1))
    before[0]["memory"]["updated_at"] = (NOW + timedelta(seconds=1)).isoformat()
    assert old == before[0]
    assert memory_state(new, NOW) == "pending"


def test_undo_does_not_overwrite_a_later_related_change():
    old, new = record(days=1), record(quote="Tea")
    new["supersedes"] = old["ts"]
    old["status"] = "superseded"
    manage_memory([old, new], old, "confirm", now=NOW)
    manage_memory([old, new], new, "pin", now=NOW + timedelta(seconds=1))
    before = copy.deepcopy([old, new])
    with pytest.raises(MemoryPolicyError):
        manage_memory([old, new], old, "undo", now=NOW + timedelta(seconds=2))
    assert [old, new] == before


def test_confirming_a_conflict_invalidates_other_sides_earlier_undo():
    old, new = record(days=1), record(quote="Tea")
    new["memory"]["conflicts_with"] = old["ts"]
    manage_memory([old, new], old, "pin", now=NOW)
    assert metadata(old)["undo"]
    manage_memory([old, new], new, "confirm", now=NOW + timedelta(seconds=1))
    assert "undo" not in metadata(old)
    assert memory_state(old, NOW) == "pending"
    with pytest.raises(MemoryPolicyError):
        manage_memory([old, new], old, "undo", now=NOW + timedelta(seconds=2))


def test_confirmation_resolves_entire_replacement_chain_in_both_directions():
    old, middle, latest = record(days=2), record(days=1, quote="Tea"), record(quote="Water")
    middle["supersedes"] = old["ts"]
    latest["supersedes"] = middle["ts"]
    old["status"] = middle["status"] = "superseded"
    diary = [old, middle, latest]
    manage_memory(diary, old, "confirm", now=NOW)
    assert memory_state(old, NOW) == "active" and memory_state(latest, NOW) == "pending"
    manage_memory(diary, latest, "confirm", now=NOW + timedelta(seconds=1))
    assert memory_state(latest, NOW) == "active"
    assert recall_memories(diary, now=NOW) == [latest]
    assert "undo" not in metadata(old)


@pytest.mark.parametrize("state", ["paused", "pending", "superseded", "expired"])
def test_noncurrent_records_never_leak_through_keyword_recall(state):
    item = record()
    if state == "superseded":
        item["status"] = state
    elif state == "expired":
        item["memory"]["valid_until"] = (NOW - timedelta(seconds=1)).isoformat()
    else:
        item["memory"][state] = True
    assert memory_state(item, NOW) == state
    assert recall_memories([item], query="Coffee", now=NOW) == []


def test_decay_is_local_reversible_and_does_not_refresh_on_reads():
    item = record(days=181)
    original = copy.deepcopy(item)
    assert memory_state(item, NOW) == "dormant"
    assert recall_memories([item], now=NOW) == []
    for _ in range(5):
        assert recall_memories([item], query="Coffee", now=NOW) == [item]
    assert item == original
    assert reinforce(item, {"quote": "Still coffee"}, NOW.isoformat())
    assert memory_state(item, NOW) == "active"
    assert metadata(item)["confirmations"] == 2


@pytest.mark.parametrize("kind", ["dislike", "overstep"])
def test_boundaries_and_hurtful_events_do_not_expire_by_model_choice(kind):
    parsed = {"kind": kind, "quote": "Boundary", "memory_type": "boundary"}
    item = record(days=3000, kind=kind)
    item["memory"] = new_metadata(parsed, item["ts"])
    assert memory_state(item, NOW) == "active"
    parsed.update({"kind": "overstep", "memory_type": "temporary", "valid_until": "2026-11-04"})
    assert new_metadata(parsed, NOW.isoformat(), user_text="2026-11-04")["type"] == "boundary"


def test_same_day_repetitions_do_not_inflate_confirmation_or_evidence():
    item = record(days=2)
    assert reinforce(item, {"quote": "Coffee"}, NOW.isoformat())
    before = copy.deepcopy(item)
    assert not reinforce(item, {"quote": "Coffee"}, (NOW + timedelta(hours=23)).isoformat())
    assert item == before
    for day in range(1, 14):
        assert reinforce(item, {"quote": "Coffee"}, (NOW + timedelta(days=day)).isoformat())
    assert len(metadata(item)["evidence"]) == 8


def test_temporary_dates_are_grounded_and_use_local_midnight():
    local_now = NOW.astimezone(timezone(timedelta(hours=8)))
    parsed = {"kind": "important", "quote": "Today", "memory_type": "temporary"}
    meta = new_metadata(parsed, NOW.isoformat(), user_text="今天不想说话", local_now=local_now)
    assert meta["valid_until"] == "2026-11-05T00:00:00+08:00"
    item = {**record(), "memory": meta}
    assert memory_state(item, datetime(2026, 11, 4, 15, 59, tzinfo=timezone.utc)) == "active"
    assert memory_state(item, datetime(2026, 11, 4, 16, tzinfo=timezone.utc)) == "expired"
    meta = new_metadata({**parsed, "valid_until": "2030-01-01"}, NOW.isoformat(), user_text="有点累")
    assert meta["pending"] and "valid_until" not in meta


def test_pinning_does_not_extend_a_temporary_expiry():
    item = record()
    item["memory"]["valid_until"] = (NOW - timedelta(seconds=1)).isoformat()
    manage_memory([item], item, "pin", now=NOW)
    assert memory_state(item, NOW) == "expired"
    manage_memory([item], item, "confirm", now=NOW)
    assert memory_state(item, NOW) == "active"


def test_legacy_records_are_not_silently_aged_or_rewritten():
    item = {"ts": "2000-01-01", "source": "auto", "kind": "like", "quote": "Coffee"}
    original = copy.deepcopy(item)
    assert recall_memories([item], now=NOW) == [item]
    assert item == original


@pytest.mark.parametrize("action", ["archive", "unarchive", "pin", "unpin", "pause", "resume"])
def test_organizing_legacy_record_does_not_create_an_aging_baseline(action):
    item = {"ts": "2000-01-01", "source": "auto", "kind": "like", "quote": "Coffee"}
    manage_memory([item], item, action, now=NOW)
    assert "last_confirmed_at" not in metadata(item)
    assert memory_state(item, NOW) == ("paused" if action == "pause" else "active")
    assert item["ts"] == "2000-01-01" and item["quote"] == "Coffee"


@pytest.mark.parametrize(("action", "text"), [("classify", "event"), ("expire", "2026-11-05")])
def test_changing_type_or_expiry_cannot_silently_resolve_conflict(action, text):
    item = record()
    item["memory"].update({"pending": True, "conflicts_with": "another"})
    manage_memory([item], item, action, text=text, now=NOW)
    assert memory_state(item, NOW) == "pending"
    manage_memory([item], item, "confirm", now=NOW)
    assert memory_state(item, NOW) == "active"


def test_candidate_search_reaches_old_archive_without_enlarging_prompt():
    diary = [record(index=i, quote="Unrelated") for i in range(130)]
    diary[0]["quote"] = "Coffee is my favorite"
    assert diary[0] in diary_partition(diary, "archive")
    selected = extraction_candidates(diary, "Coffee")
    assert len(selected) <= 10
    assert any(item["ts"] == diary[0]["ts"] for item in selected)


def test_conditions_and_uncertainty_do_not_silently_replace_facts():
    old, new = record(), record(quote="No coffee at night")
    new["memory"]["condition"] = "at night"
    parsed = {"relation": "supersede", "target": 1}
    assert apply_capture([old], [copy.deepcopy(old)], parsed, new) == "new"
    assert old["status"] == "active" and "supersedes" not in new
    old, new = record(days=1), record(quote="Tea")
    diary = [old]
    apply_capture(diary, [copy.deepcopy(old)], {"relation": "conflict", "target": 1}, new)
    assert memory_state(old, NOW) == memory_state(new, NOW) == "pending"


def test_stale_capture_target_and_user_correction_are_protected():
    old = record(days=1)
    existing = [copy.deepcopy(old)]
    manage_memory([old], old, "correct", text="Tea", now=NOW)
    new = record(quote="Coffee again")
    apply_capture([old], existing, {"relation": "supersede", "target": 1}, new)
    assert metadata(old)["correction"] == "Tea" and old["status"] == "active"
    newer = record(quote="More coffee")
    apply_capture([old], [copy.deepcopy(old)], {"relation": "supersede", "target": 1}, newer)
    assert memory_state(newer, NOW) == "pending"


def test_paused_record_is_not_resurrected_by_recapture():
    old = record(days=1)
    manage_memory([old], old, "pause", now=NOW)
    diary = [old]
    assert apply_capture(diary, [], {"relation": "new", "quote": "Coffee"}, record()) == "duplicate"
    assert diary == [old] and memory_state(old, NOW) == "paused"


def test_management_persists_restarts_and_recall_does_not_strengthen(plugin_factory_full):
    plugin = plugin_with(plugin_factory_full, [record()])
    for action in ["pin", "pause", "resume"]:
        result = run(plugin.delete_diary_item(ts=record()["ts"], action=action, expected_lanlan="Alice"))
        assert result.value["action"] == action
    shard = plugin._get_shard("Alice")
    before = copy.deepcopy(shard.diary)
    for _ in range(3):
        result = run(plugin.tool_recall_fragments(query="Coffee"))
        assert result.value["found"] == 1
    assert shard.diary == before
    restarted = plugin_with(plugin_factory_full, plugin.store.data["diary@Alice"])
    assert restarted._get_shard("Alice").diary == before
    assert plugin.store.data["diary@Other"] == [{"ts": "other", "entry": "Other role"}]


def test_management_failure_and_role_change_preserve_data(plugin_factory_full, tm):
    plugin = plugin_with(plugin_factory_full, [record()])
    shard = plugin._get_shard("Alice")
    before = copy.deepcopy(shard.diary)
    result = run(plugin.delete_diary_item(ts=record()["ts"], action="pause", expected_lanlan="Other"))
    assert str(result.error) == "mood_changed" and shard.diary == before
    async def fail(*_args):
        return tm.Err(tm.SdkError("disk full"))
    plugin.store.set = fail
    result = run(plugin.delete_diary_item(ts=record()["ts"], action="pause", expected_lanlan="Alice"))
    assert str(result.error) == "persist_failed" and shard.diary == before


def test_portable_backup_keeps_archive_evidence_corrections_and_undo():
    records = [record(index=i) for i in range(130)]
    manage_memory(records, records[0], "correct", text="Tea", now=NOW)
    source = {"lanlan_index": ["Alice"], "diary@Alice": records, "gallery_index": {"items": []}}
    content, _ = backup.make_archive(source, "1.4.7")
    restored, _ = backup.read_archive(content)
    assert restored == source
    saved = restored["diary@Alice"][0]
    manage_memory(restored["diary@Alice"], saved, "undo", now=NOW)
    assert "correction" not in metadata(saved) and saved["quote"] == "Coffee"


@pytest.mark.parametrize("bad", [
    {"schema": 2}, {"evidence": "bad"}, {"confirmations": -1},
    {"undo": [{"memory": {"undo": []}}]}, {"undo": [{"memory": {}, "related": [3]}]},
    {"type": "unknown"}, {"confirmations": 0}, {"confirmations": 10001},
    {"undo": [{"memory": {}, "status": "active"}]},
    {"undo": [{"memory": {}, "status": "active", "had_memory": True, "had_status": True,
               "related": [{"memory": {}, "ts": "other"}]}]},
])
def test_backup_rejects_invalid_or_future_policy_without_mutating_source(bad):
    source = {"lanlan_index": ["Alice"], "diary@Alice": [{**record(), "memory": bad}], "gallery_index": {"items": []}}
    before = copy.deepcopy(source)
    with pytest.raises(backup.BackupError):
        backup.make_archive(source, "1.4.7")
    assert source == before


def test_duplicate_conditions_remain_separate_and_temporary_renewal_does_not_inflate_strength():
    old, new = record(days=1), record(quote="Coffee after lunch")
    new["memory"]["condition"] = "after lunch"
    diary = [old]
    assert apply_capture(diary, [copy.deepcopy(old)], {"relation": "duplicate", "target": 1}, new) == "new"
    assert diary == [old, new] and metadata(old)["confirmations"] == 1
    temporary = record(memory_type="temporary")
    temporary["memory"].update({"valid_until": "2026-11-05T00:00:00Z", "pending": False})
    manage_memory([temporary], temporary, "pin", now=NOW)
    renewal = record(memory_type="temporary")
    renewal["memory"].update({"valid_until": "2026-11-06T00:00:00Z", "pending": False})
    assert apply_capture([temporary], [copy.deepcopy(temporary)], {"relation": "duplicate", "target": 1}, renewal) == "reinforced"
    assert metadata(temporary)["confirmations"] == 1
    assert metadata(temporary)["valid_until"] == "2026-11-06T00:00:00Z"
    assert "undo" not in metadata(temporary)


@pytest.mark.parametrize("relation", ["supersede", "conflict"])
def test_automatic_updates_invalidate_undo_of_earlier_manual_policy(relation):
    old = record(days=1)
    manage_memory([old], old, "pin", now=NOW)
    newer = record(quote="Tea")
    newer["ts"] = (NOW + timedelta(seconds=2)).isoformat()
    apply_capture([old], [copy.deepcopy(old)], {"relation": relation, "target": 1}, newer)
    assert "undo" not in metadata(old)
    assert metadata(old)["updated_at"] == newer["ts"]
    with pytest.raises(MemoryPolicyError):
        manage_memory([old], old, "undo", now=NOW + timedelta(seconds=3))


def test_paused_recapture_cannot_mutate_a_different_supersede_target():
    paused, target = record(), record(days=1, quote="Tea")
    manage_memory([paused], paused, "pause", now=NOW)
    diary = [target, paused]
    before = copy.deepcopy(diary)
    assert apply_capture(diary, [copy.deepcopy(target)], {
        "relation": "supersede", "target": 1, "quote": "Coffee",
    }, record()) == "duplicate"
    assert diary == before


def test_capacity_failure_retains_original_store_and_in_memory_history(plugin_factory_full):
    plugin = plugin_with(plugin_factory_full, [record()])
    shard = plugin._get_shard("Alice")
    before = copy.deepcopy(shard.diary)
    huge = {"source": "self", "ts": "new", "entry": "x" * (16 * 1024 * 1024)}
    result = run(plugin._update_shard_diary("Alice", shard, lambda diary: diary.append(huge)))
    assert str(result.error) == "memory_capacity_reached"
    assert shard.diary == plugin.store.data["diary@Alice"] == before
    assert not shard.diary_save_lock.locked()


@pytest.mark.parametrize("fail", [False, True])
def test_concurrent_write_is_rejected_before_mutation_and_cannot_be_lost_on_rollback(plugin_factory_full, tm, fail):
    plugin = plugin_with(plugin_factory_full, [record()])
    shard = plugin._get_shard("Alice")
    before = copy.deepcopy(shard.diary)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = plugin.store.set

        async def delayed(key, value):
            entered.set()
            await release.wait()
            return tm.Err(tm.SdkError("disk full")) if fail else await original(key, value)

        plugin.store.set = delayed
        first = asyncio.create_task(plugin._update_shard_diary("Alice", shard, lambda diary: diary.append({"ts": "first"})))
        await entered.wait()
        second = await plugin._update_shard_diary("Alice", shard, lambda diary: diary.append({"ts": "second"}))
        assert str(second.error) == "backup_busy"
        assert not any(item["ts"] == "second" for item in shard.diary)
        release.set()
        await first

    run(scenario())
    expected = before if fail else [*before, {"ts": "first"}]
    assert shard.diary == plugin.store.data["diary@Alice"] == expected
    assert not shard.diary_save_lock.locked()


@pytest.mark.parametrize("fail", [False, True])
def test_cancellation_keeps_lock_until_store_outcome_is_known(plugin_factory_full, tm, fail):
    plugin = plugin_with(plugin_factory_full, [record()])
    shard = plugin._get_shard("Alice")
    before = copy.deepcopy(shard.diary)

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = plugin.store.set

        async def delayed(key, value):
            entered.set()
            await release.wait()
            return tm.Err(tm.SdkError("disk full")) if fail else await original(key, value)

        plugin.store.set = delayed
        task = asyncio.create_task(plugin._update_shard_diary("Alice", shard, lambda diary: diary.append({"ts": "new"})))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert shard.diary_save_lock.locked() and not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    run(scenario())
    assert shard.diary == plugin.store.data["diary@Alice"] == (before if fail else [*before, {"ts": "new"}])
    assert not shard.diary_save_lock.locked()
