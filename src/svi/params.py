"""SVI params — clean reimplementation (Gatheral 2004).
w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))
k = log(K/F), w = total variance = sigma_iv^2 * tau
No Brickfort imports.
"""
from __future__ import annotations
import math
from dataclasses import dataclass

@dataclass
class SviParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def validate(self):
        if self.b < 0: raise ValueError("b >= 0")
        if self.sigma <= 0: raise ValueError("sigma > 0")
        if abs(self.rho) >= 1: raise ValueError("|rho| < 1")
        wing = self.a + self.b*self.sigma*math.sqrt(1-self.rho**2)
        if wing < 0: raise ValueError("wing variance < 0")

def total_variance(k: float, p: SviParams) -> float:
    p.validate()
    km = k - p.m
    return p.a + p.b*(p.rho*km + math.sqrt(km*km + p.sigma*p.sigma))

def iv_from_svi(k: float, tau: float, p: SviParams) -> float:
    p.validate()
    if tau <= 0: raise ValueError("tau > 0")
    w = total_variance(k, p)
    if w < 0: raise ValueError("negative total variance")
    return math.sqrt(w / tau)

def butterfly_g(k: float, p: SviParams, eps=1e-4) -> float:
    w = total_variance(k, p)
    wp = total_variance(k+eps, p)
    wm = total_variance(k-eps, p)
    w1 = (wp-wm)/(2*eps)
    w2 = (wp-2*w+wm)/(eps*eps)
    return (1 - k*w1/(2*w))**2 - w1*w1/4*(1/w+0.25) + w2/2

__all__ = ["SviParams","total_variance","iv_from_svi","butterfly_g"]
