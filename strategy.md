# Flyby strategy — implemented competition contract

Flyby uses confirmed price/volume movement for short-lived perpetual trades
and high-confidence ETH/BTC call or put debit-spread plans. The shared policy
runs deterministically inside the V2 controller; Condor provides the operator
interface and advisory workflow. An LLM does not choose leverage or bypass
the controller's risk checks.

## Decision and execution

`closed proxy candles → causal features → shared Condor policy → account/book/cost gates → Hummingbot executor`

| Stage | Implemented behavior |
|---|---|
| Data | Binance perpetual candles, Derive execution books; default 5m, supported 15m/1h/4h |
| Features | Baseline four-hour trend window; opt-in 5m scalp uses a fixed 30-minute window; efficiency, volume ratio, ATR, HAR/EWMA, CESF diagnostics |
| Confirmation | Two consecutive bars with matching trend direction, sufficient efficiency and volume |
| Quality | Volume ≥1.20× baseline, trend magnitude ≥0.90, efficiency ≥0.30, confidence ≥0.70 |
| Active mode | Normal mode volume ≥1.10× and trend ≥0.70; never relax restricted gates or hard stop |
| No clean signal | No entry; signal invalidation closes an existing executor |
| Size | ≤0.5% of budget × confidence / stop distance; also ≤20% notional and available funds |
| Restricted mode | At −10% peak-relative drawdown: latch restricted mode, confidence ≥0.85, trend ≥1.5, efficiency ≥0.45, current/previous volume ≥1.5; size ≤25%, shrinking through the remaining buffer |
| Portfolio | 30% gross cap; entries require account flat with no working orders; process-wide proposal reservation |
| Stops | ATR-dependent 0.3–1.5% price stop; target 1.5–2× stop; baseline roughly 1–3h hold, capped 6h; 5m scalp candidate 10–30m |
| Costs | Target ≥3× modeled round-trip cost, ≥4× restricted; include entry/exit fee rates, per-order base fees, exit slippage reserve and funding |
| Entry | Depth-checked marketable LIMIT, quantity quantized to venue rules, 30s unfilled-entry timeout |
| Exit | Hummingbot triple-barrier MARKET stop/profit/time exits; controller sends early-stop on halt/invalidation |
| Hard halt | At −15% peak-relative drawdown: persist hard-stop latch, no new entries, cancel/close owned executors; no automatic reset |

The approved starting budget is also a floor for the peak baseline. With a peak
of $800, $720 enters restricted mode and $680 triggers the hard stop. Profits
raise the peak, so thresholds rise too. Daily loss is diagnostic, not an independent
−2% veto in this competition policy. Restricted modeled trade risk cannot exceed
10% of the remaining dollar loss buffer. Actual losses can exceed the model.

Restricted mode remains latched after recovery. This is a conservative contest
rule, not a promise that high-confidence trades recover losses. Confidence is a
heuristic score, not an estimated win probability. No size rounds up beyond caps.

The selectable `competition_scalp` candidate shortens the trend horizon and
holding cap; it uses hold hysteresis rather than closing whenever entry volume
drops. It is **not promoted**: the fixed costed comparison increases turnover but
worsens net P&L. Samples retain `strategy_profile: baseline`, paused. Read the
[risk/turnover evidence](reports/COMPETITION_RISK_TURNOVER_REPORT.md).

Leverage is fixed at 2 in the profiles, capped at 3 by validation. Derive's
adapter doesn't apply a venue leverage setting; sizing does not multiply P&L
by that label. Thresholds are guard triggers, not guaranteed maximum losses:
gaps, fees, outages and delayed execution can exceed them.

HAR/EWMA and CESF are computed diagnostics, not proven causal predictors.
There is no active SVI fitting, Greek portfolio guard, collateral allocation
or Kelly alpha estimate in this controller. Historical research modules don't
establish that those mechanisms protect the live competition path.

## Option plans

Bullish signals can produce a call debit spread (buy lower strike, sell
higher strike); bearish signals can produce a put debit spread (buy higher
strike, sell lower strike). The policy requires confidence ≥0.75 and a
caller-provided, verified IV edge ≥0.02. Missing IV means no option plan.

The normalized chain includes instrument IDs, expiry, multiplier, lot/tick
rules, delta and fresh bid/ask depth. Reject mismatched expiries/contracts,
2–5 DTE violations, books older than 5s, crossed/unsorted/over-wide books,
inadequate depth and reward/risk below 1.5. Size uses at most 20% of both
legs' depth and a 1% account debit budget, preferring approximately 3 DTE.
The output records matched quantity, limit prices, debit, fee estimate,
maximum payoff/loss, break-even, net delta and quote expiry.

Delta-aware callers additionally supply a signed per-underlying account policy.
Bought legs use absolute delta 0.25–0.70, sold legs 0.10–0.35, with default
targets 0.50/0.25. A sold leg must have smaller absolute delta. Selection can
require ATM, OTM or ITM; ATM is an explicit ±0.5% spot/strike window, not a
probability inferred from delta. Calls and puts preserve their signed exposure.
These selection bands are uncalibrated parameters, not established alpha.

Size is floored to venue lots within 20% dollar-delta and 30% gross reference
notional caps, scaled by restricted mode. Gross here conservatively counts
both option legs at underlying spot, not premium; it is not Derive margin.
Existing exposure and pending-order fill intervals consume capacity; unfilled
orders are never credited as guaranteed hedges. Either-leg-only delta is also
bounded during a fault, but unmatched short options remain prohibited.
Plans leave headroom for the full debit/fee budget. Controller/paper entries
also cap all-in loss at the competition governor's per-trade risk budget.
Standalone legacy planner calls without a delta policy are explicitly
`delta_verified: false`; they cannot authorize execution.

The payoff reward/risk is a bound, not an expected return. Maximum loss assumes
both legs are matched and fees match the supplied model. Fees use normalized
premium fractions; the operator must supply adapter-verified costs before
considering any execution integration.

Paper exits use executable spread credit after actual entry/exit fees: +30%
profit, −18% stop, signal invalidation, 6h hold or expiry within 6h. Fresh leg
deltas are recomputed for actual filled quantities; cap breach or invalid
delta closes when executable books exist and halts subsequent entries. Missing
close books retain unresolved exposure, null equity and a latched paper halt.
No ITM condition is required. The paper harness uses the same −10%/−15%
reducer; its separate account is not a merged options/perps portfolio.

`plan_options()` accepts a normalized chain and IV edge. Each controller tick
can also read a fresh checksummed public market file, use supplied instrument
fees, and expose a shadow plan. Missing/stale public input clears the plan
without interrupting protective perp actions. No continuous public collector,
paired option executor or automatic perp delta hedge is implemented.
Detailed Condor context includes an allowlisted `options_delta` view. Delta
and fee verification are separate; old manually supplied chains without fee
metadata remain fee-unverified. Live option/hedge orders stay disabled.

**Never submit these plans as two independent position executors.** The
current controller rejects `options_enabled: true`. A future paired adapter
must prove placement, correlation, partial-fill containment and matched
closure before options can be live. Neither an assumed hedge nor a resting
limit is protection against an unmatched short option.

## Runtime safety boundaries

The controller checks connector readiness, private-stream age, observed book
updates, candle gaps, stale candles, cross-venue basis and existing exposure.
Known order IDs and bounded owned position sign/size distinguish an active
executor from unknown exposure. This is not exact ledger reconciliation.
The idempotent ledger and reconciliation modules are tested helpers; a live
adapter fill/funding bridge and restart reconciliation still need proof.

The Hummingbot executor owns order submission and cancellation. Protective
exits depend on a running client and exchange connectivity; they aren't
native guaranteed stops. Do not run other strategies or manually trade the
same account. Persist the shared `data/flyby-risk-flyby-competition.json`, its
`.initialized` marker and `.lock` file. All selected profiles share the same
`risk_state_id` and budget. The checkpoint binds to the connector's subaccount
using a digest; profile changes don't reset latches, cooldowns or consumed signals.
Reject corrupt, foreign, lost or clock-regressed state. Don't rename the risk
namespace, delete the data volume, change the budget or manually edit a latch
to restart trading. Old per-controller checkpoints require operator review.

Entries consume their completed-candle signal before emitting an executor.
One signal cannot produce duplicate entries after restart. A 60s cooldown in
the 5m candidate is not a trades/hour quota: entries still need a new closed
candle, a flat account, valid depth/costs and compatible venue minimums.

## Evidence

See [stress results](reports/STRESS_REPORT.md) for losses, mitigations and
limitations. OHLC replay doesn't prove Derive fills, spread profitability,
live restart safety or competition readiness. No winning performance is
claimed for the current strategy.
