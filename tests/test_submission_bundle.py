"""Structural distribution checks with redacted secret findings."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

import pytest

from scripts.build_submission import build, inspect_files, selected_files
from scripts.check_condor_package import validate_package

ROOT = Path(__file__).resolve().parents[1]


def test_condor_samples_are_identical_paused_profiles():
    assert validate_package()["structure_valid"]


def test_curated_bundle_has_runtime_without_operational_state():
    paths = selected_files()
    names = {str(p.relative_to(ROOT)) for p in paths}
    assert {"src/execution/derive_hb.py", "src/accounting/derive_margin.py", "scripts/hummingbot_compat.py",
            "controllers/directional_trading/flyby.py", "condor/flyby/AGENT.md",
            "condor/flyby/PROFILE.yml", "condor/flyby/loops/flyby_operator/loop.md",
            "scripts/install_condor.py", "scripts/verify_condor_runtime.py",
            "src/runtime/control.py", "src/runtime/bridge.py", "src/runtime/condor_adapter.py",
            "src/runtime/mcp_server.py", "src/runtime/__init__.py", "RUNTIME_OVERSIGHT.md",
            "src/runtime/observation.py", "scripts/prepare_observation_profile.py",
            "condor/profiles/flyby_observe_48h.yml",
            "SUBMISSION_POSITIONING.md", "SUBMISSION_UPDATE_CHECKLIST.md",
            "BOTCAMP_STRATEGY_DESCRIPTION.md"} <= names
    assert not any(n.startswith(("data/", ".local_harness/", "runtime/")) for n in names)
    assert not any(".env" in n or n.endswith((".jsonl", ".png", ".log")) for n in names)
    assert inspect_files(paths, ROOT)


def test_secret_scan_reports_path_without_value(tmp_path):
    path = tmp_path / "example.py"
    # Construct a fake token so this test itself doesn't contain a token match.
    path.write_text("key = '" + "sk-proj-" + "A" * 30 + "'\n")
    with pytest.raises(ValueError) as exc: inspect_files([path], tmp_path)
    assert "example.py" in str(exc.value) and "AAAA" not in str(exc.value)


def test_bundle_manifest_matches_every_source_and_never_overwrites(tmp_path):
    target = tmp_path / "submission.zip"
    result = build(target)
    assert result["submitted"] is False and result["live_ready"] is False
    with zipfile.ZipFile(target) as archive:
        m = json.loads(archive.read("flyby-submission/SUBMISSION_MANIFEST.json"))
        for name, expected in m["source_sha256"].items():
            assert hashlib.sha256(archive.read("flyby-submission/" + name)).hexdigest() == expected
        assert m["worktree_dirty"] is None or isinstance(m["worktree_dirty"], bool)
        assert m["strategy_profile_id"] == "flyby-baseline-dd15-dd25-v1"
        assert m["condor_loop_id"] == "flyby.flyby_operator"
    with pytest.raises(FileExistsError): build(target)


def test_condor_detects_config_drift_before_bundle(tmp_path):
    shutil.copytree(ROOT / "condor", tmp_path / "condor")
    shutil.copytree(ROOT / "conf", tmp_path / "conf")
    target = tmp_path / "condor/flyby/controllers/derive_cesf_long_vol/sample_configs/eth.yml"
    target.write_text(target.read_text().replace("manual_kill_switch: true", "manual_kill_switch: false"))
    with pytest.raises(ValueError, match="condor_sample_drift"): validate_package(tmp_path)
