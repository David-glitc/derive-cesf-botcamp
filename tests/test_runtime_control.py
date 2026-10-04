import random
import pytest

from src.runtime.control import BOUNDS, entry_allowed, patch_view, tune_exits


@pytest.mark.parametrize("field", BOUNDS)
def test_numeric_bounds_exact_and_beyond(field):
    lo, hi = BOUNDS[field]
    for value in (lo, hi, (lo + hi) / 2):
        assert patch_view({field: value})[field] == value
    for bad in (lo - 1e-9, hi + 1e-9, True, None, "1", float("nan"), float("inf")):
        with pytest.raises(ValueError):
            patch_view({field: bad})


@pytest.mark.parametrize("patch", [{}, [], None, {"budget": 1600}, {"leverage": 3},
    {"risk_state_id": "reset"}, {"stop_loss": .5}, {"veto_entry": 1}, {"close_options": "true"},
    {"close_executor_id": "../foreign"}, {"signal": 1}])
def test_unknown_authority_is_rejected(patch):
    with pytest.raises(ValueError): patch_view(patch)


def test_restricted_floor_cannot_be_lowered_or_halt_veto_overridden():
    assert not entry_allowed({"confidence_floor": .7}, .8, .85)
    assert not entry_allowed({"veto_entry": True}, 1, .7)
    assert not entry_allowed({"size_multiplier": 0}, 1, .7)
    assert entry_allowed({"confidence_floor": .9}, .95, .85)


def test_thousand_adjustments_never_widen_stop_or_increase_size():
    rng = random.Random(804)
    for _ in range(1000):
        patch = patch_view({k: rng.uniform(*bounds) for k, bounds in BOUNDS.items()})
        stop, target, hold = tune_exits(patch, .007, .014, 20000)
        assert .0035 <= stop <= .007
        assert .014 <= target <= .028
        assert 10000 <= hold <= 21600
        assert 0 <= patch["size_multiplier"] <= 1
