# Install the Flyby Condor agent

Install `condor/flyby/` as agent `flyby` in your Condor agent root. Its loop is
`flyby.flyby_operator`; its fixed profile is `flyby-baseline-dd15-dd25-v1`.
`agents/condor_agent.py` remains the shared Python policy, not the agent entrypoint.

Keep the controller paused. Installation doesn't configure a model, migrate
credentials, start Condor or enable trading. Follow [Hummingbot setup](../MAINNET_SETUP.md)
first: the controller imports the shared package, which must be in the pinned client.

## Verify an isolated installation

Run from the repository root with Python 3.11+ and PyYAML. This creates a new,
temporary agent root, not a production deployment:

```bash
python3 scripts/check_condor_package.py
flyby_review_root=$(mktemp -d)
python3 scripts/install_condor.py --agents-root "$flyby_review_root/agents"
```

Expect `structure_valid: true`, profile `flyby-baseline-dd15-dd25-v1`, loop
`flyby.flyby_operator`, `started: false` and `orders_submitted: 0`. Reinstalling
into the same target must fail without changing files. The installer refuses
links, unexpected/runtime files, sample drift and changed profile settings.

## Install into the team's environment

1. Resolve your writable root using `condor.paths.local_agents_root()` inside
   the team's Condor environment. Don't assume stock `agents/` is writable.
2. Run the installer with `--agents-root` set to that explicit path. If `flyby`
   exists, review it first: the installer won't overwrite its identity or state.
   Never install over the generic `condor` agent.
3. Confirm `AgentStore().get("flyby")` discovers the identity and
   `StrategyStore().get_by_key("flyby.flyby_operator")` discovers the loop.
4. Select your accessible Hummingbot API server and configured model. From an
   attended Condor session, request one dry-run tick of that exact loop, setting
   only `server_name` and `agent_key`. Retain `execution_mode: dry_run`,
   `max_ticks: 1` and `restart_on_boot: false`.
5. Inspect the dry-run record. With no owned bot, expect
   `not_deployed`/`HOLD_UNVERIFIED`, not automatic deployment or invented fills.

The upstream lifecycle tool uses `control_agent(action="start", loop_id=...,
config=...)`. The team runs that provider-backed check in its own environment;
the repository verifier never invokes that tool. The package follows
[Condor's structure](https://github.com/hummingbot/condor/blob/main/condor/agents/strategy.py).

## Preserve the fixed profile

All four samples retain baseline signals, stable controller IDs, the shared
`flyby-competition` risk namespace, $800 reference capital and unchanged caps.
The controller owns the −15% restricted / −25% hard-stop latches; Condor journal
drawdown is a different measurement. The team chooses compatible markets.
Don't increase caps to meet ETH/BTC minimums.

The four samples keep live options disabled. A separate operator-approved
[atomic RFQ profile](../OPTIONS_EXECUTION.md) is an explicit execution extension,
not an automatic update to those samples. Portfolio margin and spot hedging
stay disabled. The loop observes
plans/delta and controller decisions, not independent orders or strategy tuning.
A recurring live loop requires separate operator clearance of
[launch gates](../COMPETITION_READINESS.md), an explicit execution-mode change
and removal of the one-tick limit. No transition is automatic.

For recurring observation without trading, use the separate
[48-hour read-only procedure](OBSERVATION_RUN.md). It uses Condor's native loop
and the explicit observation launcher; it doesn't change the default playbook
or clear the live gates.

## Understand verification limits

`scripts/verify_condor_runtime.py` checks actual discovery, typed config, prompt
assembly, one tick and dry-run persistence in temporary roots. It mocks the API,
providers and model and refuses network connections. Run it with Condor's Python,
an explicit `--condor-root` checkout and a new `--output` JSON file. See the
[validation guide](../verification/VALIDATION.md).

Dry-run permission tests refuse exchange/running-bot actions. Upstream still
permits saved controller-config writes; the playbook forbids them, but that
isn't a configuration sandbox. ACP providers also don't enforce the identity
tool allowlist as a sandbox. Tests don't prove real-model instruction compliance,
production authentication, private fills/restarts or positive net P&L.
