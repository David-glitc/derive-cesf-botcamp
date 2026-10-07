"""Read-only installation preflight. No credentials, account calls or orders."""
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.mainnet import execution_environment, validate_installed_endpoints
from scripts.check_condor_package import FIXED_SETTINGS, exact
from src.risk.exposure import ETH_EXPOSURE_TEST
from src.risk.competition import POLICY


def validate_profiles(root=ROOT):
    environment = execution_environment()
    for name in ("eth", "btc", "sol", "hype"):
        profile = yaml.safe_load((root / f"conf/controllers/conf_flyby_{name}.yml").read_text())
        if not isinstance(profile, dict):
            raise ValueError(f"invalid_profile:{name}")
        if profile.get("connector_name") != environment["connector"]:
            raise ValueError(f"mainnet_profile_required:{name}")
        if profile.get("manual_kill_switch") is not True:
            raise ValueError(f"paused_install_profile_required:{name}")
        if profile.get("trading_pair") != name.upper() + "-USDC":
            raise ValueError(f"hummingbot_quote_pair_required:{name}")
        if (profile.get("risk_policy") != POLICY
                or profile.get("risk_state_id") != "flyby-competition"
                or profile.get("strategy_profile") != "baseline"):
            raise ValueError(f"reviewed_competition_risk_profile_required:{name}")
        for capability in ("options_enabled", "portfolio_margin", "spot_hedge_enabled"):
            if profile.get(capability) is not False:
                raise ValueError(f"unsupported_live_capability:{name}:{capability}")
        if (any(not exact(profile.get(k), v) for k, v in FIXED_SETTINGS.items())
                or set(profile) != set(FIXED_SETTINGS) | {"id", "trading_pair", "candles_connector", "candles_trading_pair"}
                or profile.get("id") != f"flyby-{name}-001"
                or profile.get("candles_connector") != "binance_perpetual"
                or profile.get("candles_trading_pair") != name.upper() + "-USDT"):
            raise ValueError(f"fixed_submission_settings_required:{name}")
    for name in ("eth", "btc"):
        optional = root / f"conf/controllers/conf_flyby_options_{name}.yml"
        if not optional.exists():
            continue
        rfq = yaml.safe_load(optional.read_text())
        expected = {**FIXED_SETTINGS, "id": f"flyby-{name}-001", "trading_pair": name.upper() + "-USDC",
                    "candles_connector": "binance_perpetual", "candles_trading_pair": name.upper() + "-USDT",
                    "options_enabled": True, "options_execution_mode": "rfq_v3"}
        if (not isinstance(rfq, dict) or set(rfq) != set(expected)
                or any(not exact(rfq.get(k), v) for k, v in expected.items())):
            raise ValueError(f"fixed_paused_rfq_settings_required:{name}")
    candidate = root / "conf/controllers/conf_flyby_eth_exposure_test.yml"
    if candidate.exists():
        expected = {**FIXED_SETTINGS, "id": "flyby-eth-cap-test-001", "trading_pair": "ETH-USDC",
                    "candles_connector": "binance_perpetual", "candles_trading_pair": "ETH-USDT",
                    "options_enabled": True, "options_execution_mode": "rfq_v3",
                    "exposure_profile": ETH_EXPOSURE_TEST, "max_notional_fraction": .40,
                    "max_gross_exposure_fraction": .40, "option_gross_fraction": .75}
        raw = yaml.safe_load(candidate.read_text())
        if (not isinstance(raw, dict) or set(raw) != set(expected)
                or any(not exact(raw.get(k), v) for k, v in expected.items())):
            raise ValueError("fixed_paused_eth_exposure_test_settings_required")

    # Separate operator activation configs are opt-in and must match the exact
    # reviewed ETH+SOL values; the default/sample profiles above remain paused.
    active_common = {**FIXED_SETTINGS, "manual_kill_switch": False, "max_perp_positions": 2, "max_option_spreads": 2}
    active_expected = {
        "eth": {**active_common, "id": "flyby-eth-active-001", "trading_pair": "ETH-USDC",
                "candles_connector": "binance_perpetual", "candles_trading_pair": "ETH-USDT",
                "exposure_profile": ETH_EXPOSURE_TEST, "max_notional_fraction": .40,
                "max_gross_exposure_fraction": .40, "option_gross_fraction": .75,
                "options_enabled": True, "options_execution_mode": "rfq_v3"},
        "sol": {**active_common, "id": "flyby-sol-active-001", "trading_pair": "SOL-USDC",
                "candles_connector": "binance_perpetual", "candles_trading_pair": "SOL-USDT"},
    }
    for name, expected in active_expected.items():
        path = root / f"conf/controllers/conf_flyby_{name}_active.yml"
        if not path.exists():
            raise ValueError(f"missing_operator_activation_profile:{name}")
        profile = yaml.safe_load(path.read_text())
        if (not isinstance(profile, dict) or set(profile) != set(expected)
                or any(not exact(profile.get(k), v) for k, v in expected.items())):
            raise ValueError(f"invalid_operator_activation_profile:{name}")

    launcher = yaml.safe_load((root / "conf/scripts/conf_v2_flyby.yml").read_text())
    allowed = {f"conf_flyby_{name}.yml" for name in ("eth", "btc", "sol", "hype")}
    selected = launcher.get("controllers_config") if isinstance(launcher, dict) else None
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(name, str) or name not in allowed for name in selected)
            or len(selected) != len(set(selected))):
        raise ValueError("approved_mainnet_launcher_required")
    active_launcher = yaml.safe_load(
        (root / "conf/scripts/conf_v2_flyby_eth_sol_active.yml").read_text())
    if active_launcher != {"id": "v2-flyby-eth-sol-active", "script_name": "v2_with_controllers",
                          "controllers_config": ["conf_flyby_eth_active.yml", "conf_flyby_sol_active.yml"]}:
        raise ValueError("invalid_operator_activation_launcher")
    manifest = json.loads((root / "hummingbot-version.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("execution_environment") != environment:
        raise ValueError("mainnet_manifest_mismatch")


def main():
    if "--profiles-only" in sys.argv:
        validate_profiles()
        print(json.dumps({**execution_environment(), "profiles_valid": True, "orders_submitted": 0}))
        return 0
    try:
        from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants
        validate_installed_endpoints(derive_perpetual_constants)
        validate_profiles()
    except (ImportError, ValueError, OSError, yaml.YAMLError) as exc:
        print(f"Mainnet preflight failed: {exc}", file=sys.stderr)
        return 1
    from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_derivative import DerivePerpetualDerivative
    print(json.dumps({**execution_environment(), "install_profiles_paused": True,
                      "install_profiles_paused_scope": "four baseline samples; selected active samples are separate",
                      "selected_active_profiles": ["flyby-eth-active-001", "flyby-sol-active-001"],
                      "active_eth_options_enabled": True,
                      "compatibility_version": getattr(DerivePerpetualDerivative, "FLYBY_COMPATIBILITY_VERSION", None),
                      "account_verified": False, "live_execution_verified": False,
                      "orders_submitted": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
