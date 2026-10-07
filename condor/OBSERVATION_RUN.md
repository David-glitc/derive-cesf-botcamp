# Prepare a 48-hour read-only Condor run

Use Condor's native `flyby.flyby_operator` loop with the separate observation
override. This run observes the controller; it doesn't trade, submit adjustments,
adopt bots or close positions. It is not the competition's live activation step.

## Prepare without starting anything

Run from the repository root with Python 3.11+ and PyYAML:

```bash
flyby_observation_review=$(mktemp -d)
python3 scripts/prepare_observation_profile.py \
  --output "$flyby_observation_review/profile" --market sol
# Expected: started=false, setup_complete=false, trading_paused=true.
```

The script creates `controller.yml` and `condor.yml` in a new directory. It refuses
existing or linked outputs. SOL is an example; select `eth`, `btc`, `sol` or `hype`
for the operator's actual universe. The controller keeps its original ID, budget,
risk namespace, signals and caps, adding only `runtime_oversight_mode: observe`.
It keeps `manual_kill_switch: true` and options execution disabled.

Supply `--server-name` and `--agent-key` when you know the configured API seat and
model name. `agent_key` means a model label, never an API credential. Preparation
doesn't verify provider connectivity or authorize model spending.

## Connect the observer

1. Install the shared package and [agent identity](INSTALL.md) in the reviewed
   Hummingbot and Condor environments.
2. Load the prepared paused controller through the operator's approved workflow.
3. Mount its private `data/flyby-runtime-<controller-id>/` directory for Condor;
   confirm that snapshots refresh and their controller/account binding matches.
4. Configure a real accessible API server and a tool-only PydanticAI model seat.
   Keep credentials in Condor's private configuration, not this repository.
5. Inspect the launcher interface before replacing your attended Condor startup:

   ```bash
   python3 -m src.runtime.condor_adapter --help
   # Expected: --observation-hours appears alongside the ownership arguments.
   ```

6. Select the explicit launcher with `--observation-hours 48`, your absolute
   `--condor-root` and private `--root`, matching `--controller-id` and
   `--account-binding`, and your authenticated `--operator-user-id`. Don't supply
   `--enable-controls`; the combination is rejected. This package must be
   installed in Condor's Python, including its runtime extra, or available through
   a persistent absolute `PYTHONPATH` inherited by subprocesses.
7. Start `flyby.flyby_operator` from an attended Condor session using its native
   `control_agent` lifecycle tool, action `start`, with the prepared `condor.yml`
   values as the config override. Verify the reported agent ID and owner. Don't
   substitute a stock launcher: without the extension, the read-only deadline
   and shutdown interception aren't installed.
8. Inspect the first real tick and its journal. Expect runtime context, three
   read-only tools and no adjustment tool. Missing state must be reported as
   `HOLD_UNVERIFIED`, not invented PnL, volume or flat inventory.

The checked-in [override template](profiles/flyby_observe_48h.yml) uses native
`execution_mode: loop`, `max_ticks: 0`, a 60-second sleep, a 30-second whole-tick
cancellation timeout and `restart_on_boot: false`. The default discovered loop
now defaults to continuous live controller operation. This read-only procedure
therefore requires its explicit observation override and launcher.

## Inspect completion and failures

Inspect Condor's native journal/session status for actual successful ticks,
errors, context age and the finish reason. Bot ownership isn't adopted, so
Condor's zero session-attributed bot return is not measured strategy performance.
Use the controller's explicit, source-labeled state for observed PnL/turnover;
unknown or unreconciled values remain unknown.

The elapsed-time window starts at the first selected operator tick, using a
monotonic clock. Condor sleeps after each tick: a 60-second setting isn't an exact
one-tick-per-minute schedule. The observer checks expiry at tick boundaries and
cancels an in-progress tick when its remaining time expires; idle sleep can add
up to one cadence before session completion. Cooperative cancellation and client
cleanup can add teardown latency; this is not an OS-enforced process kill.

At deadline, `observation_deadline` ends only the observer. An emergency Condor
risk alert records `observation_risk_alert` and stops only the observer. It doesn't
call Condor's deterministic exchange winddown. Hummingbot's own protection and
existing risk latches remain independent and unchanged.

Ordinary provider/tick errors are journaled and the native loop can retry at its
next cadence. Invalid setup or a regressed clock ends observation with
`observation_setup_or_clock_invalid`. A crash does not auto-restart; investigate
before an attended restart. Explicitly relaunching the observation process starts
a new window, so it is not continuous uptime evidence for the interrupted run.
Starting another loop session in the same process does not reset its deadline.

Read-only observation consumes no adjustment receipts. The 4,096-request limit
and 60-second leases still apply to the separate bounded-control mode; this
observer does not solve faster control-renewal capacity.

Don't claim 48 real hours of agent/provider/exchange uptime until the actual run
finishes. See the [verification evidence](../reports/OBSERVATION_LOOP_VERIFICATION.md)
and [live launch gates](../COMPETITION_READINESS.md).
