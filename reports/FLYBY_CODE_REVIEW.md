# Flyby execution-path review — 2026-10-01

Verdict: no demonstrated profitable edge; retain the live pause. This review
reads the canonical controller, shared policy/features, sizing, options planner,
accounting helpers and replay path. It does not certify every dependency in
Hummingbot or implement the proposed changes. See the
[performance evidence](PORTFOLIO_ANALYSIS.md) and
[richer-data reference](DERIVE_QUANT_DATA.md).

Provenance: this review targets current code. The final campaign's controller
snapshot predates ID/proxy/checkpoint validation and executable-limit cap
hardening, and its harness predates the 48h sampling correction. Shared policy,
feature, sizing, options and ledger hashes match the campaign snapshot. Do not
claim the plotted replay exercised those later live-controller additions.

## Findings in priority order

1. **Exit churn deserves the first controlled experiment.**
   [Stop proposals](../controllers/directional_trading/flyby.py#L286) close a
   trading executor whenever the shared entry signal becomes neutral or reverses.
   [Replay](../backtest/stress_flyby.py#L201) does the same at next open.
   Volume, confidence and confirmation failures therefore become exits, not
   merely blocks on new entries. 61.25% of closes used `signal_invalid` and
   contributed −$13.62 per account. Test a separate hold/invalidation policy
   against the unchanged baseline; retain genuine health/loss halts. Do not
   remove invalidation simply to increase holding time.
2. **The volatility/option edge is not wired into entry selection.**
   [Features](../src/signal/flyby.py#L23) calculate HAR-like/EWMA sigma and CESF;
   [policy](../agents/condor_agent.py#L35) does not consume them. Options require
   a caller-supplied `option_iv_edge`; normal controller updates never set it.
   [The planner hook](../controllers/directional_trading/flyby.py#L297) is
   callable but not automatically invoked by the tick. Current entries are
   confirmed momentum/efficiency/volume, not a live volatility-surface strategy.
3. **Costs are models, not venue-account fee estimates.**
   [Perp cost gate](../controllers/directional_trading/flyby.py#L259) uses a fixed
   fee fraction, symmetric worst-level impact and fixed funding allowance.
   [Option fees](../src/options/spread_builder.py#L97) use premium fractions for
   both legs and round trips. These differ from Derive's published base fees,
   notional-based/capped option fees and RFQ discounts. Small debits are
   especially sensitive to fixed charges. Replace estimates only after a
   version/account-specific fee reconciliation. A 3× target-distance gate is
   not positive expected value. [Official fees](https://docs.derive.xyz/integrators/trading/trading-fees.md).
4. **Options are plans, not proven paired execution or net-profit exits.**
   [Spread selection](../src/options/spread_builder.py#L52) bounds a matched
   vertical at quoted limits, but sends no RFQ/orders. The runner tests only
   synthetic option arithmetic. [Exit thresholds](../src/options/spread_builder.py#L132)
   compare credit with `plan.debit`, without subtracting the recorded round-trip
   fee estimate. Gross profitable credit need not be net profitable. Unpriceable
   credit returns a label, not a tested recovery workflow. A matched vertical's
   bounded payoff does not make independently submitted short legs safe.
5. **Reconciliation and risk are still adapter preflight requirements.**
   [Account matching](../controllers/directional_trading/flyby.py#L139) checks
   executor sign and an upper quantity bound, not the exact filled net position.
   An unrelated same-sign position inside the bound could be classified as
   known. The strict [reconciliation helper](../src/accounting/reconciliation.py#L28)
   and [event ledger](../src/accounting/ledger.py#L105) are not connected to a
   complete live fill/snapshot bridge in this controller. Deposit/withdrawal
   changes affect loss baselines; available balance is not proven free margin.
6. **Market-data health cannot be inferred from models alone.**
   [Book freshness](../controllers/directional_trading/flyby.py#L167) tracks a
   changed update ID, rather than explicit receive age; a quiet book may halt
   despite a healthy connection. First observation requires a subsequent change.
   [Basis](../controllers/directional_trading/flyby.py#L196) compares an older
   closed proxy candle with a current Derive midpoint, mixing timing movement
   with venue basis. New feeds need explicit event/receive times and tradeability
   checks. Public IV/Greeks with zero bid/ask are not executable option quotes.

## Line-by-line map: shared signal and policy

Every executable region is grouped below rather than repeating imports and
declarations as separate findings. Line numbers refer to the current worktree.

| File / lines | Current behaviour | Review / next experiment |
|---|---|---|
| `src/signal/flyby.py` 1–11 | Imports, timeframe constants, lookback guard | Closed-bar causal input contract; caller must validate timestamps |
| 12–18 | Finite/positive OHLC, legal high/low and nonnegative volume; poison bad rows | Good fail-closed approach; richer fields need independent validity/age masks |
| 19–29 | Log returns, weighted realized variance, annualization, HAR-like/EWMA average | HAR-like statistic is not a fitted HAR forecast; validate forecasting skill chronologically |
| 30–35 | Realized variance, tails, kurtosis, clustering, CESF | Calculated but not consumed by the current decision policy |
| 36–39 | Trend horizon, noise normalization, path efficiency | `max(3, floor(4h/bar))`: 4h bars use **12h**, not 4h, trend horizon |
| 40–45 | ATR14; recent 3-bar volume versus prior 20-bar baseline | Causal; volume is Binance proxy volume, not Derive demand or signed flow |
| 46–55 | Feature assembly, one-bar confirmation and all-feature validity | An unused forecast field can still invalidate entry via the common validity mask |
| `agents/condor_agent.py` 10–32 | Decision record and finite-number parsing | Legacy `thresh`/`cesf_min` fields do not drive current entries |
| 34–48 | Required fields, freshness, 2% daily / 4% peak guards, reconciliation, ATR band | Keep health guards separate from optional alpha features; triggers are not loss guarantees |
| 50–58 | Current/previous volume, efficiency and same-direction trend confirmation | Two closed-bar confirmation; scalping edge may decay before entry |
| 59–63 | Weighted heuristic confidence and ≥0.70 threshold | Not a probability, calibration or expected-return estimate |
| 64–74 | ETH/BTC options eligible at ≥0.75 confidence and IV edge ≥0.02; else perps | Define IV-edge units/tenor/sign first; no real chain source currently supplies this value |
| 77–91 | Active variant, logging, legacy research demo | Demo is not on the competition execution path; deterministic policy is not an LLM trader |

## Line-by-line map: controller and risk

| File / lines | Current behaviour | Review / next experiment |
|---|---|---|
| `controllers/directional_trading/flyby.py` 1–29 | HB imports and shared modules | Canonical implementation; Condor registration reexports it, not a second strategy |
| 31–76 | Approved perps, ONEWAY, proxy candles, bounded config, option/PM/spot live rejection | Do not change candle connector to an unimplemented Derive feed; preserve disabled-live contract |
| 79–104 | Process-wide reservation, stable-ID risk checkpoint load | Same-process coordination only; no durable cross-process allocation lock |
| 106–112 | Candle configuration and fail-closed status | Warmup retained; last halt reason available |
| 114–138 | USDC plus unrealized equity, daily/peak persistence, capped budget, committed exposure | Check balance semantics/double-counting with venue; writes checkpoint on each account call; cash-flow-adjusted baselines absent |
| 139–156 | Known order IDs, upper-bound position ownership, account-flat entry gate | Conservative no-overlap account, not an optimizer for simultaneous ETH/BTC allocation; exact net fills still needed |
| 158–173 | Ready/private-stream/book checks | Quiet feed vs stale data needs explicit health semantics |
| 174–197 | Only closed gapless proxy candles; age/basis/book checks | Basis should use synchronized prices; candle age is not millisecond book age |
| 198–208 | Features → account → shared decision; typed exception halt | Options IV-edge absent from automatic path; no Greeks/OI/book imbalance passed to policy |
| 210–231 | Kill switch, active executor, cooldown, reservation, account/data rechecks | Retain gates; recheck catch lacks `KeyError` unlike update catch; normalize malformed adapter state |
| 232–243 | ATR exits, drawdown-scaled risk and amount quantization | Quote exposure cap, not venue margin/liquidation guarantee |
| 244–265 | Reread depth; worst-price impact, cap, modeled costs and venue minimums | Good depth gating, but no queue priority or future exit-depth guarantee; requote fees and asymmetric impact |
| 266–284 | Reservation and real HB TripleBarrierConfig: LIMIT entry, MARKET exits | A crossing LIMIT can pay taker fees; it is not maker execution merely because it is a limit order |
| 286–295 | Halt/kill exits, 30s nontrading timeout, neutral/reversal close | Investigate churn; partially trading executors are not covered by the nontrading remainder timeout |
| 297–307 | Explicit shadow option-plan hook, 1% equity budget | No automatic chain subscription, paired sender or option fill lifecycle |
| `src/risk/position_sizing.py` 7–27 | Executable depth VWAP and worst level | Caller must supply correctly sorted normalized levels; helper does not verify ordering |
| 30–44 | Minimum of stop-risk, drawdown-scaled notional cap, gross headroom and available balance | Scale floors at 25% until 4% halt; no leverage multiplication; fee/gap risks outside stop sizing |
| 47–56 | 3× cost-distance gate; ATR stop 0.3–1.5%, target 1.5–2×stop, ≤6h hold | Test expected net edge, not target magnitude; 4h replay can only resolve timers on 4h grid |

## Line-by-line map: options, accounting and replay

| File / lines | Current behaviour | Review / next experiment |
|---|---|---|
| `src/options/spread_builder.py` 8–46 | Normalized quote/plan structures, delta, limits, expiry and fees | No IV/gamma/vega/theta/OI fields or separate model/book timestamps |
| 52–81 | ETH/BTC call/put, confidence, 2–5 DTE, ≤5s age, finite/sorted/uncrossed books | Strict 2–5 DTE excludes longer expiries; metadata must verify active state, universe and amount units |
| 83–104 | Long-leg absolute delta 0.25–0.55, matching expiry/size units, 20% book capacity | Both legs priced, but no future exit book or simultaneous-fill guarantee |
| 105–129 | Budget/payoff/RR, rounded limits; prefer near 3 DTE then highest payoff RR | Max payoff RR is not expected return; add liquidity and net Greeks stress rather than blindly maximizing RR |
| 132–147 | Profit/stop/expiry/time/signal labels from credit | Need net executable close credit and tested stale/no-quote handling |
| `src/accounting/ledger.py` 17–90 | Decimal normalized fills/funding with finite fields and identities | Adapters must supply correct fee/rebate/P&L semantics; defaults are not evidence of zero fees |
| 93–167 | Idempotent events, conflicting-duplicate rejection, explicit cash P&L, export/replay | Useful deterministic helper; no live event bridge or mark-to-market portfolio by itself |
| `src/accounting/reconciliation.py` 10–86 | Finite decimal snapshots, order sets and position/P&L/equity drift checks | Pure helper, not automatically called by canonical controller; reconcile at restart and throughout lifecycle |
| `backtest/stress_flyby.py` 37–68 | Fetch/cache Binance OHLCV | Fetch discards Binance trade counts and taker-side fields; none of OI/IV/L2 is historical input |
| 71–89 | Synthetic option spread and four exit probes | Not real option profitability or paired matching proof |
| 95–159 | Rotating scenarios, overlapping windows, $800 accounts, injected health faults | Repeated seeds/periods do not produce independent statistical evidence |
| 160–193 | Next-open entries, random synthetic capacity, assumed fees and partial fills | No real Derive liquidity, ticks/lot minimums, queue or API lifecycle replay |
| 194–233 | Signal/timer exits before OHLC; stop-first collisions; simplified funding | OHLC path ambiguity; funding always modeled as cost for either direction, not actual signed funding |
| 234–271 | Ledger replay checks, marked curve, confusion labels and totals | 4h nominal 6h label uses one 4h bar; not real six-hour label. Exposure only measurable at snapshots |
| 274 onward | Dataset/campaign orchestration, immutable output, hashes and summary | Local harness, not competition runtime; replot completed evidence without rerunning or tuning |

## Next controlled work

Start with actual Derive trade tape and book quality, followed by a real ETH/BTC
options chain with synchronized IV/Greeks/OI. Measure feature availability before
letting it affect a signal. Then compare isolated changes: entry vs hold policy,
venue costs, trade-flow/book filters, IV/skew/unsigned-GEX filters and Greeks-aware
spread selection. Each experiment needs a locked chronological holdout and net
costs; more volume alone is not success. No live switch, new funding, premium
subscription or strategy implementation is authorized by this review.
