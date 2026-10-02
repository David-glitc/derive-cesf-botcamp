"""Offline account/venue/compatibility boundary tests; never sign or submit."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.accounting.derive_margin import margin_snapshot, require_margin_state
from src.risk.venue_sizing import venue_size


def account_result():
    return {"subaccount_id": 7, "margin_type": "SM", "is_under_liquidation": False,
            "subaccount_value": "800", "initial_margin": "700", "maintenance_margin": "750",
            "projected_margin_change": "-10", "open_orders_margin": "-100",
            "positions": [], "open_orders": [], "collaterals": [{"asset_name": "USDC", "amount": "800"}]}


def test_signed_net_margin_not_collateral_or_double_counted_equity():
    s = margin_snapshot(account_result(), 7, 100)
    assert s["available"] == 600 and s["equity"] == 800
    assert require_margin_state(SimpleNamespace(_flyby_account_state=s), 105) is s
    with pytest.raises(ValueError, match="stale_verified_margin"):
        require_margin_state(SimpleNamespace(_flyby_account_state=s), 131)
    with pytest.raises(ValueError): require_margin_state(SimpleNamespace(), 100)


@pytest.mark.parametrize("key,value", [("subaccount_id", 8), ("margin_type", "PM"),
    ("is_under_liquidation", True), ("initial_margin", "NaN"), ("open_orders_margin", "1"),
    ("subaccount_value", "0"), ("maintenance_margin", "-1"), ("projected_margin_change", "-999"),
    ("failed_to_fetch", True), ("collaterals", [{"asset_name": "ETH", "amount": "1"}]),
    ("positions", [{"instrument_type": "option"}]), ("open_orders", None)])
def test_unhealthy_or_wrong_account_is_rejected(key, value):
    r = account_result(); r[key] = value
    with pytest.raises((ValueError, KeyError)): margin_snapshot(r, 7, 100)


@pytest.mark.parametrize("key", ["initial_margin", "maintenance_margin", "open_orders_margin",
                                  "subaccount_value", "positions", "collaterals", "open_orders"])
def test_missing_fields_do_not_fall_back_to_cash(key):
    r = account_result(); del r[key]
    with pytest.raises((ValueError, KeyError)): margin_snapshot(r, 7, 100)


def test_negative_initial_margin_yields_zero_capacity():
    r = account_result(); r["initial_margin"] = "-1"
    assert margin_snapshot(r, 7, 100)["available"] == 0


@pytest.mark.parametrize("price,minimum", [("2717.93", ".1"), ("85406.4", ".01")])
def test_current_eth_btc_minimums_never_raise_risk(price, minimum):
    size = venue_size(budget=160, price=price, side=1, min_amount=minimum,
                      amount_step=".001", price_tick=".01")
    assert size.amount == 0 and size.reason == "venue_minimum_exceeds_budget"
    assert size.minimum_notional > 160


@pytest.mark.parametrize("side", [1, -1])
def test_tick_and_lot_rounding_stays_within_budget(side):
    size = venue_size(budget="160", price="150.013", side=side, min_amount=".1",
                      amount_step=".01", price_tick=".05", max_amount="Infinity")
    assert size.amount % Decimal(".01") == 0 and size.price % Decimal(".05") == 0
    assert size.amount * max(size.price, Decimal("150.013")) <= 160
    assert size.price >= Decimal("150.013") if side == 1 else size.price <= Decimal("150.013")


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "0"])
def test_bad_venue_increment_is_rejected(bad):
    with pytest.raises(ValueError):
        venue_size(budget=160, price=150, side=1, min_amount=".1", amount_step=bad, price_tick=".01")
