---
type: directional_trading
description: Mainnet-only Flyby V2 controller; atomic options RFQs require explicit opt-in
---

# derive_cesf_long_vol

This is the canonical Flyby controller, the only copy in the repository.
Condor syncs this single file; its `agents`/`src` imports need the shared
package installed into Hummingbot first. Use
the four paused mainnet profiles in `sample_configs/`, identical to the
repository's `conf_flyby_*.yml` examples. Hummingbot pairs are BASE-USDC;
the connector maps them to Derive's BASE-PERP instruments.

Install shared modules and the explicit reviewed compatibility patch into the
pinned Hummingbot client before syncing this controller. The runtime refuses entry
without compatibility and fresh authenticated net-margin state. A controller-only
Condor upload doesn't install dependencies or patch the client.

Keep the launch paused until the operator clears the repository's readiness
gates. Only `derive_perpetual` is accepted. Testnet and paper-trading connector
overrides fail validation; a wrong or unknown runtime connector domain emits
no executor actions. Mainnet uses the stock legacy v2 API, not the public v3
options-capture endpoint. Follow [mainnet setup](../../../../MAINNET_SETUP.md).

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

This controller also implements paired options execution through
Derive v2 RFQs, not the perpetual executor. Use the separately installed paused
`conf_flyby_options_eth.yml` OR `conf_flyby_options_btc.yml` after explicit operator
approval and mainnet verification; don't change the fixed samples silently.
See [options execution](../../../../OPTIONS_EXECUTION.md). Unknown execution
acknowledgements and unmatched inventory block entries; don't reset their journal.
