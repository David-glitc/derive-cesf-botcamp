"""Pinned HB recovery wrapper, deliberately NOT registered for live execution.

An independent fixture journal survives terminal tracker eviction and process
restart. No venue credentials, automatic adoption, or native stop guarantees.
"""
from decimal import Decimal
from uuid import uuid4

from hummingbot.core.data_type.common import PositionAction, TradeType
from hummingbot.strategy_v2.executors.position_executor.position_executor import PositionExecutor
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder

from src.execution.fill_journal import FillJournal, ZERO


class JournaledRecoveryCandidate(PositionExecutor):
    def __init__(self, strategy, config, *args, journal_path=None, **kwargs):
        if (getattr(strategy, "flyby_offline_replay", False) is not True or journal_path is None
                or config.connector_name != "derive_perpetual" or not config.controller_id.startswith("flyby-")):
            raise ValueError("recovery_candidate_requires_explicit_offline_fixture")
        connector = strategy.connectors[config.connector_name]
        self.journal = FillJournal(journal_path, f"fixture:{connector._subacct_id}", config.trading_pair, config.id)
        self.reconciliation_required = bool(self.journal.orders() or self.journal.pending_intents())
        self._close_history = []
        super().__init__(strategy, config, *args, **kwargs)
        for order_id, role, _, _, status in self.journal.orders():
            tracked = TrackedOrder(order_id=order_id)
            tracked.order = self.get_in_flight_order(config.connector_name, order_id)
            if role == "entry":
                self._open_order = tracked
            else:
                self._close_history.append(tracked)
                if status not in ("filled", "canceled", "failed"):
                    self._close_order = tracked

    @property
    def open_filled_amount(self):
        return self.journal.totals()["entry_base"]

    @property
    def close_filled_amount(self):
        return self.journal.totals()["close_base"]

    @property
    def close_filled_amount_quote(self):
        return self.journal.totals()["close_quote"]

    @property
    def entry_price(self):
        totals = self.journal.totals()
        return totals["entry_quote"] / totals["entry_base"] if totals["entry_base"] else super().entry_price

    @property
    def close_price(self):
        if self.open_filled_amount:
            return (self.close_filled_amount_quote + self.amount_to_close * self.current_market_price) / self.open_filled_amount
        return super().close_price

    def get_cum_fees_quote(self):
        return self.journal.totals()["fees_quote"]

    def place_order(self, **kwargs):
        role = "close" if kwargs["position_action"] == PositionAction.CLOSE else "entry"
        if role == "close" and not ZERO < kwargs["amount"] <= self.amount_to_close:
            raise ValueError("invalid_residual_close_amount")
        if self.reconciliation_required or self.journal.pending_intents():
            raise ValueError("reconciliation_required_before_transport")
        intent = uuid4().hex
        self.journal.intent(intent, role, 1 if kwargs["side"] == TradeType.BUY else -1,
                            kwargs["amount"], self._strategy.current_timestamp)
        # Crash between these calls retains an ambiguous intent and blocks restart.
        try:
            order_id = super().place_order(**kwargs)
            self.journal.acknowledge(intent, order_id)
        except Exception:
            self.reconciliation_required = True
            raise
        return order_id

    def update_tracked_orders_with_order_id(self, order_id):
        order = self.get_in_flight_order(self.config.connector_name, order_id)
        for tracked in [self._open_order, self._close_order, *self._close_history]:
            if tracked and tracked.order_id == order_id and order is not None:
                tracked.order = order

    def process_order_filled_event(self, tag, market, event):
        if not self.journal.owns(event.order_id):
            return
        quote = self.config.trading_pair.split("-")[1]
        fee = event.trade_fee
        if ((fee.percent and fee.percent_token != quote) or any(f.token != quote for f in fee.flat_fees)):
            self.reconciliation_required = True
            raise ValueError("unverified_fee_currency_requires_reconciliation")
        paid = event.amount * event.price * fee.percent + sum((f.amount for f in fee.flat_fees), ZERO)
        try:
            self.journal.fill(event.exchange_trade_id, event.order_id, event.amount, event.price, paid, event.timestamp)
        except Exception:
            self.reconciliation_required = True
            raise
        super().process_order_filled_event(tag, market, event)
        if self.is_closed and self.amount_to_close != ZERO:
            self.reconciliation_required = True

    def process_order_completed_event(self, tag, market, event):
        if self.journal.owns(event.order_id):
            self.journal.status(event.order_id, "filled", event.timestamp)
            super().process_order_completed_event(tag, market, event)

    def _terminal(self, tag, market, event, status):
        if not self.journal.owns(event.order_id):
            return
        entry = self._open_order if self._open_order and self._open_order.order_id == event.order_id else None
        if self._close_order and self._close_order.order_id == event.order_id:
            self._close_history.append(self._close_order)
        self.journal.status(event.order_id, status, event.timestamp)
        method = super().process_order_canceled_event if status == "canceled" else super().process_order_failed_event
        method(tag, market, event)
        if entry:
            self._open_order = entry
            self.early_stop()

    def process_order_canceled_event(self, tag, market, event):
        self._terminal(tag, market, event, "canceled")

    def process_order_failed_event(self, tag, market, event):
        self._terminal(tag, market, event, "failed")

    def control_barriers(self):
        if self.open_filled_amount > ZERO:
            for barrier in (self.control_stop_loss, self.control_trailing_stop, self.control_take_profit):
                barrier()
                if self.status != RunnableStatus.RUNNING:
                    return
        self.control_time_limit()

    def all_orders_completed(self):
        return all(row[4] in ("filled", "canceled", "failed") for row in self.journal.orders())

    def open_and_close_volume_match(self):
        return self.amount_to_close == ZERO and self.all_orders_completed()

    def _collect_held_position_orders(self):
        # These are journal records, not upstream to_json or oracle conversions.
        return self.journal.held_evidence()

    def evaluate_max_retries(self):
        if self._current_retries > self._max_retries and self.amount_to_close != ZERO:
            self.reconciliation_required = True
            self.force_stop_with_position_hold()
        else:
            super().evaluate_max_retries()

    async def control_task(self):
        if self.reconciliation_required:
            return
        attempts = sum(row[1] == "close" for row in self.journal.orders())
        if attempts >= self._max_retries + 1 and self.amount_to_close > ZERO and self._close_order is None:
            self.reconciliation_required = True
            self.force_stop_with_position_hold()
            return
        await super().control_task()
        if self.amount_to_close != ZERO and self.amount_to_close < self.trading_rules.min_order_size:
            self.reconciliation_required = True

    def resume_recovery(self, snapshot):
        plan = self.journal.reconcile(snapshot, self._strategy.current_timestamp,
                                      minimum_amount=self.trading_rules.min_order_size,
                                      amount_step=self.trading_rules.min_base_amount_increment)
        if plan["reason"] == "reduce_only_recovery_required":
            if sum(row[1] == "close" for row in self.journal.orders()) >= self._max_retries + 1:
                return {**plan, "reason": "lifetime_close_attempt_budget_exhausted", "close_amount": "0"}
            self.reconciliation_required = False
            self.close_type = CloseType.EARLY_STOP
            self._status = RunnableStatus.SHUTTING_DOWN
        return plan

    def get_custom_info(self):
        return {**super().get_custom_info(), "candidate_only": True,
                "reconciliation_required": self.reconciliation_required,
                "residual_base": str(self.amount_to_close), "journal_evidence": self.journal.held_evidence()}
