# Competition artifact index

The team runs the V2 controller and its shared Condor policy—not the archived
v3 testnet runner. The controller exists in one place, inside the Condor agent folder.
The competition runtime is mainnet-only using the stock Hummingbot legacy v2
Derive connector, not a Derive v3 trading client.

Required runtime files:

- `condor/flyby/controllers/derive_cesf_long_vol/derive_cesf_long_vol.py`
- `agents/condor_agent.py`
- `agents/mainnet.py`
- `src/signal/`, `src/risk/position_sizing.py`, `src/options/`
- `src/data/` and `src/accounting/context.py` (public schemas and read-only reporting)
- `src/execution/` (pure models plus opt-in stock-connector compatibility delegates)
- `src/accounting/derive_margin.py` and `src/risk/venue_sizing.py`
- `src/risk/competition.py` (account-bound −15%/−25% governor and persisted entry signals)
- `src/runtime/` and `RUNTIME_OVERSIGHT.md` (opt-in private feed, bounded adjustment handlers and Condor/MCP integration; off by default)
- `condor/profiles/flyby_observe_48h.yml`, `condor/OBSERVATION_RUN.md` and `scripts/prepare_observation_profile.py` (separate paused read-only loop preparation, not live activation)
- `pyproject.toml` (install shared modules into the execution environment)
- Selected `conf/controllers/conf_flyby_{eth,btc,sol,hype}.yml`
- `conf/scripts/conf_v2_flyby.yml`
- `hummingbot-version.json`, `scripts/hummingbot_compat.py`,
  `scripts/check_mainnet.py` and `scripts/install_hummingbot.sh`

For the Condor identity/workflow, import [the agent package](condor/flyby/AGENT.md)
using the team's provider/model configuration. `condor/flyby/` is the only folder
injected into Condor; its `controllers/derive_cesf_long_vol/` holds the canonical
V2 controller itself, not a wrapper. It doesn't create a separate private Derive order client.
The entrypoint is `condor/flyby/AGENT.md` plus
`condor/flyby/loops/flyby_operator/loop.md`, not the Python policy alone.
The fixed identity is `flyby-baseline-dd15-dd25-v1` in `condor/flyby/PROFILE.yml`.
Follow [Condor installation](condor/INSTALL.md): `scripts/install_condor.py`
copies authored files into an explicit new `flyby` agent home without starting
a loop or replacing the coordinator. The ZIP includes these files; a GitHub
handoff must commit them too.
Every submitted agent/controller instruction selects `derive_perpetual`.
Testnet and paper-trading runtime overrides are rejected.

The [installer](scripts/install_hummingbot.sh) copies only approved controller
profiles and installs shared Python dependencies. It first runs the read-only
[mainnet preflight](scripts/check_mainnet.py); include that script with the
installer. Follow [team setup](MAINNET_SETUP.md). The
[runtime test script](scripts/test_hummingbot.sh) uses the pinned image.

The optional [native-data capture/replay workflow](backtest/NATIVE_DATA.md)
uses `scripts/capture_derive_public.py` and `backtest/replay_derive.py` as local
testing tools, not another trading runner. The controller exposes allowlisted
Condor context through `custom_info.flyby`; detailed files stay on an owned
data volume. Native input is explicit opt-in; sample defaults are unchanged. See the
[observed coverage report](reports/NATIVE_DATA_REPORT.md).

Optional [validation tools](verification/VALIDATION.md) provide paired-model
proofs and fixed entry/hold comparisons, not another competition runner.
Read the [expanded report](reports/SHADOW_VALIDATION_REPORT.md) for boundaries
and remaining gates. Keep Z3/research tooling out of running controllers.

The team chooses the account universe and enabled markets. ETH is selected in
the sample launcher; every sample is paused with `manual_kill_switch: true`.
SOL/HYPE are opt-in fallback profiles, subject to listing, candles and account
permissions. Default profiles keep options disabled; separately installed
paused RFQ profiles require explicit operator selection and mainnet verification.
Keep portfolio margin and spot hedging disabled. Include
`src/execution/derive_rfq.py`, `src/execution/options_rfq.py`, both
`conf_flyby_options_*.yml` profiles and [their setup guide](OPTIONS_EXECUTION.md).
The separate paused `conf_flyby_eth_exposure_test.yml` and
`src/risk/exposure.py` carry the approved ETH-only exposure identity. They do not
replace the fixed baseline or default launcher; see the
[test limits and measured results](reports/ETH_EXPOSURE_TEST_REPORT.md).
All four profiles share `risk_state_id: flyby-competition` and the approved
`flyby-dd15-dd25-v1` risk policy. Entry/hold defaults remain baseline and paused.
Use `scripts/prepare_competition_profile.py` only to create a separate paused
research profile; the scalp candidate isn't promoted. Read the
[latest risk/turnover report](reports/COMPETITION_RISK_TURNOVER_REPORT.md).
The [delta/options update](reports/DELTA_OPTIONS_REPORT.md) adds signed exposure
sizing and fresh public-chain shadow context. `src/options/delta.py` is a shared
runtime dependency, not an option/hedge order sender. Samples remain paused.

See [readiness gates](COMPETITION_READINESS.md) before enabling trading.
The [two-year report](reports/TWO_YEAR_OPTIONS_PERPS_REPORT.md) and
[replay instructions](backtest/TWO_YEAR_REPLAY.md) record free public input
coverage, one-$800-account comparisons and remaining economic/option-size blockers.
Research harnesses don't form another trading runner; raw data and traces stay
outside the submission. No historical option fills or profitable edge are claimed.
The [final hardening report](reports/FINAL_SUBMISSION_REPORT.md) records offline
compatibility checks and cost/capacity diagnostics. A final review archive can
be built without uploading or committing anything:

```bash
python3 scripts/check_condor_package.py
python3 scripts/build_submission.py --output data/submission/flyby-final-review.zip
```

The archive includes a manifest with every source hash and excludes credentials,
runtime state, raw traces and the old local harness. When the worktree is dirty,
its base commit is not the artifact identity. Commit/push the reviewed source
and provide that exact commit to the organizers separately; this tool doesn't
submit a repository or clear launch gates. The installer uses an explicit
`--with-compatibility` argument for the reviewed pinned client patch.
Credentials, operational traces, testnet account IDs and the local archive
must not be committed. This worktree has not been pushed as a live-ready release.
