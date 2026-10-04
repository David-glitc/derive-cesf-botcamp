"""Fixed, offline SOL range-reversion experiment; never a live controller.

Reuse the submitted replay's account, venue-lot, fee, cost, sizing, barriers and
drawdown checks. A signal hypothesis is NOT an estimated success probability.
No fit, parameter sweep, maker fills, options, credential access or promotion.
"""
import argparse
import asyncio
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd

from agents.condor_agent import AgentDecision
from backtest.public_history import END
from backtest.two_year_flyby import Replay, load_history
from src.data.derive_public import DerivePublic
from src.data.records import native_candles, normalize_perp
from src.risk.position_sizing import dynamic_exits
from src.risk.competition import POLICY
from src.risk.venue_sizing import venue_size
from src.signal.flyby import feature_frame
from src.signal.microstructure import book_metrics


@dataclass(frozen=True)
class Hypothesis:
    lookback: int = 24
    entry_z: float = 2.0
    max_efficiency: float = .35
    restricted_entry_z: float = 3.0
    restricted_max_efficiency: float = .25
    risk_weight: float = .70
    restricted_risk_weight: float = .85
    max_hold_seconds: int = 1800


FIXED = Hypothesis()
WINDOWS = {"final_year": (END - 365 * 86400, END), "latest_48h": (END - 48 * 3600, END)}
VARIANTS = ("baseline_sol", "range_sol")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def range_features(candles):
    """Each row uses only that row and preceding closed bars, never a future label."""
    frame = pd.DataFrame(candles)
    base = feature_frame(frame, "5m")
    close = frame.close.where(base.price.notna())
    mean = close.rolling(FIXED.lookback).mean()
    deviation = close.rolling(FIXED.lookback).std(ddof=0)
    result = pd.DataFrame({"mean": mean, "z": (close - mean) / deviation.replace(0, np.nan),
                           "efficiency": base.efficiency, "atr_pct": base.atr_pct,
                           "price": base.price})
    result["valid"] = base.valid & np.isfinite(result).all(axis=1)
    return result.to_dict("records")


def range_decision(row, mode):
    if mode not in ("normal", "restricted", "hard_stop"):
        return AgentDecision("HALT", reason="invalid_risk_mode", halt=True)
    if mode == "hard_stop":
        return AgentDecision("HALT", reason="competition_hard_stop", halt=True)
    fields = ("mean", "z", "efficiency", "atr_pct", "price")
    if (row.get("valid") is not True or any(not isinstance(row.get(k), (int, float))
            or not math.isfinite(row[k]) for k in fields)):
        return AgentDecision("HALT", reason="invalid_range_inputs", halt=True)
    if min(row["price"], row["mean"]) <= 0 or not .0003 <= row["atr_pct"] <= .03:
        return AgentDecision("flat", reason="range_volatility_gate")
    restricted = mode == "restricted"
    floor = FIXED.restricted_entry_z if restricted else FIXED.entry_z
    ceiling = FIXED.restricted_max_efficiency if restricted else FIXED.max_efficiency
    if not 0 <= row["efficiency"] <= ceiling:
        return AgentDecision("flat", reason="not_range_regime")
    if abs(row["z"]) < floor:
        return AgentDecision("flat", reason="no_range_dislocation")
    side = -1 if row["z"] > 0 else 1
    return AgentDecision("offline_range_reversion", reason="range_dislocation", signal=side,
                         confidence=FIXED.restricted_risk_weight if restricted else FIXED.risk_weight,
                         execution_venue="offline_proxy_only", derive_instrument="SOL-PERP")


def slice_window(history, begin, end):
    times = np.array([c["timestamp"] for c in history["ETH"]["candles"]])
    start, finish = int(np.searchsorted(times, begin)), int(np.searchsorted(times, end))
    if start < 101 or finish - start != (end - begin) // 300:
        raise ValueError("complete_fixed_window_required")
    expected = np.arange(begin - 101 * 300, end, 300)
    result = {}
    for asset, data in history.items():
        candles = data["candles"][start - 101:finish]
        if not np.array_equal([r["timestamp"] for r in candles], expected):
            raise ValueError("unaligned_fixed_window:" + asset)
        result[asset] = dict(candles=candles, features=data["features"][start - 101:finish],
            decisions={k: v[start - 101:finish] for k, v in data["decisions"].items()},
            iv=data["iv"][start - 101:finish])
    return result


class SimpleReplay(Replay):
    def __init__(self, history, rules, scenario, variant):
        if variant not in VARIANTS:
            raise ValueError("unknown_simple_variant")
        super().__init__(history, rules, "perps", scenario)
        self.variant = variant
        self.identity += "-" + variant
        self.range_rows = range_features(history["SOL"]["candles"])
        self.fill_events = []

    def decision(self, asset):
        if asset != "SOL":
            return AgentDecision("flat", reason="single_market_scope")
        if self.variant == "baseline_sol":
            return super().decision(asset)
        row = self.range_rows[self.index - 1]
        if not row["valid"]:
            return AgentDecision("HALT", reason="invalid_range_inputs", halt=True)
        if self.perp:
            p = self.perp
            if p["side"] * (self.surface.spots[asset] - p["frozen_mean"]) >= 0:
                return AgentDecision("flat", reason="mean_reversion_exit")
            # A fading entry score isn't an exit. Stops, time and hard stop still apply.
            return AgentDecision("offline_owned_position", signal=p["side"], confidence=p["risk_weight"])
        return range_decision(row, "hard_stop" if self.state["hard_stop"] else
                              "restricted" if self.state["restricted"] else "normal")

    def entry_perp(self, asset, risk):
        if asset != "SOL":
            return False
        if self.variant == "range_sol":
            if self.history[asset]["candles"][self.index - 1]["timestamp"] + 300 != self.now:
                self.blocks["SOL:unclosed_or_gapped_signal"] += 1
                return False
            d = self.decision(asset)
            if d.halt or not d.signal:
                self.blocks["SOL:" + d.reason] += 1
                return False
            row = self.range_rows[self.index - 1]
            _, target, _ = dynamic_exits(self.history[asset]["features"][self.index - 1]["atr_pct"], d.confidence, 300)
            # The hypothesized mean must be beyond the original target even at
            # the next-open/slippage reference. A gap past it cannot enter.
            reference = self.surface.spots[asset] * (1 + d.signal * self.scenario["perp_slip"])
            rule = self.rules[asset + "-perp"]
            tick = float(rule["tick_size"])
            distance = d.signal * (row["mean"] / reference - 1)
            if distance < target + tick / reference:
                self.blocks["SOL:mean_inside_original_target"] += 1
                return False
        accepted = super().entry_perp(asset, risk)
        if accepted:
            p = self.perp
            if self.variant == "range_sol":
                p.update(frozen_mean=self.range_rows[self.index - 1]["mean"],
                         risk_weight=FIXED.restricted_risk_weight if self.state["restricted"] else FIXED.risk_weight,
                         hold=FIXED.max_hold_seconds)
            self.fill_events.append(dict(time=self.now, action="entry", notional=p["amount"] * p["entry"]))
        return accepted

    def close_perp(self, price, reason, when):
        if self.variant == "range_sol" and reason == "signal_invalid":
            if self.decision("SOL").reason == "mean_reversion_exit":
                reason = "mean_reversion"
        self.fill_events.append(dict(time=when, action="exit", notional=self.perp["amount"] * price))
        super().close_perp(price, reason, when)


def trade_statistics(trades):
    values = [t["net_pnl"] for t in trades]
    wins, losses = [v for v in values if v > 0], [-v for v in values if v < 0]
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return dict(net_win_rate=len(wins) / len(values) if values else None,
        net_expectancy=sum(values) / len(values) if values else None,
        realized_net_payoff_ratio=avg_win / avg_loss if avg_win is not None and avg_loss else None,
        profit_factor=sum(wins) / sum(losses) if losses else None,
        gross_closed_pnl=sum(t["net_pnl"] + t["fees"] + t["funding"] for t in trades),
        max_hold_minutes=max(((t["closed_at"] - t["opened_at"]) / 60 for t in trades), default=0),
        exit_reasons=dict(Counter(t["reason"] for t in trades)))


def native_probe(client=None):
    """A bounded public diagnostic, never fed into historical fills or live config."""
    client = client or DerivePublic()
    result = dict(kind="public_SOL_execution_surface_probe", network="mainnet", api_generation="legacy_v2",
                  no_real_orders=True, account_verified=False, matched_historical_quotes=False, samples=[], failures=[])
    for name, action in (
        ("instruments", lambda: client.call("public/get_all_instruments", dict(currency="SOL", instrument_type="perp",
                            expired=False, page=1, page_size=1000))),
        ("book", lambda: asyncio.run(client._book("SOL"))),
    ):
        try:
            raw = action()
            if name == "instruments":
                rule = next(r for r in raw["instruments"] if r["instrument_name"] == "SOL-PERP" and r["is_active"])
                result["rule"] = {k: rule[k] for k in ("minimum_amount", "amount_step", "tick_size", "maximum_amount",
                                                       "maker_fee_rate", "taker_fee_rate", "base_fee")}
            else:
                result["book"] = book_metrics(raw, "SOL-PERP", time.time(), amount=1.0)
        except Exception as exc:
            result["failures"].append(dict(stage=name, reason=type(exc).__name__))
    for _ in range(3):
        try:
            raw = client.call("public/get_ticker", {"instrument_name": "SOL-PERP"})
            result["samples"].append(normalize_perp(raw, "SOL", time.time()))
        except Exception as exc:
            result["failures"].append(dict(stage="ticker", reason=type(exc).__name__))
    if result["samples"] and "rule" in result:
        latest, rule = result["samples"][-1], result["rule"]
        if latest["ask"] > 0:
            sized = venue_size(budget=160, price=latest["ask"], side=1,
                min_amount=rule["minimum_amount"], amount_step=rule["amount_step"], price_tick=rule["tick_size"],
                max_amount=rule["maximum_amount"])
            result["size_probe"] = dict(reason=sized.reason, amount=str(sized.amount), minimum_notional=str(sized.minimum_notional))
    result.update(observed_at=time.time(), records=client.records,
                  usable_quote_samples=sum(s["quoted"] for s in result["samples"]),
                  limitation="Three L1 samples and one bounded L2 snapshot; no queue, fills, complete tape or alpha proof")
    return result


async def evaluate(history, rules, output):
    cases = []
    for label, (begin, end) in WINDOWS.items():
        local = slice_window(history, begin, end)
        for scenario in ("base", "stress"):
            for variant in VARIANTS:
                replay = SimpleReplay(local, rules, scenario, variant)
                result = await replay.run()
                result.update(trade_statistics(replay.trades), window=label, variant=variant, scenario=scenario,
                              source_window=dict(start=begin, end_exclusive=end), promoted=False,
                              mean_turnover_per_48h=result["perp_notional_turnover"] * 48 * 3600 / (end - begin))
                result["latest_window_meets_30k"] = label == "latest_48h" and result["perp_notional_turnover"] >= 30000
                if result["errors"] or result["residual_options"] or result["option_trades"]:
                    raise ValueError("single_perp_replay_invariant_failed")
                if not replay.perp and abs(result["net_pnl"] - sum(t["net_pnl"] for t in replay.trades)) > 1e-7:
                    raise ValueError("cash_trade_ledger_mismatch")
                if abs(result["perp_notional_turnover"] - sum(e["notional"] for e in replay.fill_events)) > 1e-7:
                    raise ValueError("turnover_ledger_mismatch")
                destination = output / (label + "-" + replay.identity)
                destination.mkdir()
                (destination / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
                for name, rows in (("trades", replay.trades), ("fills", replay.fill_events)):
                    (destination / (name + ".jsonl")).write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in rows))
                pd.DataFrame(replay.curve).to_csv(destination / "equity-hourly.csv", index=False)
                cases.append(result)
                print(json.dumps({k: result[k] for k in ("window", "variant", "scenario", "trades", "net_pnl",
                                                       "perp_notional_turnover", "residual_perp")}), flush=True)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-native", action="store_true", help="bounded public reads; no private account")
    args = parser.parse_args()
    source_paths = [Path(__file__), Path("agents/condor_agent.py"), Path("backtest/two_year_flyby.py"),
                    Path("backtest/rfq_simulation.py"), Path("backtest/public_history.py"),
                    *Path("src/risk").glob("*.py"), Path("src/signal/flyby.py"),
                    Path("src/data/derive_public.py"), Path("src/data/records.py"), Path("src/signal/microstructure.py")]
    sources = {str(p): sha(p) for p in source_paths}
    args.output.mkdir(parents=True, exist_ok=False)
    # Record the frozen hypothesis before fetching data or seeing results.
    (args.output / "hypothesis.json").write_text(json.dumps(dict(parameters=asdict(FIXED), windows=WINDOWS,
        variants=VARIANTS, fit=False, live_authorized=False, created_at=time.time()), indent=2) + "\n")
    if args.capture_native:
        probe = native_probe()
        (args.output / "native-probe.json").write_text(json.dumps(probe, indent=2, allow_nan=False) + "\n")
        print(json.dumps(dict(native_usable_samples=probe["usable_quote_samples"], failures=probe["failures"])), flush=True)
    history, rules, _ = load_history(args.history)
    cases = asyncio.run(evaluate(history, rules, args.output))
    if any(sha(Path(p)) != digest for p, digest in sources.items()):
        raise ValueError("source_changed_during_experiment")
    summary = dict(kind="fixed_single_market_range_reversion_experiment", hypothesis=asdict(FIXED), cases=cases,
        source_sha256=sources, input_manifest_sha256=sha(args.history / "manifest.json"),
        artifact_sha256={str(p.relative_to(args.output)): sha(p) for p in args.output.rglob("*") if p.is_file()},
        allocation_ceiling=800, perp_notional_ceiling=160, concurrency=1, risk_policy=POLICY,
        promoted=False, production_changes=False, live_ready=False, no_real_orders=True,
        limitations=["One fixed hypothesis; no fitting, grid search, selected best window or performance guarantee",
            "Already-inspected Binance proxy history; not untouched out-of-sample discovery",
            "Still directional exposure, not delta-neutral or inventory market making",
            "Same representative historical venue rules and conservative fee/slippage model as baseline",
            "Native quotes kept separate; not backfilled into historical fills or used as account verification",
            "Original cost hurdle is target-distance plausibility, not calibrated expected profit",
            "Net win/loss averages include fees and funding; no extra cost subtraction",
            "Drawdown is bar-open/end marked; gap/barrier ambiguity handled conservatively, not full intrabar DD",
            "Independent $800 accounts per case; annual average turnover isn't a 48h forecast",
            "No artificial final close; residuals remain marked and explicitly reported",
            "Production profile, ownership recovery and mainnet readiness remain unchanged"])
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    pd.DataFrame([{k: r[k] for k in ("window", "variant", "scenario", "trades", "net_pnl", "max_drawdown_pct",
                    "net_win_rate", "realized_net_payoff_ratio", "fees", "perp_notional_turnover",
                    "avg_hold_minutes", "residual_perp")} for r in cases]).to_csv(args.output / "performance.csv", index=False)
    print(json.dumps(dict(cases=len(cases), promoted=False, live_ready=False)), flush=True)


if __name__ == "__main__":
    main()
