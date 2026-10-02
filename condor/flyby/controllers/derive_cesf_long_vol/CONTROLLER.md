---
type: directional_trading
description: Mainnet-only Flyby V2 Derive perpetual controller; options are signal-only
---

# derive_cesf_long_vol

This registration imports the canonical repository controller after the
shared package and controller modules are installed into Hummingbot. Use
the four paused mainnet profiles in `sample_configs/`, identical to the
repository's `conf_flyby_*.yml` examples. Hummingbot pairs are BASE-USDC;
the connector maps them to Derive's BASE-PERP instruments.
No independent strategy copy is maintained here.

Install shared modules and the explicit reviewed compatibility patch into the
pinned Hummingbot client before syncing this wrapper. The runtime refuses entry
without compatibility and fresh authenticated net-margin state. A wrapper-only
Condor upload doesn't install dependencies or patch the client.

Keep the launch paused until the operator clears the repository's readiness
gates. Only `derive_perpetual` is accepted. Testnet and paper-trading connector
overrides fail validation; a wrong or unknown runtime connector domain emits
no executor actions. Mainnet uses the stock legacy v2 API, not the public v3
options-capture endpoint. Follow [mainnet setup](../../../../MAINNET_SETUP.md).

Samples now use the operator-approved −10% restricted / −15% hard-stop governor,
with a shared account-bound checkpoint and no automatic latch reset. Entry/hold
samples remain `strategy_profile: baseline`; the optional `competition_scalp`
profile is a tested, unpromoted research candidate. Prepare a separate paused
profile with `scripts/prepare_competition_profile.py`; it never installs/activates.
See the [risk/turnover evidence](../../../../reports/COMPETITION_RISK_TURNOVER_REPORT.md).

Options remain shadow-only. Profiles explicitly select `option_buy_moneyness:
any` and bought/sold absolute delta targets 0.50/0.25. The canonical planner
uses lot-safe signed delta and gross-reference caps, not just debit premium.
Fresh public context can populate a fee-aware shadow plan; the detailed
Condor view exposes `options_delta`, never a live hedge authorization.
Read the [delta evidence](../../../../reports/DELTA_OPTIONS_REPORT.md).
