#!/usr/bin/env python3
"""
Standalone backtest for Derive CESF Long Vol — no Hummingbot/Brickfort deps needed.

Feeds: Binance klines (public) — works for binance_perpetual, binance, or derive candle proxy.
Logic: HAR-RV + EWMA ensemble → forecast_sigma + epsilon
       CESF crash-mass proxy → score [0,1]
       Signal -1 (short perp = synthetic long put) when forecast - IV_proxy > thresh AND score >= 0.35
Scenarios: TP 1.2 SL 0.48 time_limit 86400 with 5% risk, half-Kelly cap 8%.

Usage:
  python backtest/run_backtest.py --pair ETHUSDT --interval 3m --days 60
  python backtest/run_backtest.py --pair BTCUSDT --interval 1h --days 180 --plot
"""

import argparse
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_KLINES_FUT = "https://fapi.binance.com/fapi/v1/klines"  # perpetual

# Also try data-api fallback (geo 451 fix)
FALLBACK_URLS = [
    "https://api.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
]

def fetch_klines(symbol: str, interval: str, days: int) -> pd.DataFrame:
    # interval mapping: hummingbot 3m -> binance 3m
    limit = 1000
    # Binance max 1000 per request; paginate
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 24 * 60 * 60 * 1000
    all_rows = []
    url = None
    for cand in FALLBACK_URLS:
        try:
            r = requests.get(cand, params={"symbol": symbol, "interval": interval, "limit": 1}, timeout=10)
            if r.status_code == 200:
                url = cand
                break
        except Exception:
            continue
    if url is None:
        url = BINANCE_KLINES
        print(f"[warn] all fallbacks failed, using {url}")

    cur = start_ms
    while cur < end_ms:
        params = {"symbol": symbol, "interval": interval, "startTime": cur, "limit": limit}
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            # try fallback
            for fb in FALLBACK_URLS:
                if fb == url:
                    continue
                r2 = requests.get(fb, params=params, timeout=15)
                if r2.status_code == 200:
                    r = r2
                    url = fb
                    break
            if r.status_code != 200:
                raise RuntimeError(f"Binance klines {r.status_code}: {r.text[:500]}")
        rows = r.json()
        if not rows:
            break
        all_rows.extend(rows)
        last_open = rows[-1][0]
        # next start is last close + 1ms
        cur = rows[-1][6] + 1
        if len(rows) < limit:
            break
        # avoid hammering
        time.sleep(0.15)
        if len(all_rows) > 50000:
            break
    if not all_rows:
        raise RuntimeError("no klines returned")
    df = pd.DataFrame(all_rows, columns=["open_time","open","high","low","close","volume","close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
    df["close"] = df["close"].astype(float)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.sort_values("open_time").reset_index(drop=True)
    # trim to requested window
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    df = df[df["open_time"] >= cutoff].reset_index(drop=True)
    return df

# ----- forecasting (same as controller) -----

def har_rv_forecast(returns: np.ndarray, ppy: float) -> float:
    r = np.asarray(returns, dtype=np.float64)
    if r.size < 5:
        return float(np.sqrt(np.mean(r**2) * ppy)) if r.size else 0.20
    rv_d = float(r[-1] ** 2)
    rv_w = float(np.mean(r[-5:] ** 2))
    rv_m = float(np.mean(r**2))
    forecast_var = 0.1 * rv_m + 0.3 * rv_w + 0.6 * rv_d
    return max(float(np.sqrt(forecast_var * ppy)), 1e-8)

def ewma_vol(returns: np.ndarray, lam: float = 0.94, ppy: float = 365*24*20) -> float:
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.20
    var = float(r[0]**2)
    for x in r[1:]:
        var = lam*var + (1-lam)*float(x**2)
    return max(float(np.sqrt(var*ppy)), 1e-8)

def ensemble_sigma(returns: np.ndarray, ppy: float):
    har = har_rv_forecast(returns, ppy)
    ewma = ewma_vol(returns, ppy=ppy)
    sigma = 0.5*har + 0.5*ewma
    epsilon = max(0.01 + 0.5*abs(har-ewma), 0.01)
    return sigma, epsilon, har, ewma

def cesf_score(returns: np.ndarray, sigma: float, epsilon: float) -> float:
    r = np.asarray(returns, dtype=np.float64)
    if r.size < 20:
        return 0.0
    sigma_daily = sigma / math.sqrt(365)
    tail = float(np.mean(r < -1.5*sigma_daily)) if sigma_daily>0 else 0.0
    m = float(np.mean(r))
    var = float(np.mean((r-m)**2))
    kurt = float(np.mean((r-m)**4)/(var**2+1e-12)) if var>1e-12 else 3.0
    kurt_norm = min(max((kurt-3)/10,0),1)
    if r.size>10:
        r2=r**2
        try:
            ac=float(np.corrcoef(r2[:-1], r2[1:])[0,1])
            ac=max(ac,0) if np.isfinite(ac) else 0.0
        except: ac=0.0
    else: ac=0.0
    eps_boost=min(epsilon/0.05,1)
    s=0.45*min(tail/0.08,1)+0.25*kurt_norm+0.2*ac+0.1*eps_boost
    return float(np.clip(s,0,1))

def backtest(df: pd.DataFrame, interval: str, vol_lookback=100, thresh=1.8, cesf_min=0.35, tp=1.2, sl=0.48, time_limit_h=24, capital=800, risk_pct=0.05, kelly_cap=0.08, fee=0.0006, half_spread=0.008):
    closes = df["close"].values.astype(float)
    times = df["open_time"].values
    rets = np.diff(np.log(np.maximum(closes,1e-8)))
    # periods per year for ppy: convert interval to ppy
    interval_to_minutes = {"1m":1,"3m":3,"5m":5,"15m":15,"1h":60,"4h":240,"1d":1440}
    mins = interval_to_minutes.get(interval, 3)
    ppy = 365*24*60/mins

    equity = capital
    equity_curve = []
    trades = []
    in_pos = None  # dict with entry_px, side, entry_idx, amount_quote, qty
    # ATR proxy
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)
    tr = np.maximum(highs[1:]-lows[1:], np.maximum(np.abs(highs[1:]-closes[:-1]), np.abs(lows[1:]-closes[:-1])))
    atr = pd.Series(tr).rolling(14).mean().values

    for i in range(max(vol_lookback, 30), len(closes)-1):
        px = closes[i]
        # handle open position
        if in_pos is not None:
            hold_h = (i - in_pos["entry_idx"]) * mins / 60
            # price move
            if in_pos["side"] == "short":  # synthetic long put
                ret = (in_pos["entry_px"] - px) / in_pos["entry_px"]
            else:
                ret = (px - in_pos["entry_px"]) / in_pos["entry_px"]
            # levered
            lev = 3
            pnl_pct = ret * lev
            # fees + spread
            cost = fee + half_spread
            # TP/SL/time
            hit = None
            if pnl_pct >= tp:
                hit = "TP"
            elif pnl_pct <= -sl:
                hit = "SL"
            elif hold_h >= time_limit_h:
                hit = "TIME"
            # also daily halt check (simplified): if equity drawdown >3% intraday, force close at TIME
            if hit is not None or hold_h >= time_limit_h:
                # close
                gross = in_pos["amount_quote"] * (1 + pnl_pct)
                net = gross * (1 - cost)
                # pnl on equity: amount_quote is risk-scaled notional
                # we track equity as capital + cumulative pnl (risk-scaled)
                pnl_quote = (net - in_pos["amount_quote"])
                equity += pnl_quote
                trades.append({
                    "entry_idx": in_pos["entry_idx"], "exit_idx": i,
                    "entry_px": in_pos["entry_px"], "exit_px": px,
                    "side": in_pos["side"], "hit": hit or "TIME",
                    "hold_h": hold_h, "pnl_pct": pnl_pct, "pnl_quote": pnl_quote,
                    "equity": equity,
                })
                equity_curve.append(equity)
                in_pos = None
            else:
                equity_curve.append(equity)
            continue

        # no position -> check signal
        window = rets[i-vol_lookback:i]
        sigma, epsilon, har, ewma = ensemble_sigma(window, ppy)
        score = cesf_score(window, sigma, epsilon)
        recent_rv = float(np.sqrt(np.mean(window[-20:]**2)*ppy)) if len(window)>=20 else sigma
        iv_proxy = recent_rv
        edge = sigma - iv_proxy
        atr_ok = atr[i-1] > np.mean(closes[i-20:i])*0.002 if i>=20 and np.isfinite(atr[i-1]) else True

        long_put = (edge > thresh/100) and (score >= cesf_min) and atr_ok
        long_call = (edge > (thresh+0.4)/100) and (score < 0.30) and atr_ok

        side = None
        if long_put:
            side = "short"
        elif long_call:
            side = "long"

        if side is not None:
            # sizing: 5% risk, half-Kelly capped 8% of equity
            risk_amt = equity * risk_pct
            kelly_amt = equity * kelly_cap
            # scale by edge/epsilon (confidence)
            conf = min(max(edge / max(epsilon,0.02), 0.5), 1.5)
            notional = min(risk_amt * conf * 2, kelly_amt)  # *2 because risk 5% -> notional ~ 5%*2
            # floor at venue min lot: 0.1 contract ~ $0.64 for 1d ETH -> $10 min notional
            notional = max(notional, 10.0)
            notional = min(notional, equity * 0.3)  # cap
            in_pos = {"side": side, "entry_px": px, "entry_idx": i, "amount_quote": notional}
        equity_curve.append(equity)

    # close any remaining at end
    if in_pos is not None:
        px = closes[-1]
        if in_pos["side"]=="short":
            ret=(in_pos["entry_px"]-px)/in_pos["entry_px"]
        else:
            ret=(px-in_pos["entry_px"])/in_pos["entry_px"]
        pnl_pct=ret*3
        cost=fee+half_spread
        gross=in_pos["amount_quote"]*(1+pnl_pct)
        net=gross*(1-cost)
        pnl_quote=net-in_pos["amount_quote"]
        equity+=pnl_quote
        trades.append({"entry_idx":in_pos["entry_idx"],"exit_idx":len(closes)-1,"entry_px":in_pos["entry_px"],"exit_px":px,"side":in_pos["side"],"hit":"END","hold_h":(len(closes)-1-in_pos["entry_idx"])*mins/60,"pnl_pct":pnl_pct,"pnl_quote":pnl_quote,"equity":equity})

    # stats
    if trades:
        pnls = [t["pnl_quote"] for t in trades]
        wins = sum(1 for p in pnls if p>0)
        total = sum(pnls)
        win_rate = wins/len(trades)
        max_dd = 0.0
        peak = capital
        for eq in equity_curve:
            peak = max(peak, eq)
            dd = (eq - peak)/peak
            max_dd = min(max_dd, dd)
    else:
        total=0; win_rate=0; max_dd=0; pnls=[]

    return {
        "pair": df.attrs.get("symbol",""),
        "interval": interval,
        "candles": len(df),
        "days": (df["open_time"].iloc[-1]-df["open_time"].iloc[0]).days if len(df)>1 else 0,
        "starting": capital, "ending": equity,
        "return_pct": (equity/capital-1)*100,
        "trades": len(trades),
        "wins": wins if trades else 0,
        "win_rate": win_rate if trades else 0,
        "max_dd_pct": max_dd*100 if trades else 0,
        "equity_curve": equity_curve,
        "trades_detail": trades,
        "df": df,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", default="ETHUSDT", help="Binance symbol")
    ap.add_argument("--interval", default="3m")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--vol_lookback", type=int, default=100)
    ap.add_argument("--thresh", type=float, default=1.8)
    ap.add_argument("--cesf_min", type=float, default=0.35)
    ap.add_argument("--tp", type=float, default=1.2)
    ap.add_argument("--sl", type=float, default=0.48)
    ap.add_argument("--time_limit_h", type=float, default=24)
    ap.add_argument("--capital", type=float, default=800)
    ap.add_argument("--plot", action="store_true")
    args = ap.parse_args()

    print(f"[fetch] {args.pair} {args.interval} last {args.days}d ...")
    df = fetch_klines(args.pair, args.interval, args.days)
    df.attrs["symbol"] = args.pair
    print(f"[fetch] got {len(df)} candles from {df['open_time'].iloc[0]} to {df['open_time'].iloc[-1]}")

    res = backtest(df, args.interval, vol_lookback=args.vol_lookback, thresh=args.thresh, cesf_min=args.cesf_min, tp=args.tp, sl=args.sl, time_limit_h=args.time_limit_h, capital=args.capital)
    print("\n" + "="*60)
    print(f"Pair {args.pair} {args.interval}  {res['candles']} candles  ~{res['days']}d")
    print(f"Capital {res['starting']:.2f} -> {res['ending']:.2f}  Return {res['return_pct']:+.2f}%")
    print(f"Trades {res['trades']}  Wins {res['wins']}  Win rate {res['win_rate']:.1%}  MaxDD {res['max_dd_pct']:.2f}%")
    if res["trades_detail"]:
        print("\nLast 5 trades:")
        for t in res["trades_detail"][-5:]:
            print(f"  {t['side']:5} {t['hit']:4} hold {t['hold_h']:.1f}h  pnl {t['pnl_quote']:+.2f}  eq {t['equity']:.2f}")
    # save
    out = Path("backtest") / f"result_{args.pair}_{args.interval}_{args.days}d.json"
    import json
    out.write_text(json.dumps({k:v for k,v in res.items() if k not in ("equity_curve","df","trades_detail")}, indent=2))
    print(f"\n[saved] {out}")
    if args.plot:
        try:
            import matplotlib.pyplot as plt
            plt.figure(figsize=(10,4))
            plt.plot(res["equity_curve"])
            plt.title(f"{args.pair} {args.interval} equity {res['return_pct']:+.2f}% {res['trades']}tr")
            plt.tight_layout()
            png = Path("backtest") / f"equity_{args.pair}_{args.interval}.png"
            plt.savefig(png, dpi=150)
            print(f"[plot] {png}")
        except Exception as e:
            print(f"[plot fail] {e}")

if __name__ == "__main__":
    main()
