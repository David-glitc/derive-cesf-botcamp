"""Prepare a NEW paused operator-selected profile. Never installs or activates it."""
import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.risk.competition import POLICY


def prepare(market, profile, output, root=ROOT):
    if market not in ("ETH", "BTC", "SOL", "HYPE") or profile not in ("baseline", "competition_scalp"):
        raise ValueError("explicit_approved_market_and_profile_required")
    source = root / f"conf/controllers/conf_flyby_{market.lower()}.yml"
    config = yaml.safe_load(source.read_text())
    if (config.get("manual_kill_switch") is not True or config.get("connector_name") != "derive_perpetual"
            or config.get("trading_pair") != market + "-USDC" or config.get("risk_policy") != POLICY
            or config.get("options_enabled") is not False):
        raise ValueError("reviewed_paused_source_profile_required")
    config.update(strategy_profile=profile, interval="5m", cooldown_time=60 if profile == "competition_scalp" else 300)
    # Stable controller/account-risk identities preserve loss/cooldown history.
    payload = "# Local review candidate. Paused; not installed, selected or live-certified.\n" + yaml.safe_dump(config, sort_keys=False)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        stream.write(payload)
    return {"output": str(output), "market": market, "profile": profile, "paused": True,
            "risk_policy": POLICY, "caps_changed": False, "live_ready": False,
            "installed": False, "orders_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("ETH", "BTC", "SOL", "HYPE"), required=True)
    parser.add_argument("--profile", choices=("baseline", "competition_scalp"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.market, args.profile, args.output), indent=2))


if __name__ == "__main__":
    main()
