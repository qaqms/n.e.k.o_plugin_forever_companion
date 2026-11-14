import asyncio
from types import SimpleNamespace

import pytest
from forever_companion.core.state import _CYCLE_AGENT_BUDGET_LAST_TS, tier_budget_used
from forever_companion.services.model_gateway import ModelGateway


def client_for(content="ok", error=None):
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        if error is not None:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    async def get_client():
        return client

    return SimpleNamespace(get_client=get_client), calls


def test_gateway_uses_declared_usage_and_never_resolves_provider_config(plugin_factory_full, monkeypatch):
    plugin = plugin_factory_full()
    models, calls = client_for("A diary.")
    plugin.ctx.models = models

    def forbidden(*_, **__):
        raise AssertionError("legacy transport was used")

    monkeypatch.setattr(plugin, "_resolve_host_slot", forbidden)
    monkeypatch.setattr(plugin, "_load_core_config", forbidden)
    plugin._review_cfg["mode"] = "gateway"

    async def scenario():
        resolved, slot, config = await plugin._resolve_channel_endpoint(
            plugin._review_cfg, default_slot="agent", usage="writing",
        )
        assert slot == "agent" and config == {}
        assert plugin._model_gateway.readiness("writing") == "unverified"
        result = await plugin._channel_chat(
            resolved, "Write a diary.", timeout_sec=1,
            max_completion_tokens=1200, call_type="review",
        )
        assert result == "A diary."
        assert plugin._model_gateway.readiness("writing") == ""

    asyncio.run(scenario())
    assert calls == [{
        "model": "writing", "messages": [{"role": "user", "content": "Write a diary."}],
        "max_completion_tokens": 1200,
    }]


def test_unavailable_gateway_fails_without_legacy_fallback(plugin_factory_full):
    plugin = plugin_factory_full()
    assert plugin._model_gateway.readiness("fragments") == "no_model"
    assert asyncio.run(plugin._model_gateway.chat(
        "fragments", "private text", timeout_sec=1, max_completion_tokens=400,
    )) is None


def test_gateway_errors_are_redacted_and_unbound_is_not_reported_ready():
    class Forbidden(Exception):
        status_code = 403

    models, _ = client_for(error=Forbidden("credential and private text"))
    messages = []
    logger = SimpleNamespace(warning=lambda *args: messages.append(args))
    gateway = ModelGateway(SimpleNamespace(models=models), logger=lambda: logger)
    assert asyncio.run(gateway.chat("writing", "private text", timeout_sec=1, max_completion_tokens=20)) is None
    assert gateway.readiness("writing") == "no_model"
    assert "credential" not in repr(messages) and "private text" not in repr(messages)


def test_gateway_preserves_manual_timeout_reason():
    models, _ = client_for(error=TimeoutError("private"))
    gateway = ModelGateway(SimpleNamespace(models=models))
    with pytest.raises(TimeoutError):
        asyncio.run(gateway.chat("writing", "text", timeout_sec=1, max_completion_tokens=20, raise_timeout=True))


def test_cancellation_propagates_without_changing_gateway_readiness():
    models, _ = client_for(error=asyncio.CancelledError())
    gateway = ModelGateway(SimpleNamespace(models=models))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(gateway.chat("writing", "text", timeout_sec=1, max_completion_tokens=20))
    assert gateway.readiness("writing") == "unverified"


def test_tone_gateway_uses_tone_usage_and_keeps_fragment_pacing(plugin_factory_full):
    plugin = plugin_factory_full()
    models, calls = client_for('{"emotion":"happy","confidence":0.9}')
    plugin.ctx.models = models
    plugin._emotion_sense_cfg["slot"] = "gateway"
    shard = plugin._get_shard("default")
    shard.cycle[_CYCLE_AGENT_BUDGET_LAST_TS] = 123.0
    before = tier_budget_used(shard.cycle, str(plugin._today_str()))
    result = asyncio.run(plugin._analyze_turn_tone("An enjoyable day.", "default"))
    assert result == ("happy", 0.9)
    assert calls[0]["model"] == "tone"
    assert shard.cycle[_CYCLE_AGENT_BUDGET_LAST_TS] == 123.0
    assert tier_budget_used(shard.cycle, str(plugin._today_str())) == before + 1
    assert len(calls) == 1


def test_gateway_settings_survive_reload(plugin_factory_full, tm):
    plugin = plugin_factory_full()
    result = asyncio.run(plugin.update_settings(
        fragments_mode="gateway", review_mode="gateway", tone_slot="gateway",
    ))
    assert isinstance(result, tm.Ok)
    asyncio.run(plugin._refresh_config())
    assert plugin._fragments_cfg["mode"] == "gateway"
    assert plugin._review_cfg["mode"] == "gateway"
    assert plugin._emotion_sense_cfg["slot"] == "gateway"


def test_gateway_circuit_retries_after_rebinding_window(plugin_factory_full, monkeypatch):
    plugin = plugin_factory_full()
    clock = [100.0]
    monkeypatch.setattr("time.monotonic", lambda: clock[0])
    for _ in range(2):
        plugin._channel_break_note("Alice", "review", "gateway|agent", ok=False)
    assert plugin._channel_break_open("Alice", "review", "gateway|agent")
    clock[0] += 60.1
    assert not plugin._channel_break_open("Alice", "review", "gateway|agent")


@pytest.mark.parametrize("entry", ["journal", "review", "auto_review"])
def test_real_writing_flow_uses_writing_usage_and_counts_budget_with_legacy_slot(
    plugin_factory_full, monkeypatch, entry,
):
    plugin = plugin_factory_full(current_lanlan="Alice")
    shard = asyncio.run(plugin._ensure_shard("Alice"))
    shard.review_stats = {"turns": 60}
    plugin._review_cfg.update(mode="gateway", slot="summary")
    models, calls = client_for('{"title":"An evening","text":"We spent a quiet evening together."}')
    plugin.ctx.models = models

    async def recent(*_, **__):
        return "A quiet evening.", "I enjoyed it."

    monkeypatch.setattr(plugin, "_poll_recent_turns", recent)
    if entry == "auto_review":
        assert asyncio.run(plugin._maybe_write_review("Alice", shard))[0]
    else:
        action = plugin.invite_journal if entry == "journal" else plugin.write_review_now
        drain = plugin._drain_pending_journal_writes if entry == "journal" else plugin._drain_pending_review_writes
        assert asyncio.run(action()).value["accepted"]
        asyncio.run(drain())
    assert [call["model"] for call in calls] == ["writing"]
    assert tier_budget_used(shard.cycle, str(plugin._today_str())) == 1
    assert len(shard.journal if entry == "journal" else shard.review) == 1


@pytest.mark.parametrize("entry", ["journal", "review"])
def test_gateway_writing_cannot_bypass_exhausted_budget_with_legacy_slot(plugin_factory_full, monkeypatch, entry):
    plugin = plugin_factory_full(current_lanlan="Alice")
    shard = asyncio.run(plugin._ensure_shard("Alice"))
    shard.review_stats = {"turns": 20}
    plugin._review_cfg.update(mode="gateway", slot="summary")
    plugin._agent_tier_cfg["daily_budget"] = 5
    shard.cycle.update(agent_budget_date=str(plugin._today_str()), agent_budget_used=5)
    models, calls = client_for()
    plugin.ctx.models = models

    async def recent(*_, **__):
        return "A quiet evening.", "I enjoyed it."

    monkeypatch.setattr(plugin, "_poll_recent_turns", recent)
    result = asyncio.run((plugin.invite_journal if entry == "journal" else plugin.write_review_now)()).value
    assert result["accepted"] is False
    assert result.get("dormant_reason") == "budget" or result["reason"] == "budget_exhausted"
    assert calls == []
