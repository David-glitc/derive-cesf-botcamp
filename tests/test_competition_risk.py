"""Deterministic account risk/state tests. No trading or credentials."""
import json
import random
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agents.condor_agent import decide
from src.risk.competition import (POLICY, RiskCheckpoint, account_binding, advance, initial_state,
                                  risk_view, scalp_exits, exit_signal_reason)
from src.risk.position_sizing import risk_size, cost_allows_entry
from tests.test_flyby_policy import snapshot

BINDING = "a" * 64


@pytest.mark.parametrize("equity,mode", [(800, "normal"), ("720.000001", "normal"),
    (720, "restricted"), ("680.000001", "restricted"), (680, "hard_stop"), (0, "hard_stop")])
def test_exact_boundaries(equity, mode):
    state = advance(initial_state(800, 100, 800, BINDING), equity, 101)
    view = risk_view(state, equity)
    assert view["risk_mode"] == mode
    assert view["remaining_loss_buffer"] == pytest.approx(max(0, float(equity) - 680))


def test_peak_relative_drawdown_and_competition_baseline_not_capped_equity():
    state = advance(initial_state(800, 100, 800, BINDING), 1000, 101)
    state = advance(state, 900, 102)
    assert risk_view(state, 900)["peak_dd"] == -.10
    assert state["restricted"] and not state["hard_stop"]
    state = advance(state, 850, 103)
    assert state["hard_stop"]
    assert initial_state(680, 100, 800, BINDING)["hard_stop"]


def test_restricted_and_hard_latches_survive_recovery_midnight():
    state = advance(initial_state(800, 100, 800, BINDING), 720, 101)
    state = advance(state, 800, 86401)
    assert risk_view(state, 800)["risk_mode"] == "restricted"
    assert risk_view(state, 800)["daily_pnl_pct"] == 0
    state = advance(state, 680, 86402)
    state = advance(state, 900, 172801)
    assert risk_view(state, 900)["risk_mode"] == "hard_stop"


@pytest.mark.parametrize("equity", [720, 710, 700, 690, 681])
def test_restricted_budget_decreases_and_caps_remaining_buffer(equity):
    view = risk_view(advance(initial_state(800, 100, 800, BINDING), equity, 101), equity)
    assert 0 < view["risk_scale"] <= .25
    assert view["risk_trade_budget"] <= .1 * view["remaining_loss_buffer"] + 1e-12
    size = risk_size(equity=equity, available=equity, committed=0, confidence=.9, stop_pct=.007,
        gross_cap=equity * .3, peak_dd=view["peak_dd"], drawdown_limit=.15,
        size_scale=view["risk_scale"], trade_risk_budget=view["risk_trade_budget"])
    assert size <= equity * .2 * view["risk_scale"]
    assert size * .007 <= view["risk_trade_budget"] * .9 + 1e-12


def test_checkpoint_shared_restart_profile_and_duplicate_signal(tmp_path):
    path = tmp_path / "risk.json"
    store = RiskCheckpoint(path, BINDING, 800)
    store.observe(800, 100, allow_bootstrap=True)
    assert store.consume_entry(800, 100, "ETH-USDC", 0, 60)
    other = RiskCheckpoint(path, BINDING, 800)
    assert not other.consume_entry(800, 170, "ETH-USDC", 0, 60)
    assert other.consume_entry(800, 180, "ETH-USDC", 120, 60)
    store.observe(680, 181)
    state, view = other.observe(850, 86401)
    assert view["risk_mode"] == "hard_stop"
    assert not other.consume_entry(850, 86401, "SOL-USDC", 86000, 60)
    assert state["entries"]["ETH-USDC"]["signal_time"] == 120


def test_entry_cooldown_survives_reload(tmp_path):
    path = tmp_path / "risk.json"
    store = RiskCheckpoint(path, BINDING, 800)
    store.observe(800, 100, allow_bootstrap=True)
    assert store.consume_entry(800, 100, "ETH-USDC", 0, 60)
    other = RiskCheckpoint(path, BINDING, 800)
    assert not other.consume_entry(800, 120, "ETH-USDC", 110, 60)
    assert other.consume_entry(800, 160, "ETH-USDC", 150, 60)


def test_lost_checkpoint_is_detected_across_restart(tmp_path):
    path = tmp_path / "risk.json"
    store = RiskCheckpoint(path, BINDING, 800)
    store.observe(800, 100, allow_bootstrap=True)
    path.unlink()  # Deliberate fault injection into a test-owned file.
    with pytest.raises(ValueError, match="lost"):
        RiskCheckpoint(path, BINDING, 800).observe(800, 200, allow_bootstrap=True)


@pytest.mark.parametrize("fault", ["corrupt", "foreign_account", "budget", "policy", "latch", "future", "symlink"])
def test_bad_checkpoint_never_resets_or_overwrites(tmp_path, fault):
    path = tmp_path / "risk.json"
    store = RiskCheckpoint(path, BINDING, 800)
    store.observe(800, 100, allow_bootstrap=True)
    if fault == "corrupt":
        path.write_text("bad JSON")
    elif fault == "symlink":
        path.rename(tmp_path / "original.json")
        path.symlink_to(tmp_path / "original.json")
    else:
        state = json.loads(path.read_text())
        if fault == "foreign_account": state["account_binding"] = "b" * 64
        if fault == "budget": state["budget"] = "801"
        if fault == "policy": state["policy"] = "looser"
        if fault == "latch": state["hard_stop"] = True
        if fault == "future": state["last_observed"] = 102
        path.write_text(json.dumps(state))
    before = path.read_bytes()
    with pytest.raises((ValueError, KeyError)):
        store.observe(800, 101, allow_bootstrap=True)
    assert path.read_bytes() == before


def test_bootstrap_requires_flat_and_clock_monotonic(tmp_path):
    store = RiskCheckpoint(tmp_path / "risk.json", BINDING, 800)
    with pytest.raises(ValueError, match="flat"):
        store.observe(800, 100)
    store.observe(800, 100, allow_bootstrap=True)
    with pytest.raises(ValueError, match="clock"):
        store.observe(800, 99)


@pytest.mark.parametrize("active", [False, True])
def test_restricted_policy_is_stricter_even_in_condor_active_mode(active):
    normal = {**snapshot(), "risk_policy": POLICY, "risk_mode": "normal", "daily_pnl_pct": -.05, "peak_dd": -.09}
    assert decide(normal, active).signal == 1
    restricted = {**normal, "risk_mode": "restricted", "peak_dd": -.10}
    assert decide(restricted, active).signal == 1
    for field, value in (("volume_ratio", 1.4), ("trend_z", 1.4), ("efficiency", .4),
                         ("previous_volume_ratio", 1.4), ("previous_efficiency", .4)):
        assert not decide({**restricted, field: value}, active).signal
    assert not decide({**restricted, "efficiency": .5, "volume_ratio": 1.5, "trend_z": 1.5}, active).signal
    assert decide({**normal, "risk_mode": "hard_stop"}, active).halt
    assert decide({**restricted, "risk_mode": "normal"}, active).halt


def test_cost_and_exit_contracts():
    assert cost_allows_entry(.0091, .003, 3)
    assert not cost_allows_entry(.009, .003, 4)
    assert not cost_allows_entry(.009, .003, 2)
    stop, target, hold = scalp_exits(.004, .9, 300)
    assert 600 <= hold <= 1800 and 0 < stop < target
    weak = {**snapshot(), "volume_ratio": .5}
    decision = decide(weak)
    assert exit_signal_reason("baseline", decision, weak, 1)
    assert exit_signal_reason("competition_scalp", decision, weak, 1) is None


def test_thousand_seeded_risk_transitions_never_reset_latches_or_increase_buffer_budget():
    rng = random.Random(771)
    state = initial_state(800, 100, 800, BINDING)
    restricted, hard = False, False
    for i in range(1000):
        equity = Decimal(rng.randrange(60000, 120000)) / 100
        state = advance(state, equity, 100 + i * 86401)
        view = risk_view(state, equity)
        assert not restricted or state["restricted"]
        assert not hard or state["hard_stop"]
        if state["hard_stop"]:
            assert view["risk_scale"] == 0 and view["risk_trade_budget"] == 0
        if view["risk_mode"] == "restricted":
            assert view["risk_trade_budget"] <= view["remaining_loss_buffer"] * .1 + 1e-12
        restricted, hard = state["restricted"], state["hard_stop"]


@pytest.mark.parametrize("bad", [None, True, "bad", -1, float("nan")])
def test_missing_identity_cannot_bootstrap(bad):
    with pytest.raises(ValueError): account_binding(SimpleNamespace(_subacct_id=bad))
    assert account_binding(SimpleNamespace(_subacct_id=7)) == account_binding(SimpleNamespace(_subacct_id="7"))
