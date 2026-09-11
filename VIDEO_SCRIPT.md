# Flyby — Video Script (90s, Derive)

**[0-10 Hook]**
I'm David — Flyby. We buy cheap vol, but only when downside is real. Perps +1.73% avg, +4.23% ARB in 60 days, DD -0.8%. Same signal on Derive options +159% avg, +439% AVAX — $10 premium controls $3k, that's the convexity.

**[10-30 Why Derive — 4 bonuses, show table]**
Flyby hits all four. Spot+perp — derive ETH-PERP on api.lyra.finance spot_feed + orderbook. Options via Condor — SVI w(k) to 25Δ wings into Black76 7-day puts alongside perps. Multi-collateral — USDC 40, ETH 30, BTC 15, HYPE 10, kHYPE 5 with haircuts, not just USDC. Portfolio margin — net delta/vega/gamma, 60% less margin than isolated — impossible elsewhere. All wired.

**[30-55 How it works — show flowchart + WFA]**
Three layers. SVI extracts IV and skew. HAR+EWMA forecasts vol and uncertainty. Edge plus a CESF-inspired filter — we compress infinite futures into the few distinguishable ones before we price, so the surface is smoother and we only pay when downside is tradeable. Kelly sizes it, Guard caps it. Walk-forward 60/40 IS 13% to OOS 20% — not overfit, and 90/120-day unseen still +2% perps, +200% options.

**[55-75 Why it wins 48h]**
Slow 1h candles, 0.68 trades/day — P&L plus volume without churn. ACTIVE Condor adds strangle when vol expands for extra volume, Guard holds DD. Four agents ETH/ARB/SOL/AVAX diversify.

**[75-85 CESF side note — 10s, humble]**
Side note — CESF is my Causal Event Space Framework. Flyby borrows the idea: don't price on noise, price on the compressed, relevant space.

**[85-90 Close + CTA]**
Flyby — code at github.com/David-glitc/flyby, one flyby.py controller, start --v2 conf_v2_flyby. Ready for finals.
