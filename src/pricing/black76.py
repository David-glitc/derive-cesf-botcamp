"""Black76 — standalone, no Brickfort dep. Forward-measure options.
F = spot (or forward), K strike, tau years, r rate, vol sigma.
Call = DF*(F*N(d1)-K*N(d2)), Put = DF*(K*N(-d2)-F*N(-d1))
"""
from __future__ import annotations
import math
def _N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
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
