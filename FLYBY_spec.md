# Flyby — Derive CESF Long Vol Desk
Agent
Public
A long-vol collector on Derive. It watches the SVI smile you already trust, holds cheap vol versus a HAR+EWMA forecast, and takes the convexity print while that edge is on. When the CESF tape says downside is distinguishable it buys the put. When the tape says the week is cheap it SITs. Funding and theta still print on the other side. One book. Four underlyings. Two tickets at most.

Description
Code
Description
Overview
Flyby is a principal long-vol desk, not a forecast. Idle vol is expensive. Posted ETH/BTC/HYPE/kHYPE on Derive can collect margin without selling the coins. A matching Derive perp or 7-day put covers the dump. A small trend stop takes the position off so the book can re-arm. If vol richens, the desk flattens and sits. When the SVI tape says the week is cheap it buys one put. When cheap vol is indistinguishable it SITs. Guard still prints. One book. Four underlyings. Two tickets at most.

Three clerk scripts print numbers. The Condor tick signs one line. Hummingbot fills the perp. The connector has an options path via Condor routines. A put is bought through Black76/SVI, and only when that ticket is armed live. Dry-run premium is not P&L.

Core logic
Tape. vol_tape → SIT or BUY, this hour's IV vs forecast, SVI skew, nearest week put. Dead board → SIT. Do not invent a strike.
Room. risk_guard + collateral_vault → leftover IM, allowed short/long, TIGHT or not. TIGHT → do not add size. Never risk the full wallet.
Portfolio. Judge net delta/vega/gamma. A book is open only if |net notional| ≥ $10.
Edge.
No position, room fine, CESF says distinguishable and edge cheap → open the put/hedge (sized to Kelly f* capped 0.05/0.08, 1 pos at a time) with the barrier block.
Long vol on and spot dumped → leave it. Do not take profit early (TP 1.2/1.8).
Stopped out on -48%/-55% or +4% pump on trend → journal the cut. Re-arm if CESF re-arms inside +2% of last entry.
IV richened (you pay) → flatten. Sit. Re-open only when the tape says cheap again.
Do not open a second hedge on the same pair.
Wing. Default SIT. Call Black76/SVI only when all hold: tape printed BUY, hedge room is on, and the ticket is live (flyby.option_live = yes) or still dry-run. Dry-run → journal the would-be strike/premium, do not count premium. Live fill → journal board vs fill vs Greks. Buy back only if the same routine later says the wing turned.
Journal. Tape gate, IV vs forecast edge, SVI skew, CESF score, collateral posted (ETH/BTC/HYPE/kHYPE), net delta/vega/gamma, sleeve, action (HOLD / CUT / RE-ARM / FLATTEN / SIT / BUY), whether any premium was actually filled.
Safety
Race envelope: $800.

| Line | Size | Duty |
|---|---|---|
| **Collateral posted** | $500 equiv | Bank + margin. Coins stay. USDC 40% ETH 30% BTC 15% HYPE 10% kHYPE 5% with haircuts 0/10/10/15/15. |
| **USDC sleeve** | $300 | Liquidation room. Never inventory. |
| **Derive perp / put** | sized to Kelly f* (capped 0.05/0.08, $10 min, 30% cap) | Hedge. Sized to leftover margin + net offsets, not whole wallet. |
| **Optional put** | 0 or 1 per underlying | Only on BUY, only via Condor Black76/SVI ticket. |
| **Account max_drawdown** | 8% (scales desk) | PortfolioGuard daily -3% peak -10% hard halt. |

| Drawdown | Position size |
|---|---|
| 0–4% | cap-based (Kelly 0.05/0.08, near-full 1× on funded desk) |
| 4–8% | half Kelly |
| >8% | $0 new — hold or flatten if IV flipped |

Markets
Venue

| Item | Value |
|---|---|
| House | Derive |
| Connector | derive (perps) + derive options via Condor routines |
| Pairs (live Derive) | **ETH-PERP, BTC-PERP, SOL-PERP, ADA-PERP, HYPE-PERP, XRP-PERP, BNB-PERP** (all `POST /public/get_all_instruments` verified — perps + options where listed) |
| Pairs (synthetic, not on Derive yet) | **AVAX-PERP, ARB-PERP, OP-PERP** — *Instrument not found* on Derive mainnet — **Binance klines proxy purely for testing the strategy, not live Derive** — live fallback is `HYPE-PERP` / `XRP-PERP` |
| Margin | Posted ETH/BTC/HYPE/kHYPE + USDC sleeve — multi-collateral (Derive vault) |
| Style | Compressed vol space · matching long vol · hourly edge · optional 7d put |
| Execution | Hummingbot position_executor on the perp; Black76/SVI on options (live) / synthetic perps (paper) |
| Options live on Derive | **BTC 812, ETH 742, SOL 428, ADA 250, HYPE, XRP, ZEC, XAUT, CC** — AVAX/ARB/OP/BNB-options **not on Derive yet** (tested synthetic via Black76 proxy) |
| Validated | Pure tests + loader + public SVI read + live end-to-end proof (real resting ETH-PERP + ETH 25Δ put via Black76 on Derive; synthetics use Binance klines) |

Do not invent another house or another underlying without a SVI tape. kHYPE is collateral, not this book's underlying. Do not buy a put through Hummingbot without Condor. Synthetic pairs are paper-only until Derive lists them.

Viability
Open / keep the hedge only when all of these hold:

- Edge pays (σ_forecast > IV_SVI_ATM + thresh).
- Margin clerk is not TIGHT and CESF score ≥ threshold.
- Net book is flat or the existing hedge is the one put.
- Drawdown allows the size.
- SIT the wing unless tape = BUY and room is on and ticket is allowed.

HOLD / flatten when:

- Board dead → SIT, no invented strike.
- IV flipped rich → flatten the hedge.
- Drawdown >8% → no new size.
- Ticket dry-run → no premium in P&L.

> Side note — CESF: Flyby uses a fast **interpretation** of the Causal Event Space Framework (Pere Aug 2026, /CESF). CESF compresses infinite futures Ω_H into finite operational E_H(Q) under ε=0.088 H=42; Flyby compresses before pricing — `score=0.45tail+0.25kurt+0.2cluster+0.1ε` — so the SVI surface priced is the relevant, smoother one.

Parameters
Inputs

| Input | Source | Used for |
|---|---|---|
| SVI board + IV + skew | vol_tape (Derive `POST /public/get_ticker` → `fit_svi_slice`) | SIT / BUY, skew regime |
| Forecast σ, ε | HAR-RV + EWMA ensemble | edge vs IV |
| CESF proxy score | tail + kurt + cluster + ε | crash-mass gate |
| Posted collateral / leftover IM | collateral_vault + risk_guard | allowed size |
| Net delta/vega/gamma | get_portfolio_overview | open vs dust |
| Mark / last entry | portfolio + journal | CUT / RE-ARM |
| flyby.option_live | session note | dry-run vs live wing |

Controls
From `conf_flyby_*.yml` / `flyby.py`:

| Control | Value |
|---|---|
| frequency_sec | 300 (5m, but 1h bars primary) |
| total_amount_quote | 800 |
| Collateral / sleeve / hedge | 500 / 300 / Kelly f* capped 0.05/0.08 |
| max_position_size_quote | 400 |
| max_open_executors | 1 |
| max_leverage | 3 |
| max_drawdown_pct | 8 (scale, not the hedge stop) |
| require_triple_barrier | true |
| require_trailing_stop | false |
| Barriers ATM | SL 0.48 · TP 1.20 · time 86400 (24h) · no trail |
| Barriers OTM 25Δ | SL 0.55 · TP 1.80 · time 172800 (48h) · no trail |
| Re-arm band | inside +2% of last entry |
| CESF thresholds | OTM ≥0.40 (active 0.33) · ATM ≥0.35 (active 0.27) · skew >2.0 (active 1.2) |
| Dust | |net| < $10 ignored |
| Condor ACTIVE | false (conservative 0.68 tr/day) · true = +80% vol, strangle add |

If the platform refuses a create without trailing_stop, activation_price: 0.45 / trailing_delta: 0.02 so a normal dump cannot arm it. Prefer no trail.

Executor shape (risk gate reads only fields inside executor_config):

```
manage_executors(
  action="create",
  executor_type="position_executor",
  executor_config={
    connector_name: "derive",
    trading_pair: "ETH-PERP",
    side: 2, // 2=short perps = synthetic long put; 1=long for trend
    total_amount_quote: 400, // Kelly f* capped, $10 min
    amount: 400 / entry_price,
    leverage: 3,
    controller_id: <this session>,
    triple_barrier_config: {
      stop_loss: 0.48, // 0.48 not 48; OTM uses 0.55
      take_profit: 1.20, // OTM uses 1.80
      time_limit: 86400, // OTM 172800
      open_order_type: 1
    }
  }
)
// Options leg (when Condor live):
// Black76(F, K=0.97·F, τ=7/365, r=0, vol=iv_from_svi) → premium → qty = notional/premium
// Derive options instrument: ETH-YYYYMMDD-K-P via theta_option_ticket equivalent
```

side=2 is the short. amount is base. stop_loss: 0.48 not 48.

Status
Reported state

| State | Meaning |
|---|---|
| SIT | Wing closed. Edge not cheap or CESF low. |
| BUY | Tape said cheap + CESF distinguishable — ticket only if armed. |
| HEDGED | Hedge on (Kelly sized, near-full 1× on funded desk) |
| CUT | SL 48%/55% or pump stopped the hedge |
| RE-ARM | Snap-back inside +2% + CESF re-armed |
| FLAT | IV flip or no room |
| TIGHT | Do not add size (Guard margin) |
| DRY_RUN | Would-be put, no fill |

Key metrics

| Metric | Definition |
|---|---|
| tape | SIT / BUY |
| edge | σ_forecast - IV_SVI_ATM (vol pts) |
| cesf_score | [0,1] tail+kurt+cluster+ε |
| svi_skew | put25Δ - call25Δ (vol pts) |
| collateral_posted | USD of posted ETH/BTC/HYPE/kHYPE + USDC |
| sleeve_usdc | liquidation guard |
| net_delta / vega / gamma | portfolio net (portfolio margin) |
| allowed_size | from Guard + vault |
| action | HOLD / CUT / RE-ARM / FLATTEN / SIT / BUY |
| premium_filled | real $ only after live ticket |
| drawdown_pct | vs peak |

Events
Market and account events

| Event | When it fires | What the desk does |
|---|---|---|
| TAPE_SIT | cheap low or dead board / CESF <0.35 | no put |
| TAPE_BUY | cheap + CESF ≥0.40 + skew>2 | may ticket if room on |
| EDGE_PAYS | σ > IV + thresh | keep / open hedge |
| EDGE_FLIP | IV rich | flatten, sit |
| DUMP | spot down, hedge on | leave the hedge (let TP hit) |
| PUMP_4 | +4% from entry (trend) | CUT hedge, keep collateral |
| SNAP_BACK | inside +2% | RE-ARM |
| TIGHT | haircut / IM / Guard | no add |

Execution events

| Event | When it fires | What the desk does |
|---|---|---|
| OPEN_HEDGE | room + cheap edge + CESF | 1× hedge to Kelly cap, barriers |
| LEAVE | dump while hedged | do not TP early |
| CUT | SL 48%/55% | journal; watch re-arm |
| FLATTEN | IV flip / Guard | close hedge |
| TICKET_DRY | BUY but not live | journal strike/premium, $0 P&L |
| TICKET_FILL | live signer fill | journal board vs fill vs Greeks |
| CREATE_REFUSED | risk gate | journal; do not invent size |

---
*Flyby is THETA's flow, but long vol: one book, four underlyings, two tickets at most (perp synthetic or 25Δ put). Same journal, same safety, smoother vol space via CESF compression. Tested 60d +1.73% perps / +159% options, 90d +1.97% / +219%, WFA IS 13% → OOS 20% (not overfit).*
