"""Strict legacy get_subaccount normalization; no credentials or transport.

Schema: derivexyz/orderbook-stubs, typescript/private.get_subaccount.ts.
Initial margin is a signed net cushion, not a positive margin requirement.
Open-order margin is signed too: available cushion = initial + order margin.
"""
from decimal import Decimal, InvalidOperation
import math


def decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_venue_decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("invalid_venue_decimal") from exc
    if not result.is_finite():
        raise ValueError("nonfinite_venue_decimal")
    return result


def margin_snapshot(result, expected_subaccount, observed_at):
    """Accept only full SM snapshots with USDC collateral and perpetual positions.

    We cap usable notional by the net margin cushion without multiplying by
    leverage. This is conservative capacity, not withdrawable cash or a promise
    that a prospective order passes the venue's own margin checks.
    """
    if not isinstance(result, dict) or result.get("subaccount_id") != expected_subaccount:
        raise ValueError("subaccount_snapshot_mismatch")
    if (result.get("margin_type") != "SM" or result.get("is_under_liquidation") is not False
            or result.get("failed_to_fetch", False) is not False):
        raise ValueError("unsupported_or_unhealthy_margin")
    if not math.isfinite(observed_at) or observed_at <= 0:
        raise ValueError("invalid_margin_timestamp")
    equity = decimal(result["subaccount_value"])
    initial = decimal(result["initial_margin"])
    maintenance = decimal(result["maintenance_margin"])
    orders_margin = decimal(result["open_orders_margin"])
    projected = decimal(result["projected_margin_change"])
    if equity <= 0 or orders_margin > 0 or maintenance < 0 or maintenance + projected < 0:
        raise ValueError("unhealthy_margin_cushion")
    collaterals, positions, orders = (result[key] for key in ("collaterals", "positions", "open_orders"))
    if not all(isinstance(items, list) for items in (collaterals, positions, orders)):
        raise ValueError("incomplete_account_snapshot")
    balances = {}
    for row in collaterals:
        if row.get("asset_name") != "USDC" or "USDC" in balances:
            raise ValueError("unsupported_collateral")
        amount = decimal(row["amount"])
        if amount < 0:
            raise ValueError("borrowed_collateral_not_supported")
        balances["USDC"] = amount
    for row in positions:
        if row.get("instrument_type") != "perp":
            raise ValueError("unsupported_account_position")
    capacity = max(Decimal(0), min(equity, initial + orders_margin, balances.get("USDC", Decimal(0))))
    return {"equity": equity, "available": capacity, "initial_margin": initial,
            "maintenance_margin": maintenance, "open_orders_margin": orders_margin,
            "observed_at": observed_at, "balances": balances, "positions": positions,
            "open_orders": orders, "source": "authenticated_legacy_get_subaccount",
            "margin_type": "SM"}


def require_margin_state(connector, now, max_age=30):
    state = getattr(connector, "_flyby_account_state", None)
    if not isinstance(state, dict) or state.get("source") != "authenticated_legacy_get_subaccount":
        raise ValueError("verified_margin_unavailable")
    if not 0 <= now - state["observed_at"] <= max_age:
        raise ValueError("stale_verified_margin")
    if decimal(state["equity"]) <= 0 or decimal(state["available"]) < 0:
        raise ValueError("invalid_verified_margin")
    return state
