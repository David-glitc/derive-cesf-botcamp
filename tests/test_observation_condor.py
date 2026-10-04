"""Native Condor scheduler tests with fixture transports and accelerated time."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("condor.agents.engine", reason="Requires official Condor checkout/environment")

from condor.agents import engine
from condor.agents.agent import AgentStore
from condor.agents.config import AgentConfig
from condor.agents.providers import list_providers, _REGISTRY, ProviderResult
from condor.agents.strategy import StrategyStore
from condor.acp.client import TextChunk, PromptDone
from condor.runtime import toolsets
from condor.runtime.registry_file import read_status, LoopState
from scripts.install_condor import install
from src.runtime.bridge import RuntimeBridge
from src.runtime.condor_adapter import install_runtime
from src.runtime.observation import ObservationWindow
from tests.test_observation import profile
from tests.test_runtime_bridge import context, NOW


@pytest.fixture
def seat(tmp_path, monkeypatch):
    for name, value in {"CONDOR_STOCK_AGENTS_ROOT": tmp_path / "stock", "CONDOR_AGENTS_ROOT": tmp_path / "local",
                        "CONDOR_RUNTIME_ROOT": tmp_path / "runtime", "CONDOR_DATA_DIR": tmp_path / "data",
                        "CONDOR_REPORTS_DIR": tmp_path / "reports"}.items():
        monkeypatch.setenv(name, str(value))
    install(tmp_path / "stock")
    list_providers()
    old_registry = dict(_REGISTRY)
    for provider in list_providers():
        monkeypatch.setattr(provider, "execute", AsyncMock(return_value=ProviderResult(provider.name, {}, "fixture")))
    for name in ("_tick", "_run_shutdown", "_adopt_running_bots"):
        monkeypatch.setattr(engine.TickEngine, name, getattr(engine.TickEngine, name))
    monkeypatch.setattr(toolsets, "build_mcp_servers_for_session", lambda *a, **k: [])
    monkeypatch.setattr(engine, "build_gated_client", lambda s, r, c, mode:
        toolsets.build_mcp_servers_for_session(s.user_id, 0, agent_slug=s.agent.slug, tick=True))
    clock = [0.]
    bridge = RuntimeBridge(tmp_path / "feed", "unit", "a" * 64)
    bridge.publish(context(), "hb-session", "observe", NOW)
    strategy = StrategyStore().get_by_key("flyby.flyby_operator")
    tick = engine.TickEngine(agent=AgentStore().get("flyby"), strategy=strategy,
        config=AgentConfig.from_dict(profile()).to_engine_dict(), chat_id=0, user_id=8)
    monkeypatch.setattr(tick, "_get_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(tick, "_notify", AsyncMock())
    try:
        yield tick, bridge, clock
    finally:
        engine._supervisor().unregister(tick.agent_id, LoopState.STOPPED)
        _REGISTRY.clear()
        _REGISTRY.update(old_registry)


def test_actual_native_loop_observes_and_finishes_after_48_virtual_hours(seat, monkeypatch):
    tick, bridge, clock = seat
    window = ObservationWindow(clock=lambda: clock[0])
    adopt = AsyncMock(side_effect=AssertionError("observer must not adopt"))
    shutdown = AsyncMock(side_effect=AssertionError("observer must not wind down"))
    monkeypatch.setattr(engine.TickEngine, "_adopt_running_bots", adopt)
    monkeypatch.setattr(engine.TickEngine, "_run_shutdown", shutdown)
    install_runtime(bridge, operator_user_id=8, observation_window=window, clock=lambda: NOW + clock[0])
    model = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), prompts=[])
    async def stream(prompt):
        model.prompts.append(prompt)
        yield TextChunk("OBSERVE: fixture context; fills and PnL unverified")
        yield PromptDone("end_turn")
    model.prompt_stream = stream
    monkeypatch.setattr(tick, "_create_client", AsyncMock(return_value=model))
    async def accelerated_sleep(seconds):
        assert seconds == 60
        clock[0] += 16 * 3600  # scheduler sleep only; no real waiting or provider use
        bridge.publish(context(), "hb-session", "observe", NOW + clock[0])
    monkeypatch.setattr(engine.asyncio, "sleep", accelerated_sleep)
    tick._running = True
    engine._supervisor().register(tick)
    asyncio.run(tick._loop())
    assert len(model.prompts) == tick.journal.tick_count == 3
    assert all("Flyby runtime: seq=" in p for p in model.prompts)
    assert not tick.is_experiment and tick._finished and not tick._running
    assert tick._last_stop_reason == "observation_deadline"
    assert model.start.await_count == model.stop.await_count == 3
    assert adopt.await_count == shutdown.await_count == 0
    assert tick.ledger.bases() == [] and bridge._journal()["receipts"] == {}
    assert "--enable-controls" not in engine.build_gated_client(tick, None, None, "loop")[-1]["args"]
    assert read_status(tick.session_dir)["state"] == LoopState.COMPLETED


def test_observer_shutdown_stops_only_session_and_unrelated_seat_keeps_behavior(seat, monkeypatch):
    tick, bridge, clock = seat
    shutdown = AsyncMock()
    adopt = AsyncMock()
    monkeypatch.setattr(engine.TickEngine, "_run_shutdown", shutdown)
    monkeypatch.setattr(engine.TickEngine, "_adopt_running_bots", adopt)
    install_runtime(bridge, operator_user_id=8, observation_window=ObservationWindow(clock=lambda: clock[0]))
    asyncio.run(tick._run_shutdown("risk fixture"))
    assert tick._last_stop_reason == "observation_risk_alert" and shutdown.await_count == 0
    other = SimpleNamespace(user_id=9, agent=tick.agent, strategy=tick.strategy)
    asyncio.run(engine.TickEngine._run_shutdown(other, "other"))
    asyncio.run(engine.TickEngine._adopt_running_bots(other, object()))
    assert shutdown.await_count == adopt.await_count == 1


def test_native_loop_survives_repeated_fixture_errors_until_deadline(seat, monkeypatch):
    tick, bridge, clock = seat
    failure = AsyncMock(side_effect=RuntimeError("fixture outage"))
    monkeypatch.setattr(engine.TickEngine, "_tick", failure)
    install_runtime(bridge, operator_user_id=8, observation_window=ObservationWindow(clock=lambda: clock[0]))
    async def advance(seconds):
        clock[0] += 24 * 3600
    monkeypatch.setattr(engine.asyncio, "sleep", advance)
    tick._running = True
    engine._supervisor().register(tick)
    asyncio.run(tick._loop())
    assert failure.await_count == 2 and tick._last_stop_reason == "observation_deadline"
    assert tick._notify.await_count == 1  # native repeated-error suppression


def test_whole_tick_timeout_cancels_gather_and_reaps_client(seat, monkeypatch):
    tick, bridge, clock = seat
    cancelled = []
    async def hung(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    monkeypatch.setattr(engine.TickEngine, "_tick", hung)
    install_runtime(bridge, operator_user_id=8, observation_window=ObservationWindow(.02))
    reap = AsyncMock()
    monkeypatch.setattr(tick, "_reap_client", reap)
    asyncio.run(tick._tick())
    assert cancelled and tick._last_stop_reason == "observation_deadline"
    assert reap.await_count >= 1


def test_missing_setup_or_code_capable_model_stops_before_api(seat):
    tick, bridge, clock = seat
    install_runtime(bridge, operator_user_id=8, observation_window=ObservationWindow())
    tick.config["agent_key"] = "claude-code"
    asyncio.run(tick._tick())
    assert tick._last_stop_reason == "observation_setup_or_clock_invalid"
    assert tick._get_client.await_count == 0


def test_controls_cannot_be_enabled_with_observation(seat):
    tick, bridge, clock = seat
    writable = RuntimeBridge(bridge.root, "unit", "a" * 64, writable=True)
    with pytest.raises(ValueError, match="read_only"):
        install_runtime(writable, operator_user_id=8, observation_window=ObservationWindow())


def test_native_risk_shutdown_path_never_reaches_exchange_winddown(seat, monkeypatch):
    from condor.agents.risk import RiskState
    tick, bridge, clock = seat
    shutdown = AsyncMock(side_effect=AssertionError("no exchange winddown"))
    monkeypatch.setattr(engine.TickEngine, "_run_shutdown", shutdown)
    install_runtime(bridge, operator_user_id=8, observation_window=ObservationWindow(clock=lambda: clock[0]))
    monkeypatch.setattr(tick.risk, "get_state", lambda tracker:
                        RiskState(should_shutdown=True, shutdown_reason="fixture loss"))
    model = AsyncMock()
    monkeypatch.setattr(tick, "_create_client", model)
    asyncio.run(tick._tick())
    assert tick._last_stop_reason == "observation_risk_alert"
    assert shutdown.await_count == model.await_count == 0
