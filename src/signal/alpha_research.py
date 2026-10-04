"""Offline polynomial ridge research; never fitted or selected by a live bot.

Feature definitions extend the older local alpha-lab harness. All transformations
and label endpoints used by a fit precede its prediction boundary.
"""
import itertools
import math

import numpy as np
import pandas as pd

from src.signal.flyby import feature_frame

FEATURES = ("return_1", "return_3", "return_6", "return_12", "trend_30m", "trend_4h",
            "efficiency", "atr_pct", "log_volume_ratio", "rv_forecast_ratio", "cesf",
            "vol_edge", "utc_sin", "utc_cos")
IV_FEATURES = ("iv_available", "iv_level", "iv_change_1h", "iv_rv_gap")


def features(frame, iv=None):
    base = feature_frame(frame, "5m")
    fast = feature_frame(frame, "5m", trend_horizon_seconds=1800)
    x = pd.DataFrame(index=frame.index)
    for n in (1, 3, 6, 12):
        x[f"return_{n}"] = np.log(frame.close / frame.close.shift(n))
    x["trend_30m"], x["trend_4h"] = fast.trend_z, base.trend_z
    x["efficiency"], x["atr_pct"] = base.efficiency, base.atr_pct
    x["log_volume_ratio"] = np.log1p(base.volume_ratio)
    x["rv_forecast_ratio"] = base.realized_sigma / base.forecast_sigma
    x["cesf"], x["vol_edge"] = base.cesf_score, base.edge / base.forecast_sigma
    angle = 2 * np.pi * (frame.timestamp % 86400) / 86400
    x["utc_sin"], x["utc_cos"] = np.sin(angle), np.cos(angle)
    if iv is not None:
        iv = pd.Series(np.asarray(iv, dtype=float), index=frame.index)
        available = np.isfinite(iv) & (iv > 0)
        change = iv - iv.shift(12)
        x["iv_available"] = available.astype(float)
        # Explicit missingness, not a claim of zero implied volatility in SOL.
        x["iv_level"] = iv.where(available, 0)
        x["iv_change_1h"] = change.where(available & np.isfinite(change), 0)
        x["iv_rv_gap"] = (iv - base.realized_sigma).where(available, 0)
    return x


def labels(frame, horizon):
    return np.log(frame.open.shift(-horizon - 1) / frame.open.shift(-1)).to_numpy()


def expand(z, degree):
    if degree not in (1, 2):
        raise ValueError("bounded_degree_required")
    if degree == 1:
        return z
    return np.column_stack([z] + [z[:, i] * z[:, j]
                           for i, j in itertools.combinations_with_replacement(range(z.shape[1]), 2)])


def fit(frame, x, cutoff, *, horizon=12, degree=2, penalty=10000.):
    times = frame.timestamp.to_numpy(dtype=float)
    if (not 151 < cutoff < len(frame) or horizon not in (6, 12) or degree not in (1, 2)
            or penalty not in (100., 10000.) or len(x) != len(frame)
            or not np.isfinite(times).all() or not np.all(np.diff(times) == 300)):
        raise ValueError("invalid_chronological_research_spec")
    y = labels(frame, horizon)
    indices = np.arange(len(frame))
    mask = (indices + horizon + 1 < cutoff) & np.isfinite(y) & np.isfinite(x).all(axis=1)
    if mask.sum() < 500:
        raise ValueError("insufficient_purged_training_rows")
    values, target = x.to_numpy(dtype=float)[mask], y[mask]
    mean, scale = values.mean(axis=0), np.maximum(values.std(axis=0), 1e-8)
    p = expand((values - mean) / scale, degree)
    pm, ps = p.mean(axis=0), np.maximum(p.std(axis=0), 1e-8)
    z = (p - pm) / ps
    intercept = float(target.mean())
    coef = np.linalg.solve(z.T @ z + penalty * np.eye(z.shape[1]), z.T @ (target - intercept))
    residual = target - (z @ coef + intercept)
    return dict(kind="offline_polynomial_ridge", features=list(x.columns), horizon=horizon,
                degree=degree, penalty=penalty, mean=mean.tolist(), scale=scale.tolist(),
                expanded_mean=pm.tolist(), expanded_scale=ps.tolist(), coefficients=coef.tolist(),
                intercept=intercept, residual_rmse=float(np.sqrt(np.mean(residual ** 2))),
                training_rows=int(mask.sum()), max_label_time=float(times[indices[mask][-1] + horizon + 1]),
                evaluation_not_before=float(times[cutoff]), live_authorized=False)


def predict(model, x, times):
    times = np.asarray(times, dtype=float)
    if (list(x.columns) != model["features"] or model["live_authorized"] is not False
            or len(x) != len(times) or not np.isfinite(times).all()
            or np.any(times < model["evaluation_not_before"])
            or model["max_label_time"] >= model["evaluation_not_before"]):
        raise ValueError("prediction_contract_or_boundary_mismatch")
    values = x.to_numpy(dtype=float)
    valid = np.isfinite(values).all(axis=1)
    p, ood = np.full(len(x), np.nan), np.ones(len(x), dtype=bool)
    z = (values[valid] - model["mean"]) / model["scale"]
    ood[valid] = np.max(np.abs(z), axis=1) > 6
    transformed = (expand(z, model["degree"]) - model["expanded_mean"]) / model["expanded_scale"]
    p[valid] = transformed @ np.asarray(model["coefficients"]) + model["intercept"]
    return p, ood


def entry_gate(prediction, ood, sigma, side, cost, restricted=False):
    if (side not in (-1, 1) or ood or not all(math.isfinite(v) for v in (prediction, sigma, cost))
            or min(sigma, cost) < 0):
        return False
    # A training-error buffer, NOT a calibrated confidence interval. A veto
    # never cancels an owned position's stop or claims confidence is probability.
    return side * math.expm1(prediction) > (4 if restricted else 3) * cost + .25 * sigma
