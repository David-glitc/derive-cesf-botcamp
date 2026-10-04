"""Quote risk budgets and executable depth; no estimated venue margin."""
from __future__ import annotations
import math
from dataclasses import dataclass
from src.risk.exposure import BASELINE_EXPOSURE, exposure_limits
from src.risk.competition import HARD_STOP_DRAWDOWN


@dataclass(frozen=True)
class DepthQuote:
    amount: float
    vwap: float
    worst_price: float


def depth_quote(levels, amount: float) -> DepthQuote | None:
    if not math.isfinite(amount) or amount <= 0:
        return None
    remaining, cost, worst = amount, 0.0, 0.0
    for price, available in levels:
        if not all(math.isfinite(float(v)) and float(v) > 0 for v in (price, available)):
            return None
        take = min(remaining, float(available))
        cost += take * float(price)
        remaining -= take
        worst = float(price)
        if remaining <= max(1e-12, amount * 1e-10):
            return DepthQuote(amount, cost / amount, worst)
    return None


def risk_size(*, equity: float, available: float, committed: float, confidence: float,
              stop_pct: float, gross_cap: float, risk_fraction: float = 0.005,
              notional_fraction: float = 0.20, peak_dd: float = 0.0,
              drawdown_limit: float = .04, size_scale: float | None = None,
              trade_risk_budget: float | None = None, exposure_profile=BASELINE_EXPOSURE,
              underlying=None) -> float:
    values = (equity, available, committed, confidence, stop_pct, gross_cap, risk_fraction, notional_fraction,
              peak_dd, drawdown_limit, 1.0 if size_scale is None else size_scale,
              equity * risk_fraction if trade_risk_budget is None else trade_risk_budget)
    if not all(math.isfinite(v) for v in values) or equity <= 0 or stop_pct <= 0:
        return 0.0
    if min(available, committed, gross_cap) < 0 or not 0 <= confidence <= 1:
        return 0.0
    try:
        limits = exposure_limits(exposure_profile, underlying)
    except ValueError:
        return 0.0
    if not 0 < risk_fraction <= 0.02 or not 0 < notional_fraction <= limits["perp_notional"]:
        return 0.0
    if not 0 < drawdown_limit <= float(HARD_STOP_DRAWDOWN) or (size_scale is not None and not 0 <= size_scale <= 1):
        return 0.0
    if trade_risk_budget is not None and trade_risk_budget < 0:
        return 0.0
    if peak_dd <= -drawdown_limit:
        return 0.0
    scale = max(.25, 1 - max(0, -peak_dd) / drawdown_limit) if size_scale is None else size_scale
    budget = equity * risk_fraction * scale
    if trade_risk_budget is not None:
        budget = min(budget, trade_risk_budget)
    return max(0.0, min(budget * confidence / stop_pct,
                        equity * notional_fraction * scale, max(0.0, gross_cap - committed), available))


def cost_allows_entry(profit_pct: float, round_trip_cost: float, multiple: float = 3.0) -> bool:
    """Target distance must cover 3x estimated total costs; not expected alpha."""
    return (math.isfinite(profit_pct) and math.isfinite(round_trip_cost) and math.isfinite(multiple)
            and multiple >= 3 and round_trip_cost >= 0 and profit_pct >= max(.003, multiple * round_trip_cost))


def dynamic_exits(atr_pct: float, confidence: float, interval_seconds: int):
    stop = min(0.015, max(0.003, atr_pct * (1.25 + 0.5 * (1 - confidence))))
    profit = stop * (1.5 + 0.5 * confidence)
    hold = min(6 * 3600, max(interval_seconds * 2, int(3600 * (1 + 2 * confidence))))
    return stop, profit, hold
