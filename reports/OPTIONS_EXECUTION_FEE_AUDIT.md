# Options construction, execution and fees — 2026-10-03

The spread structure passes the controlled construction checks, but this audit
finds an unresolved exit-fee/recovery blocker. Keep trading paused. You can use
these results to distinguish a correctly formed spread from an economically
viable trade and a reliably closable position. No production strategy, risk
budget, credential, launcher or live account changed in this pass.

## What we tested

The [local audit harness](../backtest/options_execution_audit.py) calls the
production fee-adjusted planner and RFQ reducer with a real temporary disk
journal. It uses captured ETH lot/tick/standard fee rules, explicitly scripted
favorable books and Greeks, and a modeled transport. These prices/Greeks are
not a coherent historical chain or evidence of available trading opportunities.
Native signing and serialization remain separate pinned Hummingbot tests.

| Check | Result | Boundary |
|---|---|---|
| 1,000 call/put construction cases | 39 accepted, 961 rejected; zero invariant failures or invalid-input acceptances | Includes deliberately invalid cases, not 1,000 market backtests |
| Same-kind, same-expiry debit verticals | Equal paired size; correct call/put strike orientation; nonnegative bounded intrinsic payoff | Stored fee reserve is not a universal bound on future exit costs |
| Profit and loss closes | Both kinds close paired and reconcile cash/actual fixture fees | Chosen price jumps, not measured market returns |
| Time and forced closes | Both kinds close paired and reconcile | Forced callback, not a new account-drawdown test |
| Lost execution acknowledgement | Both kinds discover the owned fill and close once | Fixture transport, not private exchange connectivity |
| Exit-fee rise | Both kinds remain in `settling` with both legs open | Recovery gate fails; do not infer flat inventory |

The existing pinned options/policy suite passed **1,430 tests**, including the
600-spread/1,200-execution virtual lifecycle campaign with restarts and faults,
and 1,000 paper fault iterations. The campaign advances a 50-hour virtual clock;
it is not a 50-hour production soak. Twenty new audit regression tests passed
on both the host and pinned image (3.22s / 3.81s). A passing test that reproduces
a blocker does not clear that blocker.

## Controlled execution numbers

Each case starts independently with $800. Do not sum their P&L or turnover.
The call and put fixtures have identical cash flows by construction.

| Scenario, per kind | Net realized P&L | Ending cash | Remaining legs |
|---|---:|---:|---:|
| Profit close / lost-ack recovery | +$1.142 | $801.142 | 0 |
| Loss close | −$2.958 | $797.042 | 0 |
| Time / forced close | +$0.042 | $800.042 | 0 |
| Exit-fee rise | Unclosed; not zero | $797.726 cash, not marked equity | 2 |

The loss trigger is not a guaranteed −18% fill. Quote jumps and fees can create
a larger realized loss; the chosen loss fixture remains below the $4 budget.
Atomic execution avoids intentionally naked legs but doesn't guarantee an exit,
maker liquidity, margin sufficiency or settlement success.

## Current fee criteria and missing gates

The current planner reserves full standard fees on both legs at entry and exit:

```text
leg_fee = base_fee + min(amount × spot × taker_rate,
                         amount × limit_price × premium_cap)
round_trip_reserve = 2 × (buy_leg_fee + sell_leg_fee)
maximum_planned_loss = entry_debit + round_trip_reserve
```

For the fixture: 0.1 ETH matched size, $2,900 reference, $20/$9 entry prices,
0.03% rate, $0.50 base and 12.5% premium cap:

- Entry debit: **$1.10**.
- Reserved round-trip fees: **$2.348**, or **58.7% of the $4 budget**.
- Maximum planned loss: **$3.448**; expiry maximum reward/risk: **1.9002**.
- Break-even close credit after reserved fees: **$3.448**.
- +30% net take-profit needs **$4.1302** close credit with these fees, not $1.43.

The take-profit denominator is actual entry debit plus actual entry fees. The
current 1.5:1 reward/risk gate uses maximum expiry payoff; it does not establish
expected short-horizon edge or a probable profitable close.

| Criterion | Current behavior / required follow-up |
|---|---|
| Known fee metadata | Invalid/missing fees reject planning; no silent zero fee or rebate |
| Loss budget | Debit plus reserved fees must fit the current risk governor's budget: $4 initially; unchanged in this pass |
| Net profitability | Entry and exit fees count in TP/SL and realized P&L; add calibrated achievable-close/cost evidence before calling this alpha |
| Route-specific fees | Verify RFQ grouping, base charging and account tier on the team's actual API generation; do not import v3 discounts into v2 silently |
| Exit reserve | Replace the assumption that exit fees equal entry fees with a bounded stress reserve/current quote fee recheck; do not permit an unlimited fee cap |
| Rejected execution recovery | Distinguish a proven terminal rejection from an unknown acknowledgement; retain a persistent reason, owned inventory and halt until positively reconciled |
| Liquidity and partials | Fresh full paired quote and native limits remain required; no independent short-option repair or fake close |

The last two fee/recovery changes are **not implemented** by this diagnostic pass.
They require a production fix and revalidation, not a risk-budget increase.

## Reproduced exit blocker

After an entry at $2,900, the fixture raises reference spot to $3,300 while
providing a profitable full paired exit quote. The model requires **$1.198**
exit fees, but the lifecycle signs **$1.174001**, half the stored entry-time
round-trip reserve plus its rounding buffer. The modeled transport rejects
before a fill. The persisted intent remains `settling`; subsequent read-only
polling finds no execution and never resends. Both legs remain present.

This demonstrates a cap incompatibility and unresolved known-rejection path in
the model—not an observed mainnet incident. A real venue may report a terminal
failure differently. Never clear the intent or resend merely because no fill is
visible. The current transient error field also clears on a successful later
poll, so operators must not interpret `last_error: null` as a successful close.

## Published RFQ fee surface

The [official fee documentation](https://docs.derive.xyz/integrators/trading/trading-fees.md)
describes discounted RFQ groups: for a two-leg vertical, the cheaper leg receives
a full fee discount. The [RFQ guide](https://docs.derive.xyz/trading/rfq.md) describes
atomic package execution. These pages are in the current v3 documentation;
legacy reference URLs returned 404 in this review. They don't verify the
competition account's legacy-v2 fees or prove private execution compatibility.

For equal-cost legs in our fixture, applying that published grouping gives a
**$1.174 round-trip fee sensitivity**, versus the production reserve of $2.348.
This is a diagnostic comparison only: no discount was used for the simulated
fills, historical results, production planner or risk budget.

## Fresh historical replay and evidence

A fresh six-case, two-year approved-cap replay matches the prior results exactly:
zero executed options; perps/combined P&L −$80.04 base and −$80.10 stress.
Standalone ETH options still reject 806 eligible observations on fee-adjusted
planning and 336 on minimum gross exposure. Current-lot Black-76 proxy results
do not demonstrate viable native option opportunities.

Local evidence, excluded from the curated submission:

- `data/validation/two-year-20261003/options-execution-audit.json`
- `data/validation/two-year-20261003/options-audit-replay/summary.json`

```text
Audit SHA-256: 9529a3b1660f5b2fe5b83641beea9719eec1c5345f8529c52b2cfa5afc12ce09
Replay SHA-256: 053ee62212455e9fa3c5926af88cdb899492b8ee92a8f1b8d735e1871a1be562
```

Recorded source hashes match the working tree. All historical cases finish flat
and reconcile cash; the two deliberately adverse execution fixtures remain open
and are reported separately. Read the [ETH exposure report](ETH_EXPOSURE_TEST_REPORT.md)
for unchanged caps and [historical data boundaries](TWO_YEAR_OPTIONS_PERPS_REPORT.md).
