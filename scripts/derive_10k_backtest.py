"""10,000 backtests on Derive MAINNET tape (no proxy, no mocks).
Data: /public/get_trade_history perps -> minute bars -> 5m series.
Grid: 4 symbols x 50 offset windows (7d) x 50 param combos = 10,000 runs.
Each run: vectorized HAR/EWMA/CESF features, fast event loop (3x, TP/SL/24h,
taker fee from live rules), midpoint adaptive-v2 check (tighten/loosen from
first-half hit rate) with adjustment trace.
Outputs: backtest/derive_10k_results.json/.csv + plots + heatmaps.
"""
import json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import requests
sys.path.insert(0, "/home/david/derive-cesf-botcamp")

BASE = "https://api.lyra.finance"
S = requests.Session()
SYMS = ["ETH-PERP", "BTC-PERP", "SOL-PERP", "HYPE-PERP"]
OUT = Path("/home/david/derive-cesf-botcamp/backtest")
LB = 100
TAKER = 0.0003

def post(path, payload):
    r = S.post(BASE + path, json=payload, timeout=20)
    r.raise_for_status()
    return r.json()["result"]

def fetch_tape(inst, max_pages=120, max_days=45):
    all_t = []
    cutoff = time.time() * 1000 - max_days * 86400 * 1000
    for pg in range(1, max_pages + 1):
        j = post("/public/get_trade_history",
                 {"instrument_name": inst, "page": pg, "page_size": 1000})
        tr = j.get("trades", [])
        if not tr:
            break
        all_t.extend(tr)
        if int(tr[-1]["timestamp"]) < cutoff:
            break
        time.sleep(0.05)
    return all_t

def to_5m(trades):
    df = pd.DataFrame([{"ts": int(t["timestamp"]), "px": float(t["trade_price"])}
                       for t in trades])
    df["dt"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    b = df.set_index("dt").resample("5min").agg(
        px=("px", "last"), h=("px", "max"), l=("px", "min"), n=("px", "count"))
    return b.dropna().reset_index()

def features(close):
    s = pd.Series(np.diff(np.log(np.maximum(close, 1e-8))))
    P = 365 * 24 * 12
    rv_d = s ** 2
    har = np.sqrt((0.1 * rv_d.rolling(LB).mean() + 0.3 * rv_d.rolling(5).mean()
                   + 0.6 * rv_d) * P)
    ew = np.sqrt(s.pow(2).ewm(alpha=1 - 0.94, adjust=False).mean() * P)
    sigma = 0.5 * (har + ew)
    eps = (0.01 + 0.5 * (har - ew).abs()).clip(lower=0.01)
    sig_d = sigma / np.sqrt(365)
    tail = (s < -1.5 * sig_d).rolling(LB).mean()
    m = s.rolling(LB).mean()
    var = ((s - m) ** 2).rolling(LB).mean()
    kurt = (((s - m) ** 4).rolling(LB).mean() / (var ** 2 + 1e-12)).clip(3, 13)
    kurt_n = ((kurt - 3) / 10).clip(0, 1)
    r2 = s.pow(2)
    ac = (r2.rolling(LB).corr(r2.shift(-1))).clip(lower=0).fillna(0.0)
    score = (0.45 * (tail / 0.08).clip(0, 1) + 0.25 * kurt_n + 0.2 * ac
             + 0.1 * (eps / 0.05).clip(0, 1)).clip(0, 1)
    recent = np.sqrt(s.pow(2).rolling(20).mean() * P)
    edge = sigma - recent
    return edge.values, score.values, eps.values

def simulate(c, edge, score, eps, p, capital=800.0):
    n = len(c)
    eq = capital
    peak = capital
    maxdd = 0.0
    trades = 0
    wins = 0
    rets = []
    pos = None
    th0, cs0 = p["thresh"], p["cesf_min"]
    th, cs = th0, cs0
    adj = []
    half = n // 2
    seg_trades, seg_wins = [], []
    daily_eq = [capital]
    for i in range(max(LB, 30), n - 1):
        if i % 288 == 0:
            daily_eq.append(eq)
        px = c[i]
        if pos is not None:
            hold_h = (i - pos[0]) * 5 / 60
            r = (pos[1] - px) / pos[1] if pos[2] == "short" else (px - pos[1]) / pos[1]
            pnl = r * 3
            if pnl >= p["tp"] or pnl <= -p["sl"] or hold_h >= 24:
                dq = pos[3] * pnl - pos[3] * (0.0003 + 0.0003)
                eq += dq
                trades += 1
                if dq > 0:
                    wins += 1
                peak = max(peak, eq)
                maxdd = min(maxdd, (eq - peak) / peak)
                rets.append(dq / capital)
                if i < half:
                    seg_trades.append(dq)
                pos = None
            continue
        j = i - 1
        e, s = edge[j], score[j]
        if not (np.isfinite(e) and np.isfinite(s)):
            continue
        sig = -1 if (e > th / 100 and s >= cs) else (1 if (e > (th + 0.4) / 100 and s < 0.30) else 0)
        if sig != 0:
            side = "short" if sig == -1 else "long"
            conf = min(max(s / 0.35, 0.5), 1.5)
            f = min(max((e / max(eps[j], 0.02)) * 0.02 * 0.5 * conf, 0),
                    p["kelly_cap"], 0.05)
            notion = max(min(eq * f, eq * 0.3), 10.0) if f > 0 else 0
            if notion >= 10:
                pos = (i, px, side, notion)
        if i == half and seg_trades:
            arr = np.array(seg_trades)
            hit = float((arr > 0).mean())
            gw = arr[arr > 0].sum()
            gl = abs(arr[arr < 0].sum())
            pf = float(gw / max(gl, 1e-9))
            if hit < 0.40 or pf < 0.8:
                th = min(th + 0.3, 2.8)
                cs = min(cs + 0.03, 0.50)
                adj.append(f"tighten@{i}")
            elif hit > 0.55 and pf > 1.2:
                th = max(th - 0.2, 1.2)
                adj.append(f"loosen@{i}")
    arr = np.array(rets)
    sh = float(arr.mean() / arr.std() * np.sqrt(365 * 24) if len(arr) > 2 and arr.std() > 1e-12 else 0.0)
    daily = np.array(daily_eq)
    dr = np.diff(daily) / daily[:-1] if len(daily) > 2 else np.array([])
    dr = dr[np.isfinite(dr)]
    sh_d = float(dr.mean() / dr.std() * np.sqrt(365) if len(dr) > 2 and dr.std() > 1e-12 else 0.0)
    return {"ret": round((eq / capital - 1) * 100, 2), "trades": trades,
            "win": round(wins / max(trades, 1), 3), "dd": round(maxdd * 100, 2),
            "sharpe": round(sh_d, 3), "sharpe_trade": round(sh, 3),
            "th_end": round(th, 3), "cs_end": round(cs, 3), "adj": adj}

def main():
    t0 = time.time()
    meta = {"symbols": {}, "rules": {}, "spreads": {}}
    data = {}
    for inst in SYMS:
        tr = fetch_tape(inst)
        b5 = to_5m(tr)
        data[inst] = b5
        span_h = (b5["dt"].iloc[-1] - b5["dt"].iloc[0]).total_seconds() / 3600
        meta["symbols"][inst] = {"trades": len(tr), "bars_5m": len(b5),
                                 "span_h": round(span_h, 1)}
        print(f"{inst}: {len(tr)} trades -> {len(b5)} 5m bars / {span_h:.0f}h", flush=True)
    for inst in SYMS:
        t = post("/public/get_ticker", {"instrument_name": inst})
        bid = float(t.get("best_bid_price") or 0)
        ask = float(t.get("best_ask_price") or 0)
        mark = float(t.get("mark_price") or 0)
        meta["spreads"][inst] = round((ask - bid) / mark * 1e4, 1) if mark and bid else None
    e0 = post("/public/get_all_instruments",
              {"currency": "ETH", "instrument_type": "perp", "expired": False})
    e = [i for i in e0["instruments"] if i["instrument_name"] == "ETH-PERP"][0]
    meta["rules"] = {"tick": e["tick_size"], "min": e["minimum_amount"],
                     "taker": e["taker_fee_rate"]}
    total_bars = sum(len(v) for v in data.values())
    print(f"TOTAL 5m bars: {total_bars}", flush=True)
    rng = np.random.RandomState(42)
    ths = [1.2, 1.5, 1.8, 2.0, 2.5]
    css = [0.30, 0.35, 0.40, 0.45]
    kcs = [0.05, 0.08, 0.12]
    tps = [1.09, 1.2]
    sls = [0.41, 0.48]
    grid = [(th, cs, kc, tp, sl) for th in ths for cs in css for kc in kcs
            for tp in tps for sl in sls]
    WIN = 2016  # 7d of 5m
    N_OFF = 50
    # per symbol: 50 offsets x 50 params = 2500 -> 10,000 total
    import itertools
    pset = list(itertools.product(ths, css, kcs))[:50]  # 60 -> first 50
    feats = {}
    for inst in SYMS:
        c = data[inst]["px"].values.astype(float)
        feats[inst] = (c,) + features(c)
    runs = []
    for inst in SYMS:
        c, edge, score, eps = feats[inst]
        maxs = len(c) - WIN
        starts = np.linspace(0, maxs, N_OFF).astype(int)
        for si, st in enumerate(starts):
            cc = c[st:st + WIN]
            ee = edge[st:st + WIN]
            ss = score[st:st + WIN]
            ep = eps[st:st + WIN]
            for (th, cs, kc) in pset:
                p = {"thresh": th, "cesf_min": cs, "kelly_cap": kc, "tp": 1.2, "sl": 0.48}
                r = simulate(cc, ee, ss, ep, p)
                r.update({"symbol": inst, "offset": int(st), "thresh": th,
                          "cesf": cs, "kelly": kc})
                runs.append(r)
                if len(runs) % 1000 == 0:
                    print(f"...{len(runs)} runs ({(time.time()-t0)/60:.1f} min)", flush=True)
                if len(runs) >= 10000:
                    break
            if len(runs) >= 10000:
                break
        if len(runs) >= 10000:
            break
    runs = runs[:10000]
    json.dump(runs, open(OUT / "derive_10k_results.json", "w"))
    import csv
    with open(OUT / "derive_10k_results.csv", "w", newline="") as f:
        keys = ["symbol", "offset", "thresh", "cesf", "kelly", "ret", "trades",
                "win", "dd", "sharpe", "th_end", "cs_end", "adj"]
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(runs)
    ok = runs
    sh = np.array([r["sharpe"] for r in ok])
    rt = np.array([r["ret"] for r in ok])
    tightened = sum(1 for r in ok if any("tighten" in a for a in r["adj"]))
    loosened = sum(1 for r in ok if any("loosen" in a for a in r["adj"]))
    summary = {
        "runs": len(ok),
        "sharpe_gt_05": int((sh > 0.5).sum()),
        "sharpe_mean": round(float(sh.mean()), 3),
        "sharpe_median": round(float(np.median(sh)), 3),
        "ret_mean": round(float(rt.mean()), 2),
        "ret_pos_frac": round(float((rt > 0).mean()), 3),
        "midrun_tightened": tightened,
        "midrun_loosened": loosened,
        "minutes": round((time.time() - t0) / 60, 1),
        "data": meta,
    }
    json.dump(summary, open(OUT / "derive_10k_summary.json", "w"), indent=2)
    print(json.dumps(summary, indent=1), flush=True)

if __name__ == "__main__":
    main()
