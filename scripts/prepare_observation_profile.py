"""Prepare paused HB observe config and Condor loop override; never launch."""
import argparse
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_condor_package import validate_package
from src.runtime.observation import validate_observation_config


def prepare(output, market, *, server_name="", agent_key="", root=ROOT):
    validate_package(root)
    if market not in ("eth", "btc", "sol", "hype"):
        raise ValueError("observation_unapproved_market")
    profile = yaml.safe_load((root / "condor/profiles/flyby_observe_48h.yml").read_text())
    profile.update(server_name=server_name, agent_key=agent_key)
    validate_observation_config(profile, require_setup=False)
    controller = yaml.safe_load((root / f"conf/controllers/conf_flyby_{market}.yml").read_text())
    controller["runtime_oversight_mode"] = "observe"
    if controller.get("manual_kill_switch") is not True:
        raise ValueError("observation_paused_controller_required")
    output = Path(output).absolute()
    if output.resolve() != output:
        raise ValueError("observation_linked_output_refused")
    controller_yaml = yaml.safe_dump(controller, sort_keys=False)
    profile_yaml = yaml.safe_dump(profile, sort_keys=False)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name, payload in (("controller.yml", controller_yaml), ("condor.yml", profile_yaml)):
        with (output / name).open("x") as stream:
            stream.write(payload)
    return {"output": str(output), "controller_id": controller["id"], "loop_id": "flyby.flyby_operator",
            "observation_hours": 48, "setup_complete": bool(server_name.strip() and agent_key.strip()),
            "execution_mode": "loop", "runtime_oversight_mode": "observe", "trading_paused": True,
            "restart_on_boot": False, "started": False, "orders_submitted": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--market", choices=("eth", "btc", "sol", "hype"), required=True)
    parser.add_argument("--server-name", default="")
    parser.add_argument("--agent-key", default="", help="Model name, never a credential")
    args = parser.parse_args()
    print(json.dumps(prepare(args.output, args.market, server_name=args.server_name, agent_key=args.agent_key), indent=2))


if __name__ == "__main__":
    main()
