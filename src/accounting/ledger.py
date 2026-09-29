"""Idempotent accounting for events emitted by the Hummingbot adapter.

This module deliberately has no venue client. Hummingbot/Derive supplies the
events and account snapshots; the ledger only normalizes and records them.
That keeps accounting deterministic across restarts and prevents a second
private REST path from competing with the adapter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


@dataclass(frozen=True)
class FillEvent:
    """A normalized fill event from Hummingbot/Derive."""

    trade_id: str
    order_id: str
    instrument: str
    side: str
    amount: Decimal
    price: Decimal
    fee: Decimal = Decimal("0")
    rebate: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    realized_pnl_ex_fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    liquidity_role: str = "unknown"
    timestamp: float = 0.0

    @classmethod
    def from_mapping(cls, value: Dict[str, Any]) -> "FillEvent":
        """Build an event from normalized adapter fields."""

        return cls(
            trade_id=str(value["trade_id"]),
            order_id=str(value.get("order_id", "")),
            instrument=str(value["instrument"]),
            side=str(value["side"]).lower(),
            amount=_decimal(value.get("amount")),
            price=_decimal(value.get("price")),
            fee=_decimal(value.get("fee", value.get("trade_fee"))),
            rebate=_decimal(value.get("rebate", value.get("expected_rebate"))),
            realized_pnl=_decimal(value.get("realized_pnl")),
            realized_pnl_ex_fees=_decimal(value.get("realized_pnl_ex_fees")),
            funding=_decimal(value.get("funding")),
            liquidity_role=str(value.get("liquidity_role", "unknown")),
            timestamp=float(value.get("timestamp", 0) or 0),
        )


@dataclass(frozen=True)
class FundingEvent:
    event_id: str
    instrument: str
    amount: Decimal
    timestamp: float = 0.0

    @classmethod
    def from_mapping(cls, value: Dict[str, Any]) -> "FundingEvent":
        return cls(
            event_id=str(value["event_id"]),
            instrument=str(value["instrument"]),
            amount=_decimal(value.get("amount")),
            timestamp=float(value.get("timestamp", 0) or 0),
        )


@dataclass
class LedgerState:
    fills: Dict[str, FillEvent] = field(default_factory=dict)
    funding_events: Dict[str, FundingEvent] = field(default_factory=dict)
    volume_quote: Decimal = Decimal("0")
    fees_paid: Decimal = Decimal("0")
    rebates: Decimal = Decimal("0")
    reported_realized_pnl: Decimal = Decimal("0")
    realized_pnl_ex_fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")


class AccountingLedger:
    """Apply normalized fills/funding exactly once and expose audit totals."""

    def __init__(self, state: LedgerState | None = None):
        self.state = state or LedgerState()

    def apply_fill(self, event: FillEvent | Dict[str, Any]) -> bool:
        event = event if isinstance(event, FillEvent) else FillEvent.from_mapping(event)
        if event.trade_id in self.state.fills:
            return False
        self.state.fills[event.trade_id] = event
        self.state.volume_quote += abs(event.amount * event.price)
        self.state.fees_paid += event.fee
        self.state.rebates += event.rebate
        self.state.reported_realized_pnl += event.realized_pnl
        self.state.realized_pnl_ex_fees += event.realized_pnl_ex_fees
        self.state.funding += event.funding
        return True

    def apply_funding(self, event: FundingEvent | Dict[str, Any]) -> bool:
        event = event if isinstance(event, FundingEvent) else FundingEvent.from_mapping(event)
        if event.event_id in self.state.funding_events:
            return False
        self.state.funding_events[event.event_id] = event
        self.state.funding += event.amount
        return True

    def replay(self, fills: Iterable[FillEvent | Dict[str, Any]] = (), funding: Iterable[FundingEvent | Dict[str, Any]] = ()) -> None:
        for event in fills:
            self.apply_fill(event)
        for event in funding:
            self.apply_funding(event)

    @property
    def net_cash_pnl(self) -> Decimal:
        """Net P&L reconstructed from explicit event fields."""

        return self.state.realized_pnl_ex_fees - self.state.fees_paid + self.state.rebates + self.state.funding

    def snapshot(self) -> Dict[str, Any]:
        return {
            "fill_count": len(self.state.fills),
            "funding_event_count": len(self.state.funding_events),
            "volume_quote": str(self.state.volume_quote),
            "fees_paid": str(self.state.fees_paid),
            "rebates": str(self.state.rebates),
            "reported_realized_pnl": str(self.state.reported_realized_pnl),
            "realized_pnl_ex_fees": str(self.state.realized_pnl_ex_fees),
            "funding": str(self.state.funding),
            "net_cash_pnl": str(self.net_cash_pnl),
            "trade_ids": sorted(self.state.fills),
            "funding_ids": sorted(self.state.funding_events),
        }

    def export_state(self) -> Dict[str, Any]:
        return {
            "fills": [asdict(event) for event in self.state.fills.values()],
            "funding_events": [asdict(event) for event in self.state.funding_events.values()],
        }
