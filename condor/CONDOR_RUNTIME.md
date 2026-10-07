# Condor runtime boundary

Use the repository [Flyby agent package](flyby/AGENT.md) as the portable
identity/workflow. Configure the provider/model through Condor; don't copy
private deployment credentials into this repository.

The competition identity/controller are mainnet-only: `derive_perpetual`,
stock legacy v2 HTTP/WS endpoints. Controller validation rejects other
connector names and checks the runtime domain before emitting actions.
Follow [mainnet setup](../MAINNET_SETUP.md) with the team's account; don't
retarget an old testnet credential or loop to mainnet.

The deterministic decision path is imported directly by the V2 controller.
The explicit loop is `flyby.flyby_operator`, with continuous live defaults
(`execution_mode: loop`, `max_ticks: 0`), controller mode and no automatic restart.
[Install and verify it](INSTALL.md)
in the team's agent root; don't upload the flat Python policy as an agent.
The fixed contract is [PROFILE.yml](flyby/PROFILE.yml). Registry/tick checks
use isolated roots and mocked transports, not a deployed trading session.
The previously installed generic `condor` identity
and testnet controller copy are deployment state, not source-of-truth copies
of the corrected submission. This update did not replace that identity,
retarget the existing testnet loop, migrate credentials or restart services.
Those are not evidence of a deployed mainnet Flyby agent. Install/import the
portable package deliberately for the team's account. Its playbook can launch
only the selected ETH/SOL profiles after account and exposure checks; the
controller enforces margin, stream and checkpoint checks before placing orders.
See the [sync handoff](SYNC_HANDOFF.md), including saved configuration overrides.

The local API read-only snapshot showed no positions/orders and returned
rules for all four approved perpetual pairs. No strategy or orders were
started in this update. API/Condor upgrades are independent of the v2.17
client image pin.
