"""Risk-surrogate invariants; no network, orders or historical data needed."""
import numpy as np
import pytest

pytest.importorskip("numba", reason="Optional local Monte Carlo accelerator")
from backtest.portfolio_paths import METRICS, batch, path, policy_numbers, summarize, validate_surrogate


def pool(gross=-.005, adverse=-.008, favorable=.005, eth=True, minimum=20.):
    return np.array([[gross, adverse, favorable, 1. + gross, eth, minimum, .1, 1., .00001, 1.]], dtype=np.float64)


def test_surrogate_matches_real_risk_reducer_and_entry_sizer():
    assert validate_surrogate() == 144


def test_hard_stop_and_restricted_latches_survive_recovery():
    _, restricted, hard, scale, budget = policy_numbers(800., 900., True, True)
    assert restricted and hard and scale == budget == 0
    _, restricted, hard, scale, budget = policy_numbers(900., 900., True, False)
    assert restricted and not hard and scale == .25 and budget == pytest.approx(1.125)


def test_batch_size_does_not_change_random_paths():
    p = pool()
    whole = batch(p, True, True, False, 192, 734, 0, 40)
    split = np.vstack([batch(p, True, True, False, 192, 734, 0, 13),
                       batch(p, True, True, False, 192, 734, 13, 27)])
    assert np.array_equal(whole, split)


def test_seed_changes_paths_in_a_nondegenerate_pool():
    p = np.vstack([pool(), pool(.015, -.003, .02)])
    assert not np.array_equal(batch(p, True, False, False, 192, 734, 0, 40),
                              batch(p, True, False, False, 192, 735, 0, 40))


def test_worst_path_trace_reproduces_stored_metrics():
    p = pool()
    result = batch(p, True, True, False, 192, 734, 0, 8)
    trace = np.zeros((192, len(METRICS)))
    repeated = path(p, True, True, False, 192, 734, 3, trace)
    assert np.array_equal(repeated, result[3])
    assert trace[-1, 1] == result[3, 0]
    assert np.all(np.diff(trace[:, 10]) >= 0) and np.all(np.diff(trace[:, 11]) >= 0)


def test_venue_minimums_block_entries_instead_of_rounding_up():
    result = batch(pool(minimum=400), True, False, False, 192, 734, 0, 10)
    assert np.all(result[:, 0] == 800) and np.all(result[:, 4] == 0)


def test_no_trade_episode_is_closed_beyond_the_horizon():
    p = pool()
    p[0, 9] = 193
    result = batch(p, True, False, False, 192, 734, 0, 10)
    assert np.all(result[:, 0] == 800) and np.all(result[:, 4] == 0)
    result = batch(pool(minimum=1000000), True, True, True, 23, 734, 0, 100)
    assert np.all(result[:, 0] == 800) and np.all(result[:, 4] == 0)


def test_negative_equity_and_extreme_loss_are_not_clipped_or_hidden():
    p = pool(-4., -4., 0.)
    p[0, 3], p[0, 7] = 5., -1.
    result = batch(p, True, False, False, 192, 734, 0, 1)
    assert result[0, 0] < 0 and result[0, 1] < 0 and result[0, 10] == 1
    assert result[0, 4] == 1 and result[0, 9] == 1
    assert summarize(result, 500)["risk_verdict"] == "DISCARDED_DANGEROUS"


def test_threshold_is_strict_and_a_recovery_does_not_hide_a_breach():
    result = np.zeros((3, len(METRICS)))
    result[:, 0] = [800., 800., 1100.]
    result[:, 1] = [300., 299., 600.]
    result[:, 2] = [500., 501., 600.]
    s = summarize(result, 500)
    assert s["loss_over_threshold_paths"] == 2
    assert s["terminal_loss_over_threshold_paths"] == 0
    assert s["risk_verdict"] == "DISCARDED_DANGEROUS"


def test_options_fault_retains_two_legs_and_blocks_follow_on_trades():
    p = pool(minimum=1000000)
    result = batch(p, True, True, True, 192, 734, 0, 100)
    indices = np.flatnonzero(result[:, 12])
    assert len(indices) > 0
    assert np.all(result[indices, 13] == 2)
    trace = np.zeros((192, len(METRICS)))
    path(p, True, True, True, 192, 734, int(indices[0]), trace)
    first = int(np.flatnonzero(trace[:, 13])[0])
    assert np.all(trace[first:, 6] == trace[first, 6])
    assert summarize(result, 500)["loss_over_threshold_paths"] == 0
