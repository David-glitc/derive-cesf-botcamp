"""Chronological polynomial alpha ablation on inspected public proxy history.

Selection uses validation prediction error only. Later execution replays use
the frozen choice and the existing shared $800 ledger and production RFQ reducer.
No live model registration, risk-cap edits or automatic promotion.
"""
import argparse
import asyncio
import hashlib
import itertools
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd

from backtest.public_history import ASSETS, START, END
from backtest.two_year_flyby import Replay, load_history
from backtest.rfq_simulation import Surface, model_price
from src.signal.alpha_research import features, labels, fit, predict, entry_gate
from src.options.greeks_research import greeks, lean_gate, quote_diagnostic, YEAR

TRAIN_END = 1743465600  # 2025-04-01 UTC
TEST_START = 1759276800  # 2025-10-01 UTC
GRID = tuple(itertools.product((1, 2), (100., 10000.), (6, 12), (False, True)))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(y, p, ood):
    valid = np.isfinite(y) & np.isfinite(p)
    if not valid.any():
        raise ValueError("missing_evaluation_labels")
    error = float(np.mean((y[valid] - p[valid]) ** 2))
    zero = float(np.mean(y[valid] ** 2))
    return dict(rows=int(valid.sum()), rmse_bps=math.sqrt(error) * 10000,
                zero_rmse_bps=math.sqrt(zero) * 10000, relative_mse=error / zero,
                ood_fraction=float(np.mean(ood)),
                correlation=float(np.corrcoef(y[valid], p[valid])[0, 1])
                if np.std(p[valid]) > 1e-12 else None)


def select_models(frames, ivs, output):
    matrices = {(asset, use_iv): features(frames[asset], ivs[asset] if use_iv else None)
                for asset in ASSETS for use_iv in (False, True)}
    times = frames["ETH"].timestamp.to_numpy()
    train, test = (int(np.searchsorted(times, t)) for t in (TRAIN_END, TEST_START))
    if not all(np.array_equal(times, frames[a].timestamp) for a in ASSETS):
        raise ValueError("aligned_asset_clocks_required")
    candidates = []
    for degree, penalty, horizon, use_iv in GRID:
        rows = []
        for asset in ASSETS:
            x = matrices[asset, use_iv]
            m = fit(frames[asset], x, train, degree=degree, penalty=penalty, horizon=horizon)
            # Leave target endpoints strictly within the validation partition.
            stop = test - horizon - 1
            p, ood = predict(m, x.iloc[train:stop], times[train:stop])
            rows.append(dict(asset=asset, **metrics(labels(frames[asset], horizon)[train:stop], p, ood)))
        identity = f"d{degree}-a{int(penalty)}-h{horizon}-{'iv' if use_iv else 'underlying'}"
        candidate = dict(id=identity, degree=degree, penalty=penalty, horizon=horizon, use_iv=use_iv,
                         score=float(np.mean([r["relative_mse"] for r in rows])), validation=rows)
        candidates.append(candidate)
        print(json.dumps(dict(candidate=identity, validation_relative_mse=candidate["score"])), flush=True)
    chosen = min(candidates, key=lambda r: (r["score"], r["degree"], -r["penalty"], r["id"]))
    # Save the choice before evaluating any final-period outcomes.
    (output / "selection.json").write_text(json.dumps(dict(chosen=chosen, candidates=candidates,
        objective="mean per-asset validation MSE / zero-return MSE; not P&L tuning"), indent=2, allow_nan=False))
    models, forecasts, evaluation = {}, {}, []
    for asset in ASSETS:
        x = matrices[asset, chosen["use_iv"]]
        m = fit(frames[asset], x, test, degree=chosen["degree"], penalty=chosen["penalty"], horizon=chosen["horizon"])
        models[asset] = m
        # Replay uses feature i-1 at open i. Keep a warmup slice from the full
        # causal feature tape, and prohibit entries before the fitted boundary.
        p, ood = predict(m, x.iloc[test:], times[test:])
        forecasts[asset] = (np.r_[np.full(test, np.nan), p], np.r_[np.ones(test, dtype=bool), ood])
        stop = len(times) - m["horizon"] - 1
        evaluation.append(dict(asset=asset, **metrics(labels(frames[asset], m["horizon"])[test:stop],
                               p[:stop - test], ood[:stop - test])))
    (output / "models.json").write_text(json.dumps(models, indent=2, allow_nan=False))
    return chosen, models, forecasts, evaluation, test


class LeanSurface(Surface):
    """Research-only veto. Never waive lot/delta/debit/fee construction gates."""
    def __init__(self, rules, spread, models, forecasts, start):
        super().__init__(rules, spread)
        self.models, self.forecasts, self.start = models, forecasts, start

    def plan(self, asset, kind, now, equity, risk, confidence):
        plan, reason = super().plan(asset, kind, now, equity, risk, confidence)
        if plan is None:
            return plan, reason
        i = int((now - START) // 300) - 1
        p, ood = self.forecasts[asset]
        m = self.models[asset]
        side = 1 if kind == "call" else -1
        if i < self.start or ood[i] or not np.isfinite(p[i]):
            return None, "lean_missing_or_ood_alpha"
        move = math.expm1(p[i] - side * .25 * m["residual_rmse"])
        horizon = m["horizon"] * 300
        amounts, future_prices, net_theta = float(plan["amount"]), [], 0.
        for name, sign in ((plan["buy"], 1), (plan["sell"], -1)):
            _, strike, expiry, k = self.contracts[name]
            spot, iv = self.spots[asset], self.ivs[asset]
            g = greeks(spot, strike, (expiry - now) / YEAR, 1., iv, k)
            net_theta += sign * amounts * g["theta_per_calendar_day_fixed_discount"]
            future, _ = model_price(spot * (1 + move), strike, expiry, now + horizon, iv, k)
            tick = float(self.metadata(asset)["tick_size"])
            # Marked future prices with the existing modeled BBO wedge, not RFQ
            # offers. No historical skew or future IV forecast is invented.
            price = max(tick, math.floor(future * (1 - self.spread / 2) / tick) * tick) if sign > 0 else max(
                tick, math.ceil(future * (1 + self.spread / 2) / tick) * tick)
            future_prices.append(price)
        credit = amounts * (future_prices[0] - future_prices[1])
        budget = min(4., risk["risk_trade_budget"])
        if not lean_gate(debit=float(plan["debit"]), fee_reserve=float(plan["round_trip_fees"]),
                         max_loss=float(plan["max_loss"]), budget=budget, expected_credit=credit,
                         theta_drag=max(0., -net_theta * horizon / 86400)):
            return None, "lean_fee_theta_or_net_edge_veto"
        return plan, "qualified_lean_model_only"


class AlphaReplay(Replay):
    def __init__(self, history, rules, mode, scenario, models, forecasts, start):
        super().__init__(history, rules, mode, scenario)
        self.models, self.forecasts, self.start = models, forecasts, start
        surface = LeanSurface(rules, self.scenario["spread"], models, forecasts, start)
        self.surface = surface
        self.transport.surface = surface
        self.identity += "-polynomial-veto-lean-options"

    def entry_perp(self, asset, risk):
        decision = self.decision(asset)
        if decision.halt or not decision.signal:
            return super().entry_perp(asset, risk)
        i = self.index - 1
        p, ood = self.forecasts[asset]
        rule = self.rules[asset + "-perp"]
        # Conservative fixed-fee bound at the venue minimum rather than assuming
        # every actual rounded order achieves the maximum $160 notional.
        minimum_notional = float(rule["minimum_amount"]) * self.surface.spots[asset] * .99
        rate = max(.0006, float(rule["taker_fee_rate"]), float(rule["maker_fee_rate"]))
        cost = 2 * rate + self.scenario["perp_slip"] + .0015 + .0001 + 2 * float(rule["base_fee"]) / minimum_notional
        if (i < self.start or not entry_gate(p[i], ood[i], self.models[asset]["residual_rmse"],
                                            decision.signal, cost, self.state["restricted"])):
            self.blocks[asset + ":polynomial_net_edge_veto"] += 1
            return False
        return super().entry_perp(asset, risk)


def slice_history(history, test):
    # Keep 101 earlier bars so the original replay starts at the exact test open.
    lo = test - 101
    return {a: dict(candles=h["candles"][lo:], features=h["features"][lo:],
                    decisions={mode: rows[lo:] for mode, rows in h["decisions"].items()}, iv=h["iv"][lo:])
            for a, h in history.items()}


async def evaluate(history, rules, models, forecasts, test, output):
    histories = slice_history(history, test)
    offset = test - 101
    local_forecasts = {a: (p[offset:], ood[offset:]) for a, (p, ood) in forecasts.items()}
    cases = []
    for scenario in ("base", "stress"):
        for mode in ("perps", "options-ETH", "combined-ETH"):
            for variant in ("baseline", "polynomial_veto"):
                if variant == "baseline":
                    replay = Replay(histories, rules, mode, scenario)
                else:
                    replay = AlphaReplay(histories, rules, mode, scenario, models, local_forecasts, 101)
                    # Option surface references the full history clock, not the
                    # shortened replay's local index.
                    replay.surface.forecasts, replay.surface.start = forecasts, test
                result = await replay.run()
                # Do not label the parent's global source_window as test coverage.
                result["source_window"] = dict(start=TEST_START, end_exclusive=END)
                result["variant"] = variant
                result["model_horizon_seconds"] = models["ETH"]["horizon"] * 300
                cases.append(result)
                dest = output / result["id"]
                dest.mkdir()
                (dest / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False))
                (dest / "trades.jsonl").write_text("".join(json.dumps(t, allow_nan=False) + "\n" for t in replay.trades))
                pd.DataFrame(replay.curve).to_csv(dest / "equity-hourly.csv", index=False)
                print(json.dumps({k: result[k] for k in ("id", "net_pnl", "trades", "option_trades")}), flush=True)
    return cases


def native_inventory():
    rows = []
    for path in sorted(Path("data/native-derive").glob("*/market.jsonl")):
        snapshots = [json.loads(l) for l in path.read_text().splitlines() if l]
        quotes = [q for s in snapshots for q in s.get("options", [])]
        rows.append(dict(path=str(path), sha256=sha(path), snapshots=len(snapshots), option_quotes=len(quotes),
                         greek_complete_quotes=sum(all(q.get("pricing", {}).get(k) is not None
                              for k in ("delta", "gamma", "vega", "theta")) for q in quotes),
                         used_in_two_year_training=False))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources = [Path(__file__), Path("src/signal/alpha_research.py"), Path("src/options/greeks_research.py"),
               Path("backtest/two_year_flyby.py"), Path("backtest/rfq_simulation.py"),
               Path("agents/condor_agent.py"), *Path("src/options").glob("*.py"),
               *Path("src/risk").glob("*.py"), Path("src/execution/options_rfq.py"),
               Path("src/execution/derive_rfq.py"), Path("src/signal/flyby.py"), Path("backtest/public_history.py")]
    source_hashes = {str(p): sha(p) for p in sources}
    history, rules, manifest = load_history(args.history)
    frames = {a: pd.DataFrame(history[a]["candles"]) for a in ASSETS}
    chosen, models, forecasts, forecast_metrics, test = select_models(
        frames, {a: history[a]["iv"] for a in ASSETS}, args.output)
    cases = asyncio.run(evaluate(history, rules, models, forecasts, test, args.output))
    if any(sha(Path(p)) != digest for p, digest in source_hashes.items()):
        raise ValueError("source_changed_during_run")
    artifacts = {str(p.relative_to(args.output)): sha(p) for p in args.output.rglob("*") if p.is_file()}
    summary = dict(kind="chronological_alpha_proxy_research", starting_equity=800,
        train_window=[START, TRAIN_END], validation_window=[TRAIN_END, TEST_START],
        execution_test_window=[TEST_START, END], chosen=chosen, forecast_test_metrics=forecast_metrics,
        candidates=len(GRID), cases=cases, native_inventory=native_inventory(),
        historical_option_chains_available=False, api_greeks_used_in_historical_training=False,
        source_sha256=source_hashes, input_manifest_sha256=sha(args.history / "manifest.json"),
        artifact_sha256=artifacts, elapsed_seconds=time.monotonic() - started,
        promoted=False, no_real_orders=True, live_ready=False,
        limitations=["Already-inspected history; chronological fit holdout is not untouched discovery or forward proof",
                     "Polynomial predicts underlying next-open log returns, not option profit or IV/skew alpha",
                     "Lagged Deribit IV index; Binance OHLCV proxy; no historical Derive option chains",
                     "One frozen selection, refitted on pre-test history, no repeated optimization on final results",
                     "Original signal/stop/risk logic and baseline exposure unchanged; learned candidate is an entry veto",
                     "Mean validation forecast MSE selection is not maximization of strategy net P&L",
                     "Option credits use point drift, fixed IV and modeled spreads; uncertainty buffer is not calibrated",
                     "Full production RFQ reducer uses modeled in-memory transport, not live RFQ offers or margin",
                     "Persistent competition risk latches, no forced final close; year-long accounts are not 48h contest resets",
                     "Unresolved actual option fee-cap exit blocker remains quarantined"])
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(completed_cases=len(cases), elapsed_seconds=summary["elapsed_seconds"],
                          selected=chosen["id"], promoted=False)), flush=True)


if __name__ == "__main__":
    main()
