"""Fixed latest-archive 48h replay with stricter entries and operation traces.

No best-window search, fitting, live transport, cap changes or promotion. The
quality filter is a research heuristic, not a probability of a winning trade.
"""
import argparse
import asyncio
from collections import Counter
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from backtest.alpha_walkforward import AlphaReplay, LeanSurface, sha
from backtest.public_history import ASSETS, START, END
from backtest.rfq_simulation import Surface
from backtest.two_year_flyby import Replay, load_history
from src.signal.alpha_research import features, predict

BEGIN = END - 48 * 3600
VARIANTS = ("baseline", "high_quality", "high_quality_alpha")
QUALITY = dict(confidence=.85, trend_z=1.5, efficiency=.45, volume_ratio=1.5)


def quality_reason(row, decision):
    if decision.halt or not decision.signal:
        return "original_signal_unqualified"
    if not math.isfinite(decision.confidence) or decision.confidence < QUALITY["confidence"]:
        return "quality_confidence"
    for field in ("trend_z", "efficiency", "volume_ratio"):
        values = [row.get(field), row.get("previous_" + field)]
        if any(v is None or not math.isfinite(float(v)) for v in values):
            return "quality_invalid_features"
        if field == "trend_z":
            if any(decision.signal * float(v) < QUALITY[field] for v in values):
                return "quality_trend_confirmation"
        elif any(float(v) < QUALITY[field] for v in values):
            return "quality_" + field
    return "quality_pass"


class QualitySurface(Surface):
    def __init__(self, rules, spread, replay, downstream=None):
        super().__init__(rules, spread)
        self.replay, self.downstream = replay, downstream

    def plan(self, asset, kind, now, equity, risk, confidence):
        row = self.replay.history[asset]["features"][self.replay.index - 1]
        reason = quality_reason(row, self.replay.decision(asset))
        if reason != "quality_pass":
            self.replay.record("option_quality", asset=asset, reason=reason)
            return None, reason
        target = self.downstream or self
        if self.downstream:
            target.spots, target.ivs, target.now = self.spots, self.ivs, self.now
            # Execution transport subsequently reprices the same contracts.
            target.contracts = self.contracts
        plan, reason = (target.plan(asset, kind, now, equity, risk, confidence) if self.downstream
                        else super().plan(asset, kind, now, equity, risk, confidence))
        self.replay.record("option_construction", asset=asset, reason=reason, qualified=plan is not None)
        return plan, reason


class TracedReplay(AlphaReplay):
    def __init__(self, history, rules, mode, scenario, variant, models, forecasts, full_forecasts, start):
        Replay.__init__(self, history, rules, mode, scenario)
        if variant not in VARIANTS:
            raise ValueError("unknown_48h_variant")
        self.variant, self.models, self.forecasts, self.start = variant, models, forecasts, 101
        self.operations = {}
        self.identity += "-48h-" + variant
        if variant != "baseline":
            downstream = LeanSurface(rules, self.scenario["spread"], models, full_forecasts, start) if variant == "high_quality_alpha" else None
            self.surface = QualitySurface(rules, self.scenario["spread"], self, downstream)
            self.transport.surface = self.surface

    def record(self, stage, **data):
        slot = int(self.now // 300) * 300
        if BEGIN <= slot < END:
            self.operations.setdefault(slot, []).append(dict(stage=stage, **data))

    def decision(self, asset):
        d = super().decision(asset)
        row = self.history[asset]["features"][self.index - 1]
        self.record("signal", asset=asset, signal=d.signal, confidence=d.confidence,
                    reason=d.reason, quality=quality_reason(row, d))
        return d

    def observe(self):
        view = super().observe()
        self.record("risk_observation", equity=self.equity(), risk_mode=view["risk_mode"],
                    risk_budget=view["risk_trade_budget"],
                    lane="perps" if self.perp else "options" if self.lifecycle.busy else "flat")
        return view

    def entry_perp(self, asset, risk):
        decision = self.decision(asset)
        if self.variant != "baseline":
            reason = quality_reason(self.history[asset]["features"][self.index - 1], decision)
            if reason != "quality_pass":
                self.blocks[asset + ":" + reason] += 1
                self.record("entry_rejected", asset=asset, reason=reason)
                return False
        before = self.blocks.copy()
        placed = (AlphaReplay.entry_perp(self, asset, risk) if self.variant == "high_quality_alpha"
                  else Replay.entry_perp(self, asset, risk))
        changed = {k: v - before[k] for k, v in self.blocks.items() if v > before[k]}
        self.record("entry_attempt", asset=asset, accepted=placed, blocks=changed,
                    amount=self.perp["amount"] if placed else None,
                    entry=self.perp["entry"] if placed else None)
        return placed

    def close_perp(self, price, reason, when):
        super().close_perp(price, reason, when)
        self.record("perp_close", reason=reason, fill_time=when, net_pnl=self.trades[-1]["net_pnl"])

    def trace_rows(self):
        return [dict(time=t, stages=self.operations.get(t, []),
                     interpretation="virtual replay operations, not live controller/Condor ticks")
                for t in range(BEGIN, END, 300)]


def window(history):
    times = np.array([r["timestamp"] for r in history["ETH"]["candles"]])
    start = int(np.searchsorted(times, BEGIN))
    end = int(np.searchsorted(times, END))
    if end - start != 576 or start < 101 or times[start] != BEGIN:
        raise ValueError("complete_latest_48h_required")
    lo = start - 101
    local = {a: dict(candles=h["candles"][lo:end], features=h["features"][lo:end],
                     decisions={k: v[lo:end] for k, v in h["decisions"].items()}, iv=h["iv"][lo:end])
             for a, h in history.items()}
    return local, start, lo, end


def frozen_forecasts(history, model_path):
    models = json.loads(model_path.read_text())
    full = {}
    for asset in ASSETS:
        frame = pd.DataFrame(history[asset]["candles"])
        model = models[asset]
        if model["evaluation_not_before"] > BEGIN - 300 or model["live_authorized"] is not False:
            raise ValueError("frozen_pre_window_model_required")
        use_iv = "iv_available" in model["features"]
        x = features(frame, history[asset]["iv"] if use_iv else None)
        lo = int(np.searchsorted(frame.timestamp, model["evaluation_not_before"]))
        p, ood = predict(model, x.iloc[lo:], frame.timestamp.iloc[lo:])
        full[asset] = (np.r_[np.full(lo, np.nan), p], np.r_[np.ones(lo, dtype=bool), ood])
    return models, full


async def evaluate(history, rules, models, full, output):
    local, start, lo, end = window(history)
    forecasts = {a: (p[lo:end], ood[lo:end]) for a, (p, ood) in full.items()}
    cases = []
    for scenario in ("base", "stress"):
        for mode in ("perps", "options-ETH", "combined-ETH"):
            for variant in VARIANTS:
                replay = TracedReplay(local, rules, mode, scenario, variant, models, forecasts, full, start)
                result = await replay.run()
                result.update(variant=variant, source_window=dict(start=BEGIN, end_exclusive=END),
                              replay_bars=576, horizon_hours=48, promoted=False)
                result["gross_closed_pnl"] = sum(t["net_pnl"] + t["fees"] + t.get("funding", 0) for t in replay.trades)
                result["mean_trades_per_day"] = result["trades"] / 2
                result["pending_lifecycle"] = replay.lifecycle.busy
                result["drawdown_screen_scope"] = "bar-open/end marked equity, not full intrabar loss"
                holds = [(t["closed_at"] - t["opened_at"]) / 60 for t in replay.trades]
                result["max_hold_minutes"] = max(holds, default=0)
                destination = output / result["id"]
                destination.mkdir()
                (destination / "summary.json").write_text(json.dumps(result, indent=2, allow_nan=False))
                (destination / "operations.jsonl").write_text("".join(json.dumps(r, allow_nan=False) + "\n" for r in replay.trace_rows()))
                (destination / "trades.jsonl").write_text("".join(json.dumps(t, allow_nan=False) + "\n" for t in replay.trades))
                pd.DataFrame(replay.curve).to_csv(destination / "equity-hourly.csv", index=False)
                cases.append(result)
                print(json.dumps({k: result[k] for k in ("id", "net_pnl", "trades", "option_trades")}), flush=True)
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    # Use an earlier checked artifact, not a model silently refitted on this run.
    provenance = json.loads((args.models.parent / "summary.json").read_text())
    if provenance["artifact_sha256"].get(args.models.name) != sha(args.models):
        raise ValueError("frozen_model_hash_mismatch")
    for name, digest in provenance["source_sha256"].items():
        if sha(Path(name)) != digest:
            raise ValueError("model_evidence_source_changed:" + name)
    sources = {**provenance["source_sha256"], str(Path(__file__)): sha(Path(__file__))}
    args.output.mkdir(parents=True, exist_ok=False)
    history, rules, _ = load_history(args.history)
    models, forecasts = frozen_forecasts(history, args.models)
    cases = asyncio.run(evaluate(history, rules, models, forecasts, args.output))
    if any(sha(Path(name)) != digest for name, digest in sources.items()):
        raise ValueError("sources_changed_during_run")
    summary = dict(kind="fixed_latest_archive_48h_quality_replay", horizon_hours=48,
        source_window=dict(start=BEGIN, end_exclusive=END), cases=cases, quality_thresholds=QUALITY,
        starting_equity_per_independent_case=800, models_sha256=sha(args.models),
        input_manifest_sha256=sha(args.history / "manifest.json"), source_sha256=sources,
        artifact_sha256={str(p.relative_to(args.output)): sha(p) for p in args.output.rglob("*") if p.is_file()},
        no_real_orders=True, production_changes=False, live_ready=False, promoted=False,
        limitations=["Latest fixed archive window, not a live 48h run or fresh market capture",
                     "History already inspected; no untouched forward-discovery or profitable selection claim",
                     "High quality means heuristic entry thresholds, not calibrated success probability",
                     "No retraining, window optimization or weakening of exits/risk/lot/cost gates",
                     "Proxy OHLC/IV, modeled option books/RFQs, no native margin/fill/queue proof",
                     "Account latches simulated in memory; actual persistent checkpoints never changed",
                     "Risk marks at bar open/end; full intrabar peak-to-trough loss not measured",
                     "Trace records simulator calls; not actual Hummingbot or Condor execution ticks",
                     "Residual positions/pending intents remain marked, never force-flattened at horizon",
                     "Actual option fee-cap/recovery blocker remains quarantined"])
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(completed_cases=len(cases), horizon_hours=48, live_ready=False)), flush=True)


if __name__ == "__main__":
    main()
