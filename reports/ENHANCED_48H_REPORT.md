# Latest-archive 48-hour signal-quality replay

Baseline makes one SOL trade: +$0.68 under base costs, −$0.86 under cost stress.
The two stricter variants make zero trades. No options execute, and no candidate
is promoted. Higher quality thresholds suppress entries; they don't establish
an improved profitable strategy.

This is a fixed offline replay of 2026-09-29 00:00 UTC through 2026-10-01 00:00
UTC, end-exclusive. It isn't a live two-day run. The dates are the latest complete
48 hours in the verified archive, not a window selected by P&L.

## Results

Each independent case starts with $800 and runs 576 five-minute bars. There are
18 cases: three variants × perps/options-ETH/combined-ETH × base/stress costs.
Perps and combined results match because combined executes no options. Don't
sum their separate accounts into one portfolio.

| Perps / combined-ETH, each | Base closed trades | Base net P&L | Stress closed trades | Stress net P&L |
|---|---:|---:|---:|---:|
| Baseline | 1 | +$0.68 | 1 | −$0.86 |
| High-quality entry filter | 0 | $0 | 0 | $0 |
| High-quality + frozen model veto | 0 | $0 | 0 | $0 |

All six options-only cases also report zero trades and zero P&L. Every case ends
with no residual perp, option position or busy RFQ lifecycle. This checks modeled
terminal state, not actual private-account flatness or live fills.

The base SOL trade is long 1.315 underlying units at $121.645, exits after 25
minutes at $122.32553 because the signal becomes invalid, and reports $320.82
round-trip notional turnover. Gross P&L is +$0.894897, fees are $0.212493 and
modeled funding is $0.000837, reconciling to +$0.681567. Its entry score is
0.768206, which passes baseline but fails the stricter 0.85 threshold.

## What “high quality” means here

The research entry filter requires the original signal to qualify, then:

| Check | Fixed threshold |
|---|---:|
| Current composite quality score | At least 0.85 |
| Current and previous signed trend z-score | At least 1.50 in the trade direction |
| Current and previous efficiency | At least 0.45 |
| Current and previous volume ratio | At least 1.50 |

Those are transparent heuristics, not calibrated probabilities or a guarantee
of a winning move. The normal high-quality perp case records 14 ETH, eight BTC
and seven SOL quality-score rejections. Counts are entry-attempt events, not
independent trade opportunities. Other bars fail original volume/trend/confirmation
checks; baseline also encounters venue minimum and cost blocks.

The quality filter only vetoes entries. It doesn't rewrite the owned position's
original signal, waive stops, or trigger an extra quality-based exit. Exits,
lot rounding, fees, sizing, cooldown, $160 baseline perp cap, $4 initial risk
budget and −10%/−15% risk rules remain unchanged.

The third variant adds the prior frozen alpha artifact, without retraining or
selection on this window. It also retains the research lean-option checks.
Quality rejects every otherwise-confirmed entry before the model can add an
accepted trade, so this run doesn't isolate the model's incremental performance.
Current minimums and the fee ceiling still don't establish a tradable option sleeve.

## Evidence and limits

The [saved summary](../data/validation/two-year-20261003/enhanced-48h/summary.json)
has SHA-256 `ab39bb4a5b9f6f544118a33229d2898052790baafe9a549f7dbc156d0b677046`.
It records source/input/model/artifact hashes and all 18 cases. Each case saves
576 operation rows, a closed-trade ledger and an hourly equity curve. The
operation trace records simulated signals, quality rejections, entry attempts,
risk observations and closes—not real Hummingbot or Condor ticks. Repeated
signal calls aren't separate executions, and empty stages aren't an execution.

The focused suite passes **150 tests**, including ten new window/quality/replay
integration tests. Independent checks verify all artifact/source hashes,
48-hour endpoints, 576 trace rows per case, flat terminal state and reconciliation
of P&L, fees, funding and turnover. No new full pinned-image or wall-clock soak.

Data and model limitations remain: already-inspected Binance proxy candles,
lagged Deribit IV index, modeled option chains/RFQs, no native depth, queue,
margin or private-fill proof. Risk observations are at bar opens/ends, not a
full intrabar drawdown path. The $500 dangerous-setup screen isn't cleared by
this short replay. The known actual option exit-fee/recovery blocker remains
quarantined. No production config, persistent checkpoint, credentials or live
orders change; no commit, push or deployment.

Read the [numbered operating cycle](../FLYBY_OPERATIONS.md) to see which decisions
you can inspect, and the [reproduction command](../backtest/TWO_YEAR_REPLAY.md#run-the-fixed-enhanced-48-hour-comparison)
to reproduce this diagnostic without changing the trading runtime.
