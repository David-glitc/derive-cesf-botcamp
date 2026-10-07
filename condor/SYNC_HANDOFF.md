# Sync Flyby and run the selected controller loop

Sync the latest `master` and import the complete `condor/flyby/` folder as agent
`flyby`. It contains the controller source, continuous loop and two active sample
configs. Install the shared `agents`/`src` package into the team's Hummingbot API
and prepared bot image before controller sync; a source-only sync cannot install
those dependencies. Installation/source sync does not start a service.

Keep the team's authenticated API server, configured model, credential account
and prepared Hummingbot image. Supply `account_name` and `image` in the session's
`trading_context`; these must identify the actual account and prepared image.
The bot is `flyby-flyby_operator`; the only selected config/controller IDs are
`flyby-eth-active-001` and `flyby-sol-active-001`.

An existing loop's saved `config.yml` can override the newly synced defaults.
When the team starts `flyby.flyby_operator` through `control_agent`, explicitly
apply these values as the config override, retaining its existing server/model
binding and including the account/image in `trading_context`:

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
    "max_open_executors": 1,
    "max_leverage": 2,
    "max_drawdown_pct": -1,
    "shutdown_drawdown_pct": -1
  }
}
```

`max_ticks: 0` runs continuously until stopped; `tick_timeout_sec: 0` uses
Condor's runtime timeout. Percentage journal gates are disabled because the
controller owns the −15% restricted and −25% hard-stop latches. Its deployment
also declares a $200 absolute global loss cap. Source sync does not replace the
class already imported by a running bot; do not restart one with open exposure.

The playbook specifies `status → sync → upload_config → describe → deploy` for
the selected bot. `upload_config` uses the explicit config names above to
preserve checkpoint ownership. It does not substitute hedge routines or create
standalone executors. Confirm actual bot/controller state and exchange fills
after launch; a successful source sync alone is not trading evidence.
