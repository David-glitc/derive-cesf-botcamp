"""Explicit-unit Black-76 and lean-sleeve diagnostics; not order authority."""
import math

from src.options.pricing import black_price

YEAR = 365 * 86400


def greeks(forward, strike, years, discount, iv, kind):
    price = black_price(forward, strike, years, discount, iv, kind)
    if years <= 0:
        raise ValueError("positive_tenor_required_for_greeks")
    root = math.sqrt(years)
    d1 = (math.log(forward / strike) + .5 * iv * iv * years) / (iv * root)
    n = math.exp(-.5 * d1 * d1) / math.sqrt(2 * math.pi)
    cdf = .5 * (1 + math.erf(d1 / math.sqrt(2)))
    vega = discount * forward * n * root
    return dict(price=price, delta_forward=discount * (cdf - (kind == "put")),
                gamma_forward=discount * n / (forward * iv * root),
                vega_per_unit_iv=vega, vega_per_vol_point=vega * .01,
                theta_per_calendar_day_fixed_discount=-discount * forward * n * iv / (2 * root * 365),
                units="per underlying unit; forward Greeks; theta holds forward/discount/IV fixed")


def quote_diagnostic(quote, now):
    p = quote["pricing"]
    out = dict(instrument=quote["instrument"], api_greeks={k: p.get(k) for k in
               ("delta", "gamma", "vega", "theta")}, model_greeks=None,
               source="venue inputs; no historical backfill", entry_authorized=False,
               api_vega_theta_units_verified=False)
    try:
        g = greeks(p["forward"], quote["strike"], (quote["expiry"] - now) / YEAR,
                   p["discount"], p["iv"], quote["kind"])
        out["model_greeks"] = g
        out["delta_difference"] = g["delta_forward"] - p["delta"] if p.get("delta") is not None else None
        out["gamma_difference"] = g["gamma_forward"] - p["gamma"] if p.get("gamma") is not None else None
    except (ValueError, TypeError, KeyError):
        out["reason"] = "missing_or_invalid_pricing_inputs"
    return out


def lean_gate(*, debit, fee_reserve, max_loss, budget, expected_credit, theta_drag,
              fee_budget_fraction=.25):
    values = (debit, fee_reserve, max_loss, budget, expected_credit, theta_drag, fee_budget_fraction)
    if not all(math.isfinite(v) for v in values) or min(debit, max_loss, budget) <= 0:
        return False
    if min(fee_reserve, theta_drag) < 0 or not 0 < fee_budget_fraction <= .25:
        return False
    # Fees are inside max_loss, not added twice. Repricing already includes theta;
    # the theta check is a separate carry limit, not another P&L subtraction.
    return (max_loss >= debit + fee_reserve and max_loss <= budget
            and fee_reserve <= fee_budget_fraction * budget
            and theta_drag <= .25 * budget
            and expected_credit - debit - fee_reserve > 0)
