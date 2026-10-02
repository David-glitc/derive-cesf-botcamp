from pathlib import Path

from scripts.validate_flyby import tasks


def test_default_validation_is_local_no_live_activation():
    stages = tasks(Path("data/new-validation"))
    assert [name for name, _ in stages] == ["host_tests", "formal_model", "formal_delta", "condor_package"]
    assert all("capture_derive" not in str(cmd) for _, cmd in stages)


def test_public_validation_is_bounded_and_does_not_publish_or_submit_orders():
    stages = tasks(Path("data/new-validation"), True, Path("data/stress-candles"), 2)
    assert len(stages) == 10
    public = [cmd for name, cmd in stages if name.startswith("public_")]
    assert len(public) == 2 and all("--samples" in cmd for cmd in public)
    assert all("--publish-shadow" not in cmd for cmd in public)
    assert not any("private" in str(cmd) or "start-bot" in str(cmd) for _, cmd in stages)


def test_condor_tick_requires_explicit_runtime_and_never_uses_live_mode():
    stages = tasks(Path("data/new-validation"), condor_root=Path("/official/condor"),
                   condor_python=Path("/official/condor/.venv/bin/python"))
    command = dict(stages)["condor_tick"]
    assert "scripts/verify_condor_runtime.py" in command
    assert "--condor-root" in command and "loop" not in command and "--activate" not in command
