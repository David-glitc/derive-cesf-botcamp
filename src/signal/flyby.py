"""Shared causal features for live controllers and historical replay."""
from __future__ import annotations
import numpy as np
import pandas as pd

INTERVAL_SECONDS = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400}


def feature_frame(candles: pd.DataFrame, interval: str, lookback: int = 100,
                  trend_horizon_seconds: int = 4 * 3600) -> pd.DataFrame:
    if interval not in INTERVAL_SECONDS or lookback < 30:
        raise ValueError("Use 5m, 15m, 1h or 4h and at least 30 lookback bars")
    if type(trend_horizon_seconds) is not int or trend_horizon_seconds not in (1800, 14400):
        raise ValueError("Use the preset 30m candidate or 4h baseline trend horizon")
    values = candles[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    valid = np.isfinite(values).all(axis=1) & (values[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid &= (values.high >= values.low) & (values.volume >= 0)
    valid &= values.high.ge(values[["open", "close"]].max(axis=1))
    valid &= values.low.le(values[["open", "close"]].min(axis=1))
    # Poison invalid windows rather than dropping rows and bridging gaps.
    values = values.where(valid)
    close = values.close
    returns = np.log(close).diff()
    squared = returns ** 2
    ppy = 365 * 86400 / INTERVAL_SECONDS[interval]
    har = np.sqrt((0.1 * squared.rolling(lookback).mean()
                   + 0.3 * squared.rolling(5).mean() + 0.6 * squared) * ppy)
    weights = 0.94 ** np.arange(lookback - 1, -1, -1) * 0.06
    weights[0] += 0.94 ** lookback
    ewma = np.sqrt(squared.rolling(lookback).apply(lambda x: np.dot(x, weights), raw=True) * ppy)
    sigma = (har + ewma) / 2
    epsilon = 0.01 + (har - ewma).abs() / 2
    realized = np.sqrt(squared.rolling(20).mean() * ppy)
    tail = (returns < -1.5 * sigma / np.sqrt(ppy)).astype(float).rolling(20).mean()
    kurtosis = returns.rolling(lookback).kurt().clip(0, 10) / 10
    cluster = squared.rolling(20).corr(squared.shift(1)).clip(0, 1).fillna(0)
    cesf = (0.45 * (tail / 0.08).clip(0, 1) + 0.25 * kurtosis
            + 0.2 * cluster + 0.1 * (epsilon / 0.05).clip(0, 1)).clip(0, 1)
    trend_bars = max(3, int(trend_horizon_seconds / INTERVAL_SECONDS[interval]))
    momentum = np.log(close / close.shift(trend_bars))
    trend_noise = np.sqrt(squared.rolling(trend_bars).sum())
    efficiency = (close - close.shift(trend_bars)).abs() / close.diff().abs().rolling(trend_bars).sum()
    previous = close.shift(1)
    true_range = pd.concat([(values.high - values.low), (values.high - previous).abs(),
                            (values.low - previous).abs()], axis=1).max(axis=1)
    atr = true_range.rolling(14).mean()
    baseline = values.volume.shift(3).rolling(20).mean()
    volume_ratio = values.volume.rolling(3).mean() / baseline.replace(0, np.nan)
    result = pd.DataFrame({
        "price": close, "forecast_sigma": sigma, "epsilon": epsilon,
        "realized_sigma": realized, "edge": sigma - realized, "cesf_score": cesf,
        "momentum": momentum, "trend_z": momentum / trend_noise.replace(0, np.nan),
        "efficiency": efficiency, "atr_pct": atr / close, "volume_ratio": volume_ratio,
    })
    for name in ("trend_z", "volume_ratio", "efficiency"):
        result[f"previous_{name}"] = result[name].shift(1)
    result["valid"] = np.isfinite(result).all(axis=1) & valid.rolling(lookback + 1).min().eq(1)
    return result
