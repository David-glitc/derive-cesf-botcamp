"""Creds-free live Derive testnet scanner (public data only, no orders).
Polls Derive demo public tickers + Binance proxy klines for features,
runs Condor decide() per instrument, appends JSONL.
Usage inside hb-derive-py: PYTHONPATH=/repo python3 /tmp/live_testnet_scan.py
  --hours 5 --tick-seconds 60 --universe ETH-PERP,BTC-PERP,SOL-PERP,HYPE-PERP
"""
import argparse, json, sys, time
from datetime import datetime, timezone
sys.path.insert(0, "/repo")
import os
os.environ["DERIVE_DOMAIN"] = "testnet"
from src.venue.derive import get_ticker
from agents.condor_agent import decide

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=5)
    ap.add_argument("--tick-seconds", type=float, default=60)
    ap.add_argument("--universe", default="ETH-PERP,BTC-PERP,SOL-PERP,HYPE-PERP")
    ap.add_argument("--log", default="/repo/hb_backtest/live_testnet_scan.jsonl")
    a = ap.parse_args()
    universe = [u.strip() for u in a.universe.split(",") if u.strip()]
    end = time.time() + a.hours * 3600
    tick = 0
    # feature klines: reuse Binance proxy (public) for edge/cesf
    from backtest.run_backtest import fetch_klines, ensemble_sigma, cesf_score
    import numpy as np
    feats = {}
    for inst in universe:
        ccy = inst.split("-")[0]
        try:
            df = fetch_klines(f"{ccy}USDT", "1h", 8)
            closes = df["close"].values.astype(float)
            rets = np.diff(np.log(np.maximum(closes, 1e-8)))
            window = rets[-100:]
            sigma, eps, _, _ = ensemble_sigma(window, 365 * 24)
            score = cesf_score(window, sigma, eps)
            recent = float(np.sqrt(np.mean(window[-20:] ** 2) * 365 * 24))
            feats[inst] = dict(edge=sigma - recent, cesf=score, eps=eps,
                               mom=float(np.sum(rets[-24:])), px=float(closes[-1]))
        except Exception as e:
            feats[inst] = dict(error=str(e)[:120])
    print(f"[{now()}] live testnet scan start universe={','.join(universe)} hours={a.hours}", flush=True)
    while time.time() < end:
        tick += 1
        for inst in universe:
            rec = {"ts": now(), "tick": tick, "instrument": inst}
            try:
                t = get_ticker(inst)
                mark = t.get("mark_price") or t.get("markPrice") or t.get("last_price")
                rec["mark"] = mark
                rec["ticker_ok"] = True
            except Exception as e:
                rec["ticker_ok"] = False
                rec["error"] = str(e)[:200]
            f = feats.get(inst, {})
            if "error" not in f:
                ccy = inst.split("-")[0]
                snap = {"cesf_score": f["edge"] and f["cesf"], "edge": f["edge"],
                        "svi_skew": 0.0, "momentum": f["mom"], "epsilon": f["eps"],
                        "ccy": ccy, "spot": rec.get("mark") or f["px"],
                        "stale_secs": 0, "daily_pnl_pct": 0}
                try:
                    d = decide(snap)
                    rec["regime"] = d.regime
                    rec["venue"] = d.execution_venue
                    rec["edge"] = round(f["edge"], 4)
                    rec["cesf"] = round(f["cesf"], 3)
                except Exception as e:
                    rec["decide_error"] = str(e)[:200]
            else:
                rec["feature_error"] = f["error"]
            with open(a.log, "a") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(f"[{now()}] tick={tick} {inst} mark={rec.get('mark')} regime={rec.get('regime')}", flush=True)
        time.sleep(a.tick_seconds)
    print(f"[{now()}] scan done ticks={tick}", flush=True)

if __name__ == "__main__":
    main()
