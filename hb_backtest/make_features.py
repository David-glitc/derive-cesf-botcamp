"""Feature primitives for the Derive v3 testnet runner.

Reconstructed from the inlined forecasting math in
controllers/directional_trading/flyby.py (identical HAR/EWMA/CESF
formulation). The runner imports _har, _ewma, _cesf from here.
"""
from __future__ import annotations

import numpy as np


def _har(returns, ppy):
    r = np.asarray(returns, float)
    if r.size < 5:
        return float(np.sqrt(np.mean(r ** 2) * ppy)) if r.size else 0.2
    rv_d = float(r[-1] ** 2)
    rv_w = float(np.mean(r[-5:] ** 2))
    rv_m = float(np.mean(r ** 2))
    return max(float(np.sqrt((0.1 * rv_m + 0.3 * rv_w + 0.6 * rv_d) * ppy)), 1e-8)


def _ewma(returns, lam, ppy):
    r = np.asarray(returns, float)
    if r.size == 0:
        return 0.2
    var = float(r[0] ** 2)
    for x in r[1:]:
        var = lam * var + (1 - lam) * float(x ** 2)
    return max(float(np.sqrt(var * ppy)), 1e-8)


def _cesf(returns, sigma, eps):
    import math

    r = np.asarray(returns, float)
    if r.size < 20:
        return 0.0
    tail = float(np.mean(r < -1.5 * sigma / math.sqrt(365))) if sigma > 0 else 0.0
    m = float(np.mean(r))
    var = float(np.mean((r - m) ** 2))
    kurt = float(np.mean((r - m) ** 4) / (var ** 2 + 1e-12)) if var > 1e-12 else 3.0
    kurt_n = min(max((kurt - 3) / 10, 0), 1)
    try:
        ac = float(np.corrcoef((r ** 2)[:-1], (r ** 2)[1:])[0, 1])
        ac = max(ac, 0) if np.isfinite(ac) else 0.0
    except Exception:
        ac = 0.0
    return float(np.clip(
        0.45 * min(tail / 0.08, 1) + 0.25 * kurt_n + 0.2 * ac + 0.1 * min(eps / 0.05, 1),
        0, 1))
