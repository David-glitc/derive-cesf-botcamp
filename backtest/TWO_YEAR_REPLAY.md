# Run the two-year evaluation

Use this local harness to reproduce Flyby's fixed-policy options, perps and
shared-account comparisons. It downloads free public data and submits no orders.
You need the repository's Python dependencies and `matplotlib` for output plots.
Keep downloaded data, runtime snapshots and credentials outside your submission.

## Download public history

From the repository root, run:

```bash
python3 -m backtest.public_history --output data/validation/two-year-20261003/history
```

The fixed window is 2024-10-01 00:00 UTC through 2026-10-01 00:00 UTC,
exclusive. The downloader verifies Binance futures archive SHA-256 checksums,
requires continuous ETH/BTC/SOL five-minute candles, records Deribit hourly
IV-index response hashes, and captures representative current Derive rules.
It falls back to daily archives if a monthly archive hasn't been published.
It never interpolates missing bars or reads credentials.

## Run the fixed comparisons

Choose a new output directory; the evaluator won't overwrite prior evidence.

```bash
python3 -m backtest.two_year_flyby \
  --history data/validation/two-year-20261003/history \
  --output data/validation/two-year-20261003/final-results \
  --research-finer-lots
```

This command creates ten current-rules cases: options-ETH, options-BTC, perps,
combined-ETH and combined-BTC under base/stress execution assumptions. The
research flag adds eight explicitly hypothetical finer-lot cases; it changes
no production file, fees, risk cap or policy. These lots aren't venue-compatible.
Each independent case starts with $800. Each combined case uses one $800 cash
ledger and risk governor, one position/reservation, and one RFQ underlying owner.
Perp entry priority is ETH, BTC, then SOL. There aren't two independent portfolios
whose equity or turnover gets added together.

Read `summary.json`, `performance.csv`, `equity.png` and each case's
`trades.jsonl` / `equity-hourly.csv`. The summary records source/input hashes,
coverage, entry blockers, exit reasons, fees, modeled funding and risk transitions.
Option premium turnover and underlying-reference turnover remain separate from
perp notional turnover. A `--limit` run is a debugging slice, not a two-year result.

## Run the approved ETH exposure test

To replay the separate approved ETH exposure test, choose a new output directory:

```bash
python3 -m backtest.two_year_flyby \
  --history data/validation/two-year-20261003/history \
  --output data/validation/two-year-20261003/eth-cap-test \
  --exposure-profile eth_exposure_40_75_v1
```

This runs six cases: ETH options, perps and combined-ETH under base/stress
assumptions. Only ETH exposure changes; the loss budget and signal stay fixed.
It sends no orders or activation requests. Read the
[ETH test report](../reports/ETH_EXPOSURE_TEST_REPORT.md) for the measured results.

## Run the five-million-path risk screen

The offline accelerator additionally requires NumPy, pandas and Numba (verified
with Numba 0.61.2). These are research dependencies, not trading runtime changes.
Run from the repository root and choose a new output directory if this one exists:

```bash
python3 -m backtest.portfolio_paths --paths 5000000 \
  --output data/validation/two-year-20261003/portfolio-paths-5m-final
```

This runs five cases of one million $800 portfolio paths each. It resamples
recorded conditional trade episodes, not complete market/controller executions.
Any intra-path initial-capital loss or peak-to-trough dollar loss strictly above
$500 discards the corresponding research setup. No profiles are deleted or
activated. Read the [risk-screen report](../reports/PORTFOLIO_5M_PATHS_REPORT.md)
for declared gap, fee and hypothetical option assumptions and their limits.

The focused verification command is:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider \
  tests/test_portfolio_paths.py tests/test_options_execution_audit.py \
  tests/test_exposure_profile.py tests/test_submission_bundle.py
```

## Run the chronological alpha and Greek audits

From the repository root, choose new output directories before rerunning:

```bash
OPENBLAS_NUM_THREADS=2 python3 -m backtest.alpha_walkforward \
  --history data/validation/two-year-20261003/history \
  --output data/validation/two-year-20261003/alpha-walkforward
```

The research harness fits/selects 16 degree/penalty/horizon/IV configurations
using pre-test partitions, freezes the choice, and runs 12 execution ablations
on the final year. It retains original signals/protection/caps; the learned
candidate vetoes entries and adds lean option-construction checks. It uses no
credentials or live order transport. Inspected historical holdouts aren't
untouched discovery data. Read the [measured alpha report](../reports/ALPHA_WALKFORWARD_REPORT.md).

For a separate bounded read-only ETH/BTC public capture:

```bash
python3 -m backtest.greeks_audit \
  --output data/validation/two-year-20261003/greeks-public-audit
```

This uses only allowlisted legacy mainnet public methods, never private keys or
orders. Capture failure is reported, not filled with simulated API data. The
current quotes and Greeks aren't backfilled into historical model inputs.

## Run the fixed enhanced 48-hour comparison

Use the prior hash-verified frozen models, not a fit on the two-day window:

```bash
OPENBLAS_NUM_THREADS=2 python3 -m backtest.enhanced_48h \
  --history data/validation/two-year-20261003/history \
  --models data/validation/two-year-20261003/alpha-walkforward/models.json \
  --output data/validation/two-year-20261003/enhanced-48h
```

Choose a new output directory if that one exists. The runner compares baseline,
entry-only high-quality filters and high-quality plus the frozen alpha veto.
It uses the latest complete 48 hours in the fixed archive, without window
selection by performance. Read the [results](../reports/ENHANCED_48H_REPORT.md)
and [numbered operating cycle](../FLYBY_OPERATIONS.md). The 576 per-case operation
rows describe virtual replay calls, not real Hummingbot/Condor ticks.

## Verify execution independently

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q -p no:cacheprovider tests/test_two_year_replay.py
```

The controlled fixtures exercise production RFQ state transitions, paired
call/put profit/loss closes, lost-ack recovery and cash/fee reconciliation.
Their chosen fine lots and lower fees aren't historical performance evidence.
The existing `tests/test_options_rfq.py` and real-Hummingbot tests separately
check durable journals, native signing/contracts and faults in the pinned image.

## Interpret the results

For a separate current-lot construction and paired-execution audit, run:

```bash
python3 -m backtest.options_execution_audit \
  --rules data/validation/two-year-20261003/history/venue-rules.json \
  --iterations 1000 \
  --output data/validation/two-year-20261003/options-execution-audit.json
```

Choose a new output file if that path already exists. This uses scripted books,
not historical market opportunities, and intentionally reports unresolved
exit-fee-rise cases. Read the [fee audit](../reports/OPTIONS_EXECUTION_FEE_AUDIT.md)
before interpreting successful execution fixtures as live readiness.

Binance candles aren't native Derive executable prices. Deribit IV-index candles
aren't historical Derive option chains or three-day contract IV/skew. The model
uses Black-76, flat observed index IV, zero rates and hypothetical daily 08:00 UTC
expiries/strike grids. An hourly IV close becomes visible only after its hour ends.
Signals use completed five-minute candles; entries use the next bar's open.

Option quotes use modeled spreads/depth and five virtual seconds of frozen
bar-open prices. The production RFQ reducer runs against a fixture transport
and in-memory journal, not private APIs or real makers/settlement. Option exits
are sampled at bar opens, not intrabar ticks. Current representative venue rules
apply throughout the window as a sensitivity assumption, not historical rules.
Standard instrument fees don't prove account-specific RFQ fees or discounts.

Perps use adverse slippage, a worse opening price on stop gaps, SL-first ordering
when OHLC touches both barriers, and modeled pay-only funding. Leverage doesn't
multiply P&L or permit exceeding notional caps. This isn't a venue margin replay.
Unclosed terminal positions stay in marked equity; the harness doesn't invent
a final fill beyond the history. Risk latches survive day changes and recovery.

Read the [measured report](../reports/TWO_YEAR_OPTIONS_PERPS_REPORT.md) before
making submission claims. No historical strategy execution occurred when a case
reports zero trades. A passing lifecycle fixture doesn't establish profitability,
a live fill, or a 50-hour wall-clock production soak.
