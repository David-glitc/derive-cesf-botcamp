"""Verify every trace record and produce sanitized replay evidence."""
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
from src.signal.flyby import INTERVAL_SECONDS

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


def verify_trace(item):
    path, expected_hash, bars = item
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise AssertionError(f"trace digest mismatch {path}")
    count = fills = options = entries = 0
    pending = None
    first_time = first48 = seconds = None
    with gzip.open(path, "rt") as stream:
        for line in stream:
            record = json.loads(line)
            if isinstance(record, list):
                if record[0] != count or len(record) != 7 or not np.isfinite(record[4]):
                    raise AssertionError(f"trace sequence/number {path}")
                count += 1
                if first_time is None:
                    first_time = record[1]
                if first48 is None and record[1] + seconds - first_time >= 48 * 3600:
                    first48 = (record[4] / 800 - 1) * 100
            elif record.get("type") == "fill":
                fills += 1
                if "gross" in record:
                    assert pending is not None and record["qty"] == pending["qty"]
                    assert record["side"] == pending["side"]
                    assert abs(record["gross"] - record["entry_fee"] - record["exit_fee"] + record["funding"] - record["net"]) < 1e-7
                    pending = None
            elif record.get("type") == "entry_fill":
                assert pending is None and record["qty"] > 0
                pending = record
                entries += 1
            elif record.get("type") == "options_probe":
                assert record["orders_submitted"] == 0 and record["plan"]["signal_only"]
                options += 1
            elif record.get("type") == "metadata":
                seconds = INTERVAL_SECONDS[record["interval"]]
    if count != bars or options != 1:
        raise AssertionError(f"trace count mismatch {path}")
    if pending is not None or (entries and entries != fills):
        raise AssertionError(f"unmatched replay fill {path}")
    return count, fills, first48


def main():
    paths = [ROOT / "stress_artifacts" / f"campaign-{lane}-20261001" for lane in ("baseline", "mitigated", "final")]
    reports = ROOT / "reports"
    reports.mkdir(exist_ok=True)
    summaries, frames, audits = [], [], []
    for directory in paths:
        summary = json.loads((directory / "summary.json").read_text())
        manifest = json.loads((directory / "manifest.json").read_text())
        frame = pd.read_csv(directory / "runs.csv")
        tasks = [(directory / "traces" / f"run-{int(r.run):04d}.jsonl.gz", r.trace_sha256, int(r.bars))
                 for r in frame.itertuples()]
        with ProcessPoolExecutor(max_workers=4) as pool:
            counts = list(pool.map(verify_trace, tasks, chunksize=8))
        evaluations = sum(c[0] for c in counts)
        # Recompute from trace close times: older CSVs sampled one bar after
        # 48h. This report uses exactly the first 48h closed equity snapshot.
        frame["first48h_return_pct"] = [c[2] for c in counts]
        assert evaluations == summary["bar_evaluations"] == 5_000_000 and len(tasks) == 1000
        if (directory / "source").exists():
            for name, digest in manifest["code_sha256"].items():
                assert hashlib.sha256((directory / "source" / name).read_bytes()).hexdigest() == digest
        audit = {"campaign": directory.name, "verified_traces": len(tasks), "verified_bar_records": evaluations,
                 "close_fill_records": sum(c[1] for c in counts),
                 "manifest_sha256": hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest(),
                 "summary_sha256": hashlib.sha256((directory / "summary.json").read_bytes()).hexdigest()}
        audits.append(audit)
        summaries.append(summary)
        frames.append(frame)
        print(json.dumps(audit), flush=True)
    baseline, mitigated, final = summaries
    for column in ("return_pct", "ending_equity", "max_drawdown_pct", "trades", "fees_quote"):
        pd.testing.assert_series_equal(frames[1][column], frames[2][column])
    (reports / "stress_summary.json").write_text(json.dumps({"baseline": baseline, "mitigated": mitigated,
                                                           "final_confirmation": final, "trace_audits": audits}, indent=2))
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for ax, summary, label in zip(axes, summaries, ("Corrected baseline", "Risk-mitigated")):
        matrix = np.asarray(summary["confusion_6h"])
        normalized = matrix / matrix.sum(axis=1, keepdims=True)
        ax.imshow(normalized, cmap="Blues", vmin=0, vmax=1)
        for (i, j), value in np.ndenumerate(matrix):
            ax.text(j, i, f"{value:,}\n{normalized[i,j]:.1%}", ha="center", va="center",
                    color="white" if normalized[i,j] > .5 else "black", fontsize=8)
        ax.set(xticks=range(3), yticks=range(3), xticklabels=["Short", "Flat", "Long"],
               yticklabels=["Down", "Flat", "Up"], xlabel="Policy signal", ylabel="6h forward class",
               title=label)
    figure.suptitle("Forward proxy diagnostic — 6h nominal (4h grid: 4h), ±0.5%; not trade P&L", fontsize=10)
    figure.savefig(reports / "stress_confusion.png", dpi=180)
    plt.close(figure)
    figure, axes = plt.subplots(1, 2, figsize=(10, 4), constrained_layout=True)
    for frame, label in zip(frames, ("Baseline", "Mitigated")):
        axes[0].hist(frame.return_pct, bins=35, alpha=.5, label=label)
        axes[1].hist(frame.max_drawdown_pct, bins=35, alpha=.5, label=label)
    axes[0].set(xlabel="Run return (%)", ylabel="Scenario runs", title="Net returns")
    axes[1].set(xlabel="Worst marked drawdown (%)", title="Drawdown")
    for ax in axes: ax.legend()
    figure.savefig(reports / "stress_distributions.png", dpi=180)
    plt.close(figure)
    text = ["# Flyby stress report — 2026-10-01", "",
            "**Verdict: NO-GO for live trading.** Risk mitigations reduced losses in the replay,",
            "but didn't demonstrate a profitable edge. No live or testnet orders were submitted.", "",
            "## Campaign scope", "",
            "Three campaigns completed 1,000 runs each, 5,000 bars per run: **15 million total**",
            "bar evaluations. Each campaign assigns 250 runs to 5m, 15m, 1h and 4h.",
            "Inputs are 64,800 unique closed Binance USD-M perpetual candles across ETH/BTC/SOL,",
            "ending before 2026-10-01 UTC. HYPE has configuration/rule checks, not this P&L replay.", "",
            "Seeds start at 20261001. Ten scenarios cover base costs, 3× fees, 5× slippage,",
            "thin depth, rejected orders, partial fills, stale feeds, poisoned data windows,",
            "a price-gap shock and idempotent ledger restart. Runs reuse overlapping periods.",
            "This is a stress comparison, **not 1,000 independent samples or out-of-sample proof**.",
            "The third campaign confirmed identical per-run returns, fees, trade counts and",
            "drawdowns after planner hardening, with richer entry/exit traces and source snapshots.", "",
            "## Aggregate result", "",
            "| Metric | Corrected baseline | Mitigated |", "|---|---:|---:|"]
    for name, key, fmt in [("Mean return", "mean_return_pct", ".2f"), ("Median return", "median_return_pct", ".2f"),
                           ("Worst return", "worst_return_pct", ".2f"), ("Worst drawdown", "worst_drawdown_pct", ".2f")]:
        text.append(f"| {name} | {baseline[key]:{fmt}}% | {mitigated[key]:{fmt}}% |")
    text.extend([f"| Profitable runs | {baseline['profitable_runs']}/1000 | {mitigated['profitable_runs']}/1000 |",
                 f"| Closed trades | {baseline['trades']:,} | {mitigated['trades']:,} |", "",
                 "Both campaigns include 100 no-trade thin-book runs with 0% return. A flat run",
                 "isn't profitable. Aggregate returns include cost stress; baseline-cost runs",
                 f"alone average {baseline['by_scenario']['base']['mean_return_pct']:.2f}% before and",
                 f"{mitigated['by_scenario']['base']['mean_return_pct']:.2f}% after mitigation.", "",
                 "## By timeframe", "",
                 "| Timeframe | Runs each | Baseline mean | Mitigated mean | Mitigated worst DD |",
                 "|---|---:|---:|---:|---:|"])
    for tf in ("5m", "15m", "1h", "4h"):
        b, m = baseline["by_timeframe"][tf], mitigated["by_timeframe"][tf]
        text.append(f"| {tf} | 250 | {b['mean_return_pct']:.2f}% | {m['mean_return_pct']:.2f}% | {m['worst_drawdown_pct']:.2f}% |")
    text.extend(["", "## Cost decomposition", "",
                 "Mean dollars per scenario run, not compounded portfolio returns:", "",
                 "| Component | Baseline | Mitigated |", "|---|---:|---:|"])
    parts = []
    for frame in frames[:2]:
        net = frame.ending_equity - 800
        parts.append({"Gross P&L (includes modeled slippage)": (net + frame.fees_quote - frame.funding_quote).mean(),
                      "Fees paid": frame.fees_quote.mean(), "Funding": frame.funding_quote.mean(), "Net P&L": net.mean()})
    for label in parts[0]:
        text.append(f"| {label} | ${parts[0][label]:.2f} | ${parts[1][label]:.2f} |")
    text.extend(["", "Gross P&L is already negative before fees/funding. Lower costs alone don't",
                 "establish an edge; signal selection also needs improvement."])
    text.extend(["", "## Two-day horizon", "",
                 "The 5,000-bar runs span different calendar durations. These additional",
                 "48h measurements use marked equity and include no-trade runs. First-48h",
                 "returns are recomputed from trace close times; older CSV fields sampled",
                 "one bar late and aren't used for this table:", "",
                 "| Timeframe | Mean first 48h return | Worst rolling 48h return |", "|---|---:|---:|"])
    for tf, group in frames[1].groupby("interval"):
        text.append(f"| {tf} | {group.first48h_return_pct.mean():.2f}% | {group.worst48h_return_pct.min():.2f}% |")
    text.extend(["", "## What broke and what changed", "",
                 "- Old exit fields were ignored by the real executor model; exits now serialize inside `TripleBarrierConfig`.",
                 "- Old spot connector/HEDGE/candle settings were incompatible; profiles now validate on v2.17.",
                 "- Signal churn and costs dominated replay P&L. Added consecutive-bar confirmation, confidence ≥0.70 and a 3× cost-distance gate.",
                 "- Reduced sizing with drawdown; tightened daily/peak guard triggers from 3%/6% to 2%/4%.",
                 "- Fixed owned-position handling and normal inter-bar candle age; unknown exposure still blocks entries.",
                 "- Missing/stale/invalid data halts; depth shortages and unverified option execution don't produce orders.",
                 "- Helper ledger rejects non-finite/conflicting events and restores idempotently.", "",
                 "These mitigations were selected after seeing baseline losses. The second run",
                 "uses the same seeds for a paired comparison, not independent validation.",
                 "Loss reduction partly reflects smaller risk/earlier stopping, not better alpha.", "",
                 "## Trace audit", "",
                 "Every one of the 3,000 gzip trace files passed SHA-256, sequential-record and",
                 "bar-count checks: 15,000,000 bar records, close-fill events and 3,000 synthetic",
                 "option-planner probes. Traces are local ignored files under `stress_artifacts/`.",
                 "Manifest hashes and audit counts are in [stress_summary.json](stress_summary.json).",
                 "Mitigated/final manifests include source snapshots. The earlier baseline",
                 "records source hashes but doesn't include snapshots of every historical file.", "",
                 "![Directional matrix](stress_confusion.png)", "",
                 "The matrix labels nominal forward 6h price movement at ±0.5%; the 4h grid",
                 "uses a 4h horizon (one bar), not an interpolated 6h quote. Columns show policy",
                 "signals, not necessarily executed trades. Neutral labels don't mean holding",
                 "an open position. Period reuse inflates counts; it doesn't add independent evidence.", "",
                 "![Returns and drawdown](stress_distributions.png)", "",
                 "## Limits and remaining live blockers", "",
                 "- Actual Hummingbot models/controller ticks pass separately; historical execution is a simulator, not full exchange E2E.",
                 "- Next-open fills, stop-first OHLC collisions, modeled bid/ask impact, assumed 0.06% per-side fees and funding are approximations.",
                 "- Historical Derive basis, depth, queue priority, auth and matching are absent. Partial fills/rejects are simulated; venue quantity/minimum rules aren't replayed.",
                 "- 4h bars can't resolve sub-bar exits or a 6h timer precisely; guard triggers aren't guaranteed loss bounds.",
                 "- Synthetic option probes test arithmetic/exits, not a paired order lifecycle, actual IV selection or option P&L.",
                 "- The pinned Derive adapter hard-codes `reduce_only: false`; one-way executor closes use OPEN. Safe close semantics aren't proven.",
                 "- The adapter's empty-position response doesn't clear cached positions; stream/restart/fill reconciliation needs an integration soak.",
                 "- A local testnet book diagnostic was not ready; a read-only ETH book request timed out after 25 seconds. No live book readiness is claimed.",
                 "- Risk checkpoints assume stable IDs, budget and no external cash flows. A deposit/withdrawal isn't strategy profit.", "",
                 "See [readiness gates](../COMPETITION_READINESS.md). Samples stay paused;",
                 "do not fund a live run based on this report.", ""])
    (reports / "STRESS_REPORT.md").write_text("\n".join(text))


if __name__ == "__main__":
    main()
