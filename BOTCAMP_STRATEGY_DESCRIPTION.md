# Flyby — Botcamp form answers

Use the copy button on each block and paste it into the matching field. For dropdowns, select the value shown. These answers match the form in your screenshots and Botcamp's five-section editor. They describe the baseline, not the unpromoted optimization candidates.

## Name

```text
Flyby — Risk-Gated Perpetuals & Options Research
```

## Strategy Type

Select this existing option:

```text
Agent - AI/autonomous trading agent
```

## Summary

```text
Flyby is a Condor operator-agent package with a Hummingbot V2 Derive perpetual controller that trades confirmed price/volume moves under depth, cost and drawdown constraints. Its separate options research lane builds delta-aware call/put debit-spread plans without executing live option orders.
```

## Detailed Description → Description

```markdown
### Overview

Flyby combines a deterministic Hummingbot V2 perpetual controller with a discoverable Condor operator-agent package. The executable strategy is directional: it buys confirmed upward moves or sells confirmed downward moves when execution costs and account risk permit. It is not market-neutral volatility arbitrage, and a perpetual position is not treated as a synthetic option.

### Core logic

1. Read completed five-minute candles and calculate normalized momentum, directional efficiency, volume ratio and ATR-based volatility.
2. Require consecutive-bar direction, volume and efficiency confirmation. The confidence score is a heuristic, not a probability of profit.
3. Check fresh market/account data, reconciled exposure, available margin, existing orders, venue minimums and executable order-book depth.
4. Size within the risk and notional caps. Skip incompatible minimum orders or insufficient liquidity instead of increasing risk to force turnover.
5. Require the take-profit distance to cover the estimated round-trip costs by the policy's required multiple.
6. Open one Hummingbot position executor using a depth-aware marketable-limit entry. Manage it through volatility-adjusted stop-loss, take-profit and time-limit rules, plus signal/risk exits.

### Options research

For ETH/BTC, the advisory lane can construct bullish call debit spreads or bearish put debit spreads using two contracts with the same expiry. It checks executable quotes, fees, contract minimums and signed delta exposure. Bought/sold absolute-delta targets are approximately 0.50/0.25; eligible expiries are two to five days, preferably three.

Paper exits use net executable spread value, targeting +30% profit, −18% loss and a maximum six-hour hold, with earlier signal/expiry exits. These are planning rules, not live protective orders. There is no live paired-leg options adapter; the controller rejects live options enablement. A completed debit spread has bounded payoff risk, but incomplete leg fills can create unintended exposure.

### Safety and activation

The fixed competition profile uses an $800 budget, one position at a time and persisted account-bound risk state. Drawdown from peak equity triggers restricted trading at −10% and a hard stop at −15%. Software limits and exit requests do not guarantee fills or cap realized losses during gaps or venue failures.

Samples ship paused. Mainnet private-account reconciliation, a real Condor operator/tool tick and production endurance verification remain launch gates. Offline tests do not establish profitability or uninterrupted competition runtime.
```

## Detailed Description → Markets

```markdown
### Venue and instruments

| Item | Current scope |
|---|---|
| Execution venue | Derive mainnet through Hummingbot's legacy v2 perpetual connector |
| Primary perp profiles | ETH-USDC and BTC-USDC |
| Operator-selected fallback profiles | SOL-USDC and HYPE-USDC |
| Default signal data | Matching Binance perpetual proxy candles: ETH-USDT, BTC-USDT, SOL-USDT or HYPE-USDT, on five-minute completed bars |
| Native data | Explicit opt-in Derive native context; not the sample default |
| Options research | ETH/BTC same-expiry call or put debit-spread plans only |
| Live options, spot hedging and portfolio margin | Disabled |

The organizer/operator chooses the permitted account universe and enabled market. Reviewed venue-minimum checks excluded ETH/BTC at the existing sizing caps. Any minimum order that exceeds those caps is skipped; SOL/HYPE are fallbacks only if their current listing, liquidity, candles and account permissions permit.

### Viable market conditions

Trade only when consecutive bars confirm the same direction, volume and directional efficiency clear the signal thresholds, and ATR-based volatility is within the policy's allowed range. Derive book/private-stream data must be fresh, account exposure reconciled, and sufficient executable depth and margin available.

The default proxy price must remain within the configured basis tolerance of Derive's execution price. Expected exit distance must cover modeled fees and slippage. Stale, crossed, illiquid, unconfirmed or uneconomic conditions produce no new entry.

The strategy does not require a fixed mixed-collateral allocation or claim automatic cross-asset hedging.
```

## Detailed Description → Parameters

```markdown
### Operator configuration

| Parameter | Baseline value | Purpose |
|---|---|---|
| id | Stable per-controller identifier | Controller identity and bounded reporting |
| controller_name | derive_cesf_long_vol | Historical import name for the canonical Flyby controller |
| connector_name | derive_perpetual | Derive mainnet execution; testnet/paper overrides rejected |
| trading_pair | ETH-USDC, BTC-USDC, SOL-USDC or HYPE-USDC | Operator-selected permitted market |
| candles_connector | binance_perpetual | Default proxy candle source |
| candles_trading_pair | Matching underlying-USDT pair | Keep proxy and execution underlying aligned |
| signal_source | binance_proxy | Default; derive_native requires explicit native-data preparation |
| interval | 5m | Completed-bar interval |
| vol_lookback | 100 | Feature/volatility history |
| total_amount_quote | 800 | Budget cap in quote currency |
| position_mode | ONEWAY | Supported position mode |
| leverage | 2 | Executor configuration; not proof that venue leverage is applied |
| cooldown_time | 300 seconds | Minimum entry cooldown; signals are also persisted against reuse |
| strategy_profile | baseline | Fixed competition behavior; research candidates are not promoted |
| risk_policy | flyby-dd10-dd15-v1 | Account-bound risk contract |
| risk_state_id | flyby-competition | Shared persisted state across selected profiles |
| risk_fraction | 0.005 | Normal risk fraction, before score weighting and other constraints |
| max_notional_fraction | 0.20 | Normal entry notional cap: $160 at $800 equity |
| max_slippage | 0.0015 | 0.15% entry-depth bound and modeled exit slippage reserve |
| estimated_fee_per_side | 0.0006 | Conservative configured fee estimate; runtime checks venue fee metadata |
| max_basis | 0.03 | Maximum 3% proxy/execution price deviation |
| max_book_age | 30 seconds | Execution-book freshness bound |
| max_user_stream_age | 60 seconds | Private-stream freshness bound |
| manual_kill_switch | true in shipped samples | Keep launch paused until operator verification |
| condor_active | false | Baseline policy mode; not proof of an authenticated Condor loop |
| options_signal_enabled | true | Allow advisory spread planning when inputs qualify |
| options_enabled | false | Live options execution is unsupported |
| option_buy_moneyness | any | Permit eligible ATM, ITM or OTM bought legs |
| option_buy_delta_target | 0.50 | Advisory bought-leg absolute delta target |
| option_sell_delta_target | 0.25 | Advisory sold-leg absolute delta target |
| portfolio_margin / spot_hedge_enabled | false / false | Unsupported live execution paths |

### Fixed policy rules

- One position at a time; account orders, positions and reservations restrict further entries.
- Normal gross exposure cap: 30% of budget-limited equity, or $240 at $800.
- Normal signal floors: volume ratio 1.20, absolute trend score 0.90, efficiency 0.30 and heuristic confidence 0.70, with consecutive-bar confirmation.
- At −10% peak drawdown: restricted mode latches, capacity decreases, and entry floors rise to volume 1.50, absolute trend 1.50, efficiency 0.45 and confidence 0.85.
- At −15% peak drawdown: the hard stop latches, new entries stop and protective exits are requested. Restarting does not reset it.
- The profit target must cover at least 3× estimated round-trip costs in normal mode or 4× in restricted mode. This is a cost gate, not proof of positive expected return.
- Baseline perp stop distance is ATR/score-adjusted within 0.3%–1.5%; take-profit distance and holding limit are computed per entry. Do not use the legacy 48%/55% stop examples.
- Options research rules: two-to-five-day expiry, preferred three days, minimum theoretical expiry reward/risk 1.5, +30%/−18% paper barriers and a six-hour maximum hold. These are planner rules, not live order settings.

Changing risk caps or policy behavior requires review. Drawdown thresholds trigger actions; they are not guaranteed loss ceilings.
```

## Detailed Description → Status

```markdown
### Operational state

| Reported condition | Meaning |
|---|---|
| paused | The manual kill switch blocks entry and requests stops for active executors |
| signal = 0 | No qualifying directional entry; inspect the decision reason |
| signal = +1 / −1 | Long / short directional decision, still subject to execution gates |
| halt = true | Invalid/stale data, account/risk failure or hard-stop condition |
| risk mode: normal | Baseline risk and entry thresholds |
| risk mode: restricted | Persisted −10% drawdown restriction |
| risk mode: hard_stop | Persisted −15% trigger; no new entries |
| entry_block | Venue minimum, cost, depth, account or other proposal-level rejection |
| options shadow context | Advisory spread availability, validity and delta exposure; live_options remains false |

### Reported metrics

The allowlisted controller context reports controller/pair identity, pause state, decision time, signal, confidence, decision reason and entry-block reason. Feature context includes price, trend score, efficiency, volume ratio, ATR, forecast/realized volatility and CESF diagnostics.

Risk context includes equity, available funds, committed exposure, P&L percentages, peak drawdown, risk mode, remaining loss buffer, risk scale, trade-risk budget, venue minimum notional and computed stop/profit/time-limit values. Position/order summaries and executor metrics include active state, net P&L, cumulative fees and filled quote amount when available.

Native context distinguishes fresh, stale, unavailable and invalid data. Options context reports shadow plan/delta information, not live premium fills. Missing or unverified fields are not evidence of a reconciled account, profitable strategy or successful options execution.
```

## Detailed Description → Events

```markdown
### Market and account conditions

These are descriptions of controller behavior, not claims that separate named exchange events or notifications are implemented.

| Condition | Response |
|---|---|
| Completed-bar direction, volume and efficiency confirm | Form a directional decision; continue account, sizing, depth and cost checks |
| Signal fails or reverses while a baseline position is trading | Request the position executor to stop |
| Candle gap, stale stream/book, crossed book or excessive proxy basis | Reject new entry; halt conditions request stops for active executors |
| Unknown/unreconciled exposure, unavailable risk state or margin failure | Block entry; applicable halt conditions request protective exits |
| Minimum lot exceeds risk/notional cap or executable depth is insufficient | Skip the entry; do not enlarge the approved budget |
| Estimated round-trip costs fail the target-distance gate | Skip the entry |
| Peak drawdown reaches −10% | Persist restricted mode and tighten entry requirements/capacity |
| Peak drawdown reaches −15% | Persist hard stop, block new entries and request protective exits |
| Manual kill switch is enabled | Block entry and request stops for active executors |

### Execution and research conditions

| Condition | Response |
|---|---|
| Entry proposal clears all gates | Persist consumed signal/cooldown state, reserve capacity and propose one position executor |
| Entry remains non-trading for at least 30 seconds | Request the executor to stop |
| Executor stop-loss, take-profit or time-limit condition occurs | Follow configured Hummingbot exit handling; fill success still requires venue confirmation |
| Process restarts | Load account-bound risk state; don't automatically reset restrictions or reopen |
| Fresh eligible ETH/BTC chain and qualifying options signal | Build an advisory same-expiry debit-spread plan |
| Option quotes, delta/fee metadata, account checks or spread eligibility fail | Clear/reject the advisory plan |
| Paper spread reaches profit/loss/time/signal/expiry exit condition | Record a paper exit decision; do not submit live option orders |

Partial fills and residual positions require explicit reconciliation. Offline recovery candidates are not installed production recovery, and a stopped executor does not establish that the account is flat.
```

## Flowchart & Images

This is an upload control, not a text field. Your screenshot already shows `flyby_architecture_full_detail.png`. Keep it only if it matches the current perp-execution/options-shadow design; the thumbnail isn't sufficient to verify its full contents. No replacement image is part of this text update.

## Code Files → Add Link

Your screenshot already contains this repository link. Keep it; no new link is needed if it remains present. If the link dialog asks for a name and URL, use these blocks.

### Link name

```text
derive-cesf-botcamp (flyby)
```

### Link URL

```text
https://github.com/David-glitc/derive-cesf-botcamp
```

## Video Link

Keep the existing value shown in your screenshot. This preserves your current video; it does not certify that the recording reflects every recent code change.

```text
https://www.youtube.com/watch?v=o1wdweQhCIU
```

## Tags

Select this tag and remove the existing Arbitrage tag:

```text
Directional
```

## Exchanges

Keep this existing selection:

```text
derive
```

## Visibility

If the visibility selector is shown, keep:

```text
Public
```

## Save

Replace each text box with its matching block, keep/select the controls above, then use Save. This document doesn't sign you in, edit Botcamp, activate trading or submit a new code release.
