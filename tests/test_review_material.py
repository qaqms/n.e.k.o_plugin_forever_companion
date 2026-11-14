import asyncio
import copy
import json

from forever_companion.core import backup


def test_material_updates_do_not_rewrite_diary_text_and_survive_reload(plugin_factory_full, tm):
    plugin = plugin_factory_full()
    shard = asyncio.run(plugin._ensure_shard("Alice"))
    shard.review = [{"ts": "2026-11-01", "text": "A" * 140_000}]
    shard.review_stats = {"turns": 1}
    assert isinstance(asyncio.run(plugin._save_shard_review("Alice", shard)), tm.Ok)
    full = copy.deepcopy(plugin.store.data["review@Alice"])
    shard.review_stats["turns"] = 2
    assert isinstance(asyncio.run(plugin._save_review_material("Alice", shard)), tm.Ok)
    assert plugin.store.data["review@Alice"] == full
    material = plugin.store.data["review_stats@Alice"]
    assert len(json.dumps(material)) < len(json.dumps(full)) / 100
    plugin._shards.pop("Alice")
    loaded = asyncio.run(plugin._ensure_shard("Alice"))
    assert loaded.review_stats["turns"] == 2
    assert loaded.review == shard.review


def test_successful_full_snapshot_atomically_retires_old_material(plugin_factory_full):
    plugin = plugin_factory_full()
    shard = asyncio.run(plugin._ensure_shard("Alice"))
    shard.review_stats = {"turns": 50}
    asyncio.run(plugin._save_shard_review("Alice", shard))
    asyncio.run(plugin._save_review_material("Alice", shard))
    old_material = copy.deepcopy(plugin.store.data["review_stats@Alice"])
    shard.review = [{"text": "The completed diary."}]
    shard.review_stats = {"turns": 0}
    asyncio.run(plugin._save_shard_review("Alice", shard))
    assert plugin.store.data["review_stats@Alice"] == old_material
    plugin._shards.pop("Alice")
    loaded = asyncio.run(plugin._ensure_shard("Alice"))
    assert loaded.review_stats["turns"] == 0
    assert loaded.review[0]["text"] == "The completed diary."


def test_failed_full_snapshot_keeps_previous_material_generation(plugin_factory_full, tm):
    plugin = plugin_factory_full()
    shard = asyncio.run(plugin._ensure_shard("Alice"))
    shard.review_stats = {"turns": 5}
    asyncio.run(plugin._save_shard_review("Alice", shard))
    shard.review_stats["turns"] = 8
    asyncio.run(plugin._save_review_material("Alice", shard))
    previous = shard.review_revision
    original = plugin.store.set

    async def fail(key, value):
        return tm.Err(tm.SdkError("disk full")) if key == "review@Alice" else await original(key, value)

    plugin.store.set = fail
    shard.review_stats = {"turns": 0}
    assert isinstance(asyncio.run(plugin._save_shard_review("Alice", shard)), tm.Err)
    assert shard.review_revision == previous
    plugin._shards.pop("Alice")
    assert asyncio.run(plugin._ensure_shard("Alice")).review_stats["turns"] == 8


def test_backup_round_trip_preserves_revision_and_material():
    revision = "a" * 32
    records = {
        "lanlan_index": ["Alice"],
        "gallery_index": {"next": 1, "items": []},
        "review@Alice": {"entries": [], "stats": {"turns": 5}, "revision": revision},
        "review_stats@Alice": {"turns": 8, "_base": revision},
    }
    content, _ = backup.make_archive(records, "1.4.7")
    restored, _ = backup.read_archive(content)
    assert restored == records


def test_cancellation_waits_for_review_generation_commit(plugin_factory_full, tm):
    plugin = plugin_factory_full()
    shard = asyncio.run(plugin._ensure_shard("Alice"))

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        original = plugin.store.set

        async def delayed(key, value):
            if key == "review@Alice":
                entered.set()
                await release.wait()
            return await original(key, value)

        plugin.store.set = delayed
        task = asyncio.create_task(plugin._save_shard_review("Alice", shard))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert shard.review_save_lock.locked()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert shard.review_revision == plugin.store.data["review@Alice"]["revision"]
        assert not shard.review_save_lock.locked()

    asyncio.run(scenario())
