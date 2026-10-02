"""Replay normalized options snapshots; strictly paper-only, no private API."""
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

from src.options.paper import PaperOptions, live_options_status
from src.options.spread_builder import OptionQuote


def smoke_rows(*, base_fee=.01):
    """Synthetic lifecycle fixture; chosen fees, NOT venue costs or P&L evidence.

    base_fee=.5 preserves the previous now-infeasible high-fixed-cost case.
    """
    rows = []
    start = 1790812800
    for n, kind in enumerate(("call", "put")):
        now = start + n * 30000
        signal = {"price": 3000, "trend_z": 1.9 if kind == "call" else -1.9,
                  "previous_trend_z": 1.8 if kind == "call" else -1.8,
                  "efficiency": .8, "previous_efficiency": .8, "volume_ratio": 1.8,
                  "previous_volume_ratio": 1.8, "atr_pct": .004, "stale_secs": 0,
                  "daily_pnl_pct": 0, "peak_dd": 0, "valid": True, "reconciled": True,
                  "ccy": "ETH", "option_iv_edge": .04}
        for j, increment in enumerate((0, 20, 30)):
            quotes = []
            for k, strike in enumerate((3000, 3100) if kind == "call" else (3000, 2900)):
                bid, ask = ((29 + increment, 30 + increment) if k == 0 else (9, 10))
                q = OptionQuote(f"ETH-20261004-{strike}-{'C' if kind == 'call' else 'P'}", "ETH", kind,
                                strike, start + 3 * 86400, 1, .01, .01, now + j * 300,
                                ((bid, 10),), ((ask, 10),), (.4 if k == 0 else .2) * (1 if kind == "call" else -1))
                quotes.append({**asdict(q), "fees": {"rate": .0003, "base": base_fee, "premium_cap": .125}})
            rows.append({"time": now + j * 300, "source": "synthetic_fixture", "spot": 3000,
                         "ccy": "ETH", "chain": quotes, "signal_snapshot": signal})
    return rows


def write_results(engine, output, digest):
    # Immutable output directories protect prior market evidence.
    output.mkdir(parents=True, exist_ok=False)
    summary = {**engine.summary(), "input_sha256": digest}
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    with (output / "trace.jsonl").open("w") as stream:
        for row in engine.events:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
    (output / "curve.json").write_text(json.dumps(engine.curve, indent=2, allow_nan=False) + "\n")
    (output / "checkpoint.json").write_text(json.dumps(engine.export_state(), allow_nan=False) + "\n")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    figure, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    hours = [(p["time"] - engine.curve[0]["time"]) / 3600 for p in engine.curve]
    equity = [p["equity"] if p["equity"] is not None else np.nan for p in engine.curve]
    axes[0].plot(hours, equity, marker="o", label="Options: net liquidation equity")
    axes[0].axhline(engine.capital, color="gray", linestyle="--", label="Starting cash")
    axes[0].set(xlabel="Elapsed hours", ylabel="Quote dollars", title="Options paper line — no combined perp account")
    axes[0].legend(fontsize=7)
    axes[1].plot(hours, [p["debit_at_risk"] if p["debit_at_risk"] is not None else np.nan for p in engine.curve], marker="o")
    axes[1].set(xlabel="Elapsed hours", ylabel="Debit + entry fees ($)", title="Matched open debit at risk; gaps = flat/unmatched")
    synthetic = "synthetic_fixture" in summary["data_sources"]
    figure.suptitle("SYNTHETIC EXECUTION SMOKE TEST — NOT STRATEGY PERFORMANCE" if synthetic else
                   "Observed public snapshots / simulated fills — not proven exchange execution")
    figure.savefig(output / "options_line.png", dpi=160)
    plt.close(figure)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--synthetic-smoke", action="store_true")
    inputs.add_argument("--capabilities", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.capabilities:
        print(json.dumps(live_options_status(), indent=2))
        return
    if args.output is None:
        parser.error("--output is required for replay")
    if args.output.exists():
        parser.error("choose a new immutable output directory")
    content = (args.input.read_bytes() if args.input else
               ("\n".join(json.dumps(row) for row in smoke_rows()) + "\n").encode())
    rows = [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    if not rows:
        parser.error("snapshot input is empty")
    if len({row["source"] for row in rows}) != 1:
        parser.error("market data and synthetic fixtures must not be mixed")
    engine = PaperOptions()
    for row in rows:
        engine.step(row)
    print(json.dumps(write_results(engine, args.output, hashlib.sha256(content).hexdigest()), indent=2))


if __name__ == "__main__":
    main()
