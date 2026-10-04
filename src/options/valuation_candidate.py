"""Tenor-matched and weighted shadow diagnostics; never authorize an order."""
import math

from src.options.pricing import black_price
from src.risk.position_sizing import depth_quote

YEAR = 365 * 86400


def tenor_variance_edges(options, forecasts, now, spot):
    """Forecasts must state exact remaining tenor; never silently annualize a
    short-horizon estimate into a multi-day forecast. Variance rates are /year.
    """
    if not math.isfinite(now + spot) or min(now, spot) <= 0:
        raise ValueError("invalid_tenor_reference")
    out = []
    for forecast in forecasts:
        expiry, rate, horizon, asof = (float(forecast[k]) for k in ("expiry", "variance_rate", "horizon_seconds", "as_of"))
        if (not all(math.isfinite(v) for v in (expiry, rate, horizon, asof)) or rate < 0
                or expiry <= now or abs(horizon - (expiry - now)) > 1 or not 0 <= now - asof <= 300):
            raise ValueError("tenor_matched_fresh_forecast_required")
        chosen = []
        for kind in ("call", "put"):
            qualified = [q for q in options if q["expiry"] == expiry and q["kind"] == kind
                         and q.get("quoted") and 0 <= now - q["timestamp"] <= 5
                         and q.get("pricing", {}).get("iv") is not None
                         and math.isfinite(q["pricing"]["iv"]) and q["pricing"]["iv"] > 0]
            if qualified:
                chosen.append(min(qualified, key=lambda q: abs(q["strike"] / spot - 1)))
        if len(chosen) != 2:
            continue
        iv_variance = sum(q["pricing"]["iv"] ** 2 for q in chosen) / 2
        out.append({"expiry": expiry, "remaining_seconds": horizon,
                    "forecast_variance_rate": rate, "observed_iv_variance_rate": iv_variance,
                    "integrated_variance_gap": (rate - iv_variance) * horizon / YEAR,
                    "instruments": [q["instrument"] for q in chosen], "entry_authorized": False})
    return out


def weighted_spread_value(buy, sell, now, quantity, horizon_seconds, scenarios, *,
                          entry_fees_quote, exit_fees_quote, probability_provenance):
    """Observed entry asks/bids; hypothetical future book wedges, not fills.

    Weights and spot/IV scenarios must come from the caller and are disclosed.
    An expectation conditional on invented weights is not empirical alpha.
    """
    if (buy["expiry"] != sell["expiry"] or buy["kind"] != sell["kind"]
            or buy["instrument"] == sell["instrument"] or quantity <= 0
            or not 0 < horizon_seconds < buy["expiry"] - now
            or (sell["strike"] - buy["strike"]) * (1 if buy["kind"] == "call" else -1) <= 0):
        raise ValueError("invalid_same_expiry_vertical")
    if (not isinstance(probability_provenance, str) or not probability_provenance.strip()
            or not 1 <= len(scenarios) <= 50 or min(entry_fees_quote, exit_fees_quote) < 0
            or not all(math.isfinite(v) for v in (now, quantity, horizon_seconds, entry_fees_quote, exit_fees_quote))):
        raise ValueError("invalid_weighted_valuation_spec")
    execution = {}
    for q in (buy, sell):
        if (not q["quoted"] or not 0 <= now - q["timestamp"] <= 5
                or not q["bids"] or not q["asks"]
                or not 0 < q["bids"][0][0] < q["asks"][0][0]):
            raise ValueError("fresh_executable_quotes_required")
        for side in ("bids", "asks"):
            quote = depth_quote(q[side], quantity)
            if quote is None:
                raise ValueError("insufficient_entry_or_reference_exit_depth")
            execution[q["instrument"], side] = quote.vwap
    debit = quantity * (execution[buy["instrument"], "asks"] - execution[sell["instrument"], "bids"])
    if debit <= 0:
        raise ValueError("positive_debit_required")
    rows, weights = [], []
    for scenario in scenarios:
        weight, move, shift = (float(scenario[k]) for k in ("probability", "spot_return", "iv_change"))
        if not all(math.isfinite(v) for v in (weight, move, shift)) or not 0 <= weight <= 1 or move <= -1:
            raise ValueError("invalid_spot_iv_scenario")
        prices = []
        for q, side in ((buy, "bids"), (sell, "asks")):
            p = q["pricing"]
            base = black_price(p["forward"], q["strike"], (q["expiry"] - now) / YEAR,
                               p["discount"], p["iv"], q["kind"])
            forward, iv = p["forward"] * (1 + move), p["iv"] + shift
            future = black_price(forward, q["strike"], (q["expiry"] - now - horizon_seconds) / YEAR,
                                 p["discount"], iv, q["kind"])
            bound = p["discount"] * (forward if q["kind"] == "call" else q["strike"])
            prices.append(min(bound, max(0, future + execution[q["instrument"], side] - base)))
        net = quantity * (prices[0] - prices[1]) - debit - entry_fees_quote - exit_fees_quote
        rows.append({"probability": weight, "spot_return": move, "iv_change": shift, "net_quote": net})
        weights.append(weight)
    if not math.isclose(sum(weights), 1, abs_tol=1e-9):
        raise ValueError("scenario_probabilities_must_sum_to_one")
    return {"expected_net_quote": sum(r["probability"] * r["net_quote"] for r in rows),
            "worst_scenario_net_quote": min(r["net_quote"] for r in rows), "scenarios": rows,
            "probability_provenance": probability_provenance, "calibrated": False,
            "expiry": buy["expiry"], "horizon_seconds": horizon_seconds,
            "entry_authorized": False, "interpretation": "conditional model expectation; future books and probabilities unverified"}
