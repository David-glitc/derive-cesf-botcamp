# Flyby stress report — 2026-10-01

**Verdict: NO-GO for live trading.** Risk mitigations reduced losses in the replay,
but didn't demonstrate a profitable edge. No live or testnet orders were submitted.

## Campaign scope

Three campaigns completed 1,000 runs each, 5,000 bars per run: **15 million total**
bar evaluations. Each campaign assigns 250 runs to 5m, 15m, 1h and 4h.
Inputs are 64,800 unique closed Binance USD-M perpetual candles across ETH/BTC/SOL,
ending before 2026-10-01 UTC. HYPE has configuration/rule checks, not this P&L replay.

Seeds start at 20261001. Ten scenarios cover base costs, 3× fees, 5× slippage,
thin depth, rejected orders, partial fills, stale feeds, poisoned data windows,
a price-gap shock and idempotent ledger restart. Runs reuse overlapping periods.
This is a stress comparison, **not 1,000 independent samples or out-of-sample proof**.
The third campaign confirmed identical per-run returns, fees, trade counts and
drawdowns after planner hardening, with richer entry/exit traces and source snapshots.

## Aggregate result

| Metric | Corrected baseline | Mitigated |
|---|---:|---:|
| Mean return | -4.22% | -1.88% |
| Median return | -5.25% | -1.84% |
| Worst return | -6.22% | -4.07% |
| Worst drawdown | -6.28% | -4.09% |
| Profitable runs | 1/1000 | 10/1000 |
| Closed trades | 124,059 | 92,598 |

Both campaigns include 100 no-trade thin-book runs with 0% return. A flat run
isn't profitable. Aggregate returns include cost stress; baseline-cost runs
alone average -4.54% before and
-2.19% after mitigation.

## By timeframe

| Timeframe | Runs each | Baseline mean | Mitigated mean | Mitigated worst DD |
|---|---:|---:|---:|---:|
| 5m | 250 | -2.69% | -0.52% | -1.33% |
| 15m | 250 | -5.01% | -1.37% | -2.84% |
| 1h | 250 | -5.11% | -3.22% | -4.06% |
| 4h | 250 | -4.05% | -2.42% | -4.09% |

## Cost decomposition

Mean dollars per scenario run, not compounded portfolio returns:

| Component | Baseline | Mitigated |
|---|---:|---:|
| Gross P&L (includes modeled slippage) | $-9.38 | $-5.36 |
| Fees paid | $23.97 | $9.52 |
| Funding | $-0.39 | $-0.17 |
| Net P&L | $-33.74 | $-15.05 |

Gross P&L is already negative before fees/funding. Lower costs alone don't
establish an edge; signal selection also needs improvement.

## Two-day horizon

The 5,000-bar runs span different calendar durations. These additional
48h measurements use marked equity and include no-trade runs. First-48h
returns are recomputed from trace close times; older CSV fields sampled
one bar late and aren't used for this table:

| Timeframe | Mean first 48h return | Worst rolling 48h return |
|---|---:|---:|
| 15m | -0.06% | -1.18% |
| 1h | -0.04% | -0.84% |
| 4h | -0.01% | -1.19% |
| 5m | -0.06% | -0.47% |

## What broke and what changed

- Old exit fields were ignored by the real executor model; exits now serialize inside `TripleBarrierConfig`.
- Old spot connector/HEDGE/candle settings were incompatible; profiles now validate on v2.17.
- Signal churn and costs dominated replay P&L. Added consecutive-bar confirmation, confidence ≥0.70 and a 3× cost-distance gate.
- Reduced sizing with drawdown; tightened daily/peak guard triggers from 3%/6% to 2%/4%.
- Fixed owned-position handling and normal inter-bar candle age; unknown exposure still blocks entries.
- Missing/stale/invalid data halts; depth shortages and unverified option execution don't produce orders.
- Helper ledger rejects non-finite/conflicting events and restores idempotently.

These mitigations were selected after seeing baseline losses. The second run
uses the same seeds for a paired comparison, not independent validation.
Loss reduction partly reflects smaller risk/earlier stopping, not better alpha.

## Trace audit

Every one of the 3,000 gzip trace files passed SHA-256, sequential-record and
bar-count checks: 15,000,000 bar records, close-fill events and 3,000 synthetic
option-planner probes. Traces are local ignored files under `stress_artifacts/`.
Manifest hashes and audit counts are in [stress_summary.json](stress_summary.json).
Mitigated/final manifests include source snapshots. The earlier baseline
records source hashes but doesn't include snapshots of every historical file.

![Directional matrix](stress_confusion.png)

The matrix labels nominal forward 6h price movement at ±0.5%; the 4h grid
uses a 4h horizon (one bar), not an interpolated 6h quote. Columns show policy
signals, not necessarily executed trades. Neutral labels don't mean holding
an open position. Period reuse inflates counts; it doesn't add independent evidence.

![Returns and drawdown](stress_distributions.png)

## Limits and remaining live blockers

- Actual Hummingbot models/controller ticks pass separately; historical execution is a simulator, not full exchange E2E.
- Next-open fills, stop-first OHLC collisions, modeled bid/ask impact, assumed 0.06% per-side fees and funding are approximations.
- Historical Derive basis, depth, queue priority, auth and matching are absent. Partial fills/rejects are simulated; venue quantity/minimum rules aren't replayed.
- 4h bars can't resolve sub-bar exits or a 6h timer precisely; guard triggers aren't guaranteed loss bounds.
- Synthetic option probes test arithmetic/exits, not a paired order lifecycle, actual IV selection or option P&L.
- The pinned Derive adapter hard-codes `reduce_only: false`; one-way executor closes use OPEN. Safe close semantics aren't proven.
- The adapter's empty-position response doesn't clear cached positions; stream/restart/fill reconciliation needs an integration soak.
- A local testnet book diagnostic was not ready; a read-only ETH book request timed out after 25 seconds. No live book readiness is claimed.
- Risk checkpoints assume stable IDs, budget and no external cash flows. A deposit/withdrawal isn't strategy profit.

See [readiness gates](../COMPETITION_READINESS.md). Samples stay paused;
do not fund a live run based on this report.
