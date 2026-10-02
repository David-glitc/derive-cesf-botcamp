"""Plot completed Flyby traces. No orders, new simulations or strategy changes.

Runs are overlapping single-instrument scenario accounts, not one portfolio.
Final campaign entry records support sizing; baseline supports paired comparison.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.signal.flyby import INTERVAL_SECONDS

ROOT = Path(__file__).resolve().parents[1]
STARTING_EQUITY = 800.0
TIMEFRAMES = tuple(INTERVAL_SECONDS)


def read_trace(task):
    """Reconstruct marked notional, checking cash and entry/exit arithmetic."""
    path, expected = task
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected.trace_sha256:
        raise ValueError(f"Trace digest mismatch: {path}")
    count, cash, position, metadata = 0, STARTING_EQUITY, None, None
    curves, drawdowns, exposures, trades = [], [], [], []
    first48 = None
    first_time = None
    with gzip.open(path, "rt") as stream:
        for line in stream:
            record = json.loads(line)
            if isinstance(record, list):
                if len(record) != 7 or record[0] != count or metadata is None:
                    raise ValueError(f"Invalid sequence: {path}")
                equity, dd = record[4:6]
                if not np.isfinite([equity, dd]).all() or equity <= 0:
                    raise ValueError(f"Invalid equity: {path}")
                exposure = 0.0
                if position is not None:
                    # Equity is rounded to six decimals in the original trace.
                    mark = position["entry"] + (equity - cash) / (position["side"] * position["qty"])
                    if mark <= 0:
                        raise ValueError(f"Invalid implied mark: {path}")
                    exposure = position["qty"] * mark / equity * 100
                elif abs(equity - cash) > 1e-6:
                    raise ValueError(f"Flat equity/cash mismatch: {path}")
                if first_time is None:
                    first_time = record[1]
                seconds = INTERVAL_SECONDS[metadata["interval"]]
                if record[1] != first_time + count * seconds:
                    raise ValueError(f"Timestamp gap: {path}")
                if first48 is None and record[1] + seconds - first_time >= 48 * 3600:
                    first48 = (equity / STARTING_EQUITY - 1) * 100
                curves.append(equity)
                drawdowns.append(dd * 100)
                exposures.append(exposure)
                count += 1
            elif record["type"] == "metadata":
                metadata = record
                for key in ("run", "interval", "pair", "scenario"):
                    if metadata[key] != getattr(expected, key):
                        raise ValueError(f"Metadata mismatch: {path}")
            elif record["type"] == "entry_fill":
                if position is not None or abs(record["equity_before_fee"] - cash) > 1e-7:
                    raise ValueError(f"Entry cash mismatch: {path}")
                if record["qty"] <= 0 or record["side"] not in (-1, 1):
                    raise ValueError(f"Invalid entry: {path}")
                if abs(record["notional"] - record["qty"] * record["entry"]) > 1e-7:
                    raise ValueError(f"Entry notional mismatch: {path}")
                position = record
                cash -= record["fee"]
            elif record["type"] == "fill":
                if position is None or any(record[k] != position[k] for k in ("qty", "entry", "side")):
                    raise ValueError(f"Unmatched close: {path}")
                if abs(record["entry_fee"] - position["fee"]) > 1e-7:
                    raise ValueError(f"Entry fee mismatch: {path}")
                net = record["gross"] - record["entry_fee"] - record["exit_fee"] + record["funding"]
                if abs(record["net"] - net) > 1e-7:
                    raise ValueError(f"Close P&L mismatch: {path}")
                cash += record["gross"] - record["exit_fee"] + record["funding"]
                before = position["equity_before_fee"]
                trades.append({"run": expected.run, "interval": expected.interval, "pair": expected.pair,
                               "scenario": expected.scenario, "entry_i": position["i"], "close_i": record["i"],
                               "confidence": position["confidence"], "notional": position["notional"],
                               "allocation_pct": position["notional"] / before * 100,
                               "stop_risk_pct": position["notional"] * position["stop"] / before * 100,
                               "stop_pct": position["stop"] * 100,
                               "pre_entry_return_pct": (before / STARTING_EQUITY - 1) * 100,
                               "hold_grid_hours": (record["i"] - position["i"]) * INTERVAL_SECONDS[expected.interval] / 3600,
                               "gross": record["gross"], "net": net,
                               "fees": record["entry_fee"] + record["exit_fee"],
                               "funding": record["funding"], "reason": record["reason"]})
                position = None
    if position is not None or count != expected.bars or len(trades) != expected.trades:
        raise ValueError(f"Incomplete trace: {path}")
    if abs(cash - expected.ending_equity) > 1e-7:
        raise ValueError(f"Terminal equity mismatch: {path}")
    if abs(sum(t["fees"] for t in trades) - expected.fees_quote) > 1e-7:
        raise ValueError(f"Fee total mismatch: {path}")
    return {"run": expected.run, "equity": np.asarray(curves), "drawdown": np.asarray(drawdowns),
            "exposure": np.asarray(exposures, dtype=np.float32), "trades": trades, "first48": first48}


def save(figure, directory, name):
    import matplotlib.pyplot as plt
    figure.savefig(directory / name, dpi=165)
    plt.close(figure)


def main():
    # Plotting is a local analysis dependency, not a competition runtime import.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=ROOT / "stress_artifacts/campaign-final-20261001")
    parser.add_argument("--output", type=Path, default=ROOT / "reports")
    parser.add_argument("--workers", type=int, choices=range(1, 7), default=4)
    args = parser.parse_args()
    frame = pd.read_csv(args.campaign / "runs.csv").sort_values("run").reset_index(drop=True)
    tasks = [(args.campaign / "traces" / f"run-{int(r['run']):04d}.jsonl.gz", SimpleNamespace(**r))
             for r in frame.to_dict("records")]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(read_trace, tasks, chunksize=8))
    equity = np.stack([r["equity"] for r in results])
    dd = np.stack([r["drawdown"] for r in results])
    exposure = np.stack([r["exposure"] for r in results])
    trades = pd.DataFrame([t for r in results for t in r["trades"]])
    if trades.empty:
        raise ValueError("No entries available to plot")
    frame["first48h_return_pct"] = [r["first48"] for r in results]
    frame["bar_close_occupancy_pct"] = (exposure > 0).mean(axis=1) * 100
    frame["mean_bar_close_exposure_pct"] = exposure.mean(axis=1)
    args.output.mkdir(parents=True, exist_ok=True)
    colors = dict(zip(TIMEFRAMES, ("#2563eb", "#08916b", "#b66800", "#8a4dc4")))
    plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False})

    figure, axes = plt.subplots(2, 4, figsize=(15, 7), constrained_layout=True)
    for j, tf in enumerate(TIMEFRAMES):
        mask = frame.interval.eq(tf).to_numpy()
        days = (np.arange(equity.shape[1]) + 1) * INTERVAL_SECONDS[tf] / 86400
        for row, matrix, label in ((0, (equity / 800 - 1) * 100, "Net marked return (%)"),
                                   (1, dd, "Marked drawdown (%)")):
            low, median, high = np.percentile(matrix[mask], [10, 50, 90], axis=0)
            ax = axes[row, j]
            ax.fill_between(days, low, high, color=colors[tf], alpha=.18, label="Scenario p10–p90")
            ax.plot(days, median, color=colors[tf], label="Scenario median")
            ax.axhline(0, color="gray", linewidth=.7)
            ax.set(xlabel="Elapsed days", ylabel=label if j == 0 else "", title=f"{tf}: {mask.sum()} runs / {days[-1]:.1f} days")
        axes[0, j].legend(fontsize=7)
    figure.suptitle("Final Flyby replay: $800 per single-asset account — overlapping scenarios, not a joint portfolio")
    save(figure, args.output, "flyby_equity_drawdown.png")

    baseline = pd.read_csv(ROOT / "stress_artifacts/campaign-baseline-20261001/runs.csv")
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    x = np.arange(4)
    axes[0, 0].bar(x - .18, [baseline[baseline.interval.eq(tf)].return_pct.mean() for tf in TIMEFRAMES], .36, label="Baseline")
    axes[0, 0].bar(x + .18, [frame[frame.interval.eq(tf)].return_pct.mean() for tf in TIMEFRAMES], .36, label="Final / mitigated")
    axes[0, 0].set(xticks=x, xticklabels=TIMEFRAMES, ylabel="Mean full-run return (%)", title="Paired comparison; different calendar durations")
    axes[0, 0].legend()
    for tf in TIMEFRAMES:
        mask = frame.interval.eq(tf).to_numpy()
        n = int(48 * 3600 / INTERVAL_SECONDS[tf])
        hours = (np.arange(n) + 1) * INTERVAL_SECONDS[tf] / 3600
        axes[0, 1].plot(hours, ((equity[mask, :n] / 800 - 1) * 100).mean(axis=0), label=tf, color=colors[tf])
    axes[0, 1].set(xlabel="Elapsed hours", ylabel="Mean marked return (%)", title="First 48h, including no-trade runs")
    axes[0, 1].legend()
    for column, ylabel, ax in (("volume_quote", "Mean modeled traded notional ($/run)", axes[1, 0]),
                               ("fees_quote", "Mean modeled fees ($/run)", axes[1, 1])):
        ax.bar(TIMEFRAMES, [frame[frame.interval.eq(tf)][column].mean() for tf in TIMEFRAMES], color=list(colors.values()))
        ax.set(ylabel=ylabel, title="Both entry and exit counted" if column == "volume_quote" else "No exchange rebates modeled")
    figure.suptitle("15M total evaluations = 3 × 5M; final adds entry traces, not a third independent P&L result")
    save(figure, args.output, "flyby_performance_overview.png")

    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for tf in TIMEFRAMES:
        group = trades[trades.interval.eq(tf)]
        axes[0, 0].hist(group.allocation_pct, bins=np.linspace(0, 21, 43), histtype="step", label=tf, color=colors[tf])
        axes[0, 1].hist(group.stop_risk_pct, bins=np.linspace(0, .51, 45), histtype="step", label=tf, color=colors[tf])
    axes[0, 0].set(xlabel="Filled entry notional / pre-entry equity (%)", ylabel="Trade entries", title="Sizing (20% entry cap)")
    axes[0, 1].set(xlabel="Notional × stop distance / equity (%)", ylabel="Trade entries", title="Planned stop risk: excludes fees and gaps")
    axes[0, 0].legend()
    sample = trades.iloc[::max(1, len(trades) // 4000)]
    dots = axes[1, 0].scatter(sample.pre_entry_return_pct, sample.allocation_pct, c=sample.confidence,
                              s=5, alpha=.5, cmap="viridis", vmin=.7, vmax=1)
    axes[1, 0].set(xlabel="Account return before entry (%) — not peak drawdown", ylabel="Entry allocation (%)",
                   title="Sizing declines as losses accumulate; deterministic sample")
    figure.colorbar(dots, ax=axes[1, 0], label="Heuristic confidence (not probability)")
    axes[1, 1].bar(x - .18, [frame[frame.interval.eq(tf)].bar_close_occupancy_pct.mean() for tf in TIMEFRAMES], .36, label="Bars with open position (%)")
    axes[1, 1].bar(x + .18, [frame[frame.interval.eq(tf)].mean_bar_close_exposure_pct.mean() for tf in TIMEFRAMES], .36, label="Mean marked notional / equity (%)")
    axes[1, 1].set(xticks=x, xticklabels=TIMEFRAMES, ylabel="Percent", title="Bar-close observations, including flat accounts")
    axes[1, 1].legend(fontsize=8)
    figure.suptitle("Final 5M traces: filled sizing and gross exposure — same-bar trades disappear from close exposure")
    save(figure, args.output, "flyby_sizing_exposure.png")

    figure, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    reasons = trades.groupby("reason").agg(count=("net", "size"), net=("net", "sum")).sort_values("count", ascending=False)
    axes[0, 0].barh(reasons.index, reasons["count"] / len(trades) * 100)
    axes[0, 0].set(xlabel="Share of closes (%)", title="Exit reasons")
    axes[0, 1].barh(reasons.index, reasons.net / len(frame))
    axes[0, 1].set(xlabel="Contribution to mean account net P&L ($)", title="Sum of each reason / 1,000 accounts")
    axes[0, 1].axvline(0, color="gray", linewidth=.7)
    components = [trades.gross.sum(), -trades.fees.sum(), trades.funding.sum(), trades.net.sum()]
    axes[1, 0].bar(["Gross*", "Fees", "Funding", "Net"], np.asarray(components) / len(frame),
                   color=["#2563eb", "#d14b4b", "#b66800", "#8a4dc4"])
    axes[1, 0].set(ylabel="Mean dollars per account", title="*Gross already includes modeled slippage")
    axes[1, 1].bar(TIMEFRAMES, [trades[trades.interval.eq(tf)].net.gt(0).mean() * 100 for tf in TIMEFRAMES], color=list(colors.values()))
    axes[1, 1].set(ylabel="Net-profitable closed trades (%)", title="Trade win rate, not profitable-run rate")
    figure.suptitle(f"{len(trades):,} simulated closed perp trades — no real option P&L in this dataset")
    save(figure, args.output, "flyby_trade_diagnostics.png")

    by_tf = []
    for tf in TIMEFRAMES:
        runs, group = frame[frame.interval.eq(tf)], trades[trades.interval.eq(tf)]
        by_tf.append({"interval": tf, "runs": len(runs), "mean_return_pct": float(runs.return_pct.mean()),
                      "mean_first48h_return_pct": float(runs.first48h_return_pct.mean()),
                      "mean_volume_quote": float(runs.volume_quote.mean()), "mean_fees_quote": float(runs.fees_quote.mean()),
                      "median_entry_allocation_pct": float(group.allocation_pct.median()),
                      "max_entry_allocation_pct": float(group.allocation_pct.max()),
                      "median_stop_risk_pct": float(group.stop_risk_pct.median()),
                      "net_trade_win_pct": float(group.net.gt(0).mean() * 100),
                      "mean_bar_close_occupancy_pct": float(runs.bar_close_occupancy_pct.mean()),
                      "mean_bar_close_exposure_pct": float(runs.mean_bar_close_exposure_pct.mean())})
    summary = {"campaign": args.campaign.name, "verified_traces": len(results), "verified_bar_records": int(equity.size),
               "closed_trades": len(trades), "starting_equity": STARTING_EQUITY,
               "source_runs_sha256": hashlib.sha256((args.campaign / "runs.csv").read_bytes()).hexdigest(),
               "by_timeframe": by_tf, "exit_reasons": reasons.reset_index().to_dict("records"),
               "mean_gross_quote": float(trades.gross.sum() / len(frame)),
               "mean_net_quote": float(trades.net.sum() / len(frame)),
               "same_bar_closes": int((trades.close_i == trades.entry_i).sum()),
               "median_allocation_pct": float(trades.allocation_pct.median()),
               "max_stop_risk_pct": float(trades.stop_risk_pct.max())}
    (args.output / "flyby_portfolio_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    pd.DataFrame(by_tf).to_csv(args.output / "flyby_portfolio_by_timeframe.csv", index=False)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
