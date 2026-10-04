"""Modeled Black-76 books driving production RFQ state transitions, offline.

No maker availability, signature, onchain settlement or journal durability proof.
Both legs change together in the fixture; unacknowledged writes aren't resent.
"""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from statistics import NormalDist

from src.execution.derive_rfq import quote_cost
from src.execution.options_rfq import OptionsRFQ
from src.options.delta import account_policy
from src.options.paper import Fees
from src.options.pricing import black_price
from src.options.ranking import costed_plan
from src.options.spread_builder import OptionQuote, build_spread
from src.risk.exposure import BASELINE_EXPOSURE, exposure_limits

YEAR = 365 * 86400


def model_price(spot, strike, expiry, now, iv, kind):
    years = max(0, (expiry - now) / YEAR)
    price = black_price(spot, strike, years, 1, iv, kind)
    if years <= 0:
        delta = float(spot > strike) if kind == "call" else -float(spot < strike)
    else:
        d1 = (math.log(spot / strike) + iv * iv * years / 2) / (iv * math.sqrt(years))
        delta = NormalDist().cdf(d1) - (kind == "put")
    return price, delta


class Surface:
    def __init__(self, rules, spread=.02, finer_lots=False, exposure_profile=BASELINE_EXPOSURE):
        self.rules, self.spread, self.finer_lots = rules, spread, finer_lots
        self.exposure_profile = exposure_profile
        self.contracts = {}
        self.spots, self.ivs, self.now = {}, {}, 0

    def metadata(self, asset):
        return self.rules[asset + "-option"]

    def fees(self, asset):
        r = self.metadata(asset)
        return Fees(float(r["taker_fee_rate"]), float(r["base_fee"]), float(r["mark_price_fee_rate_cap"]))

    def quote(self, name):
        asset, strike, expiry, kind = self.contracts[name]
        mark, delta = model_price(self.spots[asset], strike, expiry, self.now, self.ivs[asset], kind)
        tick = float(self.metadata(asset)["tick_size"])
        # Fixture prices must be exact tick multiples when serialized. Do not
        # manufacture 9.620000000000001 as a supposedly better executable bid.
        native_tick = Decimal(str(tick))
        bid_ticks = max(1, math.floor(mark * (1 - self.spread / 2) / tick + 1e-10))
        ask_ticks = max(bid_ticks + 1, math.ceil(mark * (1 + self.spread / 2) / tick - 1e-10))
        bid, ask = float(native_tick * bid_ticks), float(native_tick * ask_ticks)
        return bid, ask, delta

    def plan(self, asset, kind, now, equity, risk, confidence):
        r = self.metadata(asset)
        spot, iv = self.spots[asset], self.ivs[asset]
        # Hypothetical contracts, not a reconstruction of listed expiries/strikes.
        expiry = int(now // 86400 + 3) * 86400 + 8 * 3600
        years = (expiry - now) / YEAR
        grid = 10 if asset == "ETH" else 500
        step, minimum = float(r["amount_step"]), float(r["minimum_amount"])
        if self.finer_lots:
            # Diagnostic ONLY: leave all risk/fees/exits unchanged.
            step = minimum = .001 if asset == "ETH" else .00001
        budget = min(8, equity * .01, risk["risk_trade_budget"])
        limits = exposure_limits(self.exposure_profile, asset)
        policy = account_policy(spot, max(.01, equity - budget), scale=risk["risk_scale"], underlying=asset,
                                exposure_profile=self.exposure_profile, gross_fraction=limits["option_gross"])
        if minimum * 2 * spot > policy.gross_cap_quote:
            return None, "option_minimum_gross_exceeds_cap"
        fee = self.fees(asset)
        if budget <= 4 * fee.base:
            return None, "option_fixed_fees_exhaust_risk_budget"
        chain, raw, seen = [], {}, set()
        for absolute_delta in (.15, .25, .35, .5, .6):
            probability = absolute_delta if kind == "call" else 1 - absolute_delta
            strike = round(spot * math.exp(iv * iv * years / 2 - NormalDist().inv_cdf(probability) * iv * math.sqrt(years)) / grid) * grid
            if strike <= 0 or strike in seen:
                continue
            seen.add(strike)
            name = f"{asset}-MODEL-{expiry}-{strike}-{'C' if kind == 'call' else 'P'}"
            self.contracts[name] = (asset, strike, expiry, kind)
            bid, ask, delta = self.quote(name)
            q = OptionQuote(name, asset, kind, strike, expiry, 1, step, minimum, now,
                            ((bid, 100),), ((ask, 100),), delta, float(r["tick_size"]))
            chain.append(q)
            raw[name] = {**q.__dict__, "fees": fee.__dict__}
        selected = build_spread(chain, kind=kind, underlying=asset, now=now, debit_budget=budget,
                                confidence=confidence, delta_policy=policy, fee_fraction=0)
        if selected is None:
            return None, "no_delta_debit_reward_qualified_spread"
        selected = costed_plan(raw[selected.buy], raw[selected.sell], now, spot, budget, confidence, policy)
        return (selected.to_dict(), "qualified") if selected else (None, "fee_adjusted_spread_rejected")


class MemoryJournal:
    """Performance simulator only. Production disk/restart tests remain separate."""
    def __init__(self):
        self.state = dict(phase="idle", nonce=0, executions_submitted=0, trades=[])

    def save(self, **changes):
        self.state = {**self.state, **changes}


class ModelTransport:
    def __init__(self, surface, account, faults=False):
        self.surface, self.account_state, self.faults = surface, account, faults
        self.now, self.positions, self.rfq_rows, self.executed = 0., {}, {}, {}
        self.send_count = self.execute_count = self.lost_acks = self.partial_rejections = 0
        self.fees_total = self.premium_turnover = self.reference_turnover = 0.

    def clock(self):
        return self.now

    def equity(self):
        value = self.account_state["cash"]
        for name, amount in self.positions.items():
            bid, ask, _ = self.surface.quote(name)
            value += float(amount) * ((bid + ask) / 2)
        return value

    async def account(self):
        rows = []
        for name, amount in self.positions.items():
            asset = self.surface.contracts[name][0]
            rows.append(dict(instrument_name=name, instrument_type="option", amount=str(amount),
                             delta=str(self.surface.quote(name)[2]), index_price=str(self.surface.spots[asset])))
        return dict(observed_at=self.now, equity=str(self.equity()),
                    available=str(max(0, self.account_state["cash"])), open_orders=[], positions=rows)

    async def send(self, legs, label, max_cost):
        self.send_count += 1
        row = dict(subaccount_id=42, legs=deepcopy(legs), label=label, rfq_id=str(self.send_count),
                   status="open", valid_until=(self.now + 30) * 1000)
        self.rfq_rows[row["rfq_id"]] = row
        if self.faults and self.send_count % 7 == 0:
            self.lost_acks += 1
            raise TimeoutError("modeled lost acknowledgement")
        return row

    async def rfqs(self, **filters):
        rows = list(self.rfq_rows.values()) if "rfq_id" not in filters else [self.rfq_rows[filters["rfq_id"]]]
        for row in rows:
            if row["status"] == "open" and self.now * 1000 >= row["valid_until"]:
                row["status"] = "expired"
        return rows

    async def offers(self, rfq_id):
        rfq = self.rfq_rows[rfq_id]
        legs = []
        for leg in rfq["legs"]:
            bid, ask, _ = self.surface.quote(leg["instrument_name"])
            legs.append({**leg, "price": str(round(ask if leg["direction"] == "buy" else bid, 8))})
        row = dict(rfq_id=rfq_id, quote_id="q" + rfq_id, status="open", direction="sell",
                   liquidity_role="maker", tx_status=None, creation_timestamp=self.now * 1000,
                   last_update_timestamp=self.now * 1000, legs=legs,
                   legs_hash="0x" + hashlib.sha256(json.dumps(legs, sort_keys=True).encode()).hexdigest())
        if self.faults and int(rfq_id) % 13 == 0:
            row["fill_pct"] = ".5"
            self.partial_rejections += 1
        return [row]

    async def prepare(self, quote, max_fee, nonce, label, now, plan, intent):
        buy, sell = self.surface.contracts[plan["buy"]], self.surface.contracts[plan["sell"]]
        width = (sell[1] - buy[1]) * (1 if buy[3] == "call" else -1)
        if (buy[0] != sell[0] or buy[2:] != sell[2:] or width <= 0
                or abs(width * float(plan["amount"]) - float(plan["max_payoff"])) > .000001):
            raise ValueError("modeled_plan_payoff_mismatch")
        return deepcopy(quote), max_fee, nonce, deepcopy(plan), intent

    async def submit(self, prepared):
        quote, max_fee, nonce, plan, intent = prepared
        asset = plan["underlying"]
        fees = sum(self.surface.fees(asset).charge(float(l["amount"]), float(l["price"]),
                                                 self.surface.spots[asset]) for l in quote["legs"])
        if Decimal(str(fees)) > Decimal(str(max_fee)):
            # Real terminal venue rejection must halt for reconciliation too.
            raise ValueError("modeled_fee_exceeds_reserved_bound")
        cost = float(quote_cost(quote["legs"]))
        self.account_state["cash"] -= cost + fees
        self.fees_total += fees
        self.premium_turnover += sum(float(l["amount"]) * float(l["price"]) for l in quote["legs"])
        self.reference_turnover += sum(float(l["amount"]) * self.surface.spots[asset] for l in quote["legs"])
        for leg in quote["legs"]:
            name = leg["instrument_name"]
            change = Decimal(leg["amount"]) * (1 if leg["direction"] == "buy" else -1)
            amount = self.positions.get(name, Decimal(0)) + change
            if amount:
                self.positions[name] = amount
            else:
                self.positions.pop(name, None)
        self.execute_count += 1
        row = {**quote, "subaccount_id": 42, "nonce": nonce, "direction": "buy", "liquidity_role": "taker",
               "fee": str(fees), "status": "filled", "tx_status": "settled", "tx_hash": "MODEL-" + str(nonce)}
        self.executed[(quote["rfq_id"], quote["quote_id"])] = row
        self.rfq_rows[quote["rfq_id"]]["status"] = "filled"
        if self.faults and self.execute_count % 11 == 0:
            self.lost_acks += 1
            raise TimeoutError("modeled lost execution acknowledgement")
        return row

    async def executions(self, rfq_id, quote_id):
        return [self.executed[(rfq_id, quote_id)]] if (rfq_id, quote_id) in self.executed else []

    async def cancel(self, rfq_id):
        self.rfq_rows[rfq_id]["status"] = "cancelled"


class SimLifecycle(OptionsRFQ):
    async def step(self, **kwargs):
        # The exact production state reducer, but no fsync/flock in this model.
        await self._tick(self.transport.now, kwargs.get("plan"), Decimal(str(kwargs.get("budget", 0))),
                         kwargs.get("allow_entry", False), kwargs.get("force_exit", False),
                         kwargs.get("consume_entry"), kwargs.get("entry_budget"), kwargs.get("exit_required"))
