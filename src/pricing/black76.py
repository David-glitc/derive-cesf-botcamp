"""Black76 — standalone, no Brickfort dep. Forward-measure options.
F = spot (or forward), K strike, tau years, r rate, vol sigma.
Call = DF*(F*N(d1)-K*N(d2)), Put = DF*(K*N(-d2)-F*N(-d1))

Derive use: F = Derive perp mark (forward), vol = SVI iv_from_svi(k,τ),
            premium used for Condor options execution alongside perps.
Greeks feed Derive portfolio margin net Δ/ν/Γ offsets.
"""
from __future__ import annotations
import math
def _N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def _n(x): return math.exp(-0.5*x*x)/math.sqrt(2*math.pi)
def d1d2(F,K,tau,vol):
    s=math.sqrt(tau)
    d1=(math.log(F/K)+0.5*vol*vol*tau)/(vol*s)
    return d1, d1-vol*s
def black76_price(F,K,tau,r,vol, kind="call"):
    if tau<=0: return max(F-K,0) if kind=="call" else max(K-F,0)
    if vol<=0: raise ValueError("vol>0")
    DF=math.exp(-r*tau)
    d1,d2=d1d2(F,K,tau,vol)
    if kind=="call": return DF*(F*_N(d1)-K*_N(d2))
    else: return DF*(K*_N(-d2)-F*_N(-d1))
def black76_delta(F,K,tau,r,vol, kind="call"):
    DF=math.exp(-r*tau)
    d1,_=d1d2(F,K,tau,vol)
    return DF*_N(d1) if kind=="call" else DF*(_N(d1)-1)
def black76_vega(F,K,tau,r,vol):
    """Vega — same for call/put, scaled to 1% vol move (×0.01 outside)."""
    DF=math.exp(-r*tau)
    d1,_=d1d2(F,K,tau,vol)
    return DF * F * math.sqrt(tau) * _n(d1)
def black76_gamma(F,K,tau,r,vol):
    DF=math.exp(-r*tau)
    d1,_=d1d2(F,K,tau,vol)
    return DF * _n(d1) / (F * vol * math.sqrt(tau)) if F>0 and vol>0 and tau>0 else 0.0
def black76_greeks(F,K,tau,r,vol,kind="call"):
    """Convenience: return dict with price + delta/vega/gamma for portfolio margin."""
    return dict(price=black76_price(F,K,tau,r,vol,kind),
                delta=black76_delta(F,K,tau,r,vol,kind),
                vega=black76_vega(F,K,tau,r,vol),
                gamma=black76_gamma(F,K,tau,r,vol))
