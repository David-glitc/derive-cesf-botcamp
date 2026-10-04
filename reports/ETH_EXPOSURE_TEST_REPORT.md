# Paused ETH exposure test — 2026-10-03

The approved exposure-only profile is implemented separately from the fixed
submission baseline. It remains paused and has not been activated, committed
or pushed. The six-case two-year proxy replay still fails the economic gate:
options execute zero trades and combined P&L remains negative.

## Approved limits

Select [the separate ETH test config](../conf/controllers/conf_flyby_eth_exposure_test.yml)
only for an explicitly reviewed test. Its exposure identity is
`eth_exposure_40_75_v1`; its signal strategy remains `baseline`.

| Setting | Fixed baseline | ETH test |
|---|---:|---:|
| Starting allocation | $800 | $800 |
| Perp notional ceiling | 20% / $160 | 40% / $320 |
| Perp gross ceiling | 30% / $240 | 40% / $320 |
| Option gross underlying-reference ceiling | 30% / $240 | 75% / $600 |
| Signed option-delta ceiling | 20% / $160 | 20% / $160 |
| Initial per-trade loss budget | 0.5% / $4 | 0.5% / $4 |
| Drawdown rules | −10% restricted / −15% hard stop | Unchanged |

These are ceilings, not promised order sizes or guaranteed maximum losses.
Stops, confidence, drawdown scaling, available margin, fees and venue minimums
can require smaller orders or no order. Gross option reference is the sum of
absolute leg amounts times the underlying price, not premium spent or maximum
spread loss. The planner reserves its $4 debit/risk budget before calculating
exposure: initial entry ceilings are therefore **$597 gross and $159.20 delta**.
Leverage remains 2; it does not multiply capped notional or P&L.

The controller passes the identity to both sizers and the RFQ lifecycle. Entry
validation rechecks declared exposure against current equity. Protective paired
exits use the configured policy and the stored plan's narrower limits; switching
profiles never retroactively widens an owned plan. Baseline defaults remain
unchanged, and the wider identity is rejected for BTC/SOL/HYPE. Condor's
allowlisted context exposes the selected identity and fractions.

## Two-year replay

Window: 2024-10-01 through 2026-10-01 UTC, end exclusive. Each independent case
starts with $800; each combined case shares one ledger and one risk governor.
The perp comparison includes ETH/BTC/SOL priority, but only ETH gets wider caps.
BTC/SOL keep baseline settings. Do not sum independent portfolios or interpret
two-year turnover as two-day competition volume.

| ETH test case | Ending equity | Net P&L | Max drawdown | Closed trades | Perp turnover | Option premium turnover |
|---|---:|---:|---:|---:|---:|---:|
| Options, base/stress | $800.00 | $0.00 | 0.00% | 0 | $0 | $0 |
| Perps or combined, base | $719.96 | −$80.04 | −10.23% | 315 | $110,141.28 | $0 |
| Perps or combined, cost stress | $719.90 | −$80.10 | −10.28% | 168 | $53,705.27 | $0 |

Standalone ETH options produce 1,142 eligible signal observations: 806 fail
fee-adjusted spread planning and 336 still exceed the gross cap at current
minimum lots. Widening gross exposure alone does not resolve the unchanged $4
loss budget, representative fees and reward/risk constraints. No option RFQ fill
occurred in these historical cases; separate execution fixtures test that path.

All six cases finish flat without reducer errors and reconcile ending equity
to $800 plus closed-trade net P&L. A ten-case baseline regression on the updated
source matches the previous baseline's metrics, blockers, exit reasons and risk
transitions exactly. Baseline perps/combined P&L remains −$80.83 base / −$81.45
stress. This test is not a profitable candidate promotion.

Inputs are real public underlying candles and IV-index history, with modeled
Black-76 option chains, books, fills and funding—not historical Derive option
quotes or private settlement. Read the [data boundaries](TWO_YEAR_OPTIONS_PERPS_REPORT.md)
and [replay guide](../backtest/TWO_YEAR_REPLAY.md) before making performance claims.

Local output folders, excluded from the curated submission:

- `data/validation/two-year-20261003/eth-cap-test/`
- `data/validation/two-year-20261003/cap-change-baseline-regression/`

Summary SHA-256 values:

```text
ETH test: 053ee62212455e9fa3c5926af88cdb899492b8ee92a8f1b8d735e1871a1be562
Baseline: c7e87086d6791a10158c816ecd958ae66115039ac7b1c5814e9fb76a68855574
```

Both summaries' recorded simulation-source hashes were checked against this
working tree. Older evidence stays intact; it describes its own frozen source.

## Verification

- **2,918 tests passed** in the pinned Hummingbot image, with seven upstream
  deprecation warnings. Network was disabled and the repository mounted read-only;
  the compatibility patch applied only inside the disposable container.
- **316 focused host tests passed** for exposure, delta, replay and packaging.
  The real-Hummingbot controller spy also verifies both approved entry-sizer
  arguments, including the unchanged $4 risk budget and reserved option caps.
- A fresh disposable installation imported the installed ETH test controller
  with its wider caps and kill switch enabled. Mainnet installation preflight
  passed inside the pinned image; this checks endpoints/configuration, not a
  private account. The host lacks Hummingbot and cannot run that runtime preflight.
- Condor package structure, shell syntax, documentation links, source hashes,
  replay cash ledgers and `git diff --check` passed.

Pinned image digest:

```text
hummingbot/hummingbot@sha256:d8eb5675cdd37f84f8d132b79b932f012d755d97f21e2da3fd4fef955609079d
```

These checks establish offline behavior, not a mainnet fill or production soak.

## Operational boundary

The shipped file has `manual_kill_switch: true`. The installer includes it but
the default launcher and Condor registered samples do not select it. Private
mainnet connectivity, fills and a wall-clock production soak remain unverified.

The test keeps `risk_state_id: flyby-competition`. Preserve the existing
account-bound risk checkpoint and latches; do not reset them to enable entries.
Only one RFQ controller may own an account. Its controller ID differs from the
baseline RFQ profile, so an existing RFQ journal can reject the owner switch even
when idle. Stop the old owner and verify authenticated flat inventory and no
working RFQs/orders first. Any archival/migration of an old RFQ journal requires
explicit operator review; never adopt another owner's open spread or delete
recovery state to bypass reconciliation. No state migration occurred here.
