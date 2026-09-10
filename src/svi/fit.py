"""SVI fit — coordinate descent, butterfly + calendar checks.
Mirrors bf-surface logic but standalone.
"""
from __future__ import annotations
import math
from typing import List, Tuple
from .params import SviParams, total_variance, butterfly_g, iv_from_svi

def fit_svi_slice(tau: float, log_moneyness: List[float], ivs: List[float], max_iter=600) -> Tuple[SviParams, float]:
    if tau <= 0: raise ValueError("tau > 0")
    if len(log_moneyness) < 3: raise ValueError("need >=3 points")
    targets = [(k, iv*iv*tau) for k,iv in zip(log_moneyness, ivs)]
    # initial guess: ATM variance
    atm_w = min(targets, key=lambda x: abs(x[0]))[1]
    best = SviParams(a=atm_w*0.8, b=0.12, rho=-0.3, m=0.0, sigma=0.18)
    def rmse(p):
        return sum((total_variance(k,p)-w)**2 for k,w in targets)/len(targets)
    best_err = rmse(best)
    step=0.1
    for _ in range(max_iter):
        improved=False
        for adj in [
            lambda p,d: setattr(p,'a',p.a+d),
            lambda p,d: setattr(p,'b',max(1e-6,p.b+d)),
            lambda p,d: setattr(p,'rho',max(-0.99,min(0.99,p.rho+d))),
            lambda p,d: setattr(p,'m',p.m+d),
            lambda p,d: setattr(p,'sigma',max(1e-4,p.sigma+d)),
        ]:
            for s in (-1,1):
                trial = SviParams(best.a,best.b,best.rho,best.m,best.sigma)
                adj(trial, s*step)
                try:
                    trial.validate()
                    # butterfly quick check on grid
                    if any(butterfly_g(k,trial) < -1e-6 for k in [x[0] for x in targets]):
                        continue
                    err = rmse(trial)
                    if err < best_err:
                        best, best_err = trial, err
                        improved=True
                except: continue
        if not improved:
            step*=0.5
            if step<1e-8: break
    best.validate()
    return best, math.sqrt(best_err)

def check_calendar(earlier: SviParams, later: SviParams, k_min=-0.5, k_max=0.5, steps=32) -> bool:
    for i in range(steps+1):
        k = k_min + (k_max-k_min)*i/steps
        if total_variance(k, later) + 1e-10 < total_variance(k, earlier):
            return False
    return True

def repair_calendar(earlier: SviParams, later: SviParams, k_min=-0.5, k_max=0.5):
    for _ in range(200):
        if check_calendar(earlier, later, k_min, k_max): return
        deficit=max(total_variance(k,earlier)-total_variance(k,later) for k in [k_min + (k_max-k_min)*i/32 for i in range(33)])
        later.a += deficit+1e-6

__all__=["fit_svi_slice","check_calendar","repair_calendar"]
