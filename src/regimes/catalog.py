"""Options regimes — ATM vs OTM vs Directional, calibrated to Botcamp 48h.
Replaces brickfort research/regimes.py but public, with OTM extension.
"""
from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class Regime:
    id: str
    name: str
    structure: str
    edge_src: str
    status: str  # live | scaffold | research
    moneyness: str  # ATM | OTM | wings
    tp: float
    sl: float
    hold_h: int
    delta_target: float|None

REGIMES = (
    # ATM long vol — primary edge for Derive (Your +24% regime, now with SVI ATM IV)
    Regime("scalp-long-put-atm","Long Put ATM","long ATM put","forecast - IV_ATM >1.8 vol + CESF crash", "live","ATM", 1.2, 0.48, 24, -0.5),
    Regime("scalp-long-call-atm","Long Call ATM","long ATM call","forecast - IV_ATM >2.2 vol + expansion","live","ATM", 1.2, 0.48, 24, 0.5),
    # OTM wings — lower gamma, better Sharpe when smile rich (Derive BTC skew)
    Regime("scalp-long-put-otm-25d","Long Put 25Δ","long 25Δ put (OTM)","wing IV cheap vs RV + SVI skew cheap","scaffold","OTM", 1.8, 0.55, 48, -0.25),
    Regime("scalp-long-call-otm-25d","Long Call 25Δ","long 25Δ call","wing IV cheap vs RV + SVI skew cheap","scaffold","OTM", 1.8, 0.55, 48, 0.25),
    Regime("strangle-long-otm","Long Strangle 25Δ","long 25Δ put+call","both wings cheap, vol expansion bet","scaffold","OTM", 1.5, 0.50, 48, 0.0),
    # Directional momentum — uses SVI forward + trend filter
    Regime("trend-ride-call","Trend Ride Call","long ATM call on uptrend","24x5m momentum >1.2% + vol not stretched + SVI forward drift","live","ATM", 1.0, 0.5, 12, 0.5),
    Regime("trend-ride-put","Trend Ride Put","long ATM put on downtrend","momentum <-1.2% + vol","live","ATM", 1.0, 0.5, 12, -0.5),
    # Short vol — only for completeness; needs wider halt, not for 48h finals primary
    Regime("vrp-atm-straddle","VRP ATM Straddle","short ATM straddle","IV_ATM - forecast >1.5 vol + calm CESF","research","ATM", 0.25, 0.5, 24, 0.0),
    Regime("strangle-short-otm","Short Strangle 25Δ","short 25Δ strangle","wing IV rich vs RV + smile rich","research","OTM", 0.35, 0.80, 24, 0.0),
)

def live_regimes(): return [r for r in REGIMES if r.status=="live"]
def otm_regimes(): return [r for r in REGIMES if r.moneyness=="OTM"]
