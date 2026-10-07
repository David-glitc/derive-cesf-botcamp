"""Offline Condor package structure, sample parity and optional upstream discovery."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
import os
import tempfile
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.risk.competition import POLICY, RESTRICTED_DRAWDOWN, HARD_STOP_DRAWDOWN
from src.risk.exposure import ETH_EXPOSURE_TEST
from src.runtime.control import TOOLS as RUNTIME_TOOLS

PROFILE_ID = "flyby-baseline-dd15-dd25-v1"
LOOP_ID = "flyby.flyby_operator"
TOOLS = {"manage_bots", "manage_controllers", "get_market_data", "get_prices",
         "get_portfolio_overview", "get_performance_report", "manage_agent_controllers"} | RUNTIME_TOOLS
FIXED_SETTINGS = {
    "controller_name": "derive_cesf_long_vol", "controller_type": "directional_trading",
    "manual_kill_switch": True, "connector_name": "derive_perpetual", "interval": "5m",
    "vol_lookback": 100, "total_amount_quote": 800, "leverage": 2, "position_mode": "ONEWAY",
    "cooldown_time": 300, "strategy_profile": "baseline", "risk_policy": POLICY,
    "risk_state_id": "flyby-competition", "risk_fraction": .005, "max_notional_fraction": .20,
    "max_slippage": .0015, "max_basis": .03, "condor_active": False, "options_enabled": False,
    "options_signal_enabled": True, "option_buy_moneyness": "any", "option_buy_delta_target": .50,
    "option_sell_delta_target": .25, "portfolio_margin": False, "spot_hedge_enabled": False,
}


def exact(actual, expected):
    # YAML true/false must not pass as 1/0; numeric 800 and 800.0 are equivalent.
    return actual == expected and (not isinstance(expected, bool) or type(actual) is bool)


def validate_fixed_profile(directory):
    profile = yaml.safe_load((directory / "PROFILE.yml").read_text())
    identity = {"profile_id": PROFILE_ID, "agent_slug": "flyby", "loop_id": LOOP_ID,
                "controller_name": "derive_cesf_long_vol", "execution_environment": "mainnet_v3",
                "markets": ["ETH", "BTC", "SOL", "HYPE"], "restricted_drawdown": -float(RESTRICTED_DRAWDOWN),
                "hard_stop_drawdown": -float(HARD_STOP_DRAWDOWN), "controller_settings": FIXED_SETTINGS}
    if (profile != identity or any(not exact(profile["controller_settings"].get(k), v)
                                  for k, v in FIXED_SETTINGS.items())):
        raise ValueError("fixed_submission_profile_mismatch")
    return profile


def frontmatter(path):
    text = path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("missing_condor_frontmatter")
    meta, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(meta), body


def validate_package(root=ROOT, condor_root=None):
    directory = root / "condor/flyby"
    if directory.is_symlink() or directory.parent.is_symlink():
        raise ValueError("linked_condor_package_root")
    # No runtime journals, session configs, credentials or links in authored package.
    expected_paths = {"AGENT.md", "PROFILE.yml", "loops/flyby_operator/loop.md",
                      "controllers/derive_cesf_long_vol/CONTROLLER.md",
                      "controllers/derive_cesf_long_vol/derive_cesf_long_vol.py"}
    expected_paths.update(f"controllers/derive_cesf_long_vol/sample_configs/{m}.yml"
                          for m in ("eth", "btc", "sol", "hype"))
    expected_paths.update(f"controllers/derive_cesf_long_vol/sample_configs/{m}_active.yml"
                          for m in ("eth", "sol"))
    for path in directory.rglob("*"):
        if "__pycache__" in path.parts:  # importing the controller in tests writes bytecode
            continue
        if path.is_symlink() or (path.is_file() and str(path.relative_to(directory)) not in expected_paths):
            raise ValueError("unexpected_or_linked_condor_package_file")
    profile = validate_fixed_profile(directory)
    meta, body = frontmatter(directory / "AGENT.md")
    if not isinstance(meta, dict) or not meta.get("name") or not meta.get("description") or not body.strip():
        raise ValueError("invalid_condor_identity")
    if (meta.get("name") != "Flyby Derive" or meta.get("agent_key") != ""
            or not isinstance(meta.get("tools"), list) or set(meta["tools"]) != TOOLS
            or len(meta["tools"]) != len(TOOLS) or meta.get("server_required") is not True):
        raise ValueError("invalid_condor_tools_or_binding")
    loop_meta, loop_body = frontmatter(directory / "loops/flyby_operator/loop.md")
    defaults = loop_meta.get("default_config") if isinstance(loop_meta, dict) else None
    context = str(loop_meta.get("default_trading_context", "")) if isinstance(loop_meta, dict) else ""
    required_defaults = {"execution_mode": "loop", "restart_on_boot": False, "max_ticks": 0,
                         "bot_mode": "bot", "bot_name": "flyby-flyby_operator", "total_amount_quote": 800,
                         "frequency_sec": 60, "tick_timeout_sec": 0, "canvas_enabled": False,
                         "server_name": "", "agent_key": ""}
    limits = {"max_position_size_quote": 320, "max_open_executors": 2, "max_leverage": 2,
              "max_drawdown_pct": -1, "shutdown_drawdown_pct": -1}
    if (loop_meta.get("name") != "Flyby Operator" or loop_meta.get("agent_key") is not None
            or loop_meta.get("skills") != [] or not loop_body.strip()
            or not isinstance(defaults, dict) or set(defaults) != set(required_defaults) | {"risk_limits"}
            or any(not exact(defaults.get(k), v) for k, v in required_defaults.items())
            or defaults.get("risk_limits") != limits
            or PROFILE_ID not in context or "flyby-eth-active-001" not in context
            or "flyby-sol-active-001" not in context
            or "agents/condor_agent.py" not in loop_body):
        raise ValueError("invalid_condor_loop_contract")
    controller = directory / "controllers/derive_cesf_long_vol"
    description, _ = frontmatter(controller / "CONTROLLER.md")
    if description.get("type") != "directional_trading":
        raise ValueError("wrong_controller_type")
    tree = ast.parse((controller / "derive_cesf_long_vol.py").read_text())
    classes = {n.name for n in tree.body if isinstance(n, ast.ClassDef)}
    if not {"DeriveCesfLongVolConfig", "DeriveCesfLongVolController"} <= classes:
        raise ValueError("canonical_controller_required")
    # Condor syncs one file; only the pip-installed shared package may be imported.
    if any(isinstance(n, ast.ImportFrom) and (n.level or (n.module or "").startswith("controllers"))
           for n in ast.walk(tree)):
        raise ValueError("controller_must_be_single_file")
    samples = {}
    for market in ("eth", "btc", "sol", "hype"):
        source = root / f"conf/controllers/conf_flyby_{market}.yml"
        target = controller / f"sample_configs/{market}.yml"
        if source.read_bytes() != target.read_bytes():
            raise ValueError(f"condor_sample_drift:{market}")
        sample = yaml.safe_load(target.read_text())
        if (sample.get("manual_kill_switch") is not True or sample.get("options_enabled") is not False
                or sample.get("connector_name") != "derive_perpetual"
                or sample.get("controller_type") != "directional_trading"
                or sample.get("controller_name") != "derive_cesf_long_vol"):
            raise ValueError(f"invalid_condor_sample:{market}")
        if (any(not exact(sample.get(k), v) for k, v in FIXED_SETTINGS.items())
                or set(sample) != set(FIXED_SETTINGS) | {"id", "trading_pair", "candles_connector", "candles_trading_pair"}
                or sample.get("id") != f"flyby-{market}-001"
                or sample.get("trading_pair") != market.upper() + "-USDC"
                or sample.get("candles_connector") != "binance_perpetual"
                or sample.get("candles_trading_pair") != market.upper() + "-USDT"):
            raise ValueError(f"fixed_controller_profile_mismatch:{market}")
        samples[market] = hashlib.sha256(target.read_bytes()).hexdigest()
    active_samples = {}
    for market in ("eth", "sol"):
        source = root / f"conf/controllers/conf_flyby_{market}_active.yml"
        target = controller / f"sample_configs/{market}_active.yml"
        if source.read_bytes() != target.read_bytes():
            raise ValueError(f"condor_active_sample_drift:{market}")
        active = yaml.safe_load(target.read_text())
        expected = {**FIXED_SETTINGS, "manual_kill_switch": False, "max_perp_positions": 2, "max_option_spreads": 2,
                    "id": f"flyby-{market}-active-001", "trading_pair": market.upper() + "-USDC",
                    "candles_connector": "binance_perpetual", "candles_trading_pair": market.upper() + "-USDT"}
        if market == "eth":
            expected.update(exposure_profile=ETH_EXPOSURE_TEST, max_notional_fraction=.40,
                            max_gross_exposure_fraction=.40, option_gross_fraction=.75,
                            options_enabled=True, options_execution_mode="rfq_v3")
        if (not isinstance(active, dict) or set(active) != set(expected)
                or any(not exact(active.get(k), v) for k, v in expected.items())):
            raise ValueError(f"invalid_condor_active_sample:{market}")
        active_samples[market] = hashlib.sha256(target.read_bytes()).hexdigest()
    upstream = False
    if condor_root is not None:
        # Local official checkout, filesystem helpers only. No config/server/tool calls.
        sys.path.insert(0, str(condor_root))
        from condor.frontmatter import parse_frontmatter
        from condor.agent_controllers import _load_one, load_sample
        from condor.agents.agent import AgentStore
        from condor.agents.strategy import StrategyStore
        from condor.agents.config import AgentConfig
        actual_meta, actual_body = parse_frontmatter((directory / "AGENT.md").read_text())
        if actual_meta != meta or actual_body.strip() != body.strip():
            raise ValueError("upstream_identity_parser_mismatch")
        discovered = _load_one(controller, "agent:flyby", False)
        expected_sample_names = set(samples) | {"eth_active", "sol_active"}
        if (not discovered or discovered.controller_type != "directional_trading"
                or set(discovered.samples) != expected_sample_names):
            raise ValueError("upstream_controller_discovery_mismatch")
        for sample_name in expected_sample_names:
            load_sample(discovered, sample_name)
        # Real registry lookup against isolated roots; don't touch deployed agents.
        with tempfile.TemporaryDirectory(prefix="flyby-condor-discovery-") as temporary:
            with patch.dict(os.environ, {"CONDOR_STOCK_AGENTS_ROOT": str(directory.parent.resolve()),
                                         "CONDOR_AGENTS_ROOT": temporary}):
                agent = AgentStore().get("flyby")
                loops = StrategyStore().list("flyby")
                if (agent is None or agent.tools != meta["tools"]
                        or [s.key for s in loops] != [LOOP_ID]
                        or "flyby" not in {a.slug for a in AgentStore().list_all()}):
                    raise ValueError("upstream_agent_loop_discovery_mismatch")
                strategy = StrategyStore().get_by_key(LOOP_ID)
                if strategy is None or strategy.default_config != defaults:
                    raise ValueError("upstream_loop_defaults_mismatch")
                config = AgentConfig.from_dict(defaults)
                if config.execution_mode != "loop" or config.max_ticks != 0 or config.bot_mode != "bot":
                    raise ValueError("upstream_loop_config_mismatch")
        upstream = True
    return {"agent": "flyby", "controller": "derive_cesf_long_vol", "samples": samples,
            "active_samples": active_samples,
            "profile_id": profile["profile_id"], "loop_id": LOOP_ID,
            "execution_mode": defaults["execution_mode"], "max_ticks": defaults["max_ticks"],
            "structure_valid": True, "upstream_filesystem_parser_verified": upstream,
            "upstream_agent_loop_discovery_verified": upstream,
            "upstream_agent_config_verified": upstream,
            "tick_verified": False, "real_model_verified": False,
            "runtime_import_verified": False, "live_verified": False, "orders_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--condor-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_package(condor_root=args.condor_root), indent=2))


if __name__ == "__main__":
    main()
