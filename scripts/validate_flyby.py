"""Repeatable local validation, optional pinned tests and bounded public capture. No trading."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def tasks(output, with_hummingbot=False, historical_data=None, public_samples=0,
          condor_root=None, condor_python=None):
    work = [("host_tests", [sys.executable, "-m", "pytest", "-q", "tests"]),
            ("formal_model", [sys.executable, "verification/check_safety.py", "--output", str(output / "formal.json")]),
            ("formal_delta", [sys.executable, "verification/check_delta.py", "--output", str(output / "delta.json")]),
            ("condor_package", [sys.executable, "scripts/check_condor_package.py"])]
    if condor_root is not None:
        work[-1][1].extend(["--condor-root", str(condor_root)])
    if condor_python is not None:
        if condor_root is None:
            raise ValueError("condor_root_required_with_python")
        work.append(("condor_tick", [str(condor_python), "scripts/verify_condor_runtime.py", "--condor-root",
                                    str(condor_root), "--output", str(output / "condor-runtime.json")]))
    if with_hummingbot:
        work.append(("pinned_hummingbot", ["bash", "scripts/test_hummingbot.sh"]))
    if historical_data is not None:
        work.append(("policy_comparison", [sys.executable, "-m", "backtest.compare_policies", "--data",
                                          str(historical_data), "--output", str(output / "comparison")]))
    for ccy in ("ETH", "BTC") if public_samples else ():
        folder = output / ccy.lower()
        work.append((f"public_{ccy}", [sys.executable, "scripts/capture_derive_public.py", "--currency", ccy,
                     "--samples", str(public_samples), "--quant", "--output", str(folder)]))
        work.append((f"replay_{ccy}", [sys.executable, "-m", "backtest.replay_derive", "--input",
                     str(folder / "market.jsonl"), "--raw", str(folder / "raw.jsonl"), "--output", str(folder / "replay")]))
    return work


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--with-hummingbot", action="store_true")
    parser.add_argument("--historical-data", type=Path)
    parser.add_argument("--public-samples", type=int, choices=range(0, 7), default=0)
    parser.add_argument("--condor-root", type=Path)
    parser.add_argument("--condor-python", type=Path)
    args = parser.parse_args()
    if args.condor_python is not None and args.condor_root is None:
        parser.error("--condor-python requires --condor-root")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    results = []
    for name, command in tasks(output, args.with_hummingbot, args.historical_data, args.public_samples,
                               args.condor_root, args.condor_python):
        print(f"Starting {name}", flush=True)
        started = time.time()
        try:
            run = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True, timeout=600)
            (output / f"{name}.log").write_text(run.stdout + run.stderr)
            result = {"stage": name, "command": command, "returncode": run.returncode,
                      "elapsed_seconds": time.time() - started}
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = {"stage": name, "command": command, "returncode": -1, "reason": type(exc).__name__}
        results.append(result)
        print(json.dumps(result), flush=True)
    passed = all(r["returncode"] == 0 for r in results)
    files = ["condor/flyby/controllers/derive_cesf_long_vol/derive_cesf_long_vol.py", "agents/condor_agent.py", "src/execution/paired.py",
             "src/execution/derive_hb.py", "src/accounting/derive_margin.py", "src/risk/venue_sizing.py",
             "src/risk/competition.py",
             "scripts/hummingbot_compat.py",
             "src/execution/contracts.py", "src/data/derive_public.py", "src/data/records.py",
             "src/options/ranking.py", "src/options/delta.py", "src/options/spread_builder.py", "src/options/paper.py",
             "src/accounting/context.py", "backtest/delta_performance.py",
             "src/signal/options_surface.py", "src/signal/microstructure.py",
             "src/risk/position_sizing.py", "verification/check_safety.py", "verification/check_delta.py",
             "backtest/compare_policies.py", "backtest/options_paper.py",
             "scripts/check_condor_package.py", "scripts/install_condor.py", "scripts/verify_condor_runtime.py",
             "scripts/check_mainnet.py", "scripts/install_hummingbot.sh", "pyproject.toml", "hummingbot-version.json",
             "scripts/build_submission.py", "scripts/validate_flyby.py",
             "condor/flyby/AGENT.md", "condor/flyby/PROFILE.yml", "condor/flyby/loops/flyby_operator/loop.md"]
    files.extend(f"conf/controllers/conf_flyby_{m}.yml" for m in ("eth", "btc", "sol", "hype"))
    report = {"mode": "local_validation", "checks_passed": passed, "stages": results,
              "source_sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
              "live_ready": False, "profitability_proven": False,
              "limits": ["success covers requested local checks only", "formal model excludes real connector/network",
                         "proxy history is previously inspected; chain capture is brief, not holdout/soak"]}
    (output / "validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k:v for k,v in report.items() if k not in ("stages", "source_sha256")}, indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
