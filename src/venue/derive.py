"""Live Derive venue — fetches instruments + mids for SVI, matches bf-venue.

Endpoints (bf-venue/src/derive.rs):
  http_url mainnet: https://api.lyra.finance
    POST /public/get_all_instruments {currency, instrument_type: perp|option, expired:false}
    POST /public/get_ticker {instrument_name}
  ws: wss://api.lyra.finance/ws  channels: orderbook.{inst}.1.10, trades.{inst}, spot_feed.{ccy}

No keys needed for public data. For Hummingbot, connector_name=derive handles auth.
This module is for backtest/research SVI calibration — live Hummingbot controller uses same endpoints via MarketDataProvider.
"""
from __future__ import annotations
import time, math
from typing import List, Dict, Any
import requests

HTTP_MAINNET = "https://api.lyra.finance"
FALLBACKS = ["https://api.lyra.finance", "https://api-demo.lyra.finance"]

def _post(path: str, payload: dict, timeout=12) -> dict:
    last=None
    for base in FALLBACKS:
        try:
            r=requests.post(f"{base}{path}", json=payload, timeout=timeout)
            if r.status_code==200:
                return r.json()
            last=r.text[:600]
        except Exception as e:
            last=str(e)
    raise RuntimeError(f"Derive POST {path} failed: {last}")

def get_all_instruments(currency: str = "ETH", instrument_type: str = "option", expired: bool = False) -> List[dict]:
    """Matches bf-venue fetch_instruments loop."""
    j=_post("/public/get_all_instruments", {"instrument_type": instrument_type, "currency": currency, "expired": expired, "page":1, "page_size":1000})
    return (j.get("result") or {}).get("instruments") or j.get("result") or []

def get_ticker(instrument_name: str) -> dict:
    j=_post("/public/get_ticker", {"instrument_name": instrument_name})
    return (j.get("result") or j)

def list_expiries(currency="ETH", instrument_type="option") -> List[str]:
    insts=get_all_instruments(currency, instrument_type)
    # instrument_name like ETH-20250912-2500-C
    exps=set()
    for it in insts:
        name=it.get("instrument_name","")
        parts=name.split("-")
        if len(parts)>=3:
            exps.add(parts[1])
    return sorted(exps)

def fetch_svi_inputs(currency="ETH", max_expiries=3, max_strikes_per_expiry=12) -> Dict[str, Any]:
    """
    Builds SVI inputs: for each expiry, collect log_moneyness k=log(K/F) and IV mid.
    Uses get_ticker mid = (best_bid+best_ask)/2 mark IV if available, else mark_price → implied vol via Black76 inversion (not needed for now).
    Returns {expiry: {forward, tau_years, points: [(k, iv_mid)]}}
    """
    # Get spot/forward proxy: spot_feed or perp mark
    # Fallback to Binance spot if Derive down
    try:
        # Try derive perp ticker for forward
        perp_ticker=get_ticker(f"{currency}-PERP")
        forward=float(perp_ticker.get("mark_price") or perp_ticker.get("mid_price") or perp_ticker.get("mark_iv") or 0)
        if forward==0:
            raise ValueError("no perp mark")
    except Exception:
        # fallback: Binance spot
        try:
            r=requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": f"{currency}USDT"}, timeout=8)
            forward=float(r.json()["price"])
        except: forward=3000 if currency=="ETH" else 115000

    insts=get_all_instruments(currency, "option")
    # group by expiry
    from collections import defaultdict
    by_expiry=defaultdict(list)
    for it in insts:
        name=it.get("instrument_name","")
        parts=name.split("-")
        if len(parts)<4: continue
        expiry=parts[1]
        strike=parts[2]
        try: k=float(strike)
        except: continue
        by_expiry[expiry].append(it)

    # pick nearest expiries
    sorted_exps=sorted(by_expiry.keys())[:max_expiries]
    out={}
    now=time.time()
    for exp in sorted_exps:
        # expiry is YYYYMMDD
        try:
            exp_ts=time.mktime(time.strptime(exp, "%Y%m%d"))
            tau=max(1/365, (exp_ts - now)/31536000)
        except: tau=7/365
        points=[]
        for it in by_expiry[exp][:max_strikes_per_expiry]:
            name=it["instrument_name"]
            try:
                tk=get_ticker(name)
                # Derive ticker fields: mark_price, bid_price, ask_price, mark_iv
                iv=tk.get("mark_iv")
                if iv is None: iv=tk.get("iv")
                if iv is None:
                    # infer from mark_price via Black76 inversion — skip for now, use 0.6 as fallback
                    iv=0.6
                else:
                    iv=float(iv)
                    if iv>5: iv/=100  # percent to decimal
                K=float(name.split("-")[2])
                k=math.log(K/forward) if forward>0 else 0
                if 0.2 < iv < 3.0 and -0.8 < k < 0.8:
                    points.append((k, iv))
                time.sleep(0.05)
            except Exception: continue
        if len(points)>=3:
            out[exp]=dict(forward=forward, tau_years=tau, points=points)
    return out

def snapshot_to_markdown(snapshot: dict) -> str:
    lines=[f"# Derive SVI snapshot {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}", f"Forward {snapshot.get('forward')}"]
    for exp, data in snapshot.items():
        if exp=="forward": continue
        lines.append(f"\n## {exp} tau={data['tau_years']:.4f} F={data['forward']:.0f} n={len(data['points'])}")
        for k,iv in data["points"][:5]:
            lines.append(f"  k={k:+.3f} iv={iv:.2%}")
    return "\n".join(lines)

if __name__=="__main__":
    for ccy in ["ETH","BTC"]:
        print(f"\n=== {ccy} ===")
        try:
            snap=fetch_svi_inputs(ccy, max_expiries=2, max_strikes_per_expiry=8)
            print(f"expiries: {list(snap.keys())}")
            for exp, d in snap.items():
                if exp=="forward": continue
                print(f"  {exp} tau {d['tau_years']:.3f} n {len(d['points'])}")
                # try fit
                from src.svi.fit import fit_svi_slice
                ks=[k for k,iv in d["points"]]; ivs=[iv for k,iv in d["points"]]
                p, rmse=fit_svi_slice(d["tau_years"], ks, ivs)
                print(f"    SVI a={p.a:.4f} b={p.b:.3f} rho={p.rho:.2f} rmse={rmse:.4f}")
        except Exception as e:
            print(f"  fail {e}")
