"""Derive multi-collateral vault — showcases Derive vs isolated USDC venues.

Derive advantage: post ETH / BTC / HYPE / kHYPE / stablecoins as margin collateral,
not just USDC. Haircuts apply, LTV drives effective margin. This module is the
single source of truth for 'what collateral is posted' and 'what it is worth
under stress'.

Used by:
  - PortfolioGuard (effective_collateral → headroom)
  - Controller (choose collateral asset per position, rebalance)
  - Condor agent (decide spot hedge vs perp based on collateral inventory)

References:
  - Derive docs: portfolio margin + multi-collateral enable cross-asset margining
    with offsets unavailable on isolated-margin venues (Binance, etc).

No private deps — pure Python, backtest-friendly.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

# Derive-supported collateral assets + haircuts (source: Derive risk params, simplified)
# haircut = 1 - LTV ; e.g., ETH haircut 10% → 0.90 counts toward margin
DERIVE_COLLATERAL: Dict[str, float] = {
    "USDC": 0.00,   # 100% counts
    "USDT": 0.01,   # 99%
    "ETH": 0.10,    # 90%
    "BTC": 0.10,    # 90%
    "HYPE": 0.15,   # 85%
    "kHYPE": 0.15,  # 85% (staked HYPE)
    "SOL": 0.12,    # 88%
    "ARB": 0.20,    # 80% (alt)
    "AVAX": 0.20,   # 80%
}

@dataclass
class CollateralConfig:
    """Desired collateral mix — sum of weights should ≈1.0."""
    target_weights: Dict[str, float] = field(default_factory=lambda: {
        "USDC": 0.40, "ETH": 0.30, "BTC": 0.15, "HYPE": 0.10, "kHYPE": 0.05,
    })
    # Rebalance threshold before we trade spot to realign
    rebalance_band: float = 0.08
    # If true, controller will hedge drift by trading Derive spot (ETH/USDC etc.)
    auto_hedge_spot: bool = True


@dataclass
class CollateralVault:
    """Tracks posted collateral balances and returns effective margin.

    Example:
        vault = CollateralVault(equity=800, balances={'ETH': 0.12, 'USDC': 320, 'HYPE': 180})
        eff = vault.effective_collateral(mark_prices={'ETH': 3000, 'BTC': 115000, 'HYPE': 28})
        # eff counts ETH at 90%, HYPE at 85% — demonstrates multi-collateral vs USDC-only
        headroom = eff / 800  # vs isolated: only USDC would count
    """
    equity: float = 800.0
    # balances in native units (ETH in ETH, USDC in USDC, etc.)
    balances: Dict[str, float] = field(default_factory=dict)
    cfg: CollateralConfig = field(default_factory=CollateralConfig)

    def effective_collateral(self, mark_prices: Dict[str, float] | None = None) -> float:
        """USD value of collateral after haircuts — the Derive margin number."""
        mark_prices = mark_prices or {}
        total = 0.0
        for asset, bal in self.balances.items():
            haircut = DERIVE_COLLATERAL.get(asset, 0.30)
            px = mark_prices.get(asset, 1.0 if asset in ("USDC", "USDT") else 3000.0)
            # for ETH/BTC the balance is in coins; for USDC/USDT balance is already USD
            if asset in ("USDC", "USDT"):
                usd = bal
            elif asset in ("ETH", "BTC", "SOL", "ARB", "AVAX", "HYPE", "kHYPE"):
                usd = bal * px
            else:
                usd = bal * px
            total += usd * (1 - haircut)
        return total

    def usdc_only_collateral(self) -> float:
        """What isolated USDC-only venue would count — for offset demo."""
        return self.balances.get("USDC", 0.0) + self.balances.get("USDT", 0.0) * 0.99

    def margin_benefit_vs_isolated(self, mark_prices: Dict[str, float] | None = None) -> float:
        """Extra USD margin unlocked by Derive multi-collateral vs USDC-only."""
        return self.effective_collateral(mark_prices) - self.usdc_only_collateral()

    def portfolio_margin_offset_example(self, gross_notional: float) -> dict:
        """Illustrative offset table — Derive portfolio margin vs isolated.

        With Derive portfolio margin:
          - Long spot ETH (collateral) + short ETH-PERP + long ETH put
            net delta offsets → margin down ~40-60%
          - ETH/BTC cross-asset correlation offset → further haircut reduction

        Returns a dict for logging / strategy.md table.
        """
        eff = self.effective_collateral()
        isolated_req = gross_notional * 0.50  # isolated 2x = 50% margin
        # portfolio: net delta/vega reduces requirement; haircuts already in eff
        # simplified Derive rule: requirement = max(0.10*gross, 0.25*|net_delta|*F)  here 10%
        portfolio_req = gross_notional * 0.10 + gross_notional * 0.02  # 12% with vega add
        return {
            "gross": gross_notional,
            "effective_collateral": round(eff, 2),
            "isolated_margin_req": round(isolated_req, 2),
            "portfolio_margin_req": round(portfolio_req, 2),
            "capital_efficiency_gain": f"{(1 - portfolio_req/max(isolated_req,1))*100:.0f}% less margin",
            "leverage_isolated": round(gross_notional / max(eff, 1), 2),
            "leverage_portfolio": round(gross_notional / max(portfolio_req, 1), 2),
        }

    def choose_collateral_for_trade(self, notional: float, underlying: str) -> str:
        """Pick cheapest-to-deliver collateral with headroom — prefers ETH/BTC/HYPE.

        Derive lets us post non-USDC natively; we prefer to keep USDC free for fees
        and post ETH/BTC/HYPE as margin (core Derive edge vs Binance).
        """
        # prefer non-USDC that we hold + has weight target >0
        for asset in ["ETH", "BTC", "HYPE", "kHYPE", "SOL"]:
            if asset in self.balances and self.cfg.target_weights.get(asset, 0) > 0:
                return asset
        return "USDC"

    def rebalance_hint(self, mark_prices: Dict[str, float] | None = None) -> str | None:
        """If one asset drifts > band vs target, suggest Derive spot trade to rebalance."""
        eff = self.effective_collateral(mark_prices)
        if eff < 1:
            return None
        for asset, w_target in self.cfg.target_weights.items():
            haircut = DERIVE_COLLATERAL.get(asset, 0.3)
            px = (mark_prices or {}).get(asset, 3000 if asset == "ETH" else 1)
            bal_usd = (self.balances.get(asset, 0) * px) if asset not in ("USDC", "USDT") else self.balances.get(asset, 0)
            w_actual = (bal_usd * (1 - haircut)) / eff if eff else 0
            if abs(w_actual - w_target) > self.cfg.rebalance_band:
                side = "buy" if w_actual < w_target else "sell"
                return f"{side} {asset} on Derive spot to rebalance ({w_actual:.0%} vs {w_target:.0%} target)"
        return None
