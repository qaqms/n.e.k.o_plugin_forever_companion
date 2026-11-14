import asyncio

import pytest


@pytest.mark.parametrize("lookup,path", [
    ("_fetch_known_catgirls", "/api/characters"),
    ("_tone_slot_options", "/api/config/core_api"),
])
def test_failed_panel_lookups_pause_briefly_then_recover(plugin_factory_full, monkeypatch, lookup, path):
    plugin = plugin_factory_full()
    clock = [100.0]
    calls = []
    monkeypatch.setattr("time.monotonic", lambda: clock[0])

    async def http(_, target, **kwargs):
        assert target == path
        calls.append(target)
        if len(calls) == 1:
            return None
        return {"猫娘": {"Alice": {}}} if target == "/api/characters" else {"agentModelId": "bound-model"}

    plugin._proactive_http = http
    read = getattr(plugin, lookup)
    first = asyncio.run(read())
    assert asyncio.run(read()) == first
    assert len(calls) == 1
    if lookup == "_fetch_known_catgirls":
        assert first is None
    clock[0] += 5.1
    recovered = asyncio.run(read())
    assert len(calls) == 2
    if lookup == "_fetch_known_catgirls":
        assert recovered == {"Alice"}
    else:
        assert next(item for item in recovered if item["value"] == "agent")["model"] == "bound-model"
    clock[0] += 10
    assert asyncio.run(read()) == recovered
    assert len(calls) == 2


def test_missing_legacy_config_is_cached_without_reading_again_until_expiry(plugin_factory_full, monkeypatch):
    plugin = plugin_factory_full()
    clock = [100.0]
    calls = []
    monkeypatch.setattr("time.monotonic", lambda: clock[0])

    def path():
        calls.append(True)
        return None

    plugin._core_config_path = path
    assert plugin._load_core_config() == {}
    assert plugin._load_core_config() == {}
    assert len(calls) == 1
    clock[0] += 5.1
    assert plugin._load_core_config() == {}
    assert len(calls) == 2
