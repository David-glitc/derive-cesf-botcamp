"""Real Condor discovery/prompt/tick/persistence with MOCKED transports. No network."""
import argparse
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_condor_package import LOOP_ID, PROFILE_ID, validate_package
from scripts.install_condor import install


def verify(condor_root, root=ROOT):
    condor_root = Path(condor_root).resolve()
    if not (condor_root / "condor/agents/engine.py").is_file():
        raise ValueError("official_condor_checkout_required")
    sys.path.insert(0, str(condor_root))
    network_attempts = []

    def refuse_network(*args, **kwargs):
        network_attempts.append("refused")
        raise RuntimeError("network_forbidden_in_condor_fixture_verification")

    with tempfile.TemporaryDirectory(prefix="flyby-condor-runtime-") as folder, ExitStack() as stack:
        temporary = Path(folder)
        # Stock authored files are separate from every writable runtime path.
        installation = install(temporary / "stock", root)
        stack.enter_context(patch.dict(os.environ, {
            "CONDOR_STOCK_AGENTS_ROOT": str(temporary / "stock"),
            "CONDOR_AGENTS_ROOT": str(temporary / "local"),
            "CONDOR_RUNTIME_ROOT": str(temporary / "runtime"),
            "CONDOR_DATA_DIR": str(temporary / "data"),
            "CONDOR_REPORTS_DIR": str(temporary / "reports"),
        }))
        stack.enter_context(patch.object(socket.socket, "connect", refuse_network))
        stack.enter_context(patch.object(socket, "create_connection", refuse_network))
        from condor.acp.client import TextChunk, PromptDone
        from condor.agents.agent import AgentStore
        from condor.agents.config import AgentConfig
        from condor.agents.engine import TickEngine
        from condor.agents.risk import RiskState, auto_approve_with_risk_check
        from condor.agents.strategy import StrategyStore

        package = validate_package(root, condor_root)
        agent = AgentStore().get("flyby")
        strategy = StrategyStore().get_by_key(LOOP_ID)
        if agent is None or strategy is None:
            raise ValueError("agent_loop_not_discovered")
        before = {str(p.relative_to(temporary / "stock")): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in (temporary / "stock").rglob("*") if p.is_file()}
        config = AgentConfig.from_dict(strategy.default_config).to_engine_dict()
        # A fixture label, not a configured or verified real model.
        config["agent_key"] = "fixture:offline-no-provider"
        engine = TickEngine(agent=agent, strategy=strategy, config=config, chat_id=0, user_id=0)
        if not engine.is_experiment or engine.config["bot_name"] != "flyby-flyby_operator":
            raise ValueError("dry_run_controller_mode_required")

        class FixtureModel:
            started = 0
            stopped = 0
            prompt = ""

            async def start(self):
                self.started += 1

            async def stop(self):
                self.stopped += 1

            async def prompt_stream(self, prompt):
                self.prompt = prompt
                yield TextChunk("HOLD_UNVERIFIED: offline fixture; no production state. "
                                "No executors were created (dry run)")
                yield PromptDone("end_turn")

        model = FixtureModel()
        stack.enter_context(patch.object(engine, "_get_client", AsyncMock(return_value=object())))
        stack.enter_context(patch.object(engine, "_adopt_running_bots", AsyncMock(return_value=None)))
        stack.enter_context(patch.object(engine.provider_registry, "run_core_providers", AsyncMock(return_value={})))
        stack.enter_context(patch.object(engine, "_create_client", AsyncMock(return_value=model)))
        asyncio.run(engine._tick())
        if (model.started != 1 or model.stopped != 1 or engine._active_client is not None
                or not engine._experiment_written or PROFILE_ID not in model.prompt
                or "DRY RUN" not in model.prompt or "[AUTHORIZATION —" in model.prompt):
            raise ValueError("condor_tick_prompt_or_teardown_failed")
        snapshots = list(strategy.home.glob("dry_runs/experiment_*.md"))
        if len(snapshots) != 1 or "HOLD_UNVERIFIED" not in snapshots[0].read_text():
            raise ValueError("condor_experiment_persistence_failed")

        gate = auto_approve_with_risk_check(engine.risk, RiskState(), execution_mode="dry_run",
                                          ledger=engine.ledger, agent_id=engine.agent_id)
        options = [{"optionId": "allow", "kind": "allow_once"}]
        calls = [("manage_bots", {"action": a, "bot_name": "flyby-flyby_operator"})
                 for a in ("deploy", "update_config", "start_controllers", "stop_controllers", "stop_bot")]
        calls.extend([("manage_controllers", {"action": "upsert", "target": "controller", "controller_name": "flyby"}),
                      ("manage_agent_controllers", {"action": "sync", "agent": "flyby", "overwrite": True}),
                      ("place_order", {}), ("create_order_executor", {}), ("stop_executor", {}),
                      ("run_code", {"code": "pass"}),
                      ("manage_routines", {"action": "run", "name": "anything"})])
        refusals = []
        for tool, arguments in calls:
            result = asyncio.run(gate({"tool": tool, "input": arguments}, options))
            if result["outcome"]["outcome"] != "cancelled":
                raise ValueError(f"dry_run_mutation_not_refused:{tool}:{arguments.get('action', '')}")
            refusals.append({"tool": tool, "action": arguments.get("action"), "refused": True})
        # Saved config writes are ungated. Observe sync separately; use the
        # recorded outcomes, not older source comments, as the evidence.
        design_time_calls = [
            ("manage_controllers", {"action": "upsert", "target": "config", "config_name": "flyby"}),
            ("manage_agent_controllers", {"action": "sync", "agent": "flyby", "overwrite": False}),
        ]
        design_time_outcomes = []
        for tool, arguments in design_time_calls:
            result = asyncio.run(gate({"tool": tool, "input": arguments}, options))
            design_time_outcomes.append({"tool": tool, "action": arguments["action"],
                                         "gate_outcome": result["outcome"]["outcome"], "executed": False})
        for action in ("status", "get_config", "logs"):
            result = asyncio.run(gate({"tool": "manage_bots", "input": {"action": action}}, options))
            if result["outcome"]["outcome"] != "selected":
                raise ValueError("dry_run_read_refused")
        after = {str(p.relative_to(temporary / "stock")): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in (temporary / "stock").rglob("*") if p.is_file()}
        if before != after or network_attempts:
            raise ValueError("verification_touched_authored_files_or_network")
        snapshot_text = snapshots[0].read_text()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=condor_root,
                              capture_output=True, text=True, check=True).stdout.strip()
    files = ["condor/agents/agent.py", "condor/agents/strategy.py", "condor/agents/config.py",
             "condor/agents/engine.py", "condor/agents/risk.py"]
    return {"kind": "isolated_condor_mocked_transport_verification", "checks_passed": True,
            "profile_id": PROFILE_ID, "loop_id": LOOP_ID, "package": package,
            "installation_verified": installation["started"] is False,
            "condor_base_commit": revision,
            "condor_source_sha256": {f: hashlib.sha256((condor_root / f).read_bytes()).hexdigest() for f in files},
            "real_tick_engine_verified": True, "prompt_assembled": True, "dry_run_snapshot_persisted": True,
            "model_started_stopped": [model.started, model.stopped], "dry_run_gate_refusals": refusals,
            "design_time_gate_observations": design_time_outcomes, "configuration_writes_sandboxed": False,
            "snapshot": snapshot_text, "network_attempts": 0, "orders_submitted": 0,
            "real_model_verified": False, "live_verified": False,
            "limitations": ["API/core providers/model transport are fixtures, not production connectivity",
                           "one real _tick, not a deployed daemon or production restart test",
                           "permission checks are tested directly; no real MCP subprocess or exchange",
                           "upstream permits saved config writes in dry run; playbook forbids them",
                           "tool allowlist is not an ACP sandbox; fixed identity is a packaging/preflight contract"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("verification_output_exists")
    report = verify(args.condor_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k not in ("snapshot", "condor_source_sha256", "package")}, indent=2))


if __name__ == "__main__":
    main()
