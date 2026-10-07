---
type: directional_trading
description: Mainnet Flyby V2 controller on Derive V3; selected ETH atomic options and ETH/SOL perps
---

# derive_cesf_long_vol

This is the canonical Flyby controller, the only copy in the repository.
Condor syncs this single file; its `agents`/`src` imports need the shared
package installed into Hummingbot first. Use
the four paused mainnet profiles in `sample_configs/`, identical to the
repository's `conf_flyby_*.yml` examples, plus the separately reviewed active
ETH/SOL profiles `eth_active.yml` and `sol_active.yml`. Hummingbot pairs are BASE-USDC;
the connector maps them to Derive's BASE-PERP instruments.

Install shared modules and the explicit reviewed compatibility patch into the
pinned Hummingbot client before syncing this controller. The runtime refuses entry
without compatibility and fresh authenticated net-margin state. A controller-only
Condor upload doesn't install dependencies or patch the client.

The continuous Condor loop launches the exact active ETH/SOL profiles.
It resolves the runtime, configured mainnet account and ownership before launch;
the controller checks fresh private account state, markets, reconciliation and
risk checkpoints before placing orders. These live checks must not be circular
pre-deployment requirements. Generic samples remain paused. Only
`derive_perpetual` is accepted. Testnet and paper-trading connector
overrides fail validation; a wrong or unknown runtime connector domain emits
no executor actions. Mainnet uses the reviewed Derive V3 connector and signer
on Hummingbot's V2 framework. Follow [mainnet setup](../../../../MAINNET_SETUP.md).

Samples now use the operator-approved −15% restricted / −25% hard-stop governor,
with a shared account-bound checkpoint and no automatic latch reset. Entry/hold
samples remain `strategy_profile: baseline`; the optional `competition_scalp`
profile is a tested, unpromoted research candidate. Prepare a separate paused
profile with `scripts/prepare_competition_profile.py`; it never installs/activates.
See the [risk/turnover evidence](../../../../reports/COMPETITION_RISK_TURNOVER_REPORT.md).

The four registered samples keep options shadow-only. Profiles select `option_buy_moneyness:
any` and bought/sold absolute delta targets 0.50/0.25. The canonical planner
uses lot-safe signed delta and gross-reference caps, not just debit premium.
Fresh public context can populate a fee-aware shadow plan; the detailed
Condor view exposes `options_delta`, never a live hedge authorization.
Read the [delta evidence](../../../../reports/DELTA_OPTIONS_REPORT.md).

This controller implements paired options execution through
Derive V3 RFQs, not the perpetual executor. The selected `eth_active` sample
enables options; `sol_active` is perp-only. The separately paused
`conf_flyby_options_eth.yml` and `conf_flyby_options_btc.yml` are unselected examples.
See [options execution](../../../../OPTIONS_EXECUTION.md). Unknown execution
acknowledgements and unmatched inventory block entries; don't reset their journal.

Derive publishes full order-book snapshots, so freshness uses a matching
native snapshot timestamp and `snapshot_uid`, not just `last_diff_uid`.
Repeated reads never refresh an old publication. The 30-second book limit,
60-second private-stream limit and all fee, position and drawdown gates remain.
Active configs explicitly include `trailing_stop: null` to satisfy Condor's
template validator without enabling trailing stops or changing sizing.
