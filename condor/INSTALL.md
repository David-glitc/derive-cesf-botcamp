# Install the Flyby Condor agent

Install `condor/flyby/` as agent `flyby` in your Condor agent root. Its loop is
`flyby.flyby_operator`; its fixed profile is `flyby-baseline-dd15-dd25-v1`.
`agents/condor_agent.py` remains the shared Python policy, not the agent entrypoint.

The generic controller samples remain paused; the operator-selected ETH/SOL
profiles are separately marked active. The Condor loop is configured for
continuous live controller operation, but installation does not configure a
model, migrate credentials, start Condor/the loop, or start a bot. Follow
[Hummingbot setup](../MAINNET_SETUP.md) first: the controller imports the shared
package, which must be in the pinned client.

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
   exists, use the backed-up authored-file upgrade in [the handoff](SYNC_HANDOFF.md);
   the fresh installer won't overwrite its identity or state.
   Never install over the generic `condor` agent.
3. Confirm `AgentStore().get("flyby")` discovers the identity and
   `StrategyStore().get_by_key("flyby.flyby_operator")` discovers the loop.
4. Select your accessible Hummingbot API server and configured model. From an
   attended Condor session, start that exact loop with only `server_name` and
   `agent_key` supplied. It is configured with `execution_mode: loop`,
   `max_ticks: 0` and `restart_on_boot: false`.
5. The running loop may deploy only `flyby-flyby_operator` from the exact active
   ETH/SOL profiles after its account, connector, stream and reconciliation
   gates pass. Otherwise it holds and reports the blocker. This installer only
   copies files; it never starts the loop, bot or trading session.

Use the [sync handoff](SYNC_HANDOFF.md) to override any saved dry-run/one-tick
runtime config and provide the team's account and prepared image. The loop
uses explicit config names to preserve controller IDs and a $200 deployment
loss cap accepted by Condor's permission gate.

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
ETH active sample now enables V3 atomic options; SOL active options stay disabled.
The selected lane allows up to two perps and two spreads without widening loss
or aggregate exposure limits. A separate paused
[atomic RFQ profile](../OPTIONS_EXECUTION.md) is an explicit execution extension,
not an automatic update to those samples. Portfolio margin and spot hedging
stay disabled. The loop operates the selected controller and journals its
plans/delta and decisions; order execution belongs to the controller.
The recurring loop checks authenticated account/exposure state before deploying
its owned bot. The controller then enforces margin, stream and risk checkpoint
checks before entry. No external service is started by this repository installer.

For recurring observation without trading, use the separate
[48-hour read-only procedure](OBSERVATION_RUN.md). It uses Condor's native loop
and the explicit observation launcher; it doesn't change the default playbook
or clear the live gates.

## Understand verification limits

`scripts/verify_condor_runtime.py` checks actual discovery, typed config, prompt
assembly, an explicit dry-run diagnostic and two live-mode controller ticks with
native session persistence in temporary roots. It mocks the API,
providers and model and refuses network connections. Run it with Condor's Python,
an explicit `--condor-root` checkout and a new `--output` JSON file. See the
[validation guide](../verification/VALIDATION.md).

Dry-run permission tests refuse exchange/running-bot actions; live-mode permission
tests accept the owned $200-capped deployment and reject a missing cap or foreign
bot. No deployment tool is executed. ACP providers also don't enforce the identity
tool allowlist as a sandbox. Tests don't prove real-model instruction compliance,
production authentication, private fills/restarts or positive net P&L.
