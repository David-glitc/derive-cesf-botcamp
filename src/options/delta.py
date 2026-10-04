"""Signed per-underlying exposure bounds. Planning only, never hedge orders.

Dollar delta is price sensitivity times reference spot, not premium or maximum
loss. Gross reference notional is deliberately conservative for option spreads.
Outstanding orders are an interval of possible fills, not credited as hedges.
"""
from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_FLOOR
import math
from src.risk.exposure import BASELINE_EXPOSURE, exposure_limits


def decimal(value):
    if isinstance(value, bool):
        raise ValueError("invalid_delta_number")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("invalid_delta_number")
    return result


def moneyness(kind, strike, spot):
    strike, spot = decimal(strike), decimal(spot)
    if kind not in ("call", "put") or min(strike, spot) <= 0:
        raise ValueError("invalid_moneyness")
    # Explicit 0.5% ATM window; a selection convention, not a delta definition.
    if abs(strike / spot - 1) <= Decimal("0.005"):
        return "ATM"
    return "ITM" if ((spot > strike) == (kind == "call")) else "OTM"


@dataclass(frozen=True)
class DeltaPolicy:
    spot: float
    net_cap_quote: float
    gross_cap_quote: float
    existing_units: float = 0.0
    pending_buy_units: float = 0.0
    pending_sell_units: float = 0.0
    committed_gross_quote: float = 0.0
    buy_min: float = .25
    buy_max: float = .70
    sell_min: float = .10
    sell_max: float = .35
    buy_target: float = .50
    sell_target: float = .25
    buy_moneyness: str = "any"
    underlying: str | None = None

    def __post_init__(self):
        values = {k: decimal(v) for k, v in asdict(self).items() if k not in ("buy_moneyness", "underlying")}
        if (values["spot"] <= 0 or min(values[k] for k in
                ("net_cap_quote", "gross_cap_quote", "pending_buy_units", "pending_sell_units",
                 "committed_gross_quote")) < 0
                or not 0 < values["buy_min"] <= values["buy_target"] <= values["buy_max"] <= 1
                or not 0 < values["sell_min"] <= values["sell_target"] <= values["sell_max"] <= 1
                or self.buy_moneyness not in ("any", "ATM", "OTM", "ITM")
                or self.underlying not in (None, "ETH", "BTC", "SOL", "HYPE")):
            raise ValueError("invalid_delta_policy")
        for key, value in values.items():
            numeric = float(value)
            if not math.isfinite(numeric):
                raise ValueError("invalid_delta_number")
            object.__setattr__(self, key, numeric)

    def to_dict(self):
        return asdict(self)


def account_policy(spot, equity, *, scale=1, net_fraction=.20, gross_fraction=.30,
                   exposure_profile=BASELINE_EXPOSURE, **kwargs):
    spot, equity, scale = float(decimal(spot)), float(decimal(equity)), float(decimal(scale))
    limits = exposure_limits(exposure_profile, kwargs.get("underlying"))
    if (equity <= 0 or not 0 <= scale <= 1 or not 0 < net_fraction <= limits["option_net"]
            or not 0 < gross_fraction <= limits["option_gross"]):
        raise ValueError("invalid_delta_account_budget")
    return DeltaPolicy(spot=spot, net_cap_quote=equity * net_fraction * scale,
                       gross_cap_quote=equity * gross_fraction * scale, **kwargs)


def exposure(policy, buy_delta, sell_delta, buy_amount, sell_amount, multiplier=1):
    b, s, bq, sq, mult = map(decimal, (buy_delta, sell_delta, buy_amount, sell_amount, multiplier))
    if max(abs(b), abs(s)) > 1 or min(bq, sq) < 0 or mult <= 0:
        raise ValueError("invalid_delta_legs")
    net = (b * bq - s * sq) * mult
    low = decimal(policy.existing_units) - decimal(policy.pending_sell_units) + net
    high = decimal(policy.existing_units) + decimal(policy.pending_buy_units) + net
    spot = decimal(policy.spot)
    worst = max(abs(low), abs(high)) * spot
    gross = decimal(policy.committed_gross_quote) + (bq + sq) * mult * spot
    return {"net_delta": float(net), "net_delta_quote": float(net * spot),
            "portfolio_delta_low": float(low), "portfolio_delta_high": float(high),
            "worst_delta_quote": float(worst), "gross_reference_quote": float(gross),
            "net_cap_quote": policy.net_cap_quote, "gross_cap_quote": policy.gross_cap_quote,
            "within_caps": worst <= decimal(policy.net_cap_quote) and gross <= decimal(policy.gross_cap_quote)}


def amount_limit(policy, buy_delta, sell_delta, multiplier, step):
    """No offset credit; cap matched and either-leg-only hypothetical fills.

    This bounds directional sensitivity during a fault; it cannot bound losses
    of an unmatched short option and does not authorize legging.
    """
    b, s, mult, step = map(decimal, (buy_delta, sell_delta, multiplier, step))
    if max(abs(b), abs(s)) > 1 or min(mult, step) <= 0:
        raise ValueError("invalid_delta_legs")
    low = decimal(policy.existing_units) - decimal(policy.pending_sell_units)
    high = decimal(policy.existing_units) + decimal(policy.pending_buy_units)
    room = decimal(policy.net_cap_quote) / decimal(policy.spot) - max(abs(low), abs(high))
    gross_room = decimal(policy.gross_cap_quote) - decimal(policy.committed_gross_quote)
    if min(room, gross_room) <= 0:
        return 0.0
    worst_per_unit = max(abs(b), abs(s), abs(b - s)) * mult
    gross_limit = gross_room / (2 * mult * decimal(policy.spot))
    limit = min(gross_limit, room / worst_per_unit) if worst_per_unit else gross_limit
    return float((limit / step).to_integral_value(rounding=ROUND_FLOOR) * step)


def delta_context(plan, now):
    """Small numeric allowlist for Condor; arbitrary plan payloads stay private."""
    if not isinstance(plan, dict):
        return {"status": "no_plan", "live_options": False}
    result = {"status": "stale_or_unverified", "live_options": False}
    result["underlying"] = plan.get("underlying") if plan.get("underlying") in ("ETH", "BTC") else None
    for key in ("net_delta", "net_delta_quote", "worst_delta_quote", "gross_reference_quote",
                "net_cap_quote", "gross_cap_quote", "buy_delta", "sell_delta", "amount",
                "max_loss", "debit", "valid_until", "delta_target"):
        try:
            value = float(decimal(plan.get(key)))
            result[key] = value if math.isfinite(value) else None
        except (ValueError, TypeError, ArithmeticError):
            result[key] = None
    for key in ("buy_moneyness", "sell_moneyness"):
        result[key] = plan.get(key) if plan.get(key) in ("ATM", "OTM", "ITM") else "unknown"
    verified = plan.get("delta_verified") is True and all(result[k] is not None for k in
        ("net_delta", "net_delta_quote", "worst_delta_quote", "gross_reference_quote", "net_cap_quote",
         "gross_cap_quote", "buy_delta", "sell_delta", "amount", "max_loss", "debit", "delta_target"))
    if verified:
        verified = (result["amount"] > 0 and result["max_loss"] > 0 and result["debit"] > 0
                    and 0 <= result["worst_delta_quote"] <= result["net_cap_quote"]
                    and 0 <= result["gross_reference_quote"] <= result["gross_cap_quote"]
                    and 0 < abs(result["sell_delta"]) < abs(result["buy_delta"]) <= 1
                    and result["sell_delta"] * result["buy_delta"] > 0)
    expiry = result["valid_until"]
    try:
        now = float(decimal(now))
    except (ValueError, TypeError, ArithmeticError):
        now = -1
    if verified and now >= 0 and expiry is not None and 0 <= expiry - now <= 5:
        result["status"] = "fresh_shadow_plan"
    result["delta_verified"] = verified and result["status"] == "fresh_shadow_plan"
    result["fees_verified"] = plan.get("fees_verified") is True and result["status"] == "fresh_shadow_plan"
    result["hedge_orders_enabled"] = False
    return result
