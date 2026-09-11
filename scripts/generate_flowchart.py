#!/usr/bin/env python3
"""Flyby — creative flowchart. Aviation / night-flight theme.
Single palette, contrail path, glass cards, no rainbow.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.patheffects as pe

# — palette — //
BG = "#050A18"         # deep night
GRID = "#0F1A33"
CARD = "#0F172A"
BORDER = "#1E2A44"
TEXT = "#E2E8F0"
MUTED = "#7C8DB0"
CYAN = "#22D3EE"        # data / sky
VIOLET = "#8B7CF8"      # logic
EMERALD = "#34D399"     # risk / guard
AMBER = "#F59E0B"       # execution / landing
FAINT = "#1E293B"

fig, ax = plt.subplots(figsize=(16, 10.5))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 16)
ax.set_ylim(0, 10.8)
ax.axis("off")

# faint grid
for x in range(0, 17, 2):
    ax.plot([x, x], [0, 10.8], color=GRID, lw=0.6, alpha=0.6)
for y in range(0, 11, 1):
    ax.plot([0, 16], [y, y], color=GRID, lw=0.6, alpha=0.35)

def glass_card(x, y, w, h, accent, title, body, icon=""):
    # glow
    glow = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.12,rounding_size=0.18", facecolor=accent, alpha=0.07, edgecolor="none")
    ax.add_patch(glow)
    # card
    rect = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08,rounding_size=0.16", facecolor=CARD, edgecolor=BORDER, linewidth=1.4)
    ax.add_patch(rect)
    # top accent line
    line = patches.FancyBboxPatch((x, y+h-0.02), w, 0.04, boxstyle="round,pad=0.02,rounding_size=0.04", facecolor=accent, edgecolor="none", alpha=0.95)
    ax.add_patch(line)
    # icon
    if icon:
        ax.text(x+0.28, y+h-0.38, icon, ha="left", va="center", fontsize=11, color=accent)
    # title
    ax.text(x+w/2+0.12, y+h*0.62, title, ha="center", va="center", fontsize=8.8, weight="800", color=TEXT, family="sans-serif")
    # body
    ax.text(x+w/2, y+h*0.30, body, ha="center", va="center", fontsize=6.7, color=MUTED, family="monospace", linespacing=1.35, weight="400")

def contrail(x1, y1, x2, y2, col=CYAN, alpha=0.95, lw=2.2, style="straight"):
    # main contrail
    if style == "straight":
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=lw, alpha=alpha,
                                    connectionstyle="arc3,rad=0", shrinkA=3, shrinkB=5,
                                    mutation_scale=10))
    else:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=col, lw=lw, alpha=alpha,
                                    connectionstyle=f"arc3,rad={style}", shrinkA=3, shrinkB=5,
                                    mutation_scale=10))
    # faint outer glow (contrail)
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-", color=col, lw=lw+3, alpha=0.14,
                                connectionstyle="arc3,rad=0" if style=="straight" else f"arc3,rad={style}",
                                shrinkA=3, shrinkB=5))

# — header — flyby wordmark
ax.text(0.6, 10.35, "✈  FLYBY", ha="left", va="center", fontsize=18, weight="900", color=TEXT, family="sans-serif", 
        path_effects=[pe.withStroke(linewidth=3, foreground="#0F172A")])
ax.text(3.45, 10.35, "—  DERIVE  CESF  LONG VOL  ·  1H  ·  800 $  ·  4-AGENT", ha="left", va="center", fontsize=7.5, weight="600", color=MUTED, family="monospace", alpha=0.95)
ax.text(0.6, 9.92, "Derive spot/perp  ·  Condor options (SVI → Black76)  ·  multi-collateral  ·  portfolio margin net offsets", ha="left", va="center", fontsize=6.8, color=CYAN, family="monospace", alpha=0.9)
ax.text(15.4, 10.35, "BOTCAMP ’26", ha="right", va="center", fontsize=6.5, weight="700", color="#3B4A6B", family="monospace", bbox=dict(boxstyle="round,pad=0.3", facecolor="#0F172A", edgecolor="#1E2A44", alpha=0.9))

# — row 1: waypoints (data) — cyan family
glass_card(0.55, 8.55, 3.55, 1.18, CYAN, "01  MARKET DATA", "Binance 1h klines  →  Derive WS\nspot_feed.{CCY}  ·  orderbook 1.10\nwss://api.lyra.finance/ws", "◍")
glass_card(4.45, 8.55, 3.55, 1.18, CYAN, "02  SVI SMILE", "w(k)=a+b(ρ(k-m)+sqrt…)\nIV_ATM · IV_25D · skew\nfit_svi_slice  butterfly g>=0", "=")
glass_card(8.35, 8.55, 3.55, 1.18, CYAN, "03  FORECAST", "HAR 0.1·RVm+0.3·RVw+0.6·RVd\nEWMA lambda=0.94  ->  sigma , eps\nensemble -> edge", "~")
glass_card(12.25, 8.55, 3.55, 1.18, CYAN, "04  CESF PROXY", "tail + kurt + cluster + ε  →  score\nH=42  ε=0.088  barrier 0.80\n[side note — see strategy.md]", "◐")

contrail(4.10, 9.14, 4.45, 9.14, CYAN)
contrail(8.00, 9.14, 8.35, 9.14, CYAN)
contrail(11.90, 9.14, 12.25, 9.14, CYAN)

# — decision tower (violet)
glass_card(2.2, 7.02, 5.2, 1.18, VIOLET, "05  CONDOR  —  regime router", "OTM 25Δ  CESF≥0.40 & skew>2 → derive-options\nATM put  edge>2.5 & score≥0.35 → derive-perp\ntrend |mom|>1.2%  ·  ACTIVE strangle", "⬢")
glass_card(8.6, 7.02, 5.2, 1.18, VIOLET, "06  SIGNAL  ·  PIT 1-bar", "edge = σ_forecast − IV_SVI_ATM\n−1 short / 0 flat / +1 long\nclose i → fill open i+1  no lookahead", "◇")

# contrail from row1 down to tower
contrail(2.32, 8.55, 2.32, 8.25, CYAN, lw=1.8, alpha=0.65)
contrail(6.20, 8.55, 4.80, 8.25, CYAN, lw=1.8, alpha=0.5, style="0.15")
contrail(10.10, 8.55, 11.20, 8.25, CYAN, lw=1.8, alpha=0.5, style="-0.15")
contrail(14.02, 8.55, 13.80, 8.25, CYAN, lw=1.8, alpha=0.65)
contrail(7.40, 7.61, 8.60, 7.61, VIOLET)

# — risk / vault (emerald family) — one visual family, not rainbow
glass_card(0.55, 5.48, 3.85, 1.18, EMERALD, "07  KELLY  ·  trade", "f* = 0.5·edge/ε² · conf\nconf=score/0.35  cap 0.05/0.08\n$10 min  ·  30% cap", "◆")
glass_card(4.75, 5.48, 5.50, 1.18, EMERALD, "08  GUARD  ·  portfolio margin", "gross 240  per 160  Δ40  ν25  Γ5  ·  net offsets\nmargin 25%  daily −3%  peak −10%\nGuard.can_open() → Decision  (10% vs 50%)", "⬣")
glass_card(10.60, 5.48, 4.85, 1.18, EMERALD, "09  VAULT  ·  multi-collateral", "USDC 40 · ETH 30 · BTC 15 · HYPE 10 · kHYPE 5\n haircuts 0 / 10 / 10 / 15 / 15%\neffective vs USDC-only  +60%", "▣")

contrail(4.40, 6.07, 4.75, 6.07, EMERALD)
contrail(10.25, 6.07, 10.60, 6.07, EMERALD)
contrail(4.80, 7.02, 2.47, 6.72, VIOLET, lw=1.7, alpha=0.55, style="-0.12")
contrail(11.20, 7.02, 7.50, 6.72, VIOLET, lw=1.7, alpha=0.55, style="0.12")

# — execution (amber, landing strip)
glass_card(0.55, 3.94, 3.85, 1.18, AMBER, "10  SURFACE", "perps: short 3× = synthetic long put\n options: Black76 τ7d  K=0.97·F\npremium → qty = notional/premium", "✦")
glass_card(4.75, 3.94, 5.50, 1.18, AMBER, "11  DERIVE VENUE", "perp  orderbook.{ETH-PERP}  ·  options ETH-YYYYMMDD-K-P\n spot ETH-USDC rebalance  ·  wss://api.lyra.finance/ws\n live: BTC/ETH/SOL/HYPE/XRP  ·  AVAX/ARB paper", "✈")
glass_card(10.60, 3.94, 4.85, 1.18, AMBER, "12  LOOP", "1 position at a time\n TP 1.2/0.48 24h ATM  ·  TP 1.8/0.55 48h OTM\n close → Guard.on_pnl() → next bar", "↺")

contrail(4.40, 4.53, 4.75, 4.53, AMBER)
contrail(10.25, 4.53, 10.60, 4.53, AMBER)
contrail(2.47, 5.48, 2.47, 5.18, EMERALD, lw=1.7, alpha=0.55)
contrail(7.50, 5.48, 7.50, 5.18, EMERALD, lw=1.7, alpha=0.55)
contrail(12.90, 5.48, 12.90, 5.18, EMERALD, lw=1.7, alpha=0.55)

# — footer: flight log (one dark bar, not white)
log = patches.FancyBboxPatch((0.55, 2.35), 14.9, 1.35, boxstyle="round,pad=0.12,rounding_size=0.14", facecolor="#0A142A", edgecolor="#1E2A44", linewidth=1.2)
ax.add_patch(log)
ax.text(0.95, 3.28, "FLIGHT LOG  —  PIT 1-bar lag  ·  WFA 60/40  ·  fees 0.06% + 0.8% + 5bps  ·  survivorship fixed  ·  Guard on every fill", ha="left", va="center", fontsize=6.6, weight="700", color="#8EA0C8", family="monospace")
ax.text(0.95, 2.92, "Guard.can_open(gross, per, Δ, ν, Γ, headroom)  ·  CollateralVault.effective()  ·  portfolio margin 10% + ν vs 50% isolated  ·  1 pos at a time", ha="left", va="center", fontsize=6.2, color="#5A6B8A", family="monospace")
ax.text(0.95, 2.58, "Backtest 60d — perps +1.73% avg  (+4.23% ARB)  ·  options +159% avg  (+439% AVAX)  ·  WFA IS 13% → OOS 20% (not overfit)  ·  120d OOS +23%", ha="left", va="center", fontsize=6.2, weight="600", color="#7C8DB0", family="monospace")
# contrail to log
contrail(2.47, 3.94, 2.47, 3.72, AMBER, lw=1.6, alpha=0.5)
contrail(7.50, 3.94, 7.50, 3.72, AMBER, lw=1.6, alpha=0.5)
contrail(12.90, 3.94, 12.90, 3.72, AMBER, lw=1.6, alpha=0.5)
# subtle runway centerline in log
for x in range(1, 15):
    ax.plot([x, x+0.4], [2.48, 2.48], color="#1E2A44", lw=1.2, alpha=0.9)
    x+=1

# — tiny footer
ax.text(0.6, 0.35, "Flyby  ·  CESF side note — compressed vol space → smoother Black76  ·  H=42 ε=0.088  ·  Kelly half + Guard", ha="left", va="center", fontsize=5.8, color="#3B4A6B", family="monospace")
ax.text(15.4, 0.35, "flowchart.png  300dpi  ·  dark flight", ha="right", va="center", fontsize=5.8, color="#3B4A6B", family="monospace")

plt.tight_layout()
plt.savefig("flowchart.png", dpi=300, bbox_inches="tight", facecolor=BG)
plt.savefig("backtest/flowchart.png", dpi=300, bbox_inches="tight", facecolor=BG)
print("saved flyby night-flight flowchart 300dpi — palette: night + cyan/violet/emerald/amber, contrail path")
