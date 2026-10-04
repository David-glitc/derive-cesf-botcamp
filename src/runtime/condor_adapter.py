"""Explicit process-local Condor extension; no edits to an installed framework."""
import argparse
import asyncio
import os
from contextvars import ContextVar
from pathlib import Path
import runpy
import sys
import time

from src.runtime.bridge import RuntimeBridge
from src.runtime.observation import ObservationWindow, validate_observation_config


def install_runtime(bridge, *, operator_user_id, bot_name="flyby-flyby_operator", clock=time.time,
                    observation_window=None):
    from condor.agents.providers import BaseProvider, ProviderResult, list_providers, register_provider
    from condor.agents import engine
    from condor.runtime import toolsets
    if not callable(getattr(engine, "build_gated_client", None)) or not callable(
            getattr(toolsets, "build_mcp_servers_for_session", None)) or not callable(
            getattr(toolsets, "_every_tool_name", None)) or any(not callable(getattr(engine.TickEngine, name, None))
            for name in ("_tick", "_run_shutdown", "_adopt_running_bots", "_finish", "_reap_client")):
        raise ValueError("runtime_condor_hooks_incompatible")
    if getattr(toolsets.build_mcp_servers_for_session, "_flyby_runtime_installed", False):
        raise ValueError("runtime_condor_extension_already_installed")
    if type(operator_user_id) is not int or operator_user_id <= 0:
        raise ValueError("runtime_operator_user_required")
    if observation_window is not None and (not isinstance(observation_window, ObservationWindow) or bridge.writable):
        raise ValueError("observation_read_only_bridge_required")
    list_providers()  # populate built-ins before adding a custom registry entry
    seat_user = ContextVar("flyby_runtime_operator", default=None)
    original_tick = engine.TickEngine._tick
    original_shutdown = engine.TickEngine._run_shutdown
    original_adopt = engine.TickEngine._adopt_running_bots

    def observing(seat):
        return bool(observation_window is not None and seat.user_id == operator_user_id
                    and seat.agent.slug == "flyby" and seat.strategy.slug == "flyby_operator")

    class FlybyRuntimeProvider(BaseProvider):
        name = "flyby_runtime"
        is_core = True

        async def execute(self, client, config, agent_id="", bot_names=None, owned=None):
            if (seat_user.get() != operator_user_id or not agent_id.startswith("flyby.flyby_operator_")
                    or config.get("bot_name") != bot_name or observation_window is None and
                    bot_names is not None and bot_name not in bot_names):
                return ProviderResult(self.name, {}, "Flyby runtime: outside owned bot scope")
            try:
                state = bridge.read_state(clock())
                # Bounded numeric allowlist from the controller, never arbitrary model instructions.
                summary = (f"Flyby runtime: seq={state['sequence']} fresh={state['fresh']} "
                           f"mode={state['mode']} session={state['session']}; "
                           "refresh state with flyby_get_runtime_state before an adjustment; "
                           "receipts are not fills")
                return ProviderResult(self.name, state, summary)
            except (OSError, ValueError, KeyError, TypeError):
                return ProviderResult(self.name, {"status": "unavailable", "verified": False},
                                      "Flyby runtime unavailable: no new discretionary risk")

    original_builder = toolsets.build_mcp_servers_for_session
    original_client = engine.build_gated_client
    mode = ContextVar("flyby_runtime_execution_mode", default=None)
    tool_only = ContextVar("flyby_runtime_tool_only_model", default=False)

    def scoped_client(seat, risk_state, price_client, execution_mode):
        token = mode.set(execution_mode)
        from condor.acp.pydantic_ai_client import is_pydantic_ai_model
        model_token = tool_only.set(is_pydantic_ai_model(seat._agent_key()))
        try:
            if observing(seat) and not tool_only.get():
                raise ValueError("observation_tool_only_model_required")
            return original_client(seat, risk_state, price_client, execution_mode)
        finally:
            tool_only.reset(model_token)
            mode.reset(token)

    async def scoped_tick(seat, *args, **kwargs):
        token = seat_user.set(seat.user_id)
        try:
            if observing(seat):
                from condor.runtime.registry_file import LoopState
                from condor.acp.pydantic_ai_client import is_pydantic_ai_model
                try:
                    validate_observation_config(seat.config)
                    if not is_pydantic_ai_model(seat._agent_key()):
                        raise ValueError("observation_tool_only_model_required")
                    remaining = observation_window.remaining()
                except ValueError:
                    await seat._finish(LoopState.ERROR, "observation_setup_or_clock_invalid")
                    return
                if remaining <= 0:
                    await seat._finish(LoopState.COMPLETED, "observation_deadline")
                    return
                try:
                    return await asyncio.wait_for(original_tick(seat, *args, **kwargs), timeout=min(30., remaining))
                except asyncio.TimeoutError:
                    await seat._reap_client(during="observation_timeout")
                    if observation_window.remaining() <= 0:
                        await seat._finish(LoopState.COMPLETED, "observation_deadline")
                        return
                    raise
            return await original_tick(seat, *args, **kwargs)
        finally:
            seat_user.reset(token)

    async def scoped_shutdown(seat, reason):
        if observing(seat):
            from condor.runtime.registry_file import LoopState
            # Upstream winddown performs direct API closes, outside model tools.
            # End only this observer; HB retains its independent safety governor.
            await seat._finish(LoopState.STOPPED, "observation_risk_alert")
            return
        return await original_shutdown(seat, reason)

    async def scoped_adopt(seat, client):
        if observing(seat):
            return  # read the controller binding without claiming bot ownership
        return await original_adopt(seat, client)

    def scoped_tools(user_id, chat_id, **kwargs):
        servers = original_builder(user_id, chat_id, **kwargs)
        if user_id != operator_user_id or kwargs.get("agent_slug") != "flyby" or kwargs.get("tick") is not True:
            return servers
        # Keep named overrides for ACP's static .mcp.json discovery, but mute ALL
        # original tools. No saved-config/direct-order/delegation bypass is mounted.
        muted = toolsets._every_tool_name()
        for server in servers:
            args = list(server["args"])
            if "--mute-tools" in args:
                position = args.index("--mute-tools") + 1
                args[position] = ",".join(sorted(muted | set(args[position].split(","))))
            else:
                args += ["--mute-tools", ",".join(sorted(muted))]
            server["args"] = args
        args = ["-m", "src.runtime.mcp_server", "--root", str(bridge.root),
                "--controller-id", bridge.owner["controller_id"],
                "--account-binding", bridge.owner["account_binding"]]
        if bridge.writable and mode.get() == "loop" and tool_only.get():
            args.append("--enable-controls")
        # Installed package or explicit repo PYTHONPATH; no credentials on argv.
        servers.append({"name": "flyby-runtime", "command": sys.executable, "args": args, "env": []})
        return servers

    scoped_tools._flyby_runtime_installed = True
    provider = FlybyRuntimeProvider()
    register_provider(provider)
    toolsets.build_mcp_servers_for_session = scoped_tools
    engine.build_gated_client = scoped_client
    engine.TickEngine._tick = scoped_tick
    engine.TickEngine._run_shutdown = scoped_shutdown
    engine.TickEngine._adopt_running_bots = scoped_adopt
    return provider


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condor-root", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--controller-id", required=True)
    parser.add_argument("--account-binding", required=True)
    parser.add_argument("--operator-user-id", type=int, required=True)
    parser.add_argument("--enable-controls", action="store_true")
    parser.add_argument("--observation-hours", type=float,
                        help="Read-only native-loop deadline, >0 and <=50 hours; forbids controls")
    args = parser.parse_args()
    condor_root = args.condor_root.resolve()
    if not (condor_root / "condor/agents/engine.py").is_file() or not (condor_root / "main.py").is_file():
        raise ValueError("runtime_official_condor_checkout_required")
    sys.path.insert(0, str(condor_root))
    bridge = RuntimeBridge(args.root, args.controller_id, args.account_binding, writable=args.enable_controls)
    window = None if args.observation_hours is None else ObservationWindow(args.observation_hours * 3600)
    install_runtime(bridge, operator_user_id=args.operator_user_id, observation_window=window)
    # Operator explicitly runs this instead of stock main.py; installation alone
    # never launches Condor or activates a bot. Reuse its normal authentication.
    sys.argv = [str(condor_root / "main.py")]
    os.chdir(condor_root)  # upstream resolves its settings relative to its checkout
    runpy.run_path(str(condor_root / "main.py"), run_name="__main__")


if __name__ == "__main__":
    main()
