import asyncio


def test_poll_reuses_authorization_frame_without_supervision_side_effects(plugin_factory_full, monkeypatch):
    plugin = plugin_factory_full()

    async def forbidden():
        raise AssertionError("dashboard must not supervise host settings")

    monkeypatch.setattr(plugin, "_supervise_once", forbidden)

    async def scenario():
        snapshot = await plugin.dashboard()

        async def duplicate():
            raise AssertionError("poll recomputed its authorization frame")

        monkeypatch.setattr(plugin, "dashboard", duplicate)
        assert (await plugin.poll_dashboard()).value == snapshot

    asyncio.run(scenario())


def test_direct_poll_builds_a_frame_and_busy_gate_does_not_return_old_data(plugin_factory_full, tm):
    plugin = plugin_factory_full()
    assert isinstance(asyncio.run(plugin.poll_dashboard()), tm.Ok)
    assert plugin._data_gate.enter(exclusive=True)
    try:
        result = asyncio.run(plugin.poll_dashboard())
        assert isinstance(result, tm.Err) and str(result.error) == "backup_busy"
    finally:
        plugin._data_gate.leave(exclusive=True)
