# Flyby: final Botcamp form draft

Reviewed 4 October 2026. Use the copy button on each block and paste it into the matching field. For dropdowns, select the value shown. These answers retain the field structure from your screenshots and describe the fixed baseline. Credit-spread and runtime-tuning research is not submitted as installed strategy behavior. This local draft has not been pushed or uploaded by this edit.

## Name

```text
Flyby: Risk-Gated Perpetuals & Atomic Option Spreads
```

## Strategy Type

Select this existing option:

```text
Agent - AI/autonomous trading agent
```

## Summary

```text
Flyby filters confirmed price/volume moves through cost, liquidity and account-risk checks before proposing Derive perpetual trades. A Condor agent oversees the Hummingbot V2 controller. Same-expiry debit spreads use a separately gated atomic RFQ lane. Profiles ship paused; live fills and profitability remain unverified.
```

## Detailed Description → Description

```markdown
### Overview

Flyby seeks net trading gains without increasing exposure to force competition volume. It buys confirmed upward moves or sells confirmed downward moves when execution costs, liquidity and account risk permit. The strategy is directional, not market-neutral volatility arbitrage.

A deterministic Hummingbot V2 controller owns signals, sizing and protective exits. A discoverable Condor package reads controller, market and portfolio context and journals its operating state. The agent does not place independent orders or override the risk governor. Its default loop is a one-tick observation run; a separate 48-hour observation configuration is available, but uninterrupted production endurance has not been demonstrated.

### Core logic

1. Read completed five-minute candles and calculate normalized momentum, directional efficiency, volume ratio and ATR-based volatility.
2. Require consecutive-bar direction, volume and efficiency confirmation. The confidence score is a heuristic, not a probability of profit.
3. Check fresh market/account data, reconciled exposure, available margin, existing orders, venue minimums and executable order-book depth.
4. Size within the risk and notional caps. Skip incompatible minimum orders or insufficient liquidity instead of increasing risk to force turnover.
5. Require the take-profit distance to cover the estimated round-trip costs by the policy's required multiple.
6. Open one Hummingbot position executor using a depth-aware marketable-limit entry. Manage it through volatility-adjusted stop-loss, take-profit and time-limit rules, plus signal/risk exits.

### Atomic options lane

For ETH/BTC, Flyby constructs bullish call debit spreads or bearish put debit spreads using two contracts with the same expiry. It checks executable quotes, fees, contract minimums and signed delta exposure. Bought/sold absolute-delta targets are approximately 0.50/0.25; eligible expiries are two to five days, preferably three.

The opt-in legacy v2 RFQ adapter signs one full spread transaction rather than placing two independent option orders. It persists each write intent before submission and requires a settled owned transaction plus exact authenticated positions before recording an entry or close. Lost acknowledgements trigger read-only reconciliation, not blind retries. Unmatched inventory blocks new entries and requires operator review.

Paired exits evaluate executable spread credit after fees, targeting +30% profit, −18% loss and a maximum six-hour hold. Signal, delta-cap, hard-stop or expiry conditions can request earlier exits. These are software triggers, not guaranteed fills. Offline tests reproduced a fee-cap rejection that leaves both legs awaiting reconciliation when required exit fees rise. Live options remain blocked until that recovery path and private-account execution are verified. Default samples remain shadow-only; separate ETH/BTC RFQ profiles install paused.

Credit spreads and a $5-after-costs trade target are offline research, not installed entry or exit rules. A larger premium or profit target is not evidence of repeatable profit. Receiving credit does not remove spread liability or increase the $800 allocation.

### Safety and activation

The fixed competition profile uses an $800 budget, one position at a time and persisted account-bound risk state. Drawdown from peak equity triggers restricted trading at −15% and a hard stop at −25%. Software limits and exit requests do not guarantee fills or cap realized losses during gaps or venue failures.

Samples ship paused. Mainnet private-account reconciliation, an authenticated production Condor operator/tool tick and endurance verification remain launch gates. Minimum-size orders that exceed approved caps are skipped. Offline tests do not establish profitability or uninterrupted competition runtime.
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
| Options | ETH/BTC same-expiry call/put debit spreads; separate opt-in atomic v2 RFQ profiles |
| Options activation | Paused and gated; mainnet fills unverified |
| Spot hedging and portfolio margin | Disabled |

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
| risk_policy | flyby-dd15-dd25-v1 | Account-bound risk contract |
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
| options_enabled | false in default samples; true in separate paused RFQ profiles | Explicit options execution selection, not activation |
| options_execution_mode | shadow by default; rfq_v2 in RFQ profiles | Atomic v2 execution requires both settings together |
| option_buy_moneyness | any | Permit eligible ATM, ITM or OTM bought legs |
| option_buy_delta_target | 0.50 | Advisory bought-leg absolute delta target |
| option_sell_delta_target | 0.25 | Advisory sold-leg absolute delta target |
| portfolio_margin / spot_hedge_enabled | false / false | Unsupported live execution paths |

### Fixed policy rules

- One position at a time; account orders, positions and reservations restrict further entries.
- Normal gross exposure cap: 30% of budget-limited equity, or $240 at $800.
- Normal signal floors: volume ratio 1.20, absolute trend score 0.90, efficiency 0.30 and heuristic confidence 0.70, with consecutive-bar confirmation.
- At −15% peak drawdown: restricted mode latches, capacity decreases, and entry floors rise to volume 1.50, absolute trend 1.50, efficiency 0.45 and confidence 0.85.
- At −25% peak drawdown: the hard stop latches, new entries stop and protective exits are requested. Restarting does not reset it.
- The profit target must cover at least 3× estimated round-trip costs in normal mode or 4× in restricted mode. This is a cost gate, not proof of positive expected return.
- Baseline perp stop distance is ATR/score-adjusted within 0.3%–1.5%; take-profit distance and holding limit are computed per entry. Do not use the legacy 48%/55% stop examples.
- Options rules: two-to-five-day expiry, preferred three days, minimum theoretical expiry reward/risk 1.5, +30%/−18% net executable-value exit triggers and a six-hour maximum hold. Paired exits require quotes, margin and confirmed settlement; none guarantees a fill.

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
| risk mode: restricted | Persisted −15% drawdown restriction |
| risk mode: hard_stop | Persisted −25% trigger; no new entries |
| entry_block | Venue minimum, cost, depth, account or other proposal-level rejection |
| options shadow context | Advisory spread availability, validity and delta exposure; live_options remains false |
| options_execution in RFQ profiles | Atomic lifecycle phase, submission count, settled paired P&L and fees; mainnet verification remains false |

### Reported metrics

The allowlisted controller context reports controller/pair identity, pause state, decision time, signal, confidence, decision reason and entry-block reason. Feature context includes price, trend score, efficiency, volume ratio, ATR, forecast/realized volatility and CESF diagnostics.

Risk context includes equity, available funds, committed exposure, P&L percentages, peak drawdown, risk mode, remaining loss buffer, risk scale, trade-risk budget, venue minimum notional and computed stop/profit/time-limit values. Position/order summaries and executor metrics include active state, net P&L, cumulative fees and filled quote amount when available.

Native context distinguishes fresh, stale, unavailable and invalid data. Default options context remains advisory. RFQ profiles additionally report execution phase, submitted requests and reconciled spread closes without labeling offline fixtures as mainnet fills. Missing or unverified fields are not evidence of a reconciled account or profitable strategy.

### Validation and remaining gates

The 4 October offline assurance pass recorded 3,087 passing tests in the pinned Hummingbot image, with three skipped and one long virtual-ingestion test deselected. Ten Condor/MCP interface tests passed with fixture transports. These checks do not prove exchange fills or a real 48-hour run.

In the fixed 29 September to 1 October 2026 replay, each case started independently at $800. The base perpetual case closed one trade for approximately +$0.68 net and $320.82 turnover; the cost-stress case closed one for approximately −$0.86. Options executed zero trades at baseline caps. The replay uses proxy underlying/IV history and modeled fills, not a native historical option-chain backtest.

A separate offline sensitivity tested four take-profit multipliers from 1× to 2× on that same window. P&L and turnover were unchanged because signal invalidation closed each trade before its target. The archived OTM credit-spread screen found no positive-reward structure inside its $4 modeled loss budget, even under the published RFQ-discount sensitivity. Neither test establishes a repeatable $5 net trade or changes the baseline.

The larger-exposure options fixture audit is separate research: ten of twelve scripted lifecycle cases closed both legs; two exit-fee-rise cases retained unresolved paired inventory. That profile is not promoted. Credit-spread research does not replace the submitted debit planner, gross caps or fee model. Production activation remains gated; profitable high-turnover trading is unproven.
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
| Peak drawdown reaches −15% | Persist restricted mode and tighten entry requirements/capacity |
| Peak drawdown reaches −25% | Persist hard stop, block new entries and request protective exits |
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
| Opt-in RFQ profile receives a fresh full matching quote within all bounds | Persist execution intent, validate native contracts/hash, sign one spread transaction |
| RFQ execution settles | Require matching owned transaction, exact authenticated positions and bounded actual fees before recording entry/exit |
| RFQ request acknowledgement is lost | Discover/reconcile read-only; never blindly resend the write |
| RFQ-owned spread hits profit/loss/time/signal/delta/risk/expiry exit | Request and execute both reversed legs as one bounded RFQ; no independent short-option repair |

Partial fills and residual positions require explicit reconciliation. Offline recovery candidates are not installed production recovery, and a stopped executor does not establish that the account is flat.
```

## Flowchart & Images

This is an upload control, not a text field. Your screenshot already shows `flyby_architecture_full_detail.png`. Keep it only if it matches the current perp-execution/opt-in-atomic-RFQ design; the thumbnail isn't sufficient to verify its full contents. No replacement image is part of this text update.

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
