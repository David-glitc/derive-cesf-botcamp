import json

import pytest

from backtest.simple_edge_audit import audit, fee_sensitivity, sha


def trade():
    return dict(amount=1., entry_price=100., exit_price=102., net_pnl=1.77, fees=.22, funding=.01)


RULE = dict(maker_fee_rate=".0001", taker_fee_rate=".0003", base_fee=".01")


def test_counterfactual_retains_gross_and_funding_and_no_maker_base():
    t = trade()
    result = fee_sensitivity([t], RULE)
    assert result["gross_closed_pnl"] == pytest.approx(2.)
    assert result["scenarios"]["public_taker_both_sides"]["fees"] == pytest.approx(.0806)
    assert result["scenarios"]["ASSUMED_maker_entry_taker_exit"]["fees"] == pytest.approx(.0506)
    assert result["scenarios"]["public_taker_both_sides"]["fixed_trade_net_pnl"] == pytest.approx(1.9094)
    assert not result["usable_as_strategy_performance"]


@pytest.mark.parametrize("field", ["maker_fee_rate", "taker_fee_rate", "base_fee"])
def test_invalid_fee_schedule_is_not_free(field):
    rule = {**RULE, field: "nan"}
    with pytest.raises(ValueError): fee_sensitivity([trade()], rule)


def test_empty_trade_counterfactual_is_not_strategy_profit():
    result = fee_sensitivity([], RULE)
    assert result["gross_closed_pnl"] == 0
    assert not result["usable_as_strategy_performance"]


def test_invalid_trade_values_rejected():
    t = trade(); t["amount"] = -1
    with pytest.raises(ValueError): fee_sensitivity([t], RULE)


def test_audit_rejects_altered_source_before_trusting_result(tmp_path):
    source = tmp_path / "source.py"
    source.write_text("original")
    summary = dict(source_sha256={str(source): sha(source)}, artifact_sha256={})
    (tmp_path / "summary.json").write_text(json.dumps(summary))
    source.write_text("changed")
    with pytest.raises(ValueError, match="source_hash_changed"): audit(tmp_path)
