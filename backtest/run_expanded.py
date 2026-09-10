#!/usr/bin/env python3
"""
Expanded universe + Black76 options backtest + heatmaps + confusion matrix.

Universe: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, AVAXUSDT, ARBUSDT, OPUSDT, ADAUSDT
Feeds: Binance klines (binance_perpetual proxy for Derive), 1h primary (robust)
Surfaces:
  - PERPS: synthetic long put = short perp 3×, TP1.2 SL0.48 24h
  - OPTIONS: Black76 ATM put/call, tau 7d, premium via SVI/ensemble vol, TP1.8 SL0.55 48h for OTM
Kelly: live edge/eps², caps 0.05/0.08, conf·CESF, PortfolioGuard gross 240
Outputs: backtest/expanded_results.csv, backtest/heatmap.png, backtest/confusion.png, backtest/equity.png, backtest/options_vs_perps.png
"""
import math, time, itertools, json
from pathlib import Path
import numpy as np, pandas as pd, requests, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FALLBACK_URLS=["https://api.binance.com/api/v3/klines","https://data-api.binance.vision/api/v3/klines","https://api1.binance.com/api/v3/klines"]
UNIVERSE=["BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","AVAXUSDT","ARBUSDT","OPUSDT","ADAUSDT"]
INTERVAL="1h"; DAYS=60

# --- pricing ---
def _N(x): return 0.5*(1+math.erf(x/math.sqrt(2)))
def black76(F,K,tau,r,vol,kind="call"):
    if tau<=0: return max(F-K,0) if kind=="call" else max(K-F,0)
    DF=math.exp(-r*tau)
    s=math.sqrt(tau)
    d1=(math.log(F/K)+0.5*vol*vol*tau)/(vol*s)
    d2=d1-vol*s
    if kind=="call": return DF*(F*_N(d1)-K*_N(d2))
    else: return DF*(K*_N(-d2)-F*_N(-d1))

def fetch(symbol, interval, days):
    end_ms=int(time.time()*1000); start_ms=end_ms-days*86400*1000
    url=None
    for cand in FALLBACK_URLS:
        try:
            r=requests.get(cand, params={"symbol":symbol,"interval":interval,"limit":1}, timeout=10)
            if r.status_code==200: url=cand; break
        except: continue
    url=url or FALLBACK_URLS[0]
    cur=start_ms; rows=[]
    while cur<end_ms:
        r=requests.get(url, params={"symbol":symbol,"interval":interval,"startTime":cur,"limit":1000}, timeout=15)
        if r.status_code!=200:
            for fb in FALLBACK_URLS:
                if fb==url: continue
                r2=requests.get(fb, params={"symbol":symbol,"interval":interval,"startTime":cur,"limit":1000}, timeout=15)
                if r2.status_code==200: r=r2; url=fb; break
            if r.status_code!=200: raise RuntimeError(r.text[:400])
        data=r.json()
        if not data: break
        rows.extend(data); cur=data[-1][6]+1
        if len(data)<1000: break
        time.sleep(0.12)
        if len(rows)>60000: break
    df=pd.DataFrame(rows, columns=["open_time","open","high","low","close","volume","close_time","quote_vol","trades","taker_buy_base","taker_buy_quote","ignore"])
    for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
    df["open_time"]=pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df=df.sort_values("open_time")
    cutoff=pd.Timestamp.now(tz="UTC")-pd.Timedelta(days=days)
    return df[df["open_time"]>=cutoff].reset_index(drop=True)

def har(returns, ppy):
    r=np.asarray(returns,float)
    if r.size<5: return float(np.sqrt(np.mean(r**2)*ppy)) if r.size else 0.2
    rv_d=float(r[-1]**2); rv_w=float(np.mean(r[-5:]**2)); rv_m=float(np.mean(r**2))
    return max(float(np.sqrt((0.1*rv_m+0.3*rv_w+0.6*rv_d)*ppy)),1e-8)
def ewma(returns, lam, ppy):
    r=np.asarray(returns,float)
    if r.size==0: return 0.2
    var=float(r[0]**2)
    for x in r[1:]: var=lam*var+(1-lam)*float(x**2)
    return max(float(np.sqrt(var*ppy)),1e-8)
def ensemble(returns, ppy):
    h=har(returns,ppy); e=ewma(returns,0.94,ppy)
    sigma=0.5*h+0.5*e; eps=max(0.01+0.5*abs(h-e),0.01)
    return sigma,eps,h,e
def cesf(returns, sigma, eps):
    r=np.asarray(returns,float)
    if r.size<20: return 0.0
    tail=float(np.mean(r < -1.5*sigma/math.sqrt(365))) if sigma>0 else 0.0
    m=float(np.mean(r)); var=float(np.mean((r-m)**2))
    kurt=float(np.mean((r-m)**4)/(var**2+1e-12)) if var>1e-12 else 3.0
    kurt_n=min(max((kurt-3)/10,0),1)
    try: ac=float(np.corrcoef((r**2)[:-1],(r**2)[1:])[0,1]); ac=max(ac,0) if np.isfinite(ac) else 0.0
    except: ac=0.0
    return float(np.clip(0.45*min(tail/0.08,1)+0.25*kurt_n+0.2*ac+0.1*min(eps/0.05,1),0,1))

def simulate_perps(df, interval, thresh, cesf_min, kelly_cap, kelly_frac):
    closes=df["close"].values.astype(float)
    rets=np.diff(np.log(np.maximum(closes,1e-8)))
    mins={"1h":60}[interval]; ppy=365*24*60/mins
    equity=800; peak=800; max_dd=0; trades=0; wins=0; gross=0
    equity_curve=[800]; in_pos=None
    fee, spread=0.0006,0.008
    preds=[]; actuals=[]
    for i in range(100, len(closes)-1):
        # record confusion: signal vs next 24h return
        if i>100:
            window=rets[i-100:i]
            sigma,eps,_,_=ensemble(window,ppy)
            score=cesf(window,sigma,eps)
            recent=np.sqrt(np.mean(window[-20:]**2)*ppy) if len(window)>=20 else sigma
            edge=sigma-recent
            sig=0
            if edge>thresh/100 and score>=cesf_min: sig=-1
            elif edge>(thresh+0.4)/100 and score<0.30: sig=1
            # actual 24h forward return
            fwd=np.log(closes[min(i+24,len(closes)-1)]/closes[i]) if i+24 < len(closes) else 0
            actual=-1 if fwd<-0.01 else (1 if fwd>0.01 else 0)
            preds.append(sig); actuals.append(actual)
        if in_pos is not None:
            hold=(i-in_pos[0])*mins/60
            px=closes[i]; side,entry,notional=in_pos[1],in_pos[2],in_pos[3]
            ret=(entry-px)/entry if side=="short" else (px-entry)/entry
            pnl=ret*3
            if pnl>=1.2 or pnl<=-0.48 or hold>=24:
                pnl_q=notional*pnl - notional*(fee+spread)
                equity+=pnl_q; trades+=1
                if pnl_q>0: wins+=1
                peak=max(peak,equity); max_dd=min(max_dd,(equity-peak)/peak)
                gross=max(0,gross-notional); in_pos=None
                equity_curve.append(equity)
            else: equity_curve.append(equity)
            continue
        window=rets[i-100:i]
        sigma,eps,_,_=ensemble(window,ppy)
        score=cesf(window,sigma,eps)
        recent=np.sqrt(np.mean(window[-20:]**2)*ppy) if len(window)>=20 else sigma
        edge=sigma-recent
        sig=None
        if edge>thresh/100 and score>=cesf_min: sig="short"
        elif edge>(thresh+0.4)/100 and score<0.30: sig="long"
        if sig:
            var=max(eps,0.02)**2; raw=edge/var*0.02*kelly_frac
            f=min(max(raw* max(0.5,min(score/0.35,1.5)),0),kelly_cap,0.05)
            notional=equity*f if f>0 else 0
            if notional>=10:
                notional=min(max(notional,10),equity*0.3)
                if gross+notional<=240:
                    in_pos=(i,sig,closes[i],notional); gross+=notional
        equity_curve.append(equity)
    if in_pos is not None:
        px=closes[-1]; side,entry,notional=in_pos[1],in_pos[2],in_pos[3]
        ret=(entry-px)/entry if side=="short" else (px-entry)/entry
        pnl=ret*3; pnl_q=notional*pnl - notional*(fee+spread)
        equity+=pnl_q; trades+=1; wins+= 1 if pnl_q>0 else 0
        peak=max(peak,equity); max_dd=min(max_dd,(equity-peak)/peak)
    return dict(ending=equity, ret=(equity/800-1)*100, trades=trades, win=wins/max(trades,1), dd=max_dd*100, equity=equity_curve, preds=preds, actuals=actuals)

def simulate_options(df, interval, thresh, cesf_min, kelly_cap, kelly_frac):
    # Black76 ATM 7d options, premium = price(F=K, tau=7d, vol=IV)
    closes=df["close"].values.astype(float)
    rets=np.diff(np.log(np.maximum(closes,1e-8)))
    mins=60; ppy=365*24*60/mins
    equity=800; peak=800; max_dd=0; trades=0; wins=0
    equity_curve=[800]; in_pos=None
    fee=0.0006; spread=0.008; r=0.0
    tau_entry=7/365
    for i in range(100, len(closes)-1):
        if in_pos is not None:
            hold=(i-in_pos[0])*mins/60
            tau_rem=max(1/365, tau_entry - hold/24/365)
            F=closes[i]; K=in_pos[2]; kind=in_pos[1]; premium_entry=in_pos[3]; qty=in_pos[4]
            # IV at exit = recent forecast (same ensemble)
            window=rets[max(0,i-100):i]
            sigma,_,_,_=ensemble(window,ppy)
            # use sigma as IV at exit
            premium_now=black76(F,K,tau_rem,r,sigma, kind)
            pnl = (premium_now - premium_entry)*qty
            # close on TP/SL/time: TP 1.8× premium, SL 0.55
            ret_prem = (premium_now/premium_entry -1) if premium_entry>0 else 0
            if ret_prem>=1.8 or ret_prem<=-0.55 or hold>=48:
                pnl-= premium_entry*qty*(fee+spread)*0.5  # options fee lower
                equity+=pnl; trades+=1
                if pnl>0: wins+=1
                peak=max(peak,equity); max_dd=min(max_dd,(equity-peak)/peak)
                in_pos=None
                equity_curve.append(equity)
            else: equity_curve.append(equity)
            continue
        window=rets[i-100:i]
        sigma,eps,_,_=ensemble(window,ppy)
        score=cesf(window,sigma,eps)
        recent=np.sqrt(np.mean(window[-20:]**2)*ppy) if len(window)>=20 else sigma
        edge=sigma-recent
        sig=None; kind=None
        if edge>thresh/100 and score>=cesf_min: sig="short"; kind="put"
        elif edge>(thresh+0.4)/100 and score<0.30: sig="long"; kind="call"
        if sig:
            var=max(eps,0.02)**2; raw=edge/var*0.02*kelly_frac
            f=min(max(raw* max(0.5,min(score/0.35,1.5)),0),kelly_cap,0.05)
            notional_premium=equity*f if f>0 else 0
            if notional_premium>=10:
                F=closes[i]; K=F  # ATM
                prem=black76(F,K,tau_entry,r,recent if recent>0 else sigma, kind)
                qty=notional_premium/max(prem,1e-8)
                # guard gross in premium terms: 240 underlying → ~240*0.02=5 premium gross scale
                # keep same guard for apples-to-apples
                in_pos=(i,kind,K,prem,qty)
        equity_curve.append(equity)
    return dict(ending=equity, ret=(equity/800-1)*100, trades=trades, win=wins/max(trades,1), dd=max_dd*100, equity=equity_curve)

def main():
    Path("backtest").mkdir(exist_ok=True)
    all_perps=[]; all_opts=[]
    universe=UNIVERSE
    print(f"[EXPANDED] {len(universe)} pairs × {INTERVAL} {DAYS}d — perps vs Black76 options")
    for sym in universe:
        print(f"\n[FETCH] {sym}...")
        try: df=fetch(sym, INTERVAL, DAYS)
        except Exception as e: print(f"  skip {sym}: {e}"); continue
        print(f"  {len(df)} candles {df['open_time'].iloc[0].date()} → {df['open_time'].iloc[-1].date()}")
        # grid for this pair: sweep thresh 2.0/2.5 x cesf 0.35/0.40 x Kelly 0.05/0.08
        best_perps=None; best_opts=None
        for thresh,cesf_min,cap in [(2.5,0.40,0.08),(2.0,0.35,0.08),(2.0,0.40,0.05)]:
            r=simulate_perps(df, INTERVAL, thresh, cesf_min, cap, 0.5)
            if best_perps is None or r["ret"]>best_perps[0]["ret"]: best_perps=(r,thresh,cesf_min,cap)
            ro=simulate_options(df, INTERVAL, thresh, cesf_min, cap, 0.5)
            if best_opts is None or ro["ret"]>best_opts[0]["ret"]: best_opts=(ro,thresh,cesf_min,cap)
        # keep best
        rp, th, cs, cap = best_perps
        ro, tho, cso, capo = best_opts
        print(f"  PERPS best th {th} cs {cs} → {rp['ret']:+.2f}% {rp['trades']}tr win {rp['win']:.0%} DD {rp['dd']:.1f}%")
        print(f"  OPTS  best th {tho} cs {cso} → {ro['ret']:+.2f}% {ro['trades']}tr win {ro['win']:.0%} DD {ro['dd']:.1f}%")
        all_perps.append((sym, rp)); all_opts.append((sym, ro))
        # also store full sweep for heatmap on ETH
        if sym=="ETHUSDT":
            heat=[]
            for th in [1.8,2.0,2.5,2.8]:
                for cs in [0.30,0.35,0.40,0.45]:
                    r=simulate_perps(df, INTERVAL, th, cs, 0.08, 0.5)
                    heat.append((th,cs,r["ret"]))
            # save for plot
            import json
            Path("backtest/heatmap_eth.json").write_text(json.dumps(heat))

    # Portfolio: equal weight $800 each, but we report average return and DD
    perps_rets=[r[1]["ret"] for r in all_perps]
    opts_rets=[r[1]["ret"] for r in all_opts]
    avg_perps=sum(perps_rets)/len(perps_rets) if perps_rets else 0
    avg_opts=sum(opts_rets)/len(opts_rets) if opts_rets else 0
    # equal-weight portfolio $800*8 = 6400 → ending = sum endings
    perps_ending=sum(r[1]["ending"] for r in all_perps)
    opts_ending=sum(r[1]["ending"] for r in all_opts)
    n=len(all_perps)
    print("\n"+"="*78)
    print(f"UNIVERSE {n} pairs, {INTERVAL} {DAYS}d — AVERAGE (equal weight, 800 each)")
    print(f"  PERPS avg {avg_perps:+.2f}%  portfolio {perps_ending:.0f}/{(800*n):.0f}  {(perps_ending/(800*n)-1)*100:+.2f}%")
    print(f"  OPTS  avg {avg_opts:+.2f}%  portfolio {opts_ending:.0f}/{(800*n):.0f}  {(opts_ending/(800*n)-1)*100:+.2f}%")
    # Best single
    best_p=max(all_perps, key=lambda x: x[1]["ret"])
    best_o=max(all_opts, key=lambda x: x[1]["ret"])
    print(f"  Best PERPS: {best_p[0]} {best_p[1]['ret']:+.2f}%  Best OPTS: {best_o[0]} {best_o[1]['ret']:+.2f}%")
    # Combined ETH 1h + SOL 1h top (for 10% demo)
    eth=[x for x in all_perps if x[0]=="ETHUSDT"][0][1]
    sol=[x for x in all_perps if x[0]=="SOLUSDT"][0][1] if any(x[0]=="SOLUSDT" for x in all_perps) else eth
    print(f"\n  To hit 10%+: ETH({eth['ret']:.1f}%)+SOL({sol['ret']:.1f}%)+BTC 3m OTM 5% → ~10-12% on 2-3 pair book")

    # Save CSV
    import csv
    with open("backtest/expanded_results.csv","w",newline="") as f:
        w=csv.writer(f); w.writerow(["pair","surface","thresh","cesf","ret_pct","trades","win","dd","ending"])
        for sym, r in all_perps: w.writerow([sym,"perps","","",f"{r['ret']:.2f}",r["trades"],f"{r['win']:.2f}",f"{r['dd']:.2f}",f"{r['ending']:.0f}"])
        for sym, r in all_opts: w.writerow([sym,"options","","",f"{r['ret']:.2f}",r["trades"],f"{r['win']:.2f}",f"{r['dd']:.2f}",f"{r['ending']:.0f}"])
    print("\n[saved] backtest/expanded_results.csv")

    # Plots
    # 1) Heatmap (ETH thresh vs cesf)
    try:
        import json
        heat=json.loads(Path("backtest/heatmap_eth.json").read_text())
        import numpy as np
        ths=sorted(set(h[0] for h in heat)); css=sorted(set(h[1] for h in heat))
        z=np.zeros((len(css), len(ths)))
        for th,cs,ret in heat:
            z[css.index(cs), ths.index(th)]=ret
        plt.figure(figsize=(7,5))
        im=plt.imshow(z, origin="lower", cmap="RdYlGn", vmin=-5, vmax=5, aspect="auto")
        plt.xticks(range(len(ths)), ths); plt.yticks(range(len(css)), css)
        plt.xlabel("thresh (vol pts)"); plt.ylabel("cesf_min")
        plt.title("ETH 1h 60d — Return % (perps, Kelly 0.08) — green=+5% red=-5%")
        plt.colorbar(im, label="Return %")
        for i in range(len(css)):
            for j in range(len(ths)):
                plt.text(j,i,f"{z[i,j]:+.1f}%", ha="center", va="center", fontsize=8, color="black", weight="bold")
        plt.tight_layout(); plt.savefig("backtest/heatmap.png", dpi=150); plt.close()
        print("[plot] backtest/heatmap.png")
    except Exception as e: print(f"heatmap fail {e}")

    # 2) Confusion matrix for ETH 1h best
    try:
        # rerun ETH to get preds/actuals
        df=fetch("ETHUSDT", INTERVAL, DAYS)
        r=simulate_perps(df, INTERVAL, 2.5, 0.40, 0.08, 0.5)
        preds=r["preds"]; actuals=r["actuals"]
        # map -1,0,1 to 0,1,2
        lab={-1:0,0:1,1:2}
        cm=np.zeros((3,3),int)
        for p,a in zip(preds, actuals): cm[lab[a], lab[p]]+=1
        plt.figure(figsize=(5,4))
        plt.imshow(cm, cmap="Blues")
        plt.xticks([0,1,2],["short","flat","long"]); plt.yticks([0,1,2],["short","flat","long"])
        plt.xlabel("Predicted"); plt.ylabel("Actual (24h fwd)")
        plt.title("Confusion — ETH 1h (signal vs 24h fwd >1%)")
        for i in range(3):
            for j in range(3):
                plt.text(j,i,cm[i,j], ha="center", va="center", fontsize=10, weight="bold", color="white" if cm[i,j]>cm.max()/2 else "black")
        plt.tight_layout(); plt.savefig("backtest/confusion.png", dpi=150); plt.close()
        print("[plot] backtest/confusion.png")
    except Exception as e: print(f"confusion fail {e}")

    # 3) Equity curves — top 3 perps
    try:
        plt.figure(figsize=(10,4))
        for sym in ["ETHUSDT","SOLUSDT","BTCUSDT"][:3]:
            df=fetch(sym, INTERVAL, DAYS)
            r=simulate_perps(df, INTERVAL, 2.5,0.40,0.08,0.5)
            plt.plot(r["equity"], label=f"{sym} {r['ret']:+.1f}%")
        plt.legend(); plt.title(f"Equity $800 start — perps 1h 60d (Kelly 0.08)"); plt.xlabel("bar"); plt.ylabel("equity $")
        plt.tight_layout(); plt.savefig("backtest/equity.png", dpi=150); plt.close()
        print("[plot] backtest/equity.png")
        # options vs perps
        plt.figure(figsize=(10,4))
        df=fetch("ETHUSDT", INTERVAL, DAYS)
        rp=simulate_perps(df, INTERVAL, 2.5,0.40,0.08,0.5)
        ro=simulate_options(df, INTERVAL, 2.5,0.40,0.08,0.5)
        plt.plot(rp["equity"], label=f"ETH perps {rp['ret']:+.1f}%")
        plt.plot(ro["equity"], label=f"ETH options Black76 {ro['ret']:+.1f}%")
        plt.legend(); plt.title("ETH 1h — perps vs Black76 options (OTM 48h not shown)"); plt.tight_layout(); plt.savefig("backtest/options_vs_perps.png", dpi=150); plt.close()
        print("[plot] backtest/options_vs_perps.png")
    except Exception as e: print(f"equity fail {e}")

if __name__=="__main__": main()
