import asyncio
from copy import deepcopy

import numpy as np
import pytest

from agents.condor_agent import AgentDecision
from backtest.enhanced_48h import BEGIN, END, TracedReplay, quality_reason, window


def quality_row():
    return dict(trend_z=1.8, previous_trend_z=1.8, efficiency=.8, previous_efficiency=.8,
                volume_ratio=2., previous_volume_ratio=2., atr_pct=.004)


def test_quality_threshold_is_not_probability_and_original_halt_wins():
    decision = AgentDecision("fixture", signal=1, confidence=.9)
    assert quality_reason(quality_row(), decision) == "quality_pass"
    assert quality_reason(quality_row(), AgentDecision("HALT", halt=True)) == "original_signal_unqualified"
    assert quality_reason(quality_row(), AgentDecision("fixture", signal=1, confidence=.84)) == "quality_confidence"


@pytest.mark.parametrize("field", ["trend_z", "efficiency", "volume_ratio"])
def test_current_and_previous_bar_both_need_quality(field):
    row = quality_row(); row["previous_" + field] = .1
    assert quality_reason(row, AgentDecision("fixture", signal=1, confidence=.9)) != "quality_pass"


def test_signed_put_quality_requires_two_negative_trends():
    row = quality_row(); row.update(trend_z=-1.8, previous_trend_z=-1.8)
    d = AgentDecision("fixture", signal=-1, confidence=.9)
    assert quality_reason(row,d) == "quality_pass"
    row["previous_trend_z"] = 1.8
    assert quality_reason(row,d) == "quality_trend_confirmation"


def test_fixed_window_has_576_bars_and_signal_warmup():
    times = np.arange(BEGIN - 200*300, END, 300)
    history = {a: dict(candles=[dict(timestamp=int(t)) for t in times], features=list(times),
                decisions={"normal":list(times),"restricted":list(times)},iv=np.full(len(times),.6))
               for a in ("ETH","BTC","SOL")}
    local,start,lo,end = window(history)
    assert start == 200 and end-start == 576 and lo == 99
    assert local["ETH"]["candles"][101]["timestamp"] == BEGIN
    assert local["ETH"]["features"][100] == BEGIN-300
    missing = deepcopy(history);missing["ETH"]["candles"].pop()
    with pytest.raises(ValueError):window(missing)


@pytest.mark.parametrize("variant,passes", [("baseline",True),("high_quality",True),("high_quality_alpha",True)])
def test_replay_variants_accept_controlled_quality_and_keep_stops(variant,passes):
    candles = [dict(timestamp=BEGIN+(i-101)*300,open=100.,close=100.,high=110.,low=90.,volume=10.)
               for i in range(130)]
    d = AgentDecision("fixture",signal=1,confidence=.9)
    h = {a:dict(candles=candles,features=[quality_row() for _ in candles],
               decisions={m:[d]*len(candles) for m in ("normal","restricted")},iv=np.full(len(candles),.6))
         for a in ("ETH","BTC","SOL")}
    rule = dict(minimum_amount=".1",amount_step=".001",tick_size=".01",maximum_amount="100000",
                taker_fee_rate=".0003",maker_fee_rate=".0001",base_fee=".01",mark_price_fee_rate_cap=".125")
    rules = {a+"-perp":{**rule,"minimum_amount":"1000" if a!="SOL" else ".1"} for a in h}
    models = {a:dict(residual_rmse=.001,horizon=6) for a in h}
    forecasts = {a:(np.full(len(candles),.1),np.zeros(len(candles),dtype=bool)) for a in h}
    replay = TracedReplay(h,rules,"perps","base",variant,models,forecasts,forecasts,101)
    result = asyncio.run(replay.run())
    assert result["trades"]>0 and not result["residual_perp"]
    assert result["exit_reasons"]["stop_loss"]>0
    assert result["net_pnl"] == pytest.approx(sum(t["net_pnl"] for t in replay.trades))
    assert any(r["stages"] for r in replay.trace_rows())
    assert len(replay.trace_rows())==576


def test_entry_only_quality_veto_does_not_change_owned_exit_signal():
    d=AgentDecision("fixture",signal=1,confidence=.8)
    row=quality_row()
    assert quality_reason(row,d)=="quality_confidence"
    assert d.signal==1 and not d.halt  # The original decision isn't rewritten.
