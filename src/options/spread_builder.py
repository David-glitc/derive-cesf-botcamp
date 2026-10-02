"""Depth-aware call/put debit spreads using adapter instrument fields."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
from src.risk.position_sizing import depth_quote
from src.options.delta import DeltaPolicy, amount_limit, exposure, moneyness


@dataclass(frozen=True)
class OptionQuote:
    instrument: str
    underlying: str
    kind: str
    strike: float
    expiry: float
    multiplier: float
    step: float
    min_amount: float
    timestamp: float
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]
    delta: float
    tick: float = 0.01


@dataclass(frozen=True)
class SpreadPlan:
    buy: str
    sell: str
    kind: str
    amount: float
    expiry: float
    debit: float
    max_loss: float
    max_payoff: float
    max_profit: float
    reward_risk: float
    break_even: float
    buy_limit: float
    sell_limit: float
    take_profit: float = 0.30
    stop_loss: float = 0.18
    max_hold_seconds: int = 21600
    signal_only: bool = True
    net_delta: float = 0.0
    round_trip_fees: float = 0.0
    valid_until: float = 0.0
    buy_delta: float = 0.0
    sell_delta: float = 0.0
    buy_moneyness: str = "unknown"
    sell_moneyness: str = "unknown"
    net_delta_quote: float = 0.0
    worst_delta_quote: float = 0.0
    gross_reference_quote: float = 0.0
    net_cap_quote: float = 0.0
    gross_cap_quote: float = 0.0
    delta_target: float = 0.0
    delta_verified: bool = False
    fees_verified: bool = False
    underlying: str = ""

    def to_dict(self):
        return asdict(self)


def build_spread(chain: list[OptionQuote], *, kind: str, underlying: str,
                 now: float, debit_budget: float, confidence: float,
                 fee_fraction: float = 0.001, min_reward_risk: float = 1.5,
                 delta_policy: DeltaPolicy | None = None) -> SpreadPlan | None:
    if kind not in ("call", "put") or underlying not in ("ETH", "BTC"):
        return None
    if (len({q.instrument for q in chain}) != len(chain)
            or (delta_policy and delta_policy.underlying not in (None, underlying))):
        return None
    if not all(math.isfinite(x) for x in (now, debit_budget, confidence, fee_fraction, min_reward_risk)):
        return None
    if debit_budget <= 0 or not .75 <= confidence <= 1 or fee_fraction < 0 or min_reward_risk <= 0:
        return None
    eligible = []
    for quote in chain:
        nums = (quote.strike, quote.expiry, quote.multiplier, quote.step, quote.min_amount, quote.timestamp, quote.delta, quote.tick)
        if not all(math.isfinite(x) for x in nums) or min(quote.strike, quote.multiplier, quote.step, quote.min_amount, quote.tick) <= 0:
            continue
        if (quote.underlying != underlying or quote.kind != kind or not 2 * 86400 <= quote.expiry - now <= 5 * 86400
                or not 0 <= now - quote.timestamp <= 5 or not quote.bids or not quote.asks):
            continue
        if quote.bids[0][0] <= 0 or quote.bids[0][0] >= quote.asks[0][0]:
            continue
        if not quote.instrument or not -1 <= quote.delta <= 1 or (quote.delta > 0) != (kind == "call"):
            continue
        if any(not all(math.isfinite(v) and v > 0 for v in level) for level in (*quote.bids, *quote.asks)):
            continue
        if any(a[0] < b[0] for a, b in zip(quote.bids, quote.bids[1:])):
            continue
        if any(a[0] > b[0] for a, b in zip(quote.asks, quote.asks[1:])):
            continue
        if (quote.asks[0][0] - quote.bids[0][0]) / quote.asks[0][0] > 0.15:
            continue
        eligible.append(quote)
    candidates = []
    for buy in eligible:
        if not (delta_policy.buy_min if delta_policy else .25) <= abs(buy.delta) <= (delta_policy.buy_max if delta_policy else .55):
            continue
        if delta_policy and delta_policy.buy_moneyness not in ("any", moneyness(kind, buy.strike, delta_policy.spot)):
            continue
        for sell in eligible:
            if delta_policy and not delta_policy.sell_min <= abs(sell.delta) <= delta_policy.sell_max:
                continue
            if delta_policy and abs(buy.delta) <= abs(sell.delta):
                continue
            if buy.expiry != sell.expiry or buy.multiplier != sell.multiplier or buy.step != sell.step:
                continue
            if buy.instrument == sell.instrument:
                continue
            width = sell.strike - buy.strike if kind == "call" else buy.strike - sell.strike
            if width <= 0:
                continue
            unit_debit = (buy.asks[0][0] - sell.bids[0][0]) * buy.multiplier
            if unit_debit <= 0:
                continue
            fee_unit = (buy.asks[0][0] + sell.bids[0][0]) * buy.multiplier * fee_fraction * 2
            capacity = min(sum(x[1] for x in buy.asks), sum(x[1] for x in sell.bids)) * 0.20
            if delta_policy:
                capacity = min(capacity, amount_limit(delta_policy, buy.delta, sell.delta, buy.multiplier, buy.step))
            amount = math.floor(min(debit_budget / (unit_debit + fee_unit), capacity) / buy.step + 1e-12) * buy.step
            if amount < max(buy.min_amount, sell.min_amount):
                continue
            ask, bid = depth_quote(buy.asks, amount), depth_quote(sell.bids, amount)
            if ask is None or bid is None:
                continue
            debit = (ask.vwap - bid.vwap) * buy.multiplier * amount
            fees = (ask.vwap + bid.vwap) * buy.multiplier * amount * fee_fraction * 2
            max_loss = debit + fees
            payoff = width * buy.multiplier * amount
            if not 0 < debit < payoff or max_loss > debit_budget or (payoff - max_loss) / max_loss < min_reward_risk:
                continue
            break_even = buy.strike + max_loss / amount / buy.multiplier * (1 if kind == "call" else -1)
            buy_limit = math.ceil(ask.worst_price / buy.tick - 1e-10) * buy.tick
            sell_limit = math.floor(bid.worst_price / sell.tick + 1e-10) * sell.tick
            limit_debit = (buy_limit - sell_limit) * buy.multiplier * amount
            limit_fees = (buy_limit + sell_limit) * buy.multiplier * amount * fee_fraction * 2
            if sell_limit <= 0 or limit_debit + limit_fees > debit_budget:
                continue
            # Bound the plan at the submitted limits, not only favorable
            # VWAP estimates. Fee/slippage bounds must survive tick rounding.
            debit, fees, max_loss = limit_debit, limit_fees, limit_debit + limit_fees
            if not 0 < debit < payoff or (payoff - max_loss) / max_loss < min_reward_risk:
                continue
            break_even = buy.strike + max_loss / amount / buy.multiplier * (1 if kind == "call" else -1)
            delta_fields = {}
            if delta_policy:
                view = exposure(delta_policy, buy.delta, sell.delta, amount, amount, buy.multiplier)
                if not view["within_caps"]:
                    continue
                delta_fields = {k: view[k] for k in ("net_delta_quote", "worst_delta_quote", "gross_reference_quote",
                                                     "net_cap_quote", "gross_cap_quote")}
                delta_fields.update(buy_moneyness=moneyness(kind, buy.strike, delta_policy.spot),
                                    sell_moneyness=moneyness(kind, sell.strike, delta_policy.spot),
                                    delta_target=view["net_delta"], delta_verified=True)
            candidates.append(SpreadPlan(buy.instrument, sell.instrument, kind, amount, buy.expiry,
                                         debit, max_loss, payoff, payoff - max_loss,
                                         (payoff - max_loss) / max_loss, break_even,
                                         buy_limit, sell_limit, net_delta=(buy.delta - sell.delta) * buy.multiplier * amount,
                                         round_trip_fees=fees, valid_until=min(buy.timestamp, sell.timestamp) + 5,
                                         buy_delta=buy.delta, sell_delta=sell.delta, underlying=underlying, **delta_fields))
    def score(p):
        targets = (abs(abs(p.buy_delta) - delta_policy.buy_target) + abs(abs(p.sell_delta) - delta_policy.sell_target)) if delta_policy else 0
        return (abs(p.expiry - now - 3 * 86400), targets, -p.reward_risk)
    return min(candidates, key=score) if candidates else None


def spread_exit(plan: SpreadPlan, executable_credit: float, held_seconds: float,
                now: float, signal_valid: bool = True, *, entry_fees: float = 0,
                exit_fees: float = 0, entry_debit: float | None = None) -> str | None:
    debit = plan.debit if entry_debit is None else entry_debit
    if (not all(math.isfinite(x) for x in (executable_credit, debit, entry_fees, exit_fees, held_seconds, now))
            or min(debit, executable_credit, entry_fees, exit_fees, held_seconds, now) < 0 or debit + entry_fees <= 0):
        return "unpriceable"
    pnl_fraction = (executable_credit - exit_fees - debit - entry_fees) / (debit + entry_fees)
    if now >= plan.expiry - 6 * 3600:
        return "expiry"
    if not signal_valid:
        return "signal_invalid"
    if pnl_fraction >= plan.take_profit:
        return "take_profit"
    if pnl_fraction <= -plan.stop_loss:
        return "stop_loss"
    if held_seconds >= plan.max_hold_seconds:
        return "time_limit"
    return None
