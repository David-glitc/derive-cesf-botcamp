"""HAR-RV + EWMA ensemble — standalone (mirrors bf-vol).
ppv = 365*24*60/mins  for 3m → 175200
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass

@dataclass
class VolForecast:
    sigma: float
    epsilon: float
    har: float
    ewma: float

@dataclass
class EnsembleConfig:
    lam: float = 0.94
    har_w: float = 0.5
    ewma_w: float = 0.5
    min_eps: float = 0.01

def har_rv(returns: np.ndarray, ppy: float) -> float:
    r=np.asarray(returns,float)
    if r.size<5: return float(np.sqrt(np.mean(r**2)*ppy)) if r.size else 0.2
    rv_d=float(r[-1]**2)
    rv_w=float(np.mean(r[-5:]**2))
    rv_m=float(np.mean(r**2))
    fv=0.1*rv_m+0.3*rv_w+0.6*rv_d
    return max(float(np.sqrt(fv*ppy)),1e-8)

def ewma(returns: np.ndarray, lam: float, ppy: float) -> float:
    r=np.asarray(returns,float)
    if r.size==0: return 0.2
    var=float(r[0]**2)
    for x in r[1:]: var=lam*var+(1-lam)*float(x**2)
    return max(float(np.sqrt(var*ppy)),1e-8)

def ensemble(returns: np.ndarray, ppy: float, cfg: EnsembleConfig|None=None) -> VolForecast:
    cfg=cfg or EnsembleConfig()
    r=np.asarray(returns,float)
    h=har_rv(r,ppy)
    e=ewma(r,cfg.lam,ppy)
    sigma=(cfg.har_w*h+cfg.ewma_w*e)/(cfg.har_w+cfg.ewma_w)
    eps=max(cfg.min_eps+0.5*abs(h-e),cfg.min_eps)
    return VolForecast(sigma,eps,h,e)
