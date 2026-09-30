"""Paper trading sidecar: real Flyby controller + Condor decide, stubbed venue.
No credentials, no orders. Fills simulated at live Derive testnet marks with
live taker fee (0.03%), position caps, and idempotent accounting ledger.
Usage in hb-derive-py: PYTHONPATH=/repo python3 /repo/scripts/paper_trade.py
  --hours 5 --tick-seconds 60 --universe ETH-PERP,BTC-PERP --capital 800
"""
import argparse, json, sys, time, uuid
from datetime import datetime, timezone
sys.path.insert(0, "/repo")
sys.path.insert(0, "/home/hummingbot")  # source-tree hummingbot (script mode drops CWD)
import os
os.environ["DERIVE_DOMAIN"] = "testnet"
from unittest.mock import MagicMock
import yaml
from src.venue.derive import get_ticker
from src.accounting.ledger import AccountingLedger, FillEvent
from agents.condor_agent import decide
from controllers.directional_trading.flyby import (
    DeriveCesfLongVolConfig, DeriveCesfLongVolController)

TAKER = 0.0003  # live Derive rule

def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

def load_cfg(inst):
    ccy = inst.split("-")[0].lower()
    d = yaml.safe_load(open(f"/repo/conf/controllers/conf_flyby_{ccy}.yml"))
    return DeriveCesfLongVolConfig(**d)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=5)
    ap.add_argument("--tick-seconds", type=float, default=60)
    ap.add_argument("--universe", default="ETH-PERP,BTC-PERP")
    ap.add_argument("--capital", type=float, default=800)
    ap.add_argument("--log", default="/repo/hb_backtest/paper_fills.jsonl")
    a = ap.parse_args()
    uni = [u.strip() for u in a.universe.split(",") if u.strip()]
    import urllib.request
    klines = {}
    for inst in uni:
        ccy = inst.split("-")[0]
        url = (f"https://data-api.binance.vision/api/v3/klines?symbol={ccy}USDT"
               f"&interval=1h&limit=200")
        rows = json.load(urllib.request.urlopen(url, timeout=20))
        import pandas as pd
        df = pd.DataFrame(rows, columns=["ot", "o", "h", "l", "c", "v", "ct",
                                         "qv", "t", "tb", "tq", "ig"])
        for k, src in [("close", "c"), ("high", "h"), ("low", "l"), ("open", "o")]:
            df[k] = df[src].astype(float)
        klines[inst] = df
    ctls, cfgs = {}, {}
    for inst in uni:
        cfgs[inst] = load_cfg(inst)
        ctl = DeriveCesfLongVolController.__new__(DeriveCesfLongVolController)
        ctl.config = cfgs[inst]
        ctl.max_records = max(cfgs[inst].vol_lookback, 100)
        ctl.processed_data = {}
        ctl.market_data_provider = MagicMock()
        ctl.market_data_provider.get_candles_df.return_value = klines[inst]
        ctls[inst] = ctl
    import asyncio
    ledger = AccountingLedger()
    equity = a.capital
    peak = equity
    paper_pos = {}  # inst -> [ticket, ...]; max 3 concurrent tickets each
    MAX_TICKETS = 3
    end = time.time() + a.hours * 3600
    tick = 0
    print(f"[{now()}] paper start {','.join(uni)} capital={a.capital}", flush=True)
    while time.time() < end:
        tick += 1
        for inst in uni:
            ctl = ctls[inst]
            try:
                asyncio.run(DeriveCesfLongVolController.update_processed_data(ctl))
                p = ctl.processed_data
                t = get_ticker(inst)
                mark = float(t.get("mark_price") or 0)
                snap = {"cesf_score": p["cesf_score"], "edge": p["edge"],
                        "svi_skew": p.get("skew", 0), "momentum": p.get("momentum", 0),
                        "epsilon": p.get("forecast_epsilon", 0.03),
                        "ccy": inst.split("-")[0], "spot": mark,
                        "stale_secs": 0, "daily_pnl_pct": (equity / peak - 1) if peak else 0}
                d = decide(snap)
                rec = {"ts": now(), "tick": tick, "instrument": inst, "mark": mark,
                       "signal": p["signal"], "regime": d.regime, "venue": d.execution_venue,
                       "equity": round(equity, 2)}
                # paper fill logic: signal -> open; opposing/no signal + TP/SL/time -> close
                pos_list = paper_pos.setdefault(inst, [])
                opened = None
                if p["signal"] != 0 and len(pos_list) < MAX_TICKETS:
                    side = "short" if p["signal"] < 0 else "long"
                    notion = min(equity * 0.05, equity * 0.3)
                    notion = max(notion, 10.0)
                    qty = notion / mark
                    ticket = {"side": side, "qty": qty, "entry": mark,
                              "notional": notion, "tick": tick}
                    pos_list.append(ticket)
                    fee = notion * TAKER
                    fid = f"paper-{tick}-{inst}-{uuid.uuid4().hex[:6]}"
                    from decimal import Decimal as _D
                    ledger.apply_fill(FillEvent(trade_id=fid, order_id=fid,
                                                instrument=inst, side=side,
                                                price=_D(str(mark)), amount=_D(str(qty)),
                                                fee=_D(str(round(fee, 8)))))
                    equity -= fee
                    opened = {"id": fid, "side": side, "qty": round(qty, 6),
                              "price": mark, "fee": round(fee, 4),
                              "ticket": f"{len(pos_list)}/{MAX_TICKETS}"}
                    rec["fill"] = opened
                closed = []
                for ticket in list(pos_list):
                    hold_min = (tick - ticket["tick"]) * a.tick_seconds / 60
                    ret = ((ticket["entry"] - mark) / ticket["entry"]
                           if ticket["side"] == "short"
                           else (mark - ticket["entry"]) / ticket["entry"])
                    pnl = ret * 3
                    if pnl >= 1.2 or pnl <= -0.48 or hold_min >= 24 * 60 or p["signal"] == 0:
                        gross = ticket["notional"] * (1 + pnl)
                        fee = gross * TAKER
                        fid = f"paper-x-{tick}-{inst}-{uuid.uuid4().hex[:6]}"
                        from decimal import Decimal as _D
                        ledger.apply_fill(FillEvent(
                            trade_id=fid, order_id=fid, instrument=inst,
                            side="long" if ticket["side"] == "short" else "short",
                            price=_D(str(mark)), amount=_D(str(ticket["qty"])),
                            fee=_D(str(round(fee, 8)))))
                        dq = gross - fee - ticket["notional"]
                        equity += dq
                        peak = max(peak, equity)
                        closed.append({"pnl_pct": round(pnl, 4), "dq": round(dq, 2)})
                        pos_list.remove(ticket)
                if closed:
                    rec["close"] = closed
                    rec["equity"] = round(equity, 2)
                rec["paper_pos"] = {k: [{"side": v["side"], "entry": v["entry"]} for v in tickets]
                                    for k, tickets in paper_pos.items() if tickets}
                with open(a.log, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
                print(f"[{now()}] tick={tick} {inst} mark={mark:.2f} sig={p['signal']} "
                      f"{d.regime} eq={equity:.2f} {rec.get('fill', rec.get('close', ''))}", flush=True)
            except Exception as e:
                print(f"[{now()}] tick={tick} {inst} ERROR {type(e).__name__}: {str(e)[:150]}", flush=True)
        time.sleep(a.tick_seconds)
    print(f"[{now()}] paper done equity={equity:.2f} peak={peak:.2f}", flush=True)

if __name__ == "__main__":
    main()
