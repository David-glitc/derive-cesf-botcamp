#!/usr/bin/env python3
"""Full sweep — SVI + OTM/ATM + Kelly + portfolio guard, for max upside tuning.
Reuses run_backtest.py but with regime-aware sizing.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.kelly.sizing import KellyConfig, position_notional
from src.risk.portfolio_guard import PortfolioGuard, GuardConfig
from backtest.run_backtest import fetch_klines, har_rv_forecast, ewma_vol, ensemble_sigma, cesf_score
import numpy as np, pandas as pd

def sweep():
    pairs=[("ETHUSDT","1h",60), ("BTCUSDT","1h",60), ("ETHUSDT","3m",60), ("BTCUSDT","3m",60)]
    ths=[1.8,2.0,2.5]
    cesfs=[0.35,0.40]
    kelly_caps=[0.05,0.08,0.12]
    import itertools
    best=[]
    for pair,intv,days in pairs:
        print(f"\n[FETCH] {pair} {intv} {days}d")
        df=__import__("backtest.run_backtest", fromlist=["fetch_klines"]).fetch_klines(pair,intv,days)
        closes=df["close"].values.astype(float)
        rets=np.diff(np.log(np.maximum(closes,1e-8)))
        mins={"1m":1,"3m":3,"5m":5,"1h":60}[intv]
        ppy=365*24*60/mins
        for thresh,cesf_min,cap in itertools.product(ths,cesfs,kelly_caps):
            # quick simulation
            equity=800; peak=800; trades=0; wins=0; max_dd=0
            gross=0
            in_pos=None
            for i in range(100, len(closes)-1):
                if in_pos:
                    hold=(i-in_pos[0])*mins/60
                    px=closes[i]
                    side=in_pos[1]; entry=in_pos[2]; notional=in_pos[3]
                    ret=(entry-px)/entry if side=="short" else (px-entry)/entry
                    pnl=ret*3
                    hit = pnl>=1.2 or pnl<=-0.48 or hold>=24
                    if hit:
                        pnl_quote=notional*pnl - notional*0.0086
                        equity+=pnl_quote; trades+=1
                        if pnl_quote>0: wins+=1
                        peak=max(peak,equity)
                        max_dd=min(max_dd,(equity-peak)/peak)
                        in_pos=None
                    continue
                window=rets[i-100:i]
                sigma,eps,_,_=ensemble_sigma(window,ppy)
                score=cesf_score(window,sigma,eps)
                recent=np.sqrt(np.mean(window[-20:]**2)*ppy)
                edge=sigma-recent
                sig=None
                if edge>thresh/100 and score>=cesf_min: sig="short"
                elif edge>(thresh+0.4)/100 and score<0.30: sig="long"
                if sig:
                    cfg=KellyConfig(max_fraction=0.05, kelly_cap=cap)
                    notional=position_notional(equity,edge,eps,sigma,cfg, confidence=score/0.35)
                    if notional>10 and gross+notional<240:
                        in_pos=(i,sig,closes[i],notional)
                        gross+=notional
                    # close reduces gross on exit (simplified)
            ret_pct=(equity/800-1)*100
            best.append((ret_pct,trades, wins/max(trades,1), max_dd, pair,intv,days,thresh,cesf_min,cap))
            print(f"  thresh {thresh} cesf {cesf_min} kelly {cap}: {ret_pct:+.2f}% tr {trades} win {wins/max(trades,1):.0%} dd {max_dd:.1%}")
    best.sort(reverse=True)
    print("\nTOP 5:")
    for r in best[:5]:
        print(f"  {r[4]} {r[5]} {r[6]}d thresh {r[7]} cesf {r[8]} kelly {r[9]} → {r[0]:+.2f}% tr {r[1]} win {r[2]:.0%} dd {r[3]:.1%}")

if __name__=="__main__": sweep()
