"""Read-only installation preflight. No credentials, account calls or orders."""
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.mainnet import execution_environment, validate_installed_endpoints
from scripts.check_condor_package import FIXED_SETTINGS, exact


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
        if (profile.get("risk_policy") != "flyby-dd10-dd15-v1"
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
    launcher = yaml.safe_load((root / "conf/scripts/conf_v2_flyby.yml").read_text())
    allowed = {f"conf_flyby_{name}.yml" for name in ("eth", "btc", "sol", "hype")}
    selected = launcher.get("controllers_config") if isinstance(launcher, dict) else None
    if (not isinstance(selected, list) or not selected
            or any(not isinstance(name, str) or name not in allowed for name in selected)
            or len(selected) != len(set(selected))):
        raise ValueError("approved_mainnet_launcher_required")
    manifest = json.loads((root / "hummingbot-version.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("execution_environment") != environment:
        raise ValueError("mainnet_manifest_mismatch")


def main():
    try:
        from hummingbot.connector.derivative.derive_perpetual import derive_perpetual_constants
        validate_installed_endpoints(derive_perpetual_constants)
        validate_profiles()
    except (ImportError, ValueError, OSError, yaml.YAMLError) as exc:
        print(f"Mainnet preflight failed: {exc}", file=sys.stderr)
        return 1
    from hummingbot.connector.derivative.derive_perpetual.derive_perpetual_derivative import DerivePerpetualDerivative
    print(json.dumps({**execution_environment(), "install_profiles_paused": True,
                      "compatibility_version": getattr(DerivePerpetualDerivative, "FLYBY_COMPATIBILITY_VERSION", None),
                      "account_verified": False, "live_execution_verified": False,
                      "orders_submitted": 0}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
