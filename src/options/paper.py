"""Two-leg paper accounting. No network, signing or order submission.

Even with observed books, simultaneous fills are a simulator assumption.
Unmatched fills remain exposure and a halt, never a successful spread.
"""
from dataclasses import dataclass, replace
from copy import deepcopy
import math

from agents.condor_agent import decide
from src.options.spread_builder import OptionQuote, build_spread, spread_exit
from src.options.delta import account_policy, exposure
from src.risk.position_sizing import depth_quote
from src.risk.competition import initial_state, advance, risk_view


def finite(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("nonfinite paper value")
    return result


@dataclass(frozen=True)
class Fees:
    rate: float
    base: float
    premium_cap: float

    def __post_init__(self):
        if not all(math.isfinite(x) and x >= 0 for x in (self.rate, self.base, self.premium_cap)):
            raise ValueError("invalid fee metadata")

    def charge(self, quantity, price, spot):
        if quantity == 0:
            return 0.0
        if min(quantity, price, spot) <= 0:
            raise ValueError("invalid fee inputs")
        return self.base + min(quantity * spot * self.rate, quantity * price * self.premium_cap)


def normalize_quote(raw):
    data = {key: raw[key] for key in OptionQuote.__dataclass_fields__ if key in raw}
    for side in ("bids", "asks"):
        data[side] = tuple(tuple(finite(x) for x in level) for level in data[side])
    for key in ("strike", "expiry", "multiplier", "step", "min_amount", "timestamp", "delta", "tick"):
        if key in data:
            data[key] = finite(data[key])
    quote = OptionQuote(**data)
    # Public Derive normalized quantities use underlying units in this lane.
    if quote.multiplier != 1:
        raise ValueError("unverified amount convention")
    fees = Fees(**{key: finite(raw["fees"][key]) for key in ("rate", "base", "premium_cap")})
    return quote, fees


def close_quote(quote, amount, side, now):
    if not 0 <= now - quote.timestamp <= 5:
        return None
    if not quote.bids or not quote.asks or not 0 < quote.bids[0][0] < quote.asks[0][0]:
        return None
    if any(a[0] < b[0] for a, b in zip(quote.bids, quote.bids[1:])):
        return None
    if any(a[0] > b[0] for a, b in zip(quote.asks, quote.asks[1:])):
        return None
    return depth_quote(quote.bids if side == "sell" else quote.asks, amount)


def live_options_status():
    return {"live_options_enabled": False, "live_execution_verified": False,
            "reason": "installed_hummingbot_has_no_paired_options_adapter",
            "required": ["option instrument/rule support", "paired placement and close",
                         "partial-fill containment", "margin/fill/restart reconciliation"],
            "orders_submitted": 0}


class PaperOptions:
    def __init__(self, capital=800.0, *, delta_settings=None, delta_net_fraction=.20):
        self.capital = self.cash = finite(capital)
        if capital <= 0:
            raise ValueError("positive capital required")
        self.position = None
        self.halted = False
        self.last_time = None
        self.peak = self.capital
        self.events, self.curve = [], []
        self.fees = self.volume = 0.0
        self.closed = self.unmatched = 0
        self.last_entry = -math.inf
        self.day = None
        self.day_equity = self.capital
        self.inputs = []
        self.risk_state = None
        self.delta_settings = dict(delta_settings or {})
        if not set(self.delta_settings).issubset({"buy_min", "buy_max", "buy_target", "sell_min", "sell_max", "sell_target", "buy_moneyness"}):
            raise ValueError("unknown_delta_selection_setting")
        self.delta_net_fraction = finite(delta_net_fraction)
        account_policy(1, self.capital, net_fraction=self.delta_net_fraction, **self.delta_settings)
        self.delta_view = None

    def _policy(self, equity, risk):
        return account_policy(self.spot, min(self.capital, max(.01, equity)),
                              scale=risk["risk_scale"], net_fraction=self.delta_net_fraction,
                              underlying=self.ccy,
                              **self.delta_settings)

    def _event(self, now, kind, **fields):
        self.events.append({"time": now, "type": kind, **fields})

    def _prices(self, quotes, now):
        pos = self.position
        values = []
        for name, amount, side in ((pos["plan"].buy, pos["buy_qty"], "sell"),
                                   (pos["plan"].sell, pos["sell_qty"], "buy")):
            if amount == 0:
                values.append((0.0, 0.0))
                continue
            if name not in quotes:
                return None
            quote, fee = quotes[name]
            original = pos["quotes"][name][0]
            # Metadata drift must not reprice the same named instrument.
            for key in ("underlying", "kind", "strike", "expiry", "multiplier", "step", "tick"):
                if getattr(quote, key) != getattr(original, key):
                    return None
            price = close_quote(quote, amount, side, now)
            if price is None:
                return None
            values.append((amount * price.vwap, fee.charge(amount, price.vwap, self.spot)))
        return values

    def _enter(self, row, quotes, decision, now, risk):
        budget = min(min(self.capital, self.cash) * .01, risk["risk_trade_budget"])
        # Leave headroom for the full debit/fee loss, not just pre-entry cash.
        policy = self._policy(max(.01, self.cash - budget), risk)
        plan = build_spread([q for q, _ in quotes.values()], kind=decision.option_direction,
                            underlying=row["ccy"], now=now, debit_budget=budget,
                            confidence=decision.confidence, fee_fraction=0, delta_policy=policy)
        if plan is None:
            self._event(now, "reject", reason="no_executable_spread")
            return
        buy, fb = quotes[plan.buy]
        sell, fs = quotes[plan.sell]
        fixed = 2 * (fb.base + fs.base)
        unit_debit = plan.debit / plan.amount
        unit_fees = 2 * (min(self.spot * fb.rate, plan.buy_limit * fb.premium_cap)
                         + min(self.spot * fs.rate, plan.sell_limit * fs.premium_cap))
        amount = min(plan.amount, math.floor(max(0, budget - fixed) / (unit_debit + unit_fees) / buy.step + 1e-10) * buy.step)
        if amount < max(buy.min_amount, sell.min_amount):
            self._event(now, "reject", reason="all_in_fee_budget")
            return
        ratio = amount / plan.amount
        plan = replace(plan, amount=amount, debit=plan.debit * ratio, max_payoff=plan.max_payoff * ratio)
        # Reserve full assumed four-side taker cost; no RFQ discounts assumed.
        reserve_fees = 2 * (fb.charge(plan.amount, plan.buy_limit, self.spot)
                            + fs.charge(plan.amount, plan.sell_limit, self.spot))
        if plan.debit + reserve_fees > budget or (plan.max_payoff - plan.debit - reserve_fees) / (plan.debit + reserve_fees) < 1.5:
            self._event(now, "reject", reason="all_in_fee_budget")
            return
        plan = replace(plan, max_loss=plan.debit + reserve_fees, round_trip_fees=reserve_fees,
                       max_profit=plan.max_payoff - plan.debit - reserve_fees,
                       reward_risk=(plan.max_payoff - plan.debit - reserve_fees) / (plan.debit + reserve_fees),
                       net_delta=plan.net_delta * ratio,
                       fees_verified=True,
                       break_even=buy.strike + (plan.debit + reserve_fees) / amount * (1 if plan.kind == "call" else -1))
        view = exposure(policy, buy.delta, sell.delta, amount, amount)
        if not view["within_caps"]:
            self._event(now, "reject", reason="delta_budget")
            return
        plan = replace(plan, **{k: view[k] for k in ("net_delta_quote", "worst_delta_quote", "gross_reference_quote")},
                       delta_target=view["net_delta"])
        fraction = finite(row.get("matched_fill_fraction", 1))
        if not 0 <= fraction <= 1:
            raise ValueError("fill fraction outside [0,1]")
        amount = math.floor(plan.amount * fraction / buy.step + 1e-10) * buy.step
        bq = finite(row.get("buy_filled_amount", amount))
        sq = finite(row.get("sell_filled_amount", amount))
        for qty, quote in ((bq, buy), (sq, sell)):
            if qty < 0 or qty > plan.amount + 1e-9 or (qty and (qty < quote.min_amount or abs(qty / quote.step - round(qty / quote.step)) > 1e-7)):
                raise ValueError("invalid simulated leg fill")
        if not bq and not sq:
            self._event(now, "reject", reason="paired_no_fill")
            return
        cost = bq * plan.buy_limit - sq * plan.sell_limit
        fees = fb.charge(bq, plan.buy_limit, self.spot) + fs.charge(sq, plan.sell_limit, self.spot)
        matched = abs(bq - sq) < 1e-9
        before = self.cash
        self.cash -= cost + fees
        self.fees += fees
        self.volume += bq * plan.buy_limit + sq * plan.sell_limit
        self.position = {"plan": plan, "buy_qty": bq, "sell_qty": sq, "matched": matched,
                         "debit": cost, "entry_fees": fees, "time": now, "quotes": quotes,
                         "cash_before": before}
        self.last_entry = now
        if not matched:
            self.halted = True
            self.unmatched += 1
        self._event(now, "entry_fill", buy=plan.buy, sell=plan.sell, buy_qty=bq, sell_qty=sq,
                    matched=matched, debit=cost, fees=fees, cash=self.cash,
                    delta=exposure(policy, buy.delta, sell.delta, bq, sq),
                    simulated=True, pairing_assumption="atomic_matched_or_explicit_fault")

    def step(self, row):
        now = finite(row["time"])
        if self.inputs and now == self.last_time and row == self.inputs[-1]:
            return  # Replay/duplicate snapshot cannot double-charge a fill.
        if self.last_time is not None and now <= self.last_time:
            raise ValueError("strictly increasing snapshot times required")
        if row["source"] not in ("synthetic_fixture", "derive_v3_public_l1", "derive_legacy_public_l1"):
            raise ValueError("unrecognized data provenance")
        self.spot = finite(row["spot"])
        self.ccy = row["ccy"]
        if self.spot <= 0 or row["ccy"] not in ("ETH", "BTC"):
            raise ValueError("invalid underlying")
        if self.position and row["ccy"] != self.position["plan"].buy.split("-")[0]:
            raise ValueError("one underlying per paper account")
        quotes = {}
        for raw in row["chain"]:
            quote, fees = normalize_quote(raw)
            if quote.instrument in quotes or quote.timestamp > now:
                raise ValueError("duplicate/future quote")
            quotes[quote.instrument] = quote, fees
        signal = dict(row.get("signal_snapshot", {}))
        # Enforce own account limits as well as any upstream halt.
        signal["ccy"] = row["ccy"]
        value = self._prices(quotes, now) if self.position else None
        mark = self.cash if not self.position else (self.cash + value[0][0] - value[1][0] - value[0][1] - value[1][1] if value else None)
        if mark is not None:
            day = int(now // 86400)
            if day != self.day:
                self.day, self.day_equity = day, mark
            self.peak = max(self.peak, mark)
            self.risk_state = (initial_state(max(0, mark), now, self.capital, "paper_options")
                               if self.risk_state is None else advance(self.risk_state, max(0, mark), now))
        risk = risk_view(self.risk_state, max(0, mark) if mark is not None else self.cash) if self.risk_state else None
        if risk is None:
            self.halted = True
            signal.update(valid=False)
        else:
            signal.update(risk)
            # External halt information may tighten local risk, never relax it.
            if row.get("signal_snapshot", {}).get("risk_mode") == "hard_stop":
                self.risk_state.update(restricted=True, hard_stop=True)
                signal["risk_mode"] = "hard_stop"
            signal["peak_dd"] = min(signal["peak_dd"], finite(row.get("signal_snapshot", {}).get("peak_dd", 0)))
        decision = decide(signal)
        if self.position and value is not None:
            pos = self.position
            credit = value[0][0] - value[1][0]
            exit_fees = value[0][1] + value[1][1]
            net = credit - exit_fees - pos["debit"] - pos["entry_fees"]
            cost_basis = pos["debit"] + pos["entry_fees"]
            equity = self.cash + credit - exit_fees
            self.peak = max(self.peak, equity)
            delta_reason = None
            try:
                b, s = quotes[pos["plan"].buy][0], quotes[pos["plan"].sell][0]
                if not (-1 <= b.delta <= 1 and -1 <= s.delta <= 1
                        and (b.delta > 0) == (b.kind == "call") and (s.delta > 0) == (s.kind == "call")):
                    raise ValueError("invalid_delta_sign")
                self.delta_view = exposure(self._policy(max(.01, equity), risk), b.delta, s.delta,
                                           pos["buy_qty"], pos["sell_qty"])
                if not self.delta_view["within_caps"]:
                    delta_reason = "delta_limit"
            except (ValueError, TypeError, ArithmeticError):
                self.delta_view = None
                delta_reason = "invalid_delta"
            reason = ("unmatched_recovery" if not pos["matched"] else
                      "halt" if decision.halt or self.halted else delta_reason or
                      spread_exit(pos["plan"], credit, now - pos["time"], now,
                                  decision.signal == (1 if pos["plan"].kind == "call" else -1),
                                  entry_fees=pos["entry_fees"], exit_fees=exit_fees, entry_debit=pos["debit"]))
            if reason:
                self.cash += credit - exit_fees
                self.fees += exit_fees
                self.volume += value[0][0] + value[1][0]
                if abs(self.cash - pos["cash_before"] - net) > 1e-7:
                    raise ValueError("spread cash mismatch")
                self.closed += pos["matched"]
                self._event(now, "close_fill", reason=reason, matched=pos["matched"],
                            net=net, credit=credit, fees=exit_fees, cash=self.cash,
                            delta=self.delta_view,
                            buy_qty=pos["buy_qty"], sell_qty=pos["sell_qty"], simulated=True)
                self.position = None
                if decision.halt or delta_reason:
                    self.halted = True
        elif self.position:
            self.halted = True
            self.delta_view = None
            self._event(now, "unpriceable", reason="missing_stale_or_insufficient_close_book")
        elif not self.halted and decision.option_direction and now - self.last_entry >= 300:
            self._enter(row, quotes, decision, now, risk)
        else:
            self._event(now, "no_entry", reason="paper_halted" if self.halted else decision.reason)
        value = self._prices(quotes, now) if self.position else None
        equity = self.cash if self.position is None else (self.cash + value[0][0] - value[1][0] - value[0][1] - value[1][1] if value else None)
        if equity is not None:
            self.peak = max(self.peak, equity)
            self.risk_state = advance(self.risk_state, max(0, equity), now)
        if self.position:
            try:
                b, s = quotes[self.position["plan"].buy][0], quotes[self.position["plan"].sell][0]
                self.delta_view = exposure(self._policy(max(.01, equity), risk), b.delta, s.delta,
                                           self.position["buy_qty"], self.position["sell_qty"]) if equity is not None else None
            except (ValueError, KeyError, TypeError, ArithmeticError):
                self.delta_view = None
        self.curve.append({"time": now, "equity": equity, "cash": self.cash,
                           "delta": self.delta_view if self.position else None,
                           "risk_mode": self.risk_state and risk_view(self.risk_state, max(0, equity) if equity is not None else max(0, self.cash))["risk_mode"],
                           "debit_at_risk": self.position["debit"] + self.position["entry_fees"] if self.position and self.position["matched"] else None,
                           "unmatched_exposure": bool(self.position and not self.position["matched"]),
                           "open": self.position is not None, "source": row["source"]})
        self.last_time = now
        self.inputs.append(deepcopy(row))

    def export_state(self):
        return {"schema": 2, "capital": self.capital, "inputs": deepcopy(self.inputs),
                "delta_settings": self.delta_settings, "delta_net_fraction": self.delta_net_fraction}

    @classmethod
    def restore(cls, state):
        if state.get("schema") != 2:
            raise ValueError("unknown paper checkpoint schema")
        engine = cls(state["capital"], delta_settings=state["delta_settings"], delta_net_fraction=state["delta_net_fraction"])
        for row in state["inputs"]:
            engine.step(row)
        return engine

    def summary(self):
        last = self.curve[-1]["equity"] if self.curve else self.cash
        return {"mode": "paper_only", "observations": len(self.curve), "closed_matched_spreads": self.closed,
                "unmatched_fill_events": self.unmatched, "halted": self.halted,
                "open_position": self.position is not None, "cash": self.cash, "equity": last,
                "return_pct": (last / self.capital - 1) * 100 if last is not None else None,
                "fees_quote": self.fees, "premium_volume_quote": self.volume,
                "delta_settings": self.delta_settings, "delta_net_fraction": self.delta_net_fraction,
                "delta_breach_exits": sum(e.get("reason") == "delta_limit" for e in self.events),
                "risk_policy": risk_view(self.risk_state, max(0, last) if last is not None else max(0, self.cash)) if self.risk_state else None,
                "data_sources": sorted({p["source"] for p in self.curve}),
                "performance_status": "paper_fills_only" if self.closed or self.position else "no_executed_spreads",
                "live": live_options_status(),
                "limitations": ["paper fills; not exchange matching proof", "L1/depth snapshots do not establish queue priority",
                                "no merged historical perp portfolio", "instrument standard fees; no account/RFQ discounts"]}
