"""Pure reconciliation checks for adapter-provided account snapshots."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Mapping, Set


def _d(value: Any) -> Decimal:
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    reasons: tuple[str, ...] = ()
    equity_delta: Decimal = Decimal("0")
    realized_pnl_delta: Decimal = Decimal("0")
    missing_order_ids: frozenset[str] = frozenset()
    unknown_order_ids: frozenset[str] = frozenset()
    position_deltas: Mapping[str, Decimal] = field(default_factory=dict)


def reconcile(
    local: Mapping[str, Any],
    venue: Mapping[str, Any],
    *,
    equity_tolerance: Decimal | str = Decimal("0.01"),
    pnl_tolerance: Decimal | str = Decimal("0.01"),
    position_tolerance: Decimal | str = Decimal("0.000001"),
) -> ReconciliationResult:
    """Compare normalized local and venue state without making network calls.

    ``local`` and ``venue`` are adapter boundary objects. The caller should
    safe-halt on ``ok == False`` before creating another executor.
    """

    equity_delta = _d(local.get("equity")) - _d(venue.get("equity"))
    pnl_delta = _d(local.get("realized_pnl")) - _d(venue.get("realized_pnl"))
    equity_limit = _d(equity_tolerance)
    pnl_limit = _d(pnl_tolerance)
    position_limit = _d(position_tolerance)

    local_orders: Set[str] = {str(x) for x in local.get("open_order_ids", ())}
    venue_orders: Set[str] = {str(x) for x in venue.get("open_order_ids", ())}
    missing = frozenset(venue_orders - local_orders)
    unknown = frozenset(local_orders - venue_orders)

    local_positions = local.get("positions", {}) or {}
    venue_positions = venue.get("positions", {}) or {}
    instruments = set(local_positions) | set(venue_positions)
    position_deltas = {
        instrument: _d(local_positions.get(instrument)) - _d(venue_positions.get(instrument))
        for instrument in instruments
        if abs(_d(local_positions.get(instrument)) - _d(venue_positions.get(instrument))) > position_limit
    }

    reasons = []
    if abs(equity_delta) > equity_limit:
        reasons.append("equity_drift")
    if abs(pnl_delta) > pnl_limit:
        reasons.append("realized_pnl_drift")
    if missing:
        reasons.append("missing_local_orders")
    if unknown:
        reasons.append("unknown_local_orders")
    if position_deltas:
        reasons.append("position_drift")

    return ReconciliationResult(
        ok=not reasons,
        reasons=tuple(reasons),
        equity_delta=equity_delta,
        realized_pnl_delta=pnl_delta,
        missing_order_ids=missing,
        unknown_order_ids=unknown,
        position_deltas=position_deltas,
    )
