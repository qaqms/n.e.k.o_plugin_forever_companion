"""One-time upgrade overrides must not become permanent startup defaults."""

from __future__ import annotations

import asyncio
from copy import deepcopy

import pytest
from forever_companion.mixins.shards import _STORE_AGENT_DEFAULTS_MIGRATION as MARKER


def run(coro):
    return asyncio.run(coro)


def old_settings(slot="conversation", budget=20):
    return {
        "review": {"slot": slot, "mode": "custom", "enabled": False, "turns_threshold": 70},
        "agent_tier": {"daily_budget": budget},
        "fragments": {"slot": "summary", "daily_limit": 42},
        "birthday": {"date": "06-12"},
    }


@pytest.mark.parametrize(("slot", "budget"), [("conversation", 20), ("summary", 150), ("agent", 5)])
def test_upgrade_overwrites_explicit_choices_and_preserves_other_data(plugin_factory_full, slot, budget):
    settings = old_settings(slot, budget)
    history = [{"ts": "2026-10-29", "entry": "Keep this entry", "source": "self"}]
    p = plugin_factory_full(store_initial={"settings": settings, "diary@default": deepcopy(history)})
    expected = deepcopy(settings)
    expected["review"]["slot"] = "agent"
    expected["agent_tier"]["daily_budget"] = 100
    assert p.store.data["settings"] == expected
    assert p._settings_snapshot()["review_slot"] == "agent"
    assert p._settings_snapshot()["agent_daily_budget"] == 100
    assert p.store.data[MARKER] is True
    assert p.store.data["diary@default"] == history
    assert settings == old_settings(slot, budget)


def test_fresh_install_overrides_old_toml_and_migrates_only_once(boot_factory, tm):
    p = boot_factory()
    p.config.section.update(review={"slot": "conversation"}, agent_tier={"daily_budget": 20})
    assert isinstance(run(p.startup()), tm.Ok)
    assert p._settings_snapshot()["review_slot"] == "agent"
    assert p._settings_snapshot()["agent_daily_budget"] == 100
    assert p.store.data[MARKER] is True
    assert isinstance(run(p.update_settings(review_slot="summary", agent_daily_budget=35)), tm.Ok)
    run(p.on_config_change())
    run(p._ensure_shard("another"))
    run(p._load_state())
    run(p._refresh_config())
    assert p._settings_snapshot()["review_slot"] == "summary"
    assert p._settings_snapshot()["agent_daily_budget"] == 35


def test_user_changes_survive_new_instances_and_restart(plugin_factory_full, tm):
    p = plugin_factory_full(store_initial={"settings": old_settings()})
    assert isinstance(run(p.update_settings(review_slot="conversation", agent_daily_budget=20)), tm.Ok)
    run(p.shutdown())
    for _ in range(2):
        p = plugin_factory_full(store_initial=deepcopy(p.store.data))
        assert p._settings_snapshot()["review_slot"] == "conversation"
        assert p._settings_snapshot()["agent_daily_budget"] == 20
        run(p.shutdown())


@pytest.mark.parametrize("failed_key", ["settings", MARKER])
def test_migration_retries_after_write_failure(boot_factory, monkeypatch, tm, failed_key):
    p = boot_factory()
    p.store.data["settings"] = old_settings()
    original = p.store.set

    async def fail(key, value):
        if key == failed_key:
            return tm.Err(tm.SdkError("disk_full"))
        return await original(key, value)

    monkeypatch.setattr(p.store, "set", fail)
    run(p.startup())
    assert MARKER not in p.store.data
    if failed_key == "settings":
        assert p.store.data["settings"] == old_settings()
        assert p._settings_snapshot()["review_slot"] == "conversation"
    monkeypatch.setattr(p.store, "set", original)
    run(p.startup())
    assert p.store.data[MARKER] is True
    assert p._settings_snapshot()["review_slot"] == "agent"
    assert p._settings_snapshot()["agent_daily_budget"] == 100


@pytest.mark.parametrize("failed_key", ["settings", MARKER])
def test_failed_reads_never_overwrite_saved_settings(boot_factory, monkeypatch, tm, failed_key):
    p = boot_factory()
    p.store.data["settings"] = old_settings()
    original = p.store.get

    async def fail(key):
        return tm.Err(tm.SdkError("read_failed")) if key == failed_key else await original(key)

    monkeypatch.setattr(p.store, "get", fail)
    run(p.startup())
    assert MARKER not in p.store.data
    assert p.store.data["settings"] == old_settings()
    monkeypatch.setattr(p.store, "get", original)
    run(p.startup())
    assert p.store.data[MARKER] is True
    assert p.store.data["settings"]["birthday"] == old_settings()["birthday"]


def test_invalid_settings_are_not_discarded(boot_factory):
    p = boot_factory()
    p.store.data["settings"] = ["unexpected"]
    run(p.startup())
    assert p.store.data["settings"] == ["unexpected"]
    assert MARKER not in p.store.data


def test_legacy_settings_are_migrated_before_agent_defaults(plugin_factory_full):
    p = plugin_factory_full(store_initial={
        "cycle_state": {"enabled": True, "anchor_date": "2026-08-01", "settings": old_settings()},
    })
    expected = old_settings()
    expected["review"]["slot"] = "agent"
    expected["agent_tier"]["daily_budget"] = 100
    assert p.store.data["settings"] == expected
    assert p.store.data[MARKER] is True
