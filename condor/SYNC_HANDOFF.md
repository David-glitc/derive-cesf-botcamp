# Sync Flyby for Derive V3 live controller operation

This sync converts the old observer playbook into a continuous trading operator.
Installation starts nothing. The team chooses its account, model, server and
prepared image, then starts the loop. A successful source sync alone is not
trading evidence.

## Selected configuration

Use Hummingbot V2 controllers with Derive V3 authentication, signing and schemas.
Do not apply only a URL substitution. See [mainnet setup](../MAINNET_SETUP.md).

| Setting | Selected value |
|---|---|
| Controller source | `derive_cesf_long_vol` |
| Bot base name | `flyby-flyby_operator` |
| ETH controller/config ID | `flyby-eth-active-001` |
| SOL controller/config ID | `flyby-sol-active-001` |
| ETH options | `options_enabled: true`, `options_execution_mode: rfq_v3` |
| SOL options | `options_enabled: false` |
| Account-wide concurrency | `max_perp_positions: 2`, `max_option_spreads: 2` |
| Shared allocation/risk namespace | $800 / `flyby-competition` |
| Controller equity drawdown | −15% restricted; −25% hard-stop latch |

Each option position is a disjoint two-leg debit spread, entered and closed by
atomic RFQ. Four legs count as two spreads, not four executors. Fee, minimum-lot,
signal, liquidity and aggregate exposure gates can reject entries; limits are
ceilings, not trade targets.

The active ETH config governs its reviewed 40% perp / 75% option gross caps;
SOL retains its narrower caps. `PROFILE.yml` describes the four paused baseline
samples, not the selected launch settings. The old `flyby-eth-001`,
`flyby-sol-001`, `flyby-btc-001` and `flyby-hype-001` IDs are unselected
reference samples. Do not run them alongside the selected two or reset their
risk checkpoints. Inspect any old deployment before changing ownership.

## Upgrade an existing Flyby

Pause the Condor loop before changing authored instructions; preserve the
Hummingbot bot's position ownership and safety controls. Use the backed-up
upgrade, not the fresh installer. Replace these example paths with the team's
resolved writable agents root and a new backup path:

```bash
python3 scripts/check_condor_package.py
python3 scripts/upgrade_condor.py --agents-root /path/to/team-agents
python3 scripts/upgrade_condor.py --agents-root /path/to/team-agents --backup-dir /path/to/new-flyby-backup --apply
```

Check-only is the default. Apply changes only authored files supplied in
`condor/flyby/`: identity, profile, loop, controller and samples. It preserves
extra routines, saved runtime config, credentials and checkpoints. In particular,
it preserves `routines/flyby_hedge.py` and `routines/_flyby_derive.py`; this
controller loop does not invoke those independent routines. Never replace the
whole directory or install over the generic Condor agent.

Fresh installation uses `scripts/install_condor.py`, which refuses an existing
Flyby. Neither script starts services, registers MCP tools or modifies images.

For rollback, pause the Condor loop, preview, then explicitly apply:

```bash
python3 scripts/upgrade_condor.py --rollback /path/to/new-flyby-backup
python3 scripts/upgrade_condor.py --rollback /path/to/new-flyby-backup --apply
```

Rollback restores backed-up authored files and removes only hash-verified files
introduced by the upgrade. Later operator edits cause refusal. Runtime settings,
positions, credentials, checkpoints and connector images are not rolled back.

## Tools and optional runtime oversight

The selected profiles use `runtime_oversight_mode: off`. Start through stock
Condor's Hummingbot MCP server. Verify bot/controller management, agent-controller
sync, market/prices, portfolio and performance tools before starting.

The four `flyby_*` tools come from `src.runtime.mcp_server`, not stock Condor or
agent routines. Importing this folder does not register them. The default loop
does not require or call them. The optional adapter is an oversight-only seat:
it mutes deployment/config tools and requires the private bridge, compatible
Condor hooks and the package's `runtime` extra. Do not use it for this startup
sequence. See [runtime oversight](../RUNTIME_OVERSIGHT.md).

## Saved loop settings

An existing saved `config.yml` can retain observer settings after source sync.
Apply this override when starting `flyby.flyby_operator`, preserving the team's
server/model and adding its actual account/image to `trading_context`:

```json
{
  "execution_mode": "loop",
  "max_ticks": 0,
  "frequency_sec": 60,
  "tick_timeout_sec": 0,
  "bot_mode": "bot",
  "bot_name": "flyby-flyby_operator",
  "total_amount_quote": 800,
  "restart_on_boot": false,
  "risk_limits": {
    "max_position_size_quote": 320,
    "max_open_executors": 2,
    "max_leverage": 2,
    "max_drawdown_pct": -1,
    "shutdown_drawdown_pct": -1
  }
}
```

Zero timeout uses Condor's native runtime timeout; zero max ticks runs until
stopped. `restart_on_boot: false` intentionally requires attended recovery after
a reboot. It is not a 48-hour uptime guarantee. Percentage journal gates are
disabled because the controller owns its separate drawdown latches.
Do not select `flyby_observe_48h.yml`: observation produces no trading volume.

## Exact deployment envelope

Upload `eth_active` and `sol_active` using their exact config IDs above.
Describe the saved configs and compare them with the samples before deployment.
Do not silently overwrite mismatches or use generated IDs that change ownership.
If the same active IDs still contain the prior release's disabled options or
one-position settings, the team must back up and explicitly replace those saved
configs with the reviewed active samples (`upload_config`, same `config_name`,
`overwrite: true`). Don't change the IDs, allocation, risk namespace or caps.
The loop reports mismatches rather than guessing an overwrite. Already running
clients retain imported code: reconcile and reach a safely flat state before
an attended prepared-image replacement, preserving their `data/` volume.

After the team's mainnet/account/image and existing-exposure checks pass,
Hummingbot API `POST /bot-orchestration/deploy-v2-controllers` takes this body.
The account and image strings below are placeholders, not defaults:

```json
{
  "instance_name": "flyby-flyby_operator",
  "credentials_profile": "<team mainnet credentials profile>",
  "controllers_config": ["flyby-eth-active-001", "flyby-sol-active-001"],
  "image": "<team-reviewed prepared Flyby V3 image>",
  "max_global_drawdown_quote": 200,
  "max_controller_drawdown_quote": null
}
```

For `manage_bots`, add `action: deploy`, use `bot_name` instead of
`instance_name`, and `account_name` instead of `credentials_profile`.
Send both loss-cap fields explicitly; do not inherit fleet $80 values.
The global $200 platform cap is separate from controller equity latches and
does not replace full-account RFQ exposure supervision.

The API can append a timestamp to the instance name. Resolve the returned actual
instance; do not mistake it for a missing bot and redeploy. Confirm authenticated
portfolio state, streams, controller reasons and actual exchange fills after
launch. Source sync, signing and successful tool calls are not fill evidence.
