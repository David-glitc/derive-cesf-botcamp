"""Kelly trade + portfolio sizing.
Trade Kelly: f* = edge / variance  (edge in vol pts → price edge via vega)
We use vol-edge proxy: edge_vol = sigma_forecast - iv_proxy
Convert to price edge bps: edge_bps = edge_vol / sigma_forecast * 10000 * vega_norm
Simplified: Kelly fraction ∝ edge / (epsilon^2)

Portfolio Kelly: cap gross, per-underlying, delta/vega/gamma, margin headroom.
Mirrors bf-risk limits but standalone.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

@dataclass
class KellyConfig:
    max_fraction: float = 0.05   # per-trade cap (fraction of equity)
    kelly_cap: float = 0.08      # half-Kelly hard cap
    kelly_fraction: float = 0.5  # use half-Kelly
    min_edge_bps: float = 150    # 1.5 vol pts ≈ 150bps gate
    fee_bps: float = 60          # taker fee 6bps + spread 0.8%

def kelly_fraction(edge_vol: float, epsilon: float, sigma: float, cfg: KellyConfig|None=None) -> float:
    cfg=cfg or KellyConfig()
    if edge_vol < cfg.min_edge_bps/10000:
        return 0.0
    # variance proxy = epsilon^2 + sigma^2*0.1  (don't divide by tiny eps)
    var = max(epsilon,0.02)**2
    # raw Kelly = edge / var  (edge in vol ~ 0.015)
    raw = edge_vol / var * 0.02  # 0.02 scales to ~0.1-0.3 range for typical edge
    # half-Kelly
    f = raw * cfg.kelly_fraction
    # cap
    return max(0.0, min(f, cfg.kelly_cap, cfg.max_fraction))

def position_notional(equity: float, edge_vol: float, epsilon: float, sigma: float, cfg: KellyConfig|None=None, confidence: float=1.0) -> float:
    """Returns quote notional $ for this trade."""
    cfg=cfg or KellyConfig()
    f = kelly_fraction(edge_vol, epsilon, sigma, cfg)
    if f <= 0: return 0.0
    # confidence scales (CESF score, hit-rate)
    f = f * max(0.5, min(confidence, 1.5))
    notional = equity * f
    # venue min lot: Derive 0.1 contract ≈ $0.64 (1d ATM) → floor $10
    notional = max(notional, 10.0)
    notional = min(notional, equity*0.3)
    return notional

@dataclass
class PortfolioLimits:
    max_gross_notional: float = 500_000  # scaled for $800 → override in bot with $240
    max_per_underlying: float = 250_000
    max_net_delta: float = 25_000        # for $800 → 20-50
    max_net_vega: float = 50_000         # → 15-30
    max_gamma: float = 5000
    min_margin_headroom_pct: float = 0.25
    daily_loss_halt_pct: float = 0.03
    peak_dd_halt_pct: float = 0.10
    # scaled for Botcamp $800
    @classmethod
    def botcamp_800(cls):
        return cls(
            max_gross_notional=240,
            max_per_underlying=160,
            max_net_delta=40,
            max_net_vega=25,
            max_gamma=5,
            min_margin_headroom_pct=0.25,
            daily_loss_halt_pct=0.03,
            peak_dd_halt_pct=0.10,
        )

def check_portfolio(equity: float, gross: float, per_underlying: dict, net_delta: float, net_vega: float, gamma: float, margin_headroom: float, daily_pnl_pct: float, peak_dd_pct: float, lims: PortfolioLimits|None=None):
    lims=lims or PortfolioLimits.botcamp_800()
    if gross > lims.max_gross_notional: return False, "gross"
    for _,v in per_underlying.items():
        if v > lims.max_per_underlying: return False, "per_underlying"
    if abs(net_delta) > lims.max_net_delta: return False, "delta"
    if abs(net_vega) > lims.max_net_vega: return False, "vega"
    if abs(gamma) > lims.max_gamma: return False, "gamma"
    if margin_headroom < lims.min_margin_headroom_pct: return False, "margin"
    if daily_pnl_pct <= -lims.daily_loss_halt_pct: return False, "daily_halt"
    if peak_dd_pct <= -lims.peak_dd_halt_pct: return False, "peak_halt"
    return True, "ok"
