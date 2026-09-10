"""Portfolio guard — single source of truth for Botcamp $800 book.
Tracks gross, per-underlying, delta/vega/gamma, margin, daily/peak DD.
Enforces no-bypass: every Opportunity → Decision must pass guard.

Use inside controller or standalone backtest.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict
import time

@dataclass
class GuardConfig:
    max_gross: float = 240
    max_per_underlying: float = 160
    max_delta: float = 40
    max_vega: float = 25
    max_gamma: float = 5
    min_headroom: float = 0.25
    daily_halt: float = -0.03
    peak_halt: float = -0.10

@dataclass
class PortfolioGuard:
    cfg: GuardConfig = field(default_factory=GuardConfig)
    equity_start: float = 800
    equity: float = 800
    peak: float = 800
    day_start_equity: float = 800
    day_start_ts: float = field(default_factory=time.time)
    gross: float = 0
    per_underlying: Dict[str,float] = field(default_factory=dict)
    net_delta: float = 0
    net_vega: float = 0
    net_gamma: float = 0

    def reset_day_if_needed(self):
        if time.time() - self.day_start_ts > 86400:
            self.day_start_equity = self.equity
            self.day_start_ts = time.time()

    @property
    def daily_pnl_pct(self): return (self.equity - self.day_start_equity)/max(self.day_start_equity,1)
    @property
    def peak_dd(self): return (self.equity - self.peak)/max(self.peak,1)
    @property
    def headroom(self): return max(0.0, 1 - self.gross/max(self.cfg.max_gross,1))

    def can_open(self, underlying: str, notional: float, delta: float, vega: float, gamma: float) -> tuple[bool,str]:
        self.reset_day_if_needed()
        if self.gross + notional > self.cfg.max_gross: return False, "gross"
        if self.per_underlying.get(underlying,0)+notional > self.cfg.max_per_underlying: return False, "per_underlying"
        if abs(self.net_delta+delta) > self.cfg.max_delta: return False, "delta"
        if abs(self.net_vega+vega) > self.cfg.max_vega: return False, "vega"
        if abs(self.net_gamma+gamma) > self.cfg.max_gamma: return False, "gamma"
        if self.headroom < self.cfg.min_headroom: return False, "margin"
        if self.daily_pnl_pct <= self.cfg.daily_halt: return False, "daily_halt"
        if self.peak_dd <= self.cfg.peak_halt: return False, "peak_halt"
        return True, "ok"

    def on_fill(self, underlying: str, notional: float, delta: float, vega: float, gamma: float):
        self.gross += notional
        self.per_underlying[underlying] = self.per_underlying.get(underlying,0)+notional
        self.net_delta += delta
        self.net_vega += vega
        self.net_gamma += gamma
        self.peak = max(self.peak, self.equity)

    def on_pnl(self, pnl: float):
        self.equity += pnl
        self.peak = max(self.peak, self.equity)

    def on_close(self, underlying: str, notional: float, delta: float, vega: float, gamma: float):
        self.gross = max(0, self.gross - notional)
        self.per_underlying[underlying] = max(0, self.per_underlying.get(underlying,0)-notional)
        self.net_delta -= delta
        self.net_vega -= vega
        self.net_gamma -= gamma
