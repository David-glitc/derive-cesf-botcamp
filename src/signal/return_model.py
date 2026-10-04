"""Small frozen return model. No live fitting, pickle, or alpha guarantee."""
from dataclasses import dataclass
import math

import numpy as np

FEATURES = ("trend_z", "signed_efficiency", "signed_volume")


def vector(features):
    trend, efficiency, volume = (float(features[k]) for k in ("trend_z", "efficiency", "volume_ratio"))
    if not all(math.isfinite(v) for v in (trend, efficiency, volume)) or not 0 <= efficiency <= 1 or volume < 0:
        raise ValueError("invalid_return_features")
    return np.array([trend, trend * efficiency, trend * math.log1p(volume)])


def fit_return_model(frame, features, cutoff, *, market, horizon_bars=6, penalty=100.0):
    """Target next-open to next-open return; all label endpoints precede cutoff.

    Residual RMSE is a conservative noise diagnostic, NOT a calibrated confidence
    interval. Overlapping labels do not constitute independent observations.
    """
    if market not in ("ETH", "BTC", "SOL", "HYPE") or horizon_bars != 6 or penalty != 100.0 or not 151 < cutoff < len(frame):
        raise ValueError("use_fixed_30m_model_spec")
    times = frame.timestamp.to_numpy(dtype=float)
    if not np.isfinite(times).all() or not np.all(np.diff(times) == 300):
        raise ValueError("continuous_5m_training_required")
    rows, targets, indices = [], [], []
    for i in range(100, cutoff - horizon_bars - 1):
        f = features.iloc[i].to_dict()
        if not bool(f.get("valid")):
            continue
        rows.append(vector(f))
        entry, end = float(frame.open.iloc[i + 1]), float(frame.open.iloc[i + horizon_bars + 1])
        if not min(entry, end) > 0 or not math.isfinite(entry + end):
            raise ValueError("invalid_training_prices")
        targets.append(end / entry - 1)
        indices.append(i)
    if len(rows) < 500:
        raise ValueError("insufficient_purged_training_rows")
    x, y = np.array(rows), np.array(targets)
    mean, scale = x.mean(axis=0), x.std(axis=0)
    scale = np.maximum(scale, 1e-8)
    z = (x - mean) / scale
    intercept = float(y.mean())
    coefficients = np.linalg.solve(z.T @ z + penalty * np.eye(3), z.T @ (y - intercept))
    residual = y - (z @ coefficients + intercept)
    model = {"schema": 1, "kind": "flyby_linear_return_candidate", "features": list(FEATURES), "market": market,
             "interval_seconds": 300, "horizon_bars": horizon_bars, "penalty": penalty,
             "mean": mean.tolist(), "scale": scale.tolist(), "coefficients": coefficients.tolist(),
             "intercept": intercept, "residual_rmse": float(np.sqrt(np.mean(residual ** 2))),
             "train_rows": len(rows), "max_training_label_time": float(times[indices[-1] + horizon_bars + 1]),
             "evaluation_not_before": float(times[cutoff]), "live_authorized": False}
    validate_model(model)
    return model


def validate_model(model):
    if (model.get("schema") != 1 or model.get("kind") != "flyby_linear_return_candidate"
            or model.get("market") not in ("ETH", "BTC", "SOL", "HYPE")
            or model.get("features") != list(FEATURES) or model.get("interval_seconds") != 300
            or model.get("horizon_bars") != 6 or model.get("penalty") != 100.0
            or model.get("live_authorized") is not False or model.get("train_rows", 0) < 500):
        raise ValueError("invalid_return_model_contract")
    for key in ("mean", "scale", "coefficients"):
        values = np.asarray(model[key], dtype=float)
        if values.shape != (3,) or not np.isfinite(values).all():
            raise ValueError("invalid_return_model_arrays")
    for key in ("intercept", "residual_rmse", "max_training_label_time", "evaluation_not_before"):
        if not math.isfinite(float(model[key])):
            raise ValueError("invalid_return_model_scalars")
    if (min(model["scale"]) <= 0 or model["residual_rmse"] < 0
            or not 0 <= model["max_training_label_time"] < model["evaluation_not_before"]):
        raise ValueError("invalid_return_model_training_boundary")


@dataclass(frozen=True)
class ReturnEstimate:
    gross_return: float
    noise_margin: float
    in_distribution: bool


def predict_return(model, features, signal_time):
    validate_model(model)
    if not math.isfinite(signal_time) or signal_time < model["evaluation_not_before"]:
        raise ValueError("prediction_precedes_training_boundary")
    z = (vector(features) - np.array(model["mean"])) / np.array(model["scale"])
    return ReturnEstimate(float(z @ np.array(model["coefficients"]) + model["intercept"]),
                          .25 * model["residual_rmse"], bool(np.max(np.abs(z)) <= 6))
