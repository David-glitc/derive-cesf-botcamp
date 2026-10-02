# Flyby — Hummingbot V2 + Condor

Run one deterministic Flyby policy through Hummingbot's Derive perpetual
mainnet adapter. ETH/BTC are primary candidates; SOL/HYPE are fallback profiles.
The team chooses the enabled markets and account universe.

Fixed submission identity: `flyby-baseline-dd10-dd15-v1`. Condor discovers agent
`flyby` and explicit loop `flyby.flyby_operator`; see the
[Condor installation guide](condor/INSTALL.md). All samples remain paused.
The [final Condor verification report](reports/CONDOR_FINAL_VERIFICATION.md)
records discovery/tick/install evidence and the remaining production gates.

**Current verdict: not cleared for live trading.** Contract tests pass in
Hummingbot v2.17.0, but stress replay remains negative after risk mitigations.
Option spreads are shadow plans, not live orders. Read the
[stress report](reports/STRESS_REPORT.md) and [launch gates](COMPETITION_READINESS.md).
The latest [competition risk/turnover report](reports/COMPETITION_RISK_TURNOVER_REPORT.md)
covers the approved −10% restricted / −15% hard stop and the unpromoted scalp
candidate. Higher modeled volume did not improve net P&L.
The [delta/options report](reports/DELTA_OPTIONS_REPORT.md) covers delta-aware
shadow sizing, Condor context, dynamic paper exits and twenty 48-hour proxy cases.

## Submission files

| Component | File | Responsibility |
|---|---|---|
| V2 controller | [flyby.py](controllers/directional_trading/flyby.py) | Account/book gates, bounded sizing, executor actions |
| Compatibility name | [derive_cesf_long_vol.py](controllers/directional_trading/derive_cesf_long_vol.py) | Import only; not a second strategy |
| Condor policy | [condor_agent.py](agents/condor_agent.py) | Shared deterministic price/volume decision |
| Condor identity | [agent package](condor/flyby/AGENT.md) | Operator workflow; cannot override risk gates |
| Condor loop | [loop.md](condor/flyby/loops/flyby_operator/loop.md) | Controller-mode playbook; one dry-run tick by default |
| Fixed profile | [PROFILE.yml](condor/flyby/PROFILE.yml) | Machine-checked baseline and risk identity |
| Features | [signal module](src/signal/flyby.py) | Closed-bar, causal, timeframe-aware indicators |
| Risk | [position sizing](src/risk/position_sizing.py) | Exposure, drawdown scaling, costs and executable depth |
| Competition governor | [account risk state](src/risk/competition.py) | Shared restart-persistent loss latches, consumed signals and cooldowns |
| Options | [spread builder](src/options/spread_builder.py) | Matched call/put debit-spread plans, no order sender |
| Configuration | [launcher](conf/scripts/conf_v2_flyby.yml) | ETH selected, paused; team explicitly enables others |

The [artifact index](SUBMISSION_ARTIFACT.md) lists required dependencies.
The [final hardening report](reports/FINAL_SUBMISSION_REPORT.md) covers the
explicit pinned connector patch, BASE-USDC mapping, current minimum-size
incompatibility and Condor sample discovery. Install using
[the tested team guide](MAINNET_SETUP.md); importing the Condor wrapper alone
doesn't install shared modules or clear launch gates.
The [strategy explanation](strategy.md) describes implemented rules and limits.
Legacy research scripts are not the current strategy. The old v3 runner and
raw operational logs were preserved locally outside the submission surface.

## Validate locally

Use Python 3.11+ for pure tests; run controller tests in the pinned image.

```bash
python3 -m pip install -r requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
bash scripts/test_hummingbot.sh
PYTHONPATH=. python3 backtest/stress_flyby.py --runs 1000 --bars 5000 --workers 4
```

The replay writes `stress_artifacts/` and caches candles under `data/`.
Both are ignored. Five million evaluations reuse 64,800 unique historical
candles: they are not five million independent candles or 1,000 independent
historical periods. Funding, depth and option books are scenario models.

## Install into Hummingbot

Pin the [validated client image](hummingbot-version.json). Use a dedicated
account, persist its `data/` directory, and configure secrets through
Hummingbot. v2.17 renamed Derive credential fields; re-connect the connector
as described in the [release notes](https://hummingbot.org/release-notes/2.17.0/).

Use [mainnet setup](MAINNET_SETUP.md) for the team handoff. The competition
runtime accepts only `derive_perpetual` and rejects testnet/paper overrides.
The stock connector uses the legacy v2 API at `https://api.lyra.finance`;
the options public-data harness uses v3 separately. This is not a v3 trading
migration. The installer checks endpoints and paused profiles before writes.

Run this inside your Hummingbot environment with this repository at `/repo`:

```bash
bash /repo/scripts/install_hummingbot.sh /home/hummingbot
```

In the client, configure `derive_perpetual`, review the selected profile's
budget and fee estimate, and keep `manual_kill_switch: true` until the launch
gates pass. Once the operator clears those gates and deliberately changes
that switch, the CLI launch command is:

```text
start --v2 conf_v2_flyby.yml
```

This session did not start a trading bot or submit any orders. Downloading
and testing v2.17 does not upgrade an existing API/Condor deployment: those
follow independent continuous releases.
