"""The cap probe cannot promote wider production bounds or manufacture fills."""
from types import SimpleNamespace

import pytest

from backtest.exposure_cap_probe import probe, CAPS
from src.options.delta import account_policy


def test_probe_varies_only_offline_bounds_and_restores_production_policy():
    now = 1800000000
    history, rules = {}, {}
    for asset, spot, minimum in (("ETH", 3000, ".1"), ("BTC", 90000, ".01")):
        history[asset] = dict(candles=[dict(timestamp=now, open=spot)] * 103,
            decisions={"normal": [SimpleNamespace(option_direction="call", confidence=.9)] * 103},
            iv=[.6] * 103)
        rules[asset + "-option"] = dict(amount_step=".001" if asset == "ETH" else ".00001",
            minimum_amount=minimum, tick_size=".1", taker_fee_rate=".0003",
            base_fee=".5", mark_price_fee_rate_cap=".125")
    before = account_policy(3000, 800)
    rows = probe(history, rules)
    assert len(rows) == len(CAPS) * 2
    assert all(r["signal_observations"] == 2 for r in rows)
    assert rows[0]["reasons"] == {"option_minimum_gross_exceeds_cap": 2}
    assert account_policy(3000, 800) == before
    # Wider live policy still requires a separately reviewed implementation.
    with pytest.raises(ValueError, match="invalid_delta_account_budget"):
        account_policy(3000, 800, gross_fraction=.75)
