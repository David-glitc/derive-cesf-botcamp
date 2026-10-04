# Five-million-path portfolio risk screen

All 5,000,000 paths completed. Both perp profiles and the hypothetical combined
profile are **discarded from the research shortlist** under the requested rule:
any modeled initial-capital trough loss **or** peak-to-trough dollar drawdown
strictly above $500 rejects the setup. No configuration was deleted, activated
or promoted. No real orders were sent.

The ordinary empirical cases have no $500 breach but negative mean P&L. Their
corresponding gap/fee cases breach the limit, so neither perp profile survives
the full screen. This is an accelerated conditional risk model, not five million
full controller, Condor, exchange or historical-market backtests.

## Measured results

Each independent path starts with $800 and models a 48-hour opportunity window.
Dollar values below are rounded; the saved summary retains full precision.
"Breach paths" counts the union of initial-capital and peak-to-trough violations,
not just losses at the end of a path.

| Case | Paths | Mean terminal P&L | Worst initial-capital loss | Worst peak-to-trough loss | Breach paths | Case verdict |
|---|---:|---:|---:|---:|---:|---|
| Baseline empirical perps | 1,000,000 | −$40.54 | $86.09 | $87.44 | 0 | No modeled $500 breach; negative mean |
| ETH wider-cap empirical perps | 1,000,000 | −$44.41 | $87.04 | $89.08 | 0 | No modeled $500 breach; negative mean |
| Baseline gap/fee stress | 1,000,000 | −$80.01 | $658.20 | $767.38 | 5,215 | Discarded |
| ETH wider-cap gap/fee stress | 1,000,000 | −$80.38 | $1,279.14 | $1,402.01 | 4,788 | Discarded |
| Combined hypothetical option-fault stress | 1,000,000 | −$63.39 | $1,278.67 | $1,299.00 | 3,645 | Discarded; options also quarantined |

The −10% restricted / −15% hard-stop latches persist after recovery. They stop
or restrict subsequent entries; they cannot guarantee a −15% fill during a
discontinuous price jump. The stress model retains raw negative equity: 1,146
wider-cap perp paths and 862 combined paths reach nonpositive marked equity.
These are model failures, not estimates of venue liquidation prices, debt or
collectable losses. Exchange margin/liquidation mechanics are not simulated.

## What the model actually tests

The runner resamples eight-trade blocks from two existing conditional replay
tapes: 344 baseline trades and 315 wider-cap trades. Those tapes come from the
two-year public-underlying replay; they are small and already selected by prior
risk latches. Five million resamples do not create five million independent
historical market observations or expose regimes missing from those tapes.

Each path has 192 conditional 15-minute opportunity slots. A trade episode's
cash outcome and mark extrema are applied at its opportunity slot; its recorded
holding duration blocks later entries. Episodes that cannot complete within
48 hours are skipped, rather than inventing a post-horizon close. Favorable
before adverse OHLC extrema give a pessimistic drawdown envelope, including the
closing bar; actual intrabar chronology and post-fill extrema are unknown.

The risk-only sizing surrogate uses $800 capped allocation, 0.5% trade risk,
fixed 0.9 confidence, a 0.7% stop and 1.365% target. Estimated round-trip cost is
0.43%; entry requires 3× costs normally and 4× when restricted. At these fixed
values, restricted entries fail the cost gate. Baseline perp notional is capped
at 20%; the separate ETH test uses 40% notional/gross. SOL stays baseline.
Recorded minimum lots and quantity steps are enforced without rounding up.
Leverage does not multiply notional or P&L.

This does not re-execute changing signal confidence, ATR, native books,
freshness, actual available margin or the full controller/Condor loop. Mean
empirical perp turnover is $50,034.68 baseline and $60,604.13 wider-cap, but that
reflects conditional opportunity resampling, **not a competition-volume forecast**.
Their mean fees are $33.23 and $39.54 respectively, with net P&L still negative.

### Declared stress assumptions

Gap/fee cases apply unexpected 3× fees and 8 basis points of extra adverse
slippage per side. Each filled perp episode has an assumed 0.0002 chance of an
adversarial +400% price jump or −80% crash, chosen with equal probability.
Those are deliberately extreme sensitivity inputs, not estimated probabilities.
The breach counts must not be presented as real-world loss likelihoods.

The combined case adds a hypothetical 0.1 ETH paired vertical with $1.10 debit,
$2.348 round-trip fee reserve and $10 maximum payoff. Its scripted six-hour
close credits are $0.49, $3.49 or $4.59 with equal assumed probability. Eligible
slots have a 10% option opportunity assumption and entered spreads a 10%
blocked-exit assumption. These probabilities are not calibrated. The prior
current-rules historical replay executed **zero options**, so there is no
historical option-fill tape to resample.

There are 204,280 blocked-option paths, retaining 408,560 matched legs across
independent portfolios. Their spread marks remain bounded between $0 and $10;
no subsequent entry is allowed around unresolved inventory, and no terminal
close is fabricated. The less-negative combined mean is not evidence of option
alpha: blocked inventory also suppresses subsequent perp trading. The actual
[option exit-fee/recovery blocker](OPTIONS_EXECUTION_FEE_AUDIT.md) remains
unfixed and quarantined; this simulation does not clear it.

## Reproducibility and verification

The final run used seed `20261003`, batches of 50,000 and completed in 75.65
seconds. The accelerated risk math matched the production reducer/sizer in
144 checked variants. The focused portfolio, option-audit, exposure-profile
and submission-bundle suite passed **46 tests**. This is not a new full pinned
Hummingbot test run or a live soak.

Saved [final summary](../data/validation/two-year-20261003/portfolio-paths-5m-final/summary.json):

```text
SHA-256: dc1515055d5443767fb24f74c9a45e073f0abb10d498c85a714586b97c68c9f0
```

The summary records five compressed arrays with 1,000,000 × 14 metrics each,
five worst-path CSV traces, source/input/artifact hashes and explicit limitations.
Independent verification checked all hashes, finite array values, recomputed
case statistics, total path count and worst-trace terminal metrics. Each worst
path was also replayed exactly against its saved metric row by the runner.

An earlier completed pass allowed episodes to extend beyond the horizon. It
is preserved in `portfolio-paths-5m/` but **superseded**; only
`portfolio-paths-5m-final/` supports this report. Neither pass changes production.

See [reproduction commands](../backtest/TWO_YEAR_REPLAY.md#run-the-five-million-path-risk-screen).
The [readiness status](../COMPETITION_READINESS.md) remains NO-GO: no tested
profile has both positive economic evidence and acceptance under this stress
screen, and private execution/recovery gates remain unresolved.
