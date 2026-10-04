# Chronological alpha and options-bleed evaluation

No candidate is promoted. The 16-model chronological search doesn't beat the
zero-return forecast on validation error. Its least-bad choice rejects all
otherwise-qualified entries in the final execution period. Avoiding losses with
zero turnover isn't evidence of a profitable trading strategy.

The earlier five-million-path screen measured wider **perp** cap effects, not
historical option bleed. Its combined option sleeve used hypothetical outcomes.
This pass again executes zero historical modeled options at baseline caps;
it cannot estimate option alpha or option P&L from those zero trades.

## Execution results

The final execution period is 2025-10-01 through 2026-10-01 UTC, end-exclusive.
Each independent case starts with $800; combined cases share one ledger. The
table shows six distinct result combinations from 12 ablation cases, because
perps and combined-ETH have identical results when options execute zero trades.
Do not add their capital, turnover or P&L into one portfolio.

| Lane | Candidate | Cost scenario | Closed trades | Fees | Turnover | Net P&L |
|---|---|---|---:|---:|---:|---:|
| Perps / combined-ETH, each | Baseline | Base | 300 | $62.28 | $93,801.75 | −$53.49 |
| Perps / combined-ETH, each | Learned veto + lean options | Base | 0 | $0 | $0 | $0 |
| Options-ETH | Baseline or lean candidate, each | Base | 0 | $0 | $0 | $0 |
| Perps / combined-ETH, each | Baseline | Stress | 194 | $39.97 | $60,144.35 | −$66.86 |
| Perps / combined-ETH, each | Learned veto + lean options | Stress | 0 | $0 | $0 | $0 |
| Options-ETH | Baseline or lean candidate, each | Stress | 0 | $0 | $0 | $0 |

Normal baseline gross trading P&L is +$8.89, fees are $62.28 and modeled pay-only
funding is $0.0964. That reconciles to −$53.49 net. Its 300 trades include 87 net
wins and 213 net losses, with 11.65 minutes average holding time. Its maximum
observed bar-end drawdown is 7.89%; stress drawdown is 9.14%. These are year-long
proxy results, not two-day competition forecasts or intrabar liquidation tests.

The learned normal perp gate records 1,400 ETH, 1,431 BTC and 1,354 SOL entry
vetoes. Both normal options-only variants record 600 minimum-gross-cap blocks.
No option plan reaches the additional lean-sleeve veto in those cases. Therefore
the added fee/theta rules have controlled-test evidence, not historical option
performance evidence. Every final case ends flat with no recorded runtime error.

## Model search and data boundaries

The older polynomial harness lives in `.local_harness/alpha-lab/research.py`.
The active controller candidate's `src/signal/return_model.py` remains a separate
three-feature linear model. This pass adds portable, offline-only research in
`src/signal/alpha_research.py` and `backtest/alpha_walkforward.py`; it doesn't
register a model with Condor or alter a production signal.

| Partition | UTC interval | Use |
|---|---|---|
| Initial training | 2024-10-01 to 2025-04-01 | Fit each model using only preceding label endpoints |
| Validation | 2025-04-01 to 2025-10-01 | Select degree, penalty, horizon and IV feature pack |
| Execution/forecast test | 2025-10-01 to 2026-10-01 | Evaluate one frozen choice, refitted on pre-test history |

The search compares degree 1/2, penalties 100/10,000, 30/60-minute next-open
log-return targets and underlying-only/IV-augmented features: 16 configurations,
with separate ETH/BTC/SOL fits. Scaling and polynomial expansion statistics use
training rows only. Training labels and validation target endpoints are purged
at partition boundaries. Prediction timestamps cannot precede the fitted boundary.

The 14 underlying features are returns over 1/3/6/12 bars, 30-minute and 4-hour
trend, efficiency, ATR, log volume ratio, realized/forecast volatility ratio,
CESF, normalized volatility edge and UTC sine/cosine. The IV extension adds
availability, level, one-hour change and IV-minus-realized-volatility gap.
Unavailable SOL IV uses an explicit missingness flag, not fabricated IV history.
ETH/BTC Deribit hourly IV closes become available only after their hour closes.

Selection minimizes mean per-asset validation MSE relative to a zero-return
forecast. It does **not** optimize strategy P&L or select on final-period results.
The winner is `d1-a10000-h6-underlying`, with validation relative MSE 1.001509:
about 0.151% worse than zero. Degree-two IV models fare worse, up to 1.096846.
Adding polynomial terms or these IV inputs does not demonstrate better alpha.

| Final-period asset | Model RMSE, bps | Zero-return RMSE, bps | Prediction/return correlation |
|---|---:|---:|---:|
| ETH | 47.443 | 47.445 | 0.0171 |
| BTC | 34.070 | 34.082 | 0.0298 |
| SOL | 54.566 | 54.625 | 0.0478 |

Those small final-period forecast-error improvements don't overcome the
candidate's cost/error cushions. The learned entry gate requires directional
predicted return above 3× costs normally or 4× when restricted, plus 0.25×
training residual RMSE. That residual buffer isn't a calibrated confidence
interval. Out-of-distribution inputs veto new entries, never protective exits.

The test history has been inspected in earlier research. This is a chronological
holdout from the current fit, **not genuinely untouched discovery or forward
data**. Binance candles are underlying proxies, Deribit IV is an index rather
than Derive contract IV/skew, and current representative venue rules are applied
across history. Option chains, RFQ books, margin and settlement remain modeled.

## Native data and Greeks

The inventory separates incompatible time/data surfaces instead of backfilling
current native features into the two-year model:

| Data surface | Verified extent | Treatment |
|---|---|---|
| Public underlying candles | ETH/BTC/SOL, 210,240 five-minute rows each | Chronological alpha training/replay |
| Hourly IV index | ETH/BTC, 17,521 rows each including warmup | Causally lagged optional features |
| Earlier native market snapshots | 17 snapshots, 1,570 repeated option observations with all four Greeks | Inventoried separately, not historical training |
| Earlier native stream | 13,439 messages over 298.67 seconds: 10,176 books, 3,247 tickers, 16 trade messages | Short previously inspected slice, not a two-year microstructure tape |
| Earlier native trade pages | ETH perp pagination incomplete | Never treated as complete history |
| Fresh public option capture | 116 ETH + 74 BTC option quotes, all four Greeks present | Current Greek diagnostics only |

The previous stream/capture file manifest checks pass. HYPE has short native
observations but no verified common two-year history; it isn't synthesized.
Native skew/OI/books aren't inserted into missing historical rows or used to
invent option fills. The five-million-path surrogate isn't reused as training
data for this alpha model.

The existing native normalizer already retains venue delta/gamma/theta/vega.
The new `src/options/greeks_research.py` explicitly computes forward delta,
forward gamma, vega per absolute IV unit and per one volatility point, and theta
per calendar day with forward/discount/IV held fixed. Call and put finite-
difference tests check those derivatives. The two-year RFQ simulator itself
still models price/delta; additional Greeks inform the research sleeve veto,
not a claim of full live portfolio-Greek risk control.

Fresh model-versus-API absolute delta differences are at most 0.0003291 for ETH
and 0.0002230 for BTC using venue forward/IV/discount inputs. This checks a
numeric slice, not hedge effectiveness or private positions. API vega/theta
unit conventions remain unverified and aren't silently combined with model
values. The current official [ticker schema](https://docs.derive.xyz/api-reference/market-data/publicget_ticker.md)
exposes all four fields but doesn't establish the legacy unit conventions.

Only zero ETH and one BTC fresh captures pass all existing quote gates; all ETH
and most BTC ticker timestamps are older than the five-second freshness limit.
Many also have missing depth or wide spreads. These are capture/gate failures,
not evidence that venue liquidity is universally absent. No entry or fill is
established by an API Greek or a model price.

## Lean options sleeve: research-only

The candidate keeps the baseline exposure caps, signed delta bounds, venue lots,
paired construction and $4 initial loss budget. It retains the full conservative
four-side fee reserve; no RFQ discount is assumed. Additional research gates
require reserved fees no greater than 25% of the current budget, modeled theta
carry no greater than 25%, and positive repriced credit minus debit and fees.
These fixed thresholds haven't been selected for profitable option outcomes.

The captured ETH/BTC option base fee is $0.50 per leg: four sides reserve at
least $2 before variable fees. The candidate's 25% ceiling at a $4 budget is
$1, so **that research sleeve cannot trade under the captured fee schedule**.
This is an explicit incompatibility, not a working live optimization. Verified
account-specific lower fees, a different approved fee criterion or a separately
approved budget change would be needed to revisit it; none is assumed here.

Repricing uses the learned underlying drift with a residual-error haircut,
the selected 30/60-minute horizon, unchanged IV and modeled BBO wedges. It is
a conditional point scenario, not calibrated expected profit. Repricing already
includes time decay, so the theta cap doesn't subtract theta a second time.
Fees are already inside maximum loss and likewise aren't double-counted.

The previous controlled $1.10-debit example with $2.348 fee reserve fails the
new fee-budget gate. Controlled cheap-fee fixtures can pass it, but that doesn't
prove such spreads exist at required size with executable native offers.
The [actual exit-fee/recovery blocker](OPTIONS_EXECUTION_FEE_AUDIT.md) remains
unfixed. Lean construction cannot replace exit reconciliation or authorize
trading around unresolved owned inventory.

## Verification and decision

The run completes 12 execution cases in 81.18 seconds. The focused suite passes
**435 tests**, including sklearn polynomial parity, future-data invariance,
label purging, Greek finite differences, lean fee/theta gates, actual replay
ledger integration and protective-stop behavior. This isn't a new pinned
Hummingbot run, security audit or 50-hour production soak.

Independent verification checks saved source/model/artifact hashes, partition
boundaries, 12 cash/P&L/fee/funding ledgers, $160 entry caps, terminal curves and
public snapshot/raw-record provenance. No account state, live caps, active
controller, credentials or deployment changes. No commit or push.

The [saved summary](../data/validation/two-year-20261003/alpha-walkforward/summary.json)
has SHA-256 `e798cf1c29d66429bf183c56aeb530347d67bc1a6e23a10f57022abe0b6ac40a`.
Read [reproduction commands](../backtest/TWO_YEAR_REPLAY.md#run-the-chronological-alpha-and-greek-audits)
and the [readiness status](../COMPETITION_READINESS.md). A new active alpha
candidate must demonstrate cost-adjusted edge on new observations; zero trading
and a better-looking fitted polynomial don't satisfy that gate.
