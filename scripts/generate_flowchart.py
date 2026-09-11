#!/usr/bin/env python3
"""Generate clean, readable flowchart for Derive CESF — replaces Excalidraw export.

Dark theme, high contrast, 300dpi, readable fonts.
Shows all 12 steps + Derive bonuses (spot/perp, options, multi-collateral, portfolio margin)
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# ── colors ──
BG = "#0F172A"        # slate-900
CARD_BG = "#1E293B"   # slate-800
ACCENT = "#0EA5E9"    # sky-500
ACCENT2 = "#8B5CF6"   # violet
ACCENT3 = "#10B981"   # emerald
ACCENT4 = "#F59E0B"   # amber
TEXT = "#F8FAFC"
MUTED = "#94A3B8"

fig, ax = plt.subplots(figsize=(16, 11))
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)
ax.set_xlim(0, 16)
ax.set_ylim(0, 11)
ax.axis("off")

def card(x, y, w, h, title, subtitle, color, subtitle_color=MUTED):
    # rounded rect
    rect = patches.FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.08", facecolor=CARD_BG, edgecolor=color, linewidth=2)
    ax.add_patch(rect)
    # title
    ax.text(x+w/2, y+h*0.62, title, ha="center", va="center", fontsize=10, weight="bold", color=TEXT, family="monospace")
    ax.text(x+w/2, y+h*0.28, subtitle, ha="center", va="center", fontsize=7.5, color=subtitle_color, family="monospace", linespacing=1.3)

def arrow(x1, y1, x2, y2):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color="#475569", lw=1.8, shrinkA=4, shrinkB=4, connectionstyle="arc3,rad=0"))

# ─ Title ─
ax.text(8, 10.5, "Derive CESF Crash-Mass  —  Hummingbot V2 Controller + Condor Agent", ha="center", va="center", fontsize=13, weight="bold", color=TEXT, family="monospace")
ax.text(8, 10.15, "SVI  •  HAR-RV / EWMA  •  CESF  •  Kelly  •  Guard    —    Perps & Options  •  Multi-Collateral  •  Portfolio Margin    •    $800  •  1h  •  4-agent  (ETH/ARB/SOL/AVAX)", ha="center", va="center", fontsize=7, color=MUTED, family="monospace")
ax.text(8, 9.85, "Derive scoring:  spot/perp [ok]   options via Condor/SVI/Black76 [ok]   multi-collateral ETH/BTC/HYPE/kHYPE [ok]   portfolio margin net D/v/G offsets [ok]", ha="center", va="center", fontsize=7, color=ACCENT, family="monospace", style="italic")

# Row 1: y 8.2
card(0.4, 8.2, 3.5, 1.3, "1  Market Data", "Binance 1h klines\nDerive WS spot_feed.{CCY}\norderbook.{inst}.1.10", ACCENT)
card(4.3, 8.2, 3.5, 1.3, "2  SVI Surface", "w(k)=a+b(ρ(k-m)+√…)\nIV_ATM  IV_25Δ  skew\nfit_svi_slice 600it", "#3B82F6")
card(8.2, 8.2, 3.5, 1.3, "3  Forecast", "HAR 0.1·RVm+0.3·RVw+0.6·RVd\nEWMA λ=0.94 → σ , ε\nensemble(σ,ε)", ACCENT2)
card(12.1, 8.2, 3.5, 1.3, "4  CESF Crash-Mass", "tail 1.5σ + kurt + cluster + ε\nscore [0,1]  H=42 ε=0.088\nbarrier 0.80", ACCENT3)

arrow(3.9, 8.85, 4.3, 8.85)
arrow(7.8, 8.85, 8.2, 8.85)
arrow(11.7, 8.85, 12.1, 8.85)

# Row 2: y 6.5
card(2.0, 6.5, 5.0, 1.3, "5  Regime Router  — Condor decide()", "OTM 25Δ if CESF≥0.40 & skew>2 → derive-options\nATM put if edge>2.5 & score≥0.35 → derive-perp\nTrend if |mom 24×1h|>1.2%  + ACTIVE strangle", "#F59E0B")
card(8.5, 6.5, 5.5, 1.3, "6  Signal  •  PIT 1-bar lag", "edge = σ_forecast − IV_SVI_ATM\n-1 short / 0 flat / +1 long\nclose i → fill open i+1  (no lookahead)", "#EF4444", MUTED)

arrow(6.0, 7.9, 6.0, 7.8)
arrow(7.0, 7.15, 8.5, 7.15)

# Row 3: y 4.8
card(0.4, 4.8, 3.8, 1.3, "7  Kelly — Trade", "f* = 0.5·edge/ε²·conf\nconf=score/0.35  cap 0.05/0.08\n$10 min  30% cap", "#EC4899")
card(4.7, 4.8, 5.2, 1.3, "8  PortfolioGuard  — no bypass", "gross 240  per 160  Δ40  ν25  Γ5\nmargin 25%  daily -3%  peak -10%\nnet Δ/ν/Γ offsets (portfolio, not isolated)", "#6366F1")
card(10.4, 4.8, 4.8, 1.3, "9  Multi-Collateral Vault", "USDC 40%  ETH 30%  BTC 15%\nHYPE 10%  kHYPE 5%  haircuts 0/10/15%\neffective vs USDC-only  +60%", ACCENT3)

arrow(4.2, 5.45, 4.7, 5.45)
arrow(9.9, 5.45, 10.4, 5.45)
# vertical from signal to kelly
arrow(5.0, 6.5, 2.2, 6.1)
arrow(11.2, 6.5, 7.3, 6.1)

# Row 4: y 3.1
card(0.4, 3.1, 3.8, 1.3, "10  Execution Surface", "Perps: short perp 3× (synthetic put)\nOptions: Black76 τ7d  K=F·0.97\npremium → qty = notional/premium", "#06B6D4")
card(4.7, 3.1, 5.2, 1.3, "11  Derive Venue  — execution", "derive  perp  orderbook.{ETH-PERP}.1.10\nderive  options  ETH-YYYYMMDD-K-P\nspot ETH-USDC for rebalance", "#14B8A6")
card(10.4, 3.1, 4.8, 1.3, "12  Risk & Loop", "1 position at a time\nTP1.2/SL0.48 24h  ATM\nTP1.8/SL0.55 48h  OTM", "#A78BFA")

arrow(2.2, 4.8, 2.2, 4.4)
arrow(7.3, 4.8, 7.3, 4.4)
arrow(12.8, 4.8, 12.8, 4.4)
arrow(4.2, 3.75, 4.7, 3.75)
arrow(9.9, 3.75, 10.4, 3.75)

# Bottom loop bar
loop_rect = patches.FancyBboxPatch((0.4, 1.7), 15.2, 0.9, boxstyle="round,pad=0.06", facecolor="#F8FAFC", edgecolor="#E2E8F0", linewidth=1.5)
ax.add_patch(loop_rect)
ax.text(8, 2.25, "Loop  →  next 1h bar close (PIT)    •    Backtest: WFA 60/40  •  fees 0.06% + 0.8% half-spread + 5bps  •  survivorship fixed  •  Guard on every fill", ha="center", va="center", fontsize=7.5, color="#0F172A", family="monospace", weight="bold")
ax.text(8, 1.9, "Guard can_open(gross, per, Δ, ν, Γ, headroom)  •  CollateralVault effective_collateral()  •  Portfolio margin: 10% gross + ν add vs 50% isolated", ha="center", va="center", fontsize=6.5, color="#475569", family="monospace")
# arrow down from execution to loop
arrow(5.5, 3.1, 5.5, 2.6)
arrow(12.0, 3.1, 12.0, 2.6)
ax.annotate("", xy=(8, 1.7), xytext=(15.6, 1.2), arrowprops=dict(arrowstyle="->", color="#475569", lw=1.5, connectionstyle="angle3,angleA=-90,angleB=0"))

# Results bar
res_rect = patches.FancyBboxPatch((0.4, 0.4), 15.2, 0.9, boxstyle="round,pad=0.06", facecolor="#ECFDF5", edgecolor="#10B981", linewidth=1.8)
ax.add_patch(res_rect)
ax.text(8, 0.85, "Perps: +1.74% avg  (+4.25% ARB  +3.53% ETH  -1.54% DD)    •    Options Black76: +159% avg  (+439% AVAX  +223% BTC)  —  same signal, true convexity   •   120d WFA OOS +23% (IS -8% → not overfit)", ha="center", va="center", fontsize=7.2, weight="bold", color="#065F46", family="monospace")

plt.tight_layout()
plt.savefig("flowchart.png", dpi=300, bbox_inches="tight", facecolor=BG)
plt.savefig("backtest/flowchart.png", dpi=300, bbox_inches="tight", facecolor=BG)
print("saved flowchart.png and backtest/flowchart.png (300dpi)")
