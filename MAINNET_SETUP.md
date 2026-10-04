# Set up Flyby for the competition team

Install the mainnet-only controller and portable Condor identity using your
own account. Installation leaves every profile paused and doesn't submit
orders. The runtime is not yet cleared by the [live gates](COMPETITION_READINESS.md).

## Check the target environment

Use the image in [hummingbot-version.json](hummingbot-version.json), with the
repository mounted at `/repo` and Hummingbot's Python environment active.
Run the read-only preflight inside that environment:

```bash
python /repo/scripts/check_mainnet.py
```

Expected: `network: mainnet`, `connector: derive_perpetual`,
`api_generation: legacy_v2`, `install_profiles_paused: true`, and
`live_execution_verified: false`. It checks the installed connector constants
and submitted profiles, not your credentials, balances or private stream.
It makes no exchange requests. A mismatch exits with status 1 before installation.
`compatibility_version: null` means the stock connector still needs the reviewed
compatibility patch below. A version marker isn't private-account verification.

The stock connector uses `https://api.lyra.finance` and
`wss://api.lyra.finance/ws`. These are the reviewed legacy v2 mainnet endpoints.
The analysis-only options collector uses `https://api.derive.xyz/v3/`.
Don't swap the stock connector's URL to v3: private methods and signing need
a separate migration. See [Hummingbot's Derive guide](https://hummingbot.org/exchanges/derive/).

## Install the controller

Use a clean team environment: installation copies the sample profiles over
files with the same names. Preserve any custom profiles outside those names
before installing. The installer checks the mainnet contract before writes:

```bash
bash /repo/scripts/install_hummingbot.sh /home/hummingbot
```

Expected: `Installed mainnet-only paused profiles (derive_perpetual, legacy v2 API).`
No bot starts. The package installs shared policy/features/risk/options modules;
the historical controller name remains an import alias, not another strategy.
Without compatibility installed, the controller refuses entry.

## Install the reviewed compatibility patch

Use a stopped, dedicated client on the exact pinned image. Don't patch a running
bot or a shared client. Review [the patcher](scripts/hummingbot_compat.py) and
[the delegates](src/execution/derive_hb.py) before the team approves installation.

```bash
python /repo/scripts/hummingbot_compat.py --hb-dir /home/hummingbot
bash /repo/scripts/install_hummingbot.sh /home/hummingbot --with-compatibility
python /repo/scripts/hummingbot_compat.py --hb-dir /home/hummingbot
```

Expected: the first check reports `installed: false` on stock source; the
installer applies `flyby-derive-2.17.0-r1`; the last check reports `installed: true`.
Both upstream file hashes must match before any patch write. Re-running is
idempotent; unexpected upstream or edited source fails instead of guessing.
The patch preserves original `.py.flyby-original` files alongside both targets.

The Derive-only executor close branch sends `PositionAction.CLOSE`; the connector
serializes `reduce_only: true`. It preserves tick prices, maps maker-only orders
to `post_only`, and uses full authenticated `get_subaccount` snapshots for margin
and positions. Initial margin is a signed net cushion; open-order margin is
added to it. Missing, unhealthy, stale or unsupported snapshots block new entries.
USDC collateral alone doesn't prove capacity. Other connectors retain their
original executor close behavior. No LLM decides these safety checks.
The separately selected [RFQ profiles](OPTIONS_EXECUTION.md) retain option
positions in that full snapshot and use one atomic RFQ instead of a perpetual
executor. Both profiles install paused and aren't selected by the default launcher.
Reduce-only limit closes use IOC; resting reduce-only orders are rejected.
Market orders use a signed 15bp worst-price bound around the current mid, rounded
inside the bound. This can leave partial/unfilled closes during fast moves; it
isn't a promise of unlimited liquidity or guaranteed stop execution.

If you must roll back, stop the client first, then restore only verified originals:

```bash
python /repo/scripts/hummingbot_compat.py --hb-dir /home/hummingbot --restore
```

Expected: `installed: false`; Flyby refuses entry on the restored stock client.
Backups remain available. These offline checks don't prove real closes, dust
recovery, signing, private-stream operation or restart reconciliation.

## Connect your account and import Condor

Connect `derive_perpetual` in your Hummingbot client or Condor/API credential
dashboard. Use your own mainnet wallet, session key, subaccount and account
type matching the installed connector schema. Follow the field mapping in
the [official guide](https://hummingbot.org/exchanges/derive/#how-to-connect).
Don't put keys/account IDs in this repository or reuse an old testnet credential.

Import [the portable Flyby identity](condor/flyby/AGENT.md) and its
[controller registration](condor/flyby/controllers/derive_cesf_long_vol/CONTROLLER.md)
through your Condor agent-import workflow. Configure your own provider/model.
This repository doesn't replace a generic running Condor identity or register
an autonomous loop automatically.

## Select and inspect the paused profile

Hummingbot uses `ETH-USDC`, `BTC-USDC`, `SOL-USDC` and `HYPE-USDC`; the stock
connector maps these to Derive's corresponding `*-PERP` instruments. Don't put
venue instrument names in Hummingbot's `trading_pair` field.

The launcher selects ETH only. Choose BTC instead, or explicitly opt into
listed SOL/HYPE fallbacks, after checking your account universe, instrument
rules, candle availability and budget. Don't enable all four by default.
Keep `manual_kill_switch: true` and `options_enabled: false` while inspecting.

Run a credential-free current-minimum check from the repository:

```bash
python3 scripts/inspect_market_rules.py
python3 scripts/check_condor_package.py
```

Expected: public sizing diagnostics and four identical paused Condor samples.
With $800 and the unchanged 20% cap, the observed ETH/BTC minimums exceed budget;
SOL/HYPE fit that notional cap, subject to stop risk, liquidity and signal gates.
`venue_minimum_exceeds_budget` skips the entry without rounding up or changing
caps. The operator must discuss any explicit risk-cap change before activation.
Sample configs also ship inside the Condor controller's `sample_configs/`.

Verify balances, actual available margin, positions, orders, instrument lots,
private-stream freshness and the matching candle proxy before activation.
Persist `data/` and use stable controller IDs on a dedicated account.
The controller exposes `processed_data.execution_environment` in normal and
halted states. Wrong or unknown connector domains emit no executor actions;
testnet/paper connector names fail config validation.

For native index, perp volume and option-price context, follow the optional
[bounded capture guide](backtest/NATIVE_DATA.md). It requires no credentials
and doesn't change default candle inputs. Share its owned `data/` volume with the
controller and mount detailed context read-only into Condor. Inspect
`custom_info.flyby` in normal status reports; `context_path` identifies the
allowlisted file. A stopped collector produces expired context, not a fresh feed.

The controller accepts `signal_source: derive_native` only at 5m. Use that
explicit opt-in for isolated fixture/shadow testing, not to bypass launch gates.
Missing/stale context halts without fallback; leave sample profiles paused.
See the [local verification workflow](verification/VALIDATION.md).

Only the operator clears the live gates and deliberately activates trading.
The opt-in close/account fixes have offline contract evidence, not a private
mainnet soak. Dust closes, fees/funding, reconnect and restart still require
operator-approved validation, and replay economics remain negative.
Options are call/put shadow plans and paper tests, not a
paired live executor. Mainnet configuration isn't live certification.

## Preserve competition drawdown state

The approved policy is `flyby-dd15-dd25-v1`: −15% enters restricted trading;
−25% latches a hard stop. With an $800 peak, these are $680 and $600. Profits
raise the peak; the approved starting budget is its minimum baseline. Restricted
mode raises confidence to 0.85, strengthens two-bar trend/volume confirmation,
requires a 4× modeled cost cushion and reduces size to at most 25%, decreasing
as the final ten percentage points are consumed. Daily P&L is diagnostic.

Persist the entire owned `data/` volume. All selected profiles use the same
`risk_state_id: flyby-competition` and $800 budget. The account-bound checkpoint
is `data/flyby-risk-flyby-competition.json`, with `.initialized` and `.lock`
companions. Neither restricted mode nor the hard stop resets on recovery,
midnight, profile change or restart. Don't delete/rename the files or namespace
to resume. Missing/corrupt/foreign state blocks entry; an unknown position isn't
automatically adopted or declared flat. A fresh flat dedicated account can
initialize the new state against the fixed starting budget.

Checkpoints and initialization markers using the previous
`flyby-dd10-dd15-v1` policy are rejected with
`risk_checkpoint_contract_mismatch`, even when bootstrap is allowed. The update
does not migrate them or reset their latches. Operator review must preserve the
account binding, peak, entry history and any restricted/hard-stop latch before
an explicit migration is approved. Do not delete state to bypass this check.

Old `data/flyby-risk-<controller-id>.json` files cause
`legacy_risk_checkpoint_requires_review`; keep them intact for operator review.
There is no automated migration/reset command that discards the old peak.
Restoring risk state doesn't prove actual executor/position recovery. Real
partial/dust closes, reconnect and restart adoption remain launch gates.

## Prepare an optional scalp research profile

From the repository root, generate a NEW paused file for your selected market:

```bash
python3 scripts/prepare_competition_profile.py --market SOL --profile competition_scalp --output data/review/conf_flyby_sol_scalp.yml
```

Expected: `paused: true`, `caps_changed: false`, `installed: false`,
`live_ready: false`, `orders_submitted: 0`. An existing output is never overwritten.
This example doesn't choose SOL for the organizer, update the launcher or install
the profile. You can explicitly choose ETH/BTC/SOL/HYPE; venue compatibility
and universe checks still apply. Only one strategy profile should run per pair.

The opt-in 5m candidate uses a fixed 30-minute trend window, 10–30 minute maximum
holds, 60s cooldown and hold hysteresis. Each entry still requires a new completed
candle and a reconciled flat account. The preset isn't a profitable recommendation:
the costed comparison increases volume and worsens P&L. Keep baseline samples
paused and don't promote it from these results. Read the
[comparison and launch limitations](reports/COMPETITION_RISK_TURNOVER_REPORT.md).
