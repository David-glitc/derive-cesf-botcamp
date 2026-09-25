#!/usr/bin/env python3
"""Flyby Condor runner for Derive v3 testnet.

This is the Botcamp demonstration lane:

- Derive v3 testnet execution through derive-py.
- Multi-asset Flyby universe, limited to perps that actually exist on v3.
- Condor decisions from agents/condor_agent.py.
- V2 Hummingbot controller/mainnet configs stay in conf/ and controllers/.

The runner is intentionally defensive. One broken symbol, missing Binance
candles, venue rejection, or stale open order should not crash the loop.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, "/repo")
sys.path.insert(0, "/repo/hb_backtest")
sys.path.insert(0, ".")

from agents.condor_agent import decide  # noqa: E402
from derive_py import HTTPClient  # noqa: E402
from derive_py.data_types import Direction, OrderType  # noqa: E402
from hb_backtest.make_features import _cesf, _ewma, _har  # noqa: E402


GMT_PLUS_ONE = timezone(timedelta(hours=1), "GMT+1")
DERIVE_TESTNET_HTTP = "https://api-demo.lyra.finance"
DEFAULT_UNIVERSE = "ETH-PERP,BTC-PERP,DOGE-PERP,ZEC-PERP,HYPE-PERP,SOL-PERP,BNB-PERP"


@dataclass
class InstrumentMeta:
    name: str
    ccy: str
    amount_step: Decimal
    minimum_amount: Decimal
    tick_size: Decimal


def gmt1_now() -> str:
    return datetime.now(GMT_PLUS_ONE).strftime("%Y-%m-%d %H:%M:%S %Z")


def write_jsonl(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")


def public_post(path: str, payload: dict[str, Any], timeout: float = 15) -> dict[str, Any]:
    r = requests.post(f"{DERIVE_TESTNET_HTTP}{path}", json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_public_perp_metadata() -> dict[str, InstrumentMeta]:
    data = public_post(
        "/public/get_all_instruments",
        {"instrument_type": "perp", "expired": False, "page": 1, "page_size": 1000},
    )
    instruments = (data.get("result") or {}).get("instruments") or []
    out: dict[str, InstrumentMeta] = {}
    for item in instruments:
        name = item.get("instrument_name")
        if not name:
            continue
        out[name] = InstrumentMeta(
            name=name,
            ccy=name.split("-")[0],
            amount_step=Decimal(str(item.get("amount_step") or "0.01")),
            minimum_amount=Decimal(str(item.get("minimum_amount") or item.get("amount_step") or "0.01")),
            tick_size=Decimal(str(item.get("tick_size") or "0.01")),
        )
    return out


def fetch_trading_perp_metadata(client: HTTPClient) -> dict[str, InstrumentMeta]:
    """Use the authenticated derive-py cache for order constraints.

    Derive's public testnet metadata can differ from the trading client's cache
    for min sizes and amount steps. Orders must use the authenticated cache.
    """
    out: dict[str, InstrumentMeta] = {}
    for name, item in client.markets.perp_instruments_cache.items():
        out[name] = InstrumentMeta(
            name=name,
            ccy=name.split("-")[0],
            amount_step=Decimal(str(getattr(item, "amount_step", "0.01"))),
            minimum_amount=Decimal(str(getattr(item, "minimum_amount", getattr(item, "amount_step", "0.01")))),
            tick_size=Decimal(str(getattr(item, "tick_size", "0.01"))),
        )
    return out


def get_mark(instrument_name: str) -> float:
    data = public_post("/public/get_ticker", {"instrument_name": instrument_name}, timeout=8)
    result = data.get("result") or data
    for field in ("mark_price", "mid_price", "best_bid_price", "index_price"):
        value = result.get(field)
        if value not in (None, ""):
            return float(value)
    raise RuntimeError(f"no mark price in ticker for {instrument_name}")


def fetch_binance_klines(ccy: str, days: float) -> pd.DataFrame:
    end_ts = int(time.time())
    start_ms = int((end_ts - days * 86400) * 1000)
    symbol = f"{ccy}USDT"
    rows: list[list[Any]] = []
    cursor = start_ms
    while True:
        batch = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={"symbol": symbol, "interval": "1h", "startTime": cursor, "limit": 1000},
            timeout=20,
        ).json()
        if isinstance(batch, dict):
            raise RuntimeError(batch.get("msg") or f"Binance error for {symbol}")
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < 1000 or cursor >= end_ts * 1000:
            break
    if len(rows) < 12:
        raise RuntimeError(f"only {len(rows)} Binance candles for {symbol}")
    df = pd.DataFrame(
        rows,
        columns=["ts", "open", "high", "low", "close", "vol", "ct", "qv", "nt", "tb", "tq", "x"],
    )
    df["timestamp"] = pd.to_datetime(df["ts"], unit="ms")
    for c in ("open", "high", "low", "close"):
        df[c] = df[c].astype(float)
    return df


def alpha_snapshot(meta: InstrumentMeta, feature_days: float) -> dict[str, Any]:
    df = fetch_binance_klines(meta.ccy, feature_days)
    closes = df["close"].astype(float).values
    rets_all = np.diff(np.log(np.maximum(closes, 1e-8)))
    lookback = min(100, len(rets_all))
    rets = rets_all[-lookback:]
    ppy = 365 * 24
    har = _har(rets, ppy)
    ewma = _ewma(rets, 0.94, ppy)
    sigma = 0.5 * har + 0.5 * ewma
    eps = max(0.01 + 0.5 * abs(har - ewma), 0.01)
    score = _cesf(rets, sigma, eps)
    recent = float(np.sqrt(np.mean(rets[-20:] ** 2) * ppy)) if len(rets) >= 20 else sigma
    edge = float(sigma - recent)
    mom = float(np.sum(rets[-24:])) if len(rets) >= 24 else 0.0
    downside = float(np.mean(rets[-20:] < -recent / math.sqrt(ppy))) if recent > 0 else 0.0
    upside = float(np.mean(rets[-20:] > recent / math.sqrt(ppy))) if recent > 0 else 0.0
    skew = float((downside - upside) * 30)
    return {
        "ccy": meta.ccy,
        "inst": meta.name,
        "ts": time.time(),
        "mark_price": get_mark(meta.name),
        "spot": float(closes[-1]),
        "cesf_score": round(float(score), 4),
        "edge": round(edge, 5),
        "momentum": round(mom, 5),
        "svi_skew": round(skew, 4),
        "skew": round(skew, 4),
        "iv_proxy": round(float(recent), 5),
        "epsilon": round(float(eps), 5),
        "kelly_frac": 0.02,
        "stale_secs": 0,
        "daily_pnl_pct": 0,
    }


def side_for_decision(regime: str) -> Direction | None:
    r = regime.lower()
    if "halt" in r or "strangle" in r:
        return None
    if "put" in r:
        return Direction.sell
    if "call" in r:
        return Direction.buy
    return None


def signed_amount(position: Any) -> Decimal:
    try:
        return Decimal(str(getattr(position, "amount", "0")))
    except Exception:
        return Decimal("0")


def position_map(client: HTTPClient) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for p in client.active_subaccount.positions.list():
        inst = getattr(p, "instrument_name", None)
        if inst:
            out[inst] = signed_amount(p)
    return out


def open_order_instruments(client: HTTPClient) -> set[str]:
    out: set[str] = set()
    for order in client.active_subaccount.orders.list_open():
        inst = getattr(order, "instrument_name", None)
        if inst:
            out.add(inst)
    return out


def should_trade(decision_reason: str, allow_default: bool) -> tuple[bool, str | None]:
    if decision_reason.startswith("default ATM") and not allow_default:
        return False, "default-regime skipped"
    return True, None


def quantize_amount(meta: InstrumentMeta, multiplier: Decimal) -> Decimal:
    amount = meta.minimum_amount * multiplier
    steps = (amount / meta.amount_step).to_integral_value(rounding="ROUND_CEILING")
    return steps * meta.amount_step


def would_increase_exposure(pos: Decimal, side: Direction) -> bool:
    return (side == Direction.buy and pos > 0) or (side == Direction.sell and pos < 0)


def run_once(args: argparse.Namespace, client: HTTPClient, metas: dict[str, InstrumentMeta], tick: int) -> None:
    log_path = Path(args.log_jsonl)
    selected = [x.strip().upper() for x in args.universe.split(",") if x.strip()]
    executable: list[tuple[float, InstrumentMeta, dict[str, Any], Any, Direction | None, str | None]] = []
    positions = position_map(client)
    open_insts = open_order_instruments(client)

    for name in selected:
        now = gmt1_now()
        if name in args.disabled_instruments:
            write_jsonl(log_path, {"timestamp": now, "tick": tick, "instrument": name, "status": "skip", "reason": "disabled-after-venue-reject"})
            continue
        if name not in metas:
            rec = {"timestamp": now, "tick": tick, "instrument": name, "status": "skip", "reason": "not-listed-on-derive-v3-testnet"}
            write_jsonl(log_path, rec)
            print(f"[{now}] {name} skip not-listed-on-derive-v3-testnet", flush=True)
            continue
        meta = metas[name]
        try:
            snap = alpha_snapshot(meta, args.feature_days)
            dec = decide(snap, active=args.active)
            side = side_for_decision(dec.regime)
            score = snap["cesf_score"] + max(snap["edge"], 0) * 20 + abs(snap["momentum"]) * 3
            executable.append((float(score), meta, snap, dec, side, None))
            rec = {
                "timestamp": now,
                "tick": tick,
                "instrument": name,
                "snapshot": snap,
                "decision": asdict(dec),
                "side": str(side) if side else None,
                "status": "decision",
            }
            write_jsonl(log_path, rec)
            print(
                f"[{now}] {name} decision={dec.regime} side={side} halt={dec.halt} "
                f"mark={snap['mark_price']:.4f} cesf={snap['cesf_score']:.3f} "
                f"edge={snap['edge']:.4f} mom={snap['momentum']:.4f}",
                flush=True,
            )
        except Exception as e:
            rec = {"timestamp": now, "tick": tick, "instrument": name, "status": "error", "error": str(e)}
            write_jsonl(log_path, rec)
            print(f"[{now}] {name} ERROR {e}", flush=True)

    executable.sort(key=lambda x: x[0], reverse=True)
    sent = 0
    for _, meta, snap, dec, side, _ in executable:
        now = gmt1_now()
        if sent >= args.max_orders_per_tick:
            break
        ok, why = should_trade(dec.reason, args.allow_default_orders)
        if dec.halt or side is None or not ok:
            write_jsonl(
                log_path,
                {"timestamp": now, "tick": tick, "instrument": meta.name, "status": "no-order", "reason": why or "no-perp-side"},
            )
            continue
        if meta.name in open_insts:
            write_jsonl(log_path, {"timestamp": now, "tick": tick, "instrument": meta.name, "status": "no-order", "reason": "open-order-exists"})
            continue
        pos = positions.get(meta.name, Decimal("0"))
        cap = meta.minimum_amount * Decimal(str(args.max_min_multiple))
        if abs(pos) >= cap and would_increase_exposure(pos, side):
            write_jsonl(
                log_path,
                {
                    "timestamp": now,
                    "tick": tick,
                    "instrument": meta.name,
                    "status": "no-order",
                    "reason": f"position-cap pos={pos} cap={cap}",
                },
            )
            continue
        amount = quantize_amount(meta, Decimal(str(args.amount_multiplier)))
        if args.dry_run:
            write_jsonl(
                log_path,
                {
                    "timestamp": now,
                    "tick": tick,
                    "instrument": meta.name,
                    "status": "dry-run-order",
                    "side": side.value,
                    "amount": str(amount),
                    "price": snap["mark_price"],
                },
            )
            print(f"[{now}] {meta.name} DRY {side.value} {amount} @ {snap['mark_price']:.4f}", flush=True)
            sent += 1
            continue
        try:
            result = client.active_subaccount.orders.create(
                instrument_name=meta.name,
                direction=side,
                order_type=OrderType.limit,
                limit_price=Decimal(str(snap["mark_price"])),
                amount=amount,
                label=f"flyby-v3-{tick}",
            )
            order = result.order
            rec = {
                "timestamp": now,
                "tick": tick,
                "instrument": meta.name,
                "status": "order",
                "side": side.value,
                "amount": str(amount),
                "price": str(snap["mark_price"]),
                "order_id": getattr(order, "order_id", None),
                "filled_amount": str(getattr(order, "filled_amount", None)),
            }
            write_jsonl(log_path, rec)
            print(
                f"[{now}] {meta.name} ORDER {side.value} {amount} "
                f"id={rec['order_id']} filled={rec['filled_amount']}",
                flush=True,
            )
            sent += 1
        except Exception as e:
            msg = str(e)
            if "risk universe" in msg or "not found in perp instrument cache" in msg:
                args.disabled_instruments.add(meta.name)
            write_jsonl(
                log_path,
                {"timestamp": now, "tick": tick, "instrument": meta.name, "status": "order-error", "error": msg},
            )
            print(f"[{now}] {meta.name} ORDER ERROR {msg}", flush=True)


def _decimal_attr(obj: Any, name: str) -> Decimal | None:
    value = getattr(obj, name, None)
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def print_status(client: HTTPClient) -> None:
    sub = client.active_subaccount
    orders = sub.orders.list_open()
    positions = sub.positions.list()
    total_abs_notional = Decimal("0")
    total_upnl = Decimal("0")
    position_rows = []
    order_rows = []

    for p in positions:
        amount = _decimal_attr(p, "amount")
        mark = _decimal_attr(p, "mark_price")
        upnl = _decimal_attr(p, "unrealized_pnl")
        notional = abs(amount * mark) if amount is not None and mark is not None else None
        if notional is not None:
            total_abs_notional += notional
        if upnl is not None:
            total_upnl += upnl
        position_rows.append((p, notional))

    for o in orders:
        amount = _decimal_attr(o, "amount")
        price = _decimal_attr(o, "limit_price")
        notional = abs(amount * price) if amount is not None and price is not None else None
        order_rows.append((o, notional))

    print(
        f"[{gmt1_now()}] subaccount={sub.id} open_orders={len(orders)} positions={len(positions)} "
        f"position_notional≈{total_abs_notional:.2f} upnl≈{total_upnl:.4f}"
    )
    for p, notional in position_rows:
        notional_s = f" notional≈{notional:.2f}" if notional is not None else ""
        print(
            "POSITION "
            f"{getattr(p, 'instrument_name', '?')} amount={getattr(p, 'amount', '?')} "
            f"mark={getattr(p, 'mark_price', '?')}{notional_s} upnl={getattr(p, 'unrealized_pnl', '?')}"
        )
    for o, notional in order_rows:
        notional_s = f" notional≈{notional:.2f}" if notional is not None else ""
        print(
            "OPEN "
            f"{getattr(o, 'instrument_name', '?')} {getattr(o, 'direction', '?')} "
            f"amount={getattr(o, 'amount', '?')} filled={getattr(o, 'filled_amount', '?')} "
            f"price={getattr(o, 'limit_price', '?')}{notional_s} id={getattr(o, 'order_id', '?')}"
        )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run Flyby Condor on Derive v3 testnet")
    p.add_argument("--universe", default=DEFAULT_UNIVERSE)
    p.add_argument("--hours", type=float, default=5)
    p.add_argument("--tick-seconds", type=float, default=60)
    p.add_argument("--feature-days", type=float, default=5)
    p.add_argument("--max-orders-per-tick", type=int, default=2)
    p.add_argument("--amount-multiplier", type=float, default=1.1)
    p.add_argument("--max-min-multiple", type=float, default=3.0)
    p.add_argument("--active", action="store_true", help="Use Condor active mode for finals style volume")
    p.add_argument("--allow-default-orders", action="store_true", help="Allow default ATM fallback regimes to execute")
    p.add_argument("--execute", action="store_true", help="Place real Derive v3 testnet orders")
    p.add_argument("--status-only", action="store_true")
    p.add_argument("--log-jsonl", default="/repo/hb_backtest/flyby_v3_testnet.jsonl")
    args = p.parse_args()
    args.dry_run = not args.execute
    args.disabled_instruments = set()
    return args


def main() -> None:
    args = parse_args()
    missing = [k for k in ("DERIVE_SESSION_KEY", "DERIVE_WALLET", "DERIVE_SUBACCOUNT_ID") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"missing required env vars: {', '.join(missing)}")

    client = HTTPClient.from_env()
    client.connect()
    try:
        if args.status_only:
            print_status(client)
            return
        metas = fetch_trading_perp_metadata(client)
        public_metas = fetch_public_perp_metadata()
        for name in list(metas):
            if name not in public_metas:
                metas.pop(name, None)
        listed = ", ".join(sorted(metas))
        print(f"[{gmt1_now()}] Flyby v3 testnet start execute={args.execute} active={args.active}", flush=True)
        print(f"[{gmt1_now()}] Derive v3 testnet perps: {listed}", flush=True)
        end_at = time.time() + args.hours * 3600
        tick = 0
        while time.time() < end_at:
            tick += 1
            try:
                run_once(args, client, metas, tick)
            except Exception as e:
                write_jsonl(Path(args.log_jsonl), {"timestamp": gmt1_now(), "tick": tick, "status": "loop-error", "error": str(e)})
                print(f"[{gmt1_now()}] LOOP ERROR {e}", flush=True)
            remaining = end_at - time.time()
            if remaining <= 0:
                break
            time.sleep(min(args.tick_seconds, remaining))
        print(f"[{gmt1_now()}] Flyby v3 testnet complete ticks={tick}", flush=True)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
