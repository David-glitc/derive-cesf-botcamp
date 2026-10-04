"""Isolated candidate economics/holding rules; baseline quality is unchanged."""
import math

from src.risk.position_sizing import risk_size
from src.risk.competition import HARD_STOP_DRAWDOWN


def expected_edge_allows(estimate, side, round_trip_cost, restricted=False):
    if side not in (-1, 1) or estimate is None:
        return False
    values = (estimate.gross_return, estimate.noise_margin, round_trip_cost)
    if not all(math.isfinite(v) for v in values) or min(estimate.noise_margin, round_trip_cost) < 0:
        return False
    # Deliberately retain a stronger cost cushion during the remaining DD buffer.
    margin = estimate.noise_margin + (round_trip_cost if restricted else 0)
    return estimate.in_distribution and side * estimate.gross_return - round_trip_cost - margin > 0


def holding_exit(decision, features, side, estimate=None):
    if decision.halt:
        return "halt"
    if side not in (-1, 1) or not features.get("valid"):
        return "invalid_holding_context"
    trend, efficiency = features.get("trend_z"), features.get("efficiency")
    if trend is None or efficiency is None or not all(math.isfinite(v) for v in (trend, efficiency)):
        return "invalid_holding_context"
    if decision.signal == -side:
        return "opposite_confirmation"
    if side * trend <= .2:
        return "trend_reversal"
    if efficiency < .15:
        return "trend_decay"
    # Weak, absent or out-of-distribution forecasts don't cancel protection or
    # imply a reversal. Entry cost is sunk; it must not be charged again to hold.
    if (estimate is not None and estimate.in_distribution
            and side * estimate.gross_return < -estimate.noise_margin):
        return "adverse_return_forecast"
    return None


def fixed_risk_size(*, equity, available, committed, stop_pct, view):
    # Fixed 70% of the approved risk budget, never a probability interpretation.
    return risk_size(equity=min(800.0, equity), available=available, committed=committed,
                     confidence=.70, stop_pct=stop_pct, gross_cap=min(800.0, equity) * .30,
                     risk_fraction=.005, notional_fraction=.20, peak_dd=view["peak_dd"],
                     drawdown_limit=float(HARD_STOP_DRAWDOWN), size_scale=view["risk_scale"],
                     trade_risk_budget=view["risk_trade_budget"])
