"""Simulation-only atomic-package lifecycle. Faults retain reservations/exposure.

This is not an exchange adapter. Independent-leg placement and live mode are
intentionally absent. Quantities are integer instrument lots; budgets cents.
"""
from dataclasses import asdict, dataclass, replace
import math


def matched_report_guard(previous_buy, previous_sell, buy, sell, limit, combine=all):
    """The same arithmetic guard is imported by the SMT verifier."""
    return combine((buy >= previous_buy, sell >= previous_sell, buy == sell,
                    buy <= limit, sell <= limit))


def entry_guard(paused, fresh, reconciled, flat, pending, daily_pnl, peak_dd, combine=all):
    return combine((~paused if not isinstance(paused, bool) else not paused,
                    fresh, reconciled, flat,
                    ~pending if not isinstance(pending, bool) else not pending,
                    daily_pnl > -.02, peak_dd > -.04))


def reserve_guard(committed, request, budget, combine=all):
    return combine((committed >= 0, committed <= budget, request > 0, request <= budget - committed))


def remaining_position(position, close_quantity, choose=lambda cond, yes, no: yes if cond else no):
    return choose(position >= 0, position - close_quantity, position + close_quantity)


@dataclass(frozen=True)
class State:
    phase: str = "flat"
    target: int = 0
    open_buy: int = 0
    open_sell: int = 0
    close_buy: int = 0
    close_sell: int = 0
    reserved: int = 0
    reason: str = ""
    reported: tuple | None = None

    @property
    def exposure(self):
        return self.open_buy - self.close_buy, self.open_sell - self.close_sell


def integers(*values):
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("nonnegative integer lots/cents required")


def transition(state, event):
    """Pure reducer. An unsafe report halts; it doesn't pretend the account is flat."""
    kind = event["type"]
    if state.phase == "halted":
        return state
    if kind == "prepare":
        target, reserve, budget = (event[k] for k in ("target", "reserve", "budget"))
        integers(target, reserve, budget)
        flags = event.get("guards", {})
        if set(flags) - {"paused", "fresh", "reconciled", "daily_pnl", "peak_dd"}:
            raise ValueError("invalid guard schema")
        if any(type(flags.get(k, default)) is not bool for k, default in (("paused", True), ("fresh", False), ("reconciled", False))):
            raise ValueError("boolean guards required")
        if any(not math.isfinite(flags.get(k, -1)) for k in ("daily_pnl", "peak_dd")):
            raise ValueError("finite risk guards required")
        allowed = entry_guard(flags.get("paused", True), flags.get("fresh", False), flags.get("reconciled", False),
                              state.phase == "flat", state.reserved > 0,
                              flags.get("daily_pnl", -1), flags.get("peak_dd", -1))
        if not allowed or not reserve_guard(state.reserved, reserve, budget) or target <= 0:
            return state
        return State(phase="opening", target=target, reserved=reserve)
    if kind == "request_close":
        return replace(state, phase="closing") if state.phase == "open" else state
    if kind == "timeout":
        return replace(state, phase="halted", reason="unknown_pending_package") if state.phase in ("opening", "closing") else state
    if kind not in ("open_report", "close_report"):
        raise ValueError("unknown package event")
    buy, sell, terminal = event["buy"], event["sell"], event.get("terminal", False)
    integers(buy, sell)
    if type(terminal) is not bool:
        raise ValueError("terminal must be bool")
    opening = kind == "open_report"
    phase = "opening" if opening else "closing"
    prev_b, prev_s = (state.open_buy, state.open_sell) if opening else (state.close_buy, state.close_sell)
    limit = state.target if opening else state.open_buy
    if state.phase != phase or not matched_report_guard(prev_b, prev_s, buy, sell, limit):
        return replace(state, phase="halted", reason="unmatched_or_conflicting_package_report", reported=(buy, sell))
    if opening:
        updated = replace(state, open_buy=buy, open_sell=sell)
        if terminal:
            return State() if buy == 0 else replace(updated, phase="open")
    else:
        updated = replace(state, close_buy=buy, close_sell=sell)
        if terminal:
            if buy == state.open_buy:
                return State()
            return replace(updated, phase="open")
    return updated


def invariant(state):
    if state.phase == "halted":
        # External faults aren't a no-exposure guarantee. Reservation remains.
        return state.reserved >= 0 and (state.target == 0 or state.reserved > 0)
    if state.phase == "flat":
        return state.reserved == 0 and state.exposure == (0, 0)
    return (state.reserved > 0 and 0 <= state.close_buy <= state.open_buy <= state.target
            and state.open_buy == state.open_sell and state.close_buy == state.close_sell)


class PairedModel:
    def __init__(self, mode="simulation"):
        if mode != "simulation":
            raise ValueError("live paired transport not implemented")
        self.state = State()
        self.journal, self.events = [], {}

    def apply(self, event):
        # Boundary accepts a strict schema, not arbitrary credential-bearing payloads.
        allowed = {"type", "id", "target", "reserve", "budget", "guards", "buy", "sell", "terminal"}
        if set(event) - allowed or not event.get("id") or not isinstance(event["id"], str):
            raise ValueError("invalid package event schema/id")
        if event["id"] in self.events:
            if self.events[event["id"]] == event:
                return False
            if len(self.journal) >= 10000:
                raise ValueError("package journal capacity reached")
            self.state = replace(self.state, phase="halted", reason="conflicting_duplicate", reported=self.state.exposure)
            import copy
            self.journal.append(copy.deepcopy(event))
            # A flat conflicting duplicate also blocks further activity, without inventing exposure.
            return False
        if len(self.journal) >= 10000:
            raise ValueError("package journal capacity reached; reconcile before continuing")
        import copy
        saved = copy.deepcopy(event)
        next_state = transition(self.state, saved)
        self.state = next_state
        self.journal.append(saved)
        self.events[saved["id"]] = saved
        return True

    def checkpoint(self):
        import copy
        return {"schema": 1, "mode": "simulation", "journal": copy.deepcopy(self.journal), "state": asdict(self.state)}

    @classmethod
    def restore(cls, checkpoint):
        if checkpoint.get("schema") != 1 or checkpoint.get("mode") != "simulation":
            raise ValueError("unverified package checkpoint")
        if not isinstance(checkpoint.get("journal"), list) or len(checkpoint["journal"]) > 10000:
            raise ValueError("invalid package journal")
        model = cls()
        for event in checkpoint["journal"]:
            model.apply(event)
        import json
        if json.loads(json.dumps(asdict(model.state))) != json.loads(json.dumps(checkpoint["state"])):
            raise ValueError("package checkpoint state drift")
        return model
