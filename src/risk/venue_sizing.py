"""Decimal venue constraints; report incompatibility, never increase risk caps."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from src.accounting.derive_margin import decimal


@dataclass(frozen=True)
class VenueSize:
    amount: Decimal
    price: Decimal
    minimum_notional: Decimal
    reason: str


def venue_size(*, budget, price, side, min_amount, amount_step, price_tick,
               min_notional=0, max_amount=None):
    budget, price, minimum, step, tick, min_quote = map(decimal,
        (budget, price, min_amount, amount_step, price_tick, min_notional))
    if side not in (1, -1) or min(budget, price, minimum, step, tick) <= 0 or min_quote < 0:
        raise ValueError("invalid_venue_size_inputs")
    limit = (price / tick).to_integral_value(rounding=ROUND_CEILING if side == 1 else ROUND_FLOOR) * tick
    if limit <= 0:
        raise ValueError("invalid_venue_price")
    exposure_price = max(price, limit)
    required = max(minimum, min_quote / limit)
    required = (required / step).to_integral_value(rounding=ROUND_CEILING) * step
    minimum_notional = required * exposure_price
    amount = (budget / exposure_price / step).to_integral_value(rounding=ROUND_FLOOR) * step
    if max_amount is not None:
        maximum = Decimal(str(max_amount))
        if maximum.is_nan() or maximum <= 0:
            raise ValueError("invalid_venue_maximum")
        if maximum.is_finite():
            amount = min(amount, (maximum / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if amount < required:
        return VenueSize(Decimal(0), limit, minimum_notional, "venue_minimum_exceeds_budget")
    if amount * exposure_price > budget:
        raise AssertionError("venue_size_exceeds_budget")
    return VenueSize(amount, limit, minimum_notional, "compatible")
