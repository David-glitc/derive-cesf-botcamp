"""Install authored Flyby files into an explicit NEW agent home. Never starts a loop."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_condor_package import LOOP_ID, PROFILE_ID, validate_package


def install(agents_root, root=ROOT):
    validate_package(root)
    selected = Path(agents_root).absolute()
    if selected != selected.resolve():
        raise ValueError("linked_condor_agents_root_refused")
    target = selected / "flyby"
    if target.exists() or target.is_symlink():
        raise FileExistsError("existing_flyby_agent_refused: preserve its authored and runtime state")
    # Full source validation precedes writes. Exclusive mkdir also refuses races.
    target.mkdir(parents=True, exist_ok=False)
    try:
        source = root / "condor/flyby"
        for path in source.rglob("*"):
            if "__pycache__" in path.parts:
                continue
            destination = target / path.relative_to(source)
            if path.is_dir():
                destination.mkdir(exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(path.read_bytes())
                shutil.copymode(path, destination)
    except Exception:
        # Don't erase evidence or state after a partial failure. No loop starts.
        raise RuntimeError(f"partial_install_left_in_place:{target}; choose a new root") from None
    return {"installed_agent": str(target), "agent": "flyby", "loop_id": LOOP_ID,
            "profile_id": PROFILE_ID, "execution_mode": "loop", "restart_on_boot": False,
            "started": False, "orders_submitted": 0, "live_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.agents_root), indent=2))


if __name__ == "__main__":
    main()
