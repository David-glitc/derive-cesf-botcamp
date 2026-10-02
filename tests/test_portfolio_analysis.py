"""Analysis-only regression checks; no Hummingbot or network required."""
import gzip
import hashlib
import json
from types import SimpleNamespace

import pytest

from backtest.plot_portfolio import read_trace


def trace_task(tmp_path, side=1, corrupt=False):
    entry = {"type": "entry_fill", "i": 0, "side": side, "qty": 1.0, "entry": 100.0,
             "notional": 100.0, "fee": 1.0, "equity_before_fee": 800.0, "confidence": .8, "stop": .01}
    # One dollar entry fee and two dollars exit fee, gross $10, funding -$1.
    fill = {"type": "fill", "i": 1, "side": side, "qty": 1.0, "entry": 100.0,
            "exit": 110.0 if side == 1 else 90.0, "entry_fee": 1.0, "exit_fee": 2.0,
            "gross": 10.0, "funding": -1.0, "net": 6.0, "reason": "take_profit"}
    if corrupt:
        fill["net"] = 7.0
    records = [{"type": "metadata", "run": 0, "interval": "4h", "pair": "ETHUSDT", "scenario": "base"},
               entry, [0, 0, side, "confirmed", 804.0, 0.0, "entry"], fill,
               [1, 14400, 0, "flat", 806.0, 0.0, "close"]]
    records += [[i, i * 14400, 0, "flat", 806.0, 0.0, ""] for i in range(2, 12)]
    path = tmp_path / "trace.gz"
    with gzip.open(path, "wt") as stream:
        for record in records:
            stream.write(json.dumps(record) + "\n")
    expected = SimpleNamespace(run=0, interval="4h", pair="ETHUSDT", scenario="base", bars=12,
                               trades=1, ending_equity=806.0, fees_quote=3.0,
                               trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    return path, expected


@pytest.mark.parametrize("side,mark", [(1, 105), (-1, 95)])
def test_long_short_marked_exposure_and_first48(tmp_path, side, mark):
    result = read_trace(trace_task(tmp_path, side))
    assert result["exposure"][0] == pytest.approx(mark / 804 * 100)
    assert result["exposure"][1] == 0
    assert result["trades"][0]["allocation_pct"] == 12.5
    assert result["trades"][0]["stop_risk_pct"] == .125
    assert result["trades"][0]["net"] == 6
    assert result["first48"] == pytest.approx(.75)


def test_close_arithmetic_is_checked(tmp_path):
    with pytest.raises(ValueError, match="P&L mismatch"):
        read_trace(trace_task(tmp_path, corrupt=True))


def test_trace_hash_is_checked(tmp_path):
    path, expected = trace_task(tmp_path)
    expected.trace_sha256 = "incorrect"
    with pytest.raises(ValueError, match="digest mismatch"):
        read_trace((path, expected))


def test_bar_count_is_checked(tmp_path):
    path, expected = trace_task(tmp_path)
    expected.bars += 1
    with pytest.raises(ValueError, match="Incomplete"):
        read_trace((path, expected))
