# Two-year options/perps evaluation — 2026-10-03

The fixed baseline fails the economic gate in this proxy simulation. The
current-rules options cases place no trades; combining them with perps doesn't
improve P&L. You can reproduce these results with the
[local harness](../backtest/TWO_YEAR_REPLAY.md). This report records simulated
execution, not historical Derive fills, live profitability or a competition forecast.

## Data and coverage

Window: **2024-10-01 00:00 UTC → 2026-10-01 00:00 UTC**, end exclusive.

| Surface | Source | Verified coverage | Boundary |
|---|---|---|---|
| ETH/BTC/SOL OHLCV | [Binance futures public archives](https://github.com/binance/binance-public-data) | 210,240 five-minute bars each; zero missing/extra rows; archive checksums verified | Underlying proxy, not Derive ticks/books |
| ETH/BTC IV index | [Deribit public IV API](https://docs.deribit.com/api-reference/market-data/public-get_volatility_index_data) | 17,521 hourly bars each including the prior warm-up hour; zero missing/extra rows | IV-index proxy, not Derive contract IV/skew/BBO |
| Representative venue rules | Unsigned Derive legacy `public/get_instrument` | Current ETH/BTC options and ETH/BTC/SOL perp lot/tick/fee metadata | Current rules fixed across history, not historical rules |
| Existing native option captures | Checksummed local Derive legacy public records | Four separate ETH/BTC replays, 16 observations total | Short snapshots, not two years or continuous coverage |

IV close values become visible only at the end of their hour. Signal features
use the previous completed five-minute candle; the first 101 bars warm up features
and aren't trading opportunities. HYPE has no verified common
two-year dataset here and stays outside this comparison; no history is fabricated.
No historical Derive option-chain/bid–ask archive was available in this run.

The options model uses Black-76, flat IV, zero rates, hypothetical three-day
08:00 UTC expiries and ETH $10 / BTC $500 strike grids. It models 2%/6% option
book widths and ample depth; these aren't observations of listing or liquidity.
Standard instrument fees aren't verified account-specific RFQ fees/discounts.
This tests the fixed planner and production RFQ reducer against a model, not
the historical opportunity set, private transport, settlement or margin.

## Shared capital and fixed policy

Each independent case starts with **$800**. Each combined case has one cash
ledger, one shared risk governor and at most one position/RFQ reservation.
Combined-ETH selects one ETH RFQ owner; combined-BTC selects one BTC RFQ owner.
Both use explicit ETH/BTC/SOL perp priority. They never run two RFQ owners.
These are model portfolio arrangements, not proof of a deployed multi-controller account.

The baseline's signal, four-hour trend horizon, 0.5% per-trade risk, 20% perp
notional cap, signed option-delta/gross caps and −10% restricted / −15% hard-stop
latches remain unchanged. No optimization or candidate promotion occurred.
The controller's $800 allocation ceiling also limits entry sizing after gains.
Leverage doesn't multiply capped notional or P&L. Capital/volume stretch targets
aren't permission to increase risk or reset latches.

## Current-rules results

| Case | Ending equity | Net P&L | Return | Max drawdown | Closed trades | Perp notional turnover | Option premium turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| ETH options, base/stress | $800.00 | $0.00 | 0.00% | 0.00% | 0 | $0 | $0 |
| BTC options, base/stress | $800.00 | $0.00 | 0.00% | 0.00% | 0 | $0 | $0 |
| Perps, base | $719.17 | −$80.83 | −10.10% | −10.20% | 344 | $103,116.67 | $0 |
| Combined ETH or BTC, base | $719.17 | −$80.83 | −10.10% | −10.20% | 344 | $103,116.67 | $0 |
| Perps, cost stress | $718.55 | −$81.45 | −10.18% | −10.35% | 201 | $59,030.98 | $0 |
| Combined ETH or BTC, cost stress | $718.55 | −$81.45 | −10.18% | −10.35% | 201 | $59,030.98 | $0 |

Turnover is entry-plus-exit notional **over two years**, not a two-day competition
result. Don't add independent cases or count option underlying-reference exposure
as premium turnover. All 18 final cases finish flat and reconcile ending cash to
$800 plus their closed-trade net P&L; no transport errors occurred. Because
historical cases execute no option spreads, they don't exercise RFQ fills/faults.

Perp base assumptions: 2 bps adverse slippage per side, at least 6 bps per-side
fees plus current fixed fees, and pay-only funding of 0.0000125 per hour.
Cost stress uses 10 bps adverse slippage and funding of 0.00005 per hour.
These are declared assumptions, not historical Derive spread/funding records.
Funding, fees and gap-aware SL-first OHLC fills feed the same cash ledger.

## Why options place zero trades

The standalone cases produce 1,142 ETH and 987 BTC eligible direction/IV signal
observations. Every current-lot candidate fails the conservative two-leg gross
cap before execution. Current representative ETH minimum is 0.1 units and BTC
minimum is 0.01 units. The maximum initial gross cap is $240; the planner reserves
the debit budget before calculating its cap, making the entry cap slightly lower.

Across this history, even the lowest reference opens imply minimum two-leg gross
of **$279.36 ETH** and **$1,162.75 BTC**. An atomic spread can be defined-risk
and still fail this deliberately conservative reference-exposure rule.
No limit is widened and no minimum amount is rounded up.

Eight separate diagnostic cases try hypothetical ETH 0.001 / BTC 0.00001 lots,
retaining the same fees, $4 initial trade budget and reward/risk gate. They also
execute zero spreads: the controller-equivalent selected pair fails fee-adjusted
planning. Representative standard fixed fees are $0.50 per leg per side, or
$2 for a four-side round trip before variable fees. Smaller lots alone don't
resolve the fee/budget/reward incompatibility. These aren't tradable venue lots
and aren't submission performance or a strategy promotion.

The four native snapshot replays also produce zero executed spreads, zero
unmatched fills and unchanged $800 paper equity. That adds provenance evidence,
not a native performance track record.

## Perp exits and losses

| Metric | Base | Cost stress |
|---|---:|---:|
| Profitable / losing closes | 103 / 241 | 54 / 147 |
| Average profit / loss | +$1.14 / −$0.82 | +$1.44 / −$1.08 |
| Average hold | 11.60 min | 11.34 min |
| Signal-invalid exits | 230 | 117 |
| Stop-loss exits | 70 | 56 |
| Take-profit exits | 44 | 28 |
| Fees | $68.75 | $39.44 |
| Modeled funding | $0.11 | $0.23 |

Base signal-invalid closes contribute −$69.97, stop losses −$103.54 and take
profits +$92.67. The −10% latch enters restricted mode on 2025-07-24 22:30 UTC
in base and 2025-05-23 12:30 UTC in stress; it never resets. Neither case hits
the −15% hard-stop latch. Sampled drawdown can cross a threshold between bars;
the governor isn't a guarantee of an exact loss ceiling.

Base trades are seven ETH and 337 SOL; BTC minimums block entries. This result
primarily measures the operator-selected SOL fallback under the fixed priority,
not effective ETH/BTC primary-market operation. Stronger restrictions sharply
reduce later entries rather than restoring a demonstrated positive edge.

## Verification and artifact identity

Final data/run files stay local under `data/validation/two-year-20261003/`.
Use `final-results/summary.json`, `performance.csv`, `equity.png` and the per-case
hourly curves / trade ledgers. The earlier `debug/` slice isn't a two-year result;
`results/` is the initial equivalent full pass, not the final source-bound evidence.
The final pass binds its inputs and shared policy/reducer/harness source hashes.

- Public-history manifest SHA-256:
  `f5adfe9826af0d23e5322bc020d3282919414fccff8e5e868125358a2a223182`.
- Final 18-case summary SHA-256:
  `304eba6e01071fc0ede972b8d4e80461b04ce8c45638e6855bff95673a9d62d8`.
- Full pinned Hummingbot pass: 2,891 tests, seven upstream warnings, network
  disabled, source mounted read-only. This pass collected the first ten new
  harness checks. Four additional call/put profit/loss fixture cases subsequently
  passed in both the 14-case focused host run and the final 14-case pinned-image
  run. Mainnet configuration preflight passed in the disposable pinned image;
  account and private execution remained explicitly unverified.
- The official Condor checkout again discovers the agent, loop and fixed
  configuration. A passing mocked-provider tick isn't a live provider/API soak.

Controlled execution fixtures use chosen small lots/low fees and exercise the
actual RFQ reducer for paired call/put entries, profitable/loss-making exits,
lost-ack recovery and fee/cash reconciliation. They are **not** historical
profitable trades. Existing durable-journal, signer/controller and virtual
50-hour fault tests remain separate. No wall-clock live endurance claim is made.

The documentation evidence checks keep measured performance separate from
implementation, modeling assumptions and operator gates. Read
[live readiness](../COMPETITION_READINESS.md) before deployment. The code can
be packaged for review, but these results don't clear profitability, venue-sized
options execution, private mainnet validation or activation. All profiles remain
paused. No mainnet order, credential change, upload or Git push occurred.
