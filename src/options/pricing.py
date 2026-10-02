"""Venue-input Black-76 diagnostics, not a calibrated edge or executable mark."""
import math

from src.data.records import number


def black_price(forward, strike, years, discount, iv, kind):
    values = [number(v) for v in (forward, strike, years, discount, iv)]
    forward, strike, years, discount, iv = values
    if min(forward, strike, discount, iv) <= 0 or years < 0 or kind not in ("call", "put"):
        raise ValueError("invalid Black-76 inputs")
    if years == 0:
        return discount * max((forward - strike) * (1 if kind == "call" else -1), 0)
    z = iv * math.sqrt(years)
    d1 = (math.log(forward / strike) + .5 * z * z) / z
    d2 = d1 - z
    normal = lambda x: .5 * (1 + math.erf(x / math.sqrt(2)))
    if kind == "call":
        return discount * (forward * normal(d1) - strike * normal(d2))
    return discount * (strike * normal(-d2) - forward * normal(-d1))


def option_diagnostic(quote, now, forecast_iv=None):
    p = quote["pricing"]
    out = {"instrument": quote["instrument"], "quoted": quote["quoted"],
           "mark_model": None, "forecast_model": None, "model_error": None,
           "model_minus_ask": None, "scenario_prices": None,
           "interpretation": "model diagnostic, not predicted profit or a fill"}
    years = (quote["expiry"] - now) / (365 * 86400)
    try:
        out["mark_model"] = black_price(p["forward"], quote["strike"], years, p["discount"], p["iv"], quote["kind"])
        if p["mark"] is not None:
            out["model_error"] = out["mark_model"] - p["mark"]
        if forecast_iv is not None and forecast_iv > 0:
            out["forecast_model"] = black_price(p["forward"], quote["strike"], years, p["discount"], forecast_iv, quote["kind"])
        if quote["quoted"] and out["forecast_model"] is not None:
            out["model_minus_ask"] = out["forecast_model"] - quote["asks"][0][0]
        out["scenario_prices"] = {}
        for name, move, vol_change in (("down_1pct", -.01, 0), ("up_1pct", .01, 0),
                                       ("iv_down_5pts", 0, -.05), ("iv_up_5pts", 0, .05)):
            out["scenario_prices"][name] = black_price(p["forward"] * (1 + move), quote["strike"],
                max(0, years - 3600 / (365 * 86400)), p["discount"], max(.001, p["iv"] + vol_change), quote["kind"])
    except (ValueError, TypeError, KeyError):
        out["reason"] = "missing_or_invalid_pricing_inputs"
    return out
