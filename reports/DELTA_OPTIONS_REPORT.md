# Delta-aware options: implementation and evidence

You can inspect delta-aware shadow plans and Condor context, but you cannot
trade live options with this release. Twenty fixed 48-hour perp proxy cases
produce $37,352.51 summed experiment turnover and −1.174% to 0% returns.
Neither the 150% return target nor $50,000 turnover target is achieved.
No preset is promoted, no account is activated and no order is submitted.

## Implemented boundaries

| Component | Behaviour |
|---|---|
| Signed exposure | Option delta × actual underlying-unit amount × verified multiplier; dollars use reference spot |
| Moneyness | Spot/strike ATM window ±0.5%; OTM/ITM differ for calls and puts; not a delta-probability rule |
| Strike selection | Bought absolute delta 0.25–0.70, sold 0.10–0.35; default targets 0.50/0.25; sold delta must be smaller |
| Sizing | Floor to lot step; debit/depth/fee budget plus 20% net-dollar-delta and 30% gross-reference caps |
| Gross reference | Both option legs valued at underlying spot, not premium or venue margin; full loss headroom reserved |
| Pending fills | Existing signed exposure plus buy/sell fill interval; never assume a resting hedge fills |
| Partial-leg sensitivity | Either-leg-only local delta must fit; this does NOT make a naked short option bounded-risk |
| Controller | Fresh account recheck, clear obsolete plan, optional fresh public-file chain/fee ingestion; advisory failure does not interrupt perp exits |
| Condor | Bounded `options_delta` context with delta, moneyness, caps, fees, freshness, target and disabled hedge-order status |
| Paper exits | Refresh delta using actual fills; cap breach/invalid delta closes only with executable books; net +30%/−18%, signal, 6h hold/expiry rules |
| Missing books | Preserve unresolved exposure, null equity and latched halt; no invented liquidation |
| Account risk | Paper uses shared pure −10% restricted / −15% hard-stop reducer, retained by input replay |
| Live capability | Perps only; no option/hedge order sender, paired adapter, merged options/perps portfolio or continuous public feed |

Standalone older spread-builder calls without a delta policy retain an explicit
`delta_verified: false` status. Manually supplied controller quotes without
fee metadata remain fee-unverified. Neither flag authorizes execution.
Current controller entry is flat-account only; unknown positions/orders block
plans rather than assuming their Greeks. ETH and BTC units are never netted.
Perp sizing keeps the existing notional/risk controls; these tests do not
establish a new perp alpha signal or options hedge strategy.

The exact delta target in a plan is its bounded directional entry exposure,
not zero. A full hedge would counteract that directional signal. No hedge
profit, risk reduction or funding benefit is booked without an executed hedge.
Delta alone does not bound gamma, vega, gaps, total option loss or exchange margin.

## Twenty 48-hour performance cases

The predeclared matrix uses BTC/SOL × baseline/scalp × five disjoint 48-hour
windows. Every case starts with $800. Both policies reuse each market's
window; these are not 20 independent statistical samples or one portfolio.
The 172-bar gaps cover warm-up/outcome separation. Histories were previously
inspected Binance proxies, not fresh holdout Derive execution history.
Current recorded venue rules apply to older prices. Fees, slippage and funding
are modeled; book queue, native fills and option chains are not reconstructed.

| Five-case group | Closed trades | Sum turnover | Sum fees | Per-case net return range |
|---|---:|---:|---:|---:|
| BTC baseline | 0 | $0 | $0 | 0% |
| BTC scalp | 0 | $0 | $0 | 0% |
| SOL baseline | 16 | $5,110.72 | $1.85 | −0.299% to −0.090% |
| SOL scalp | 101 | $32,241.79 | $11.69 | −1.174% to −0.421% |

Combined **experiment turnover** is $37,352.51, short by $12,647.49.
Zero-return BTC cases are minimum-lot blocked, not profitable trading.
Every SOL case loses after costs. These results support keeping the scalp
candidate unpromoted. Do not sum case returns or use experiment turnover as
one account's competition volume. No case reaches 150%; no competitor-return
forecast exists. A future 1.5× peer-return target requires audited competitor
repositories, same capital/horizon/cost assumptions and uncertainty estimates.
Best-case peer scenarios are not expected returns or winning-score forecasts.

Local evidence: `data/validation/delta-options-20261002/final-performance/perps-48h/`.
The 90-case timeframe/split regression matrix lives under
`data/validation/delta-options-20261002/perps-public-taker-venue/` and retains
the prior perp results. Adding shadow delta doesn't change executed perp alpha.
Local raw evidence is ignored and excluded from the submission archive.

## Public options evidence

Twenty selection/cap feasibility cases reuse the ETH/BTC public captures:
five selections (`any`, ATM, OTM, ITM, OTM 35-delta target) × 10%/20% delta cap
× two assets. Every case produces zero option fills, fees and premium volume.
Each capture has two observations over about 1.16 seconds. This cannot test
48-hour option performance, options/perps portfolio returns or close liquidity.
The option premium-volume convention is not a verified competition scoring metric.

The paper engine reserves all four leg-side fees and full-debit risk, applies
minimums/caps and records why it rejects entries. The previous $0.50 fixed-fee
synthetic fixture now correctly fails all-in reward/risk. Lifecycle tests use
an explicitly synthetic $0.01 fixed-fee variant. Those chosen fixture fees are
not a claim about the venue or evidence of profitable trades.

## Verification scope

Final local validation passes **2,637 host tests** (three Hummingbot-only skips)
and **2,729 pinned Hummingbot 2.17.0 tests** (seven upstream warnings), plus
the existing paired model and 60-case legacy comparison. The separate
current-lot 90-case regression and 20-case 48-hour runs also complete.
Source hashes match the final validation and public feasibility manifests.
See `data/validation/delta-options-20261002/final-validation/validation.json`.

The host and pinned Hummingbot suites exercise signed delta, strike selection,
pending fill intervals, unchanged caps, no upward lot rounding, fee-aware exits,
Greek changes at unchanged spot, unpriceable books, risk/checkpoint replay,
freshness, cleared plans, supplied fee costs, automatic shadow context and
redacted Condor views. The existing 1,000 paper fault iterations remain
synthetic execution coverage, not market backtests. Two hundred randomized
lot/exposure cases add algebraic boundary coverage.

`verification/check_delta.py` returns UNSAT for call, put and gross-bound
violation searches. Its real-valued model assumes same-kind deltas and bounded
quantities; it is not implementation equivalence, fee/margin safety, atomic
execution, Greek freshness or a maximum-loss proof. Existing paired-model
proofs have the same live-execution limitation. See
[validation instructions](../verification/VALIDATION.md) and
[readiness gates](../COMPETITION_READINESS.md).

## Research basis

- [OIC delta](https://www.optionseducation.org/advancedconcepts/delta) and
  [gamma](https://www.optionseducation.org/advancedconcepts/gamma): signed price
  sensitivity changes with price, volatility and time. Not a calibrated win probability.
- [Boyd et al., 2017](https://web.stanford.edu/~boyd/papers/cvx_portfolio.html):
  costs/risk constrain allocation; the framework does not supply profitable forecasts.
- [Matic, Packham and Härdle](https://arxiv.org/abs/2112.06807): crypto option
  hedging distinguishes delta, gamma, vega and minimum-variance approaches.

These sources motivate conservative controls. They do not validate our
selection parameters, two-day return target or a competition-winning edge.
