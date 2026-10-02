"""Pure authoritative-account and reduce-only intent contracts. No private client."""
from decimal import Decimal

from src.accounting.reconciliation import reconcile
from src.execution.paired import remaining_position


def decimal(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite authoritative account field")
    return result


def close_intent(position_lots, requested_lots, pending_close_lots=0):
    if type(position_lots) is not int or any(type(x) is not int or x < 0 for x in (requested_lots, pending_close_lots)):
        raise ValueError("signed integer position and nonnegative close lots required")
    quantity = min(requested_lots, max(0, abs(position_lots) - pending_close_lots))
    if quantity == 0:
        return None
    return {"side": "sell" if position_lots > 0 else "buy", "lots": quantity,
            "reduce_only": True, "remaining_after_this_close": remaining_position(position_lots, quantity),
            "scope": "intent only; backend must enforce reduce-only atomically"}


class AccountMirror:
    """Replace entire confirmed snapshots, including empty positions, without guessing margin."""
    def __init__(self):
        self.snapshot = None

    def replace(self, observation, now):
        required = {"network", "api_generation", "received_at", "equity", "available_margin", "margin_source",
                    "realized_pnl", "positions", "open_order_ids"}
        if not required.issubset(observation) or observation["network"] != "mainnet" or observation["api_generation"] != "legacy_v2":
            raise ValueError("authoritative account provenance mismatch")
        if observation["margin_source"] != "verified_free_margin":
            raise ValueError("collateral balance is not verified free margin")
        received = decimal(observation["received_at"])
        if not 0 <= decimal(now) - received <= 5 or (self.snapshot and received <= self.snapshot["received_at"]):
            raise ValueError("stale/future/reordered authoritative account")
        equity, available = decimal(observation["equity"]), decimal(observation["available_margin"])
        if equity <= 0 or available < 0:
            raise ValueError("invalid authoritative equity/margin")
        positions = {str(k): decimal(v) for k, v in observation["positions"].items()}
        orders = observation["open_order_ids"]
        if not isinstance(orders, (list, tuple)) or any(not isinstance(x, str) or not x for x in orders) or len(set(orders)) != len(orders):
            raise ValueError("invalid authoritative order identities")
        self.snapshot = {"received_at": received, "equity": equity, "available_margin": available,
                         "realized_pnl": decimal(observation["realized_pnl"]),
                         "positions": {k:v for k,v in positions.items() if v != 0}, "open_order_ids": list(orders)}
        return self.snapshot

    def matches(self, local):
        if self.snapshot is None:
            return False
        return reconcile(local, self.snapshot).ok
