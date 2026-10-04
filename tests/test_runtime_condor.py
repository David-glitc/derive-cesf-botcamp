"""Actual optional Condor + MCP interfaces; no provider network or exchange orders."""
import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys
import time

import pytest

pytest.importorskip("mcp", reason="Run with the Condor runtime extra/environment")
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from src.runtime.bridge import RuntimeBridge
from src.runtime.mcp_server import build_server
from tests.test_runtime_bridge import setup, context


def test_actual_mcp_tool_discovery_and_stdio_read_only(tmp_path):
    bridge = RuntimeBridge(tmp_path / "owned", "unit", "a" * 64, writable=True)
    # Real system clock for the child; private empty-account fixture only.
    state = bridge.publish(context(), "session1", "bounded", time.time())

    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "src.runtime.mcp_server",
            "--root", str(bridge.root), "--controller-id", "unit", "--account-binding", "a" * 64])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert names == {"flyby_get_runtime_state", "flyby_read_events", "flyby_get_adjustment_status"}
                result = await client.call_tool("flyby_get_runtime_state", {})
                assert not result.isError
                denied = await client.call_tool("flyby_submit_adjustment", {"request_id": "no"})
                assert denied.isError
    asyncio.run(check())


def test_actual_mcp_bounded_request_and_validation_receipt(tmp_path):
    bridge, state = setup(tmp_path)
    now = state["time"]
    server = build_server(bridge, clock=lambda: now)

    async def check():
        assert "flyby_submit_adjustment" in {t.name for t in await server.list_tools()}
        result = await server.call_tool("flyby_submit_adjustment", dict(request_id="mcp-one", session=state["session"],
            basis_sequence=state["sequence"], patch={"size_multiplier": .5}))
        assert "queued" in str(result)
        assert bridge.consume(state, now) == {"size_multiplier": .5}
    asyncio.run(check())


def test_real_condor_tick_provider_injection_and_mode_scoping(tmp_path, monkeypatch):
    pytest.importorskip("condor.agents.engine", reason="Requires official Condor checkout on PYTHONPATH")
    from condor.agents import engine
    from condor.agents.providers import list_providers, _REGISTRY, ProviderResult
    from condor.runtime import toolsets
    from src.runtime.condor_adapter import install_runtime
    from scripts.install_condor import install
    from condor.agents.agent import AgentStore
    from condor.agents.strategy import StrategyStore
    from condor.agents.config import AgentConfig
    from condor.acp.client import TextChunk, PromptDone
    from scripts.check_condor_package import LOOP_ID

    for name, value in {"CONDOR_STOCK_AGENTS_ROOT": tmp_path / "stock", "CONDOR_AGENTS_ROOT": tmp_path / "local",
                        "CONDOR_RUNTIME_ROOT": tmp_path / "runtime", "CONDOR_DATA_DIR": tmp_path / "condor-data",
                        "CONDOR_REPORTS_DIR": tmp_path / "reports"}.items():
        monkeypatch.setenv(name, str(value))
    install(tmp_path / "stock")
    bridge, state = setup(tmp_path)
    original_servers = [{"name": "original", "args": ["-m", "fixture", "--mute-tools", "existing"]}]
    from copy import deepcopy
    monkeypatch.setattr(toolsets, "build_mcp_servers_for_session", lambda *a, **k: deepcopy(original_servers))
    monkeypatch.setattr(engine, "build_gated_client", lambda seat, risk, client, mode:
        toolsets.build_mcp_servers_for_session(seat.user_id, 0, agent_slug=seat.agent.slug, tick=True))
    original_tick = engine.TickEngine._tick
    monkeypatch.setattr(engine.TickEngine, "_tick", original_tick)
    monkeypatch.setattr(engine.TickEngine, "_run_shutdown", engine.TickEngine._run_shutdown)
    monkeypatch.setattr(engine.TickEngine, "_adopt_running_bots", engine.TickEngine._adopt_running_bots)
    list_providers()
    old_registry = dict(_REGISTRY)
    for provider in list_providers():
        monkeypatch.setattr(provider, "execute", AsyncMock(return_value=ProviderResult(provider.name, {}, "fixture")))
    provider = install_runtime(bridge, operator_user_id=8, clock=lambda: state["time"])
    monkeypatch.setattr(toolsets, "build_mcp_servers_for_session", toolsets.build_mcp_servers_for_session)
    # Keep teardown restoring process-local wrappers to avoid affecting other tests.
    monkeypatch.setattr(engine.TickEngine, "_tick", engine.TickEngine._tick)
    try:
        seat = SimpleNamespace(user_id=8, agent=SimpleNamespace(slug="flyby"), _agent_key=lambda: "openai:fixture")
        live = engine.build_gated_client(seat, None, None, "loop")
        dry = engine.build_gated_client(seat, None, None, "dry_run")
        assert "--enable-controls" in live[-1]["args"]
        assert "--enable-controls" not in dry[-1]["args"]
        assert "--enable-controls" not in engine.build_gated_client(seat, None, None, "shutdown")[-1]["args"]
        mute_arg = live[0]["args"][live[0]["args"].index("--mute-tools") + 1]
        assert toolsets._every_tool_name() <= set(mute_arg.split(","))
        assert "existing" in mute_arg.split(",")
        seat._agent_key = lambda: "claude-acp:fixture"
        assert "--enable-controls" not in engine.build_gated_client(seat, None, None, "loop")[-1]["args"]
        seat._agent_key = lambda: "openai:fixture"
        seat.user_id = 9
        assert engine.build_gated_client(seat, None, None, "loop") == original_servers
        seat.user_id = 8
        seat.agent.slug = "other"
        assert engine.build_gated_client(seat, None, None, "loop") == original_servers

        config = AgentConfig.from_dict(StrategyStore().get_by_key(LOOP_ID).default_config).to_engine_dict()
        config["agent_key"] = "fixture:no-model"
        tick = engine.TickEngine(agent=AgentStore().get("flyby"), strategy=StrategyStore().get_by_key(LOOP_ID),
                                 config=config, chat_id=0, user_id=8)
        model = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(), text="")
        async def stream(prompt):
            model.text = prompt
            yield TextChunk("HOLD_UNVERIFIED: no real fills. No executors were created (dry run)")
            yield PromptDone("end_turn")
        model.prompt_stream = stream
        monkeypatch.setattr(tick, "_get_client", AsyncMock(return_value=object()))
        monkeypatch.setattr(tick, "_adopt_running_bots", AsyncMock(return_value=None))
        monkeypatch.setattr(tick.ledger, "bases", lambda: ["flyby-flyby_operator"])
        monkeypatch.setattr(tick, "_create_client", AsyncMock(return_value=model))
        asyncio.run(tick._tick())
        assert "Flyby runtime: seq=" in model.text
        assert model.start.await_count == model.stop.await_count == 1
        outside = asyncio.run(provider.execute(object(), config, agent_id="other_1"))
        assert outside.data == {}
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(old_registry)
