"""Fixed-policy, shared-$800 replay; proxy data and modeled execution, not alpha proof."""
import argparse
import asyncio
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from agents.condor_agent import decide
from backtest.public_history import START, END, ASSETS, coverage
from backtest.rfq_simulation import Surface, ModelTransport, MemoryJournal, SimLifecycle
from src.risk.competition import POLICY, HARD_STOP_DRAWDOWN, initial_state, advance, risk_view
from src.risk.position_sizing import dynamic_exits, risk_size, cost_allows_entry
from src.risk.venue_sizing import venue_size
from src.signal.flyby import feature_frame
from src.risk.exposure import BASELINE_EXPOSURE, ETH_EXPOSURE_TEST, exposure_limits

MODES = ("options-ETH", "options-BTC", "perps", "combined-ETH", "combined-BTC")
SCENARIOS = {"base": dict(spread=.02, perp_slip=.0002, funding=.0000125, faults=False),
             "stress": dict(spread=.06, perp_slip=.001, funding=.00005, faults=True)}


def causal_iv(times, iv):
    available = iv.timestamp.to_numpy(dtype=np.int64) + 3600
    indices = np.searchsorted(available, times, side="right") - 1
    safe = np.maximum(indices, 0)
    values = iv.close.to_numpy(dtype=float)[safe] / 100
    valid = (indices >= 0) & (times - available[safe] <= 3600) & np.isfinite(values) & (values > 0)
    return np.where(valid, values, np.nan)


def load_history(path):
    manifest = json.loads((path / "manifest.json").read_text())
    if (manifest["start"], manifest["end_exclusive"]) != (START, END):
        raise ValueError("fixed_two_year_window_required")
    for name, expected in manifest["normalized_sha256"].items():
        if Path(name).name != name or hashlib.sha256((path / name).read_bytes()).hexdigest() != expected:
            raise ValueError("normalized_history_hash_mismatch")
    result = {}
    for asset in ASSETS:
        candles = pd.read_csv(path / f"{asset}-5m.csv")
        view = coverage(candles, START, END, 300)
        if view["missing_rows"] or view["extra_rows"]:
            raise ValueError("incomplete_two_year_candles")
        f = feature_frame(candles, "5m")
        times = candles.timestamp.to_numpy(dtype=np.int64)
        iv = causal_iv(times, pd.read_csv(path / f"{asset}-dvol-1h.csv")) if asset != "SOL" else np.full(len(times), np.nan)
        f["ccy"], f["stale_secs"], f["reconciled"] = asset, 0, True
        f["option_iv_edge"] = f.forecast_sigma - iv
        f["valid"] = f.valid.astype(bool)
        # Cache the deterministic signal policy at normal/restricted risk.
        # Actual account DD/latches remain authoritative at every replay bar.
        records = f.to_dict("records")
        signals = {}
        for mode in ("normal", "restricted"):
            base = dict(risk_policy=POLICY, risk_mode=mode, daily_pnl_pct=0,
                        peak_dd=0 if mode == "normal" else -.11)
            decisions = [decide({**r, **base}) for r in records]
            signals[mode] = decisions
        result[asset] = dict(candles=candles.to_dict("records"), features=records,
                             decisions=signals, iv=iv)
        print(f"prepared {asset}: {sum(d.signal != 0 for d in signals['normal'])} confirmed signals", flush=True)
    return result, json.loads((path / "venue-rules.json").read_text())["instruments"], manifest


def barrier_fill(position, candle, slippage):
    """Gap at open; otherwise SL-first when both touched. No OHLC path invention."""
    side, entry = position["side"], position["entry"]
    stop = entry * (1 - side * position["stop"])
    target = entry * (1 + side * position["target"])
    opened = candle["open"]
    if (opened <= stop if side > 0 else opened >= stop):
        price, reason = opened, "stop_gap"
    elif (opened >= target if side > 0 else opened <= target):
        price, reason = opened, "take_profit_gap"
    elif (candle["low"] <= stop if side > 0 else candle["high"] >= stop):
        price, reason = stop, "stop_loss"
    elif (candle["high"] >= target if side > 0 else candle["low"] <= target):
        price, reason = target, "take_profit"
    else:
        return None
    return price * (1 - side * slippage), reason


class Replay:
    def __init__(self, history, rules, mode, scenario, finer_lots=False, exposure_profile=BASELINE_EXPOSURE):
        self.history, self.rules, self.mode = history, rules, mode
        if exposure_profile == ETH_EXPOSURE_TEST and mode not in ("options-ETH", "perps", "combined-ETH"):
            raise ValueError("eth_exposure_replay_requires_eth_or_fallback_mode")
        exposure_limits(exposure_profile, "ETH")
        self.exposure_profile = exposure_profile
        self.scenario, self.finer_lots = SCENARIOS[scenario], finer_lots
        self.identity = mode + "-" + scenario + ("-HYPOTHETICAL-finer-lots" if finer_lots else "-current-rules")
        if exposure_profile != BASELINE_EXPOSURE:
            self.identity += "-" + exposure_profile
        self.account = {"cash": 800.}
        self.state = initial_state(800, START, 800, "two_year_shared_paper")
        self.surface = Surface(rules, self.scenario["spread"], finer_lots, exposure_profile)
        self.transport = ModelTransport(self.surface, self.account, self.scenario["faults"])
        self.lifecycle = SimLifecycle(self.transport, MemoryJournal(), 42, exposure_profile=exposure_profile,
            underlying="ETH" if exposure_profile == ETH_EXPOSURE_TEST else None)
        self.perp = None
        self.trades, self.curve, self.transitions = [], [], []
        self.blocks = Counter()
        self.fees = self.funding = self.perp_turnover = 0.
        self.peak, self.max_dd, self.now, self.index = 800., 0., START, 0
        self.last_entry = -1e30
        self.last_consumed = {}
        self.option_trade_count = 0
        self.option_reason = None
        self.errors = Counter()

    def decision(self, asset):
        mode = "restricted" if self.state["restricted"] else "normal"
        return self.history[asset]["decisions"][mode][self.index - 1]

    def equity(self):
        equity = self.transport.equity()
        if self.perp:
            p = self.perp
            equity += p["side"] * p["amount"] * (self.surface.spots[p["asset"]] - p["entry"])
        return equity

    def observe(self):
        equity = self.equity()
        before = self.state["restricted"], self.state["hard_stop"]
        self.state = advance(self.state, max(0, equity), self.now)
        after = self.state["restricted"], self.state["hard_stop"]
        if before != after:
            self.transitions.append(dict(time=self.now, equity=equity, restricted=after[0], hard_stop=after[1]))
        self.peak = max(self.peak, equity)
        self.max_dd = min(self.max_dd, equity / self.peak - 1)
        return risk_view(self.state, max(0, equity))

    def consume(self, account, now):
        asset = self.lifecycle.journal.state["plan"]["underlying"]
        signal_time = self.now - 300
        if self.state["hard_stop"] or now - self.last_entry < 300 or self.last_consumed.get(asset) == signal_time:
            return False
        self.last_entry = now
        self.last_consumed[asset] = signal_time
        return True

    async def options_step(self, plan=None, force=False):
        s = self.lifecycle.journal.state
        if s.get("plan") and s["phase"] != "idle":
            asset = s["plan"]["underlying"]
            decision = self.decision(asset)
            side = 1 if s["plan"]["kind"] == "call" else -1
            if self.state["hard_stop"]:
                force, self.option_reason = True, "hard_stop"
            elif decision.halt or decision.signal != side:
                force, self.option_reason = True, "signal_invalid"
            elif self.now - (s.get("opened_at") or self.now) >= 21600:
                force, self.option_reason = True, "time_limit"
        for offset in range(5):
            self.transport.now = self.now + offset
            risk = self.observe()
            # The model freezes the bar-open book for five virtual seconds.
            # A real RFQ/latency book is not available in this dataset.
            before_phase = self.lifecycle.journal.state["phase"]
            try:
                await self.lifecycle.step(plan=plan, budget=min(8, risk["risk_trade_budget"]),
                    allow_entry=not self.state["hard_stop"] and self.perp is None,
                    force_exit=force or self.state["hard_stop"], consume_entry=self.consume,
                    entry_budget=lambda a, t: min(8, risk["risk_trade_budget"]),
                    exit_required=lambda a, t: self.state["hard_stop"])
            except Exception as exc:
                # Same failure boundary as production tick; preserve uncertain intent.
                self.errors[type(exc).__name__] += 1
            after = self.lifecycle.journal.state
            if before_phase.startswith("quoting_exit") and after["phase"] == "settling" and not force:
                debit = float(after["entry_debit"]) + float(after["entry_fee"])
                net = -float(after["execution_cost"]) - float(after["max_fee"]) - debit
                self.option_reason = "take_profit" if net / debit >= .30 else "stop_loss"
            if len(after["trades"]) > self.option_trade_count:
                trade = after["trades"][-1]
                self.trades.append(dict(lane="options", asset=after["plan"]["underlying"],
                    opened_at=trade["opened_at"], closed_at=trade["closed_at"], net_pnl=float(trade["net_pnl"]),
                    fees=float(trade["fees"]), reason=self.option_reason or "delta_or_protective_exit",
                    amount=float(trade["amount"]), buy=trade["buy"], sell=trade["sell"],
                    entry_debit=float(trade["entry_debit"]), exit_credit=float(trade["exit_credit"])))
                self.option_trade_count += 1
                self.option_reason = None
                break
            if after["phase"] in ("idle", "halted") or (before_phase == "settling" and after["phase"] == "open"):
                break

    def close_perp(self, price, reason, when):
        p = self.perp
        fees = price * p["amount"] * p["fee_rate"] + p["base_fee"]
        gross = p["side"] * p["amount"] * (price - p["entry"])
        self.account["cash"] += gross - fees
        self.fees += fees
        self.perp_turnover += price * p["amount"]
        self.trades.append(dict(lane="perps", asset=p["asset"], opened_at=p["opened_at"], closed_at=when,
            amount=p["amount"], net_pnl=gross - fees - p["entry_fees"] - p["funding"],
            fees=fees + p["entry_fees"], funding=p["funding"], reason=reason,
            entry_price=p["entry"], exit_price=price, side=p["side"]))
        self.perp = None

    def entry_perp(self, asset, risk):
        decision = self.decision(asset)
        if decision.halt or not decision.signal:
            self.blocks[asset + ":" + decision.reason] += 1
            return False
        row = self.history[asset]["features"][self.index - 1]
        stop, profit, hold = dynamic_exits(row["atr_pct"], decision.confidence, 300)
        equity = min(800, self.equity())  # same operational budget cap as _account
        selected_profile = self.exposure_profile if asset == "ETH" else BASELINE_EXPOSURE
        limits = exposure_limits(selected_profile, asset)
        notional_fraction = .40 if selected_profile == ETH_EXPOSURE_TEST else .20
        budget = risk_size(equity=equity, available=min(800, self.account["cash"]), committed=0,
            confidence=decision.confidence, stop_pct=stop + 2 * (.0006 + .0015) + .0001,
            gross_cap=equity * limits["perp_gross"], risk_fraction=.005, notional_fraction=notional_fraction,
            peak_dd=risk["peak_dd"], drawdown_limit=float(HARD_STOP_DRAWDOWN), size_scale=risk["risk_scale"],
            trade_risk_budget=risk["risk_trade_budget"], exposure_profile=selected_profile, underlying=asset)
        if budget <= 0:
            self.blocks[asset + ":risk_budget_zero"] += 1
            return False
        rule = self.rules[asset + "-perp"]
        spot = self.surface.spots[asset]
        price = spot * (1 + decision.signal * self.scenario["perp_slip"])
        sized = venue_size(budget=budget, price=price, side=decision.signal,
            min_amount=rule["minimum_amount"], amount_step=rule["amount_step"], price_tick=rule["tick_size"],
            max_amount=rule["maximum_amount"])
        if sized.amount <= 0:
            self.blocks[asset + ":" + sized.reason] += 1
            return False
        amount, price = float(sized.amount), float(sized.price)
        notional = amount * max(spot, price)
        fee_rate = max(.0006, float(rule["taker_fee_rate"]), float(rule["maker_fee_rate"]))
        base = float(rule["base_fee"])
        costs = 2 * fee_rate + abs(price / spot - 1) + .0015 + 2 * base / notional + .0001
        if not cost_allows_entry(profit, costs, risk["cost_multiple"]):
            self.blocks[asset + ":cost_gate"] += 1
            return False
        if notional * (stop + costs) > risk["risk_trade_budget"] * decision.confidence:
            self.blocks[asset + ":trade_risk_budget"] += 1
            return False
        if self.now - self.last_entry < 300:
            self.blocks[asset + ":cooldown"] += 1
            return False
        fees = amount * price * fee_rate + base
        self.account["cash"] -= fees
        self.fees += fees
        self.perp_turnover += amount * price
        self.last_entry = self.now
        self.perp = dict(asset=asset, side=decision.signal, amount=amount, entry=price,
            opened_at=self.now, stop=stop, target=profit, hold=hold, fee_rate=fee_rate,
            base_fee=base, entry_fees=fees, funding=0.)
        return True

    async def run(self, limit=None):
        n = len(self.history["ETH"]["candles"])
        option_asset = self.mode.rsplit("-", 1)[-1] if self.mode != "perps" else None
        for i in range(101, min(n, limit or n)):
            self.index = i
            self.now = int(self.history["ETH"]["candles"][i]["timestamp"])
            self.surface.now = self.now
            self.surface.spots = {a: self.history[a]["candles"][i]["open"] for a in ASSETS}
            self.surface.ivs = {a: self.history[a]["iv"][i] for a in ("ETH", "BTC")}
            self.transport.now = self.now
            # Flat cash cannot change between events. Preserve every signal and
            # hourly/day risk observation without repeatedly validating Decimal
            # state on bars that provably cannot place an order.
            has_option = option_asset and self.decision(option_asset).option_direction
            has_perp = not self.mode.startswith("options") and any(self.decision(a).signal for a in ASSETS)
            if not self.perp and not self.lifecycle.busy and (self.state["hard_stop"] or not (has_option or has_perp)):
                if option_asset:
                    self.blocks[option_asset + ":no_option_signal"] += 1
                if not self.mode.startswith("options") and not self.state["hard_stop"]:
                    for asset in ASSETS:
                        self.blocks[asset + ":" + self.decision(asset).reason] += 1
                self.now += 300
                if i % 12 == 0 or i == n - 1 or int(self.now // 86400) != self.state["day"]:
                    self.observe()
                if i % 12 == 0 or i == n - 1:
                    self.curve.append(dict(time=self.now, equity=self.equity(), cash=self.account["cash"],
                        risk_mode=risk_view(self.state, max(0, self.equity()))["risk_mode"], lane="flat"))
                continue
            risk = self.observe()
            if self.perp:
                p = self.perp
                # Pay-only modeled carry, no historical funding attribution.
                funding = p["amount"] * self.surface.spots[p["asset"]] * self.scenario["funding"] * 300 / 3600
                self.account["cash"] -= funding
                self.funding += funding
                p["funding"] += funding
                decision = self.decision(p["asset"])
                reason = "hard_stop" if self.state["hard_stop"] else "signal_invalid" if decision.halt or decision.signal != p["side"] else "time_limit" if self.now - p["opened_at"] >= p["hold"] else None
                if reason:
                    self.close_perp(self.surface.spots[p["asset"]] * (1 - p["side"] * self.scenario["perp_slip"]), reason, self.now)
            if self.lifecycle.busy:
                await self.options_step()
            risk = self.observe()
            if not self.perp and not self.lifecycle.busy and not self.state["hard_stop"]:
                if option_asset:
                    decision = self.decision(option_asset)
                    if decision.option_direction and np.isfinite(self.surface.ivs[option_asset]):
                        plan, reason = self.surface.plan(option_asset, decision.option_direction, self.now,
                            min(800, self.equity()), risk, decision.confidence)
                        self.blocks[option_asset + ":" + reason] += 1
                        if plan:
                            await self.options_step(plan)
                    else:
                        self.blocks[option_asset + ":no_option_signal"] += 1
                if not self.lifecycle.busy and not self.mode.startswith("options"):
                    # Fixed, explicit priority; one RFQ profile, never two owners.
                    for asset in ASSETS:
                        if self.entry_perp(asset, risk):
                            break
            if self.perp:
                candle = self.history[self.perp["asset"]]["candles"][i]
                fill = barrier_fill(self.perp, candle, self.scenario["perp_slip"])
                if fill:
                    self.close_perp(*fill, self.now + 300)
            # Perp end-of-bar valuation; options only reprice at causal bar opens.
            # Keep separate feature/IV clocks to avoid using an unclosed IV candle.
            for asset in ASSETS:
                self.surface.spots[asset] = self.history[asset]["candles"][i]["close"]
            self.now += 300
            self.observe()
            if i % 12 == 0 or i == n - 1:
                self.curve.append(dict(time=self.now, equity=self.equity(), cash=self.account["cash"],
                    risk_mode=risk_view(self.state, max(0, self.equity()))["risk_mode"],
                    lane="options" if self.lifecycle.busy else "perps" if self.perp else "flat"))
        # A replay ending isn't a real fill. Report residual positions rather
        # than manufacture a terminal close beyond the available history.
        return self.summary()

    def summary(self):
        pnls = [t["net_pnl"] for t in self.trades]
        wins, losses = [v for v in pnls if v > 0], [v for v in pnls if v < 0]
        options = [t for t in self.trades if t["lane"] == "options"]
        return dict(id=self.identity, exposure_profile=self.exposure_profile, starting_equity=800, final_equity=self.equity(),
            net_pnl=self.equity() - 800, return_pct=(self.equity() / 800 - 1) * 100,
            max_drawdown_pct=self.max_dd * 100, trades=len(pnls), option_trades=len(options),
            perp_trades=len(pnls) - len(options), wins=len(wins), losses=len(losses),
            avg_win=float(np.mean(wins)) if wins else None, avg_loss=float(np.mean(losses)) if losses else None,
            avg_hold_minutes=float(np.mean([(t["closed_at"] - t["opened_at"]) / 60 for t in self.trades])) if pnls else None,
            fees=self.fees + self.transport.fees_total, modeled_funding=self.funding,
            perp_notional_turnover=self.perp_turnover, option_premium_turnover=self.transport.premium_turnover,
            option_underlying_reference_turnover=self.transport.reference_turnover,
            residual_perp=bool(self.perp), residual_options=bool(self.transport.positions),
            rfq_phase=self.lifecycle.journal.state["phase"], simulated_executions=self.transport.execute_count,
            lost_acknowledgements=self.transport.lost_acks, partial_quotes_rejected=self.transport.partial_rejections,
            errors=dict(self.errors), blocks=dict(self.blocks), exit_reasons=dict(Counter(t["reason"] for t in self.trades)),
            risk_transitions=self.transitions, final_risk=self.state, venue_executable_lots=not self.finer_lots,
            live_execution_verified=False, no_real_orders=True, execution_model="proxy OHLC/IV plus modeled RFQ books",
            source_window=dict(start=START, end_exclusive=END),
            option_profile_owner=self.mode.rsplit("-", 1)[-1] if self.mode != "perps" else None)


async def evaluate(history, rules, output, finer_lots=False, limit=None, exposure_profile=BASELINE_EXPOSURE):
    summaries = []
    for scenario in SCENARIOS:
        modes = ("options-ETH", "perps", "combined-ETH") if exposure_profile == ETH_EXPOSURE_TEST else MODES
        for mode in modes:
            if finer_lots and mode == "perps":
                continue
            replay = Replay(history, rules, mode, scenario, finer_lots, exposure_profile)
            started = time.monotonic()
            result = await replay.run(limit)
            summaries.append(result)
            destination = output / replay.identity
            destination.mkdir()
            (destination / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
            pd.DataFrame(replay.curve).to_csv(destination / "equity-hourly.csv", index=False)
            (destination / "trades.jsonl").write_text("".join(json.dumps(t, allow_nan=False) + "\n" for t in replay.trades))
            print(json.dumps({k: result[k] for k in ("id", "final_equity", "net_pnl", "trades", "option_trades", "rfq_phase")}) + f" elapsed={time.monotonic()-started:.1f}s", flush=True)
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--research-finer-lots", action="store_true")
    parser.add_argument("--exposure-profile", choices=(BASELINE_EXPOSURE, ETH_EXPOSURE_TEST), default=BASELINE_EXPOSURE)
    parser.add_argument("--limit", type=int, help="debug only; marks report incomplete")
    args = parser.parse_args()
    # Bind execution evidence to reviewed harness and shared runtime source.
    source_paths = [Path(__file__), Path("backtest/rfq_simulation.py"), Path("backtest/public_history.py"),
        Path("agents/condor_agent.py"), *Path("src/options").glob("*.py"),
        Path("src/risk/competition.py"), Path("src/risk/position_sizing.py"),
        Path("src/risk/venue_sizing.py"), Path("src/signal/flyby.py"),
        Path("src/risk/exposure.py"),
        Path("src/execution/options_rfq.py"), Path("src/execution/derive_rfq.py")]
    source_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    args.output.mkdir(parents=True, exist_ok=False)
    history, rules, manifest = load_history(args.history)
    rows = asyncio.run(evaluate(history, rules, args.output, limit=args.limit, exposure_profile=args.exposure_profile))
    if args.research_finer_lots:
        rows += asyncio.run(evaluate(history, rules, args.output, finer_lots=True, limit=args.limit,
                                     exposure_profile=args.exposure_profile))
    if any(hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest for p, digest in source_hashes.items()):
        raise ValueError("source_changed_during_evaluation")
    summary = dict(kind="flyby_two_year_proxy_execution_simulation", complete_two_year=args.limit is None,
        starting_equity_per_independent_case=800, combined_cases_share_one_account=True,
        policy="fixed baseline, not optimized on this history", no_real_orders=True,
        exposure_profile=args.exposure_profile,
        source_sha256=source_hashes,
        input_manifest_sha256=hashlib.sha256((args.history / "manifest.json").read_bytes()).hexdigest(),
        input_coverage={a: r["coverage"] for a, r in manifest["candles"].items()},
        iv_coverage={a: r["coverage"] for a, r in manifest["iv"].items()}, cases=rows,
        limitations=["No historical Derive option chain/BBO, RFQ makers, settlement or margin replay",
            "Binance underlying proxy, Deribit IV index; flat IV, zero rates, no observed skew",
            "Current Derive minimums/ticks/fees applied across history, not historical rules",
            "Modeled spreads/depth, five-second frozen book, immediate atomic settlement",
            "Options sampled at 5m bar opens, not historical tick execution",
            "Perp gap-aware OHLC barriers with SL-first ambiguity, modeled pay-only funding",
            "One position/RFQ reservation, ETH/BTC/SOL perp priority; one RFQ underlying per case",
            "RFQ in-memory journal here; persistence/restart tests are separate",
            "Finer-lot research is NOT exchange-compatible and changes no production settings",
            "No terminal artificial close, residual positions included in marked equity",
            "HYPE excluded: no verified common two-year history; no candles synthesized"])
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    table = pd.DataFrame([{k: r[k] for k in ("id", "net_pnl", "return_pct", "max_drawdown_pct", "trades",
        "option_trades", "fees", "modeled_funding", "perp_notional_turnover", "option_premium_turnover",
        "option_underlying_reference_turnover", "rfq_phase", "venue_executable_lots")} for r in rows])
    table.to_csv(args.output / "performance.csv", index=False)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 9), constrained_layout=True)
    for r in rows:
        frame = pd.read_csv(args.output / r["id"] / "equity-hourly.csv")
        axis = axes[0 if r["venue_executable_lots"] else 1]
        axis.plot(pd.to_datetime(frame.time, unit="s", utc=True), frame.equity, label=r["id"], linewidth=1)
    for axis, title in zip(axes, ("Current minimums — modeled executions, not Derive historical fills",
                                 "Hypothetical finer lots — NOT venue-compatible, not submission performance")):
        axis.axhline(800, color="gray", linestyle="--")
        axis.set(ylabel="Shared account equity ($)", title=title)
        axis.legend(fontsize=6)
    fig.savefig(args.output / "equity.png", dpi=150)
    plt.close(fig)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
