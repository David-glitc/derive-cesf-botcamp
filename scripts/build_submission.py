"""Curated local review archive with source hashes; no git writes or upload."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.check_condor_package import validate_package
from scripts.check_mainnet import validate_profiles

ROOT_FILES = ("README.md", "strategy.md", "FLYBY_spec.md", "MAINNET_SETUP.md", "COMPETITION_READINESS.md",
              "OPTIONS_EXECUTION.md", "RUNTIME_OVERSIGHT.md",
              "SUBMISSION_ARTIFACT.md", "SUBMISSION_UPDATE_CHECKLIST.md", "SUBMISSION_POSITIONING.md",
              "BOTCAMP_STRATEGY_DESCRIPTION.md",
              "hummingbot-version.json", "pyproject.toml", "requirements.txt")
SCRIPTS = ("install_hummingbot.sh", "check_mainnet.py", "hummingbot_compat.py", "test_hummingbot.sh",
           "check_condor_package.py", "install_condor.py", "verify_condor_runtime.py",
           "build_submission.py", "inspect_market_rules.py", "install_derive_v3.py", "upgrade_condor.py", "check_derive_v3_public.py",
           "prepare_competition_profile.py",
           "prepare_observation_profile.py",
           "capture_derive_public.py", "validate_flyby.py")
TREES = {"agents": {".py"}, "src": {".py"}, "conf": {".yml"},
         "vendor/derive_v3": {".py", ".json"},
         "condor": {".md", ".py", ".yml"}, "tests": {".py"}, "verification": {".md", ".py"},
         "reports": {".md"}, "backtest": {".md", ".py"}}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"(?:sk-proj-|sk-ant-api03-)[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"(?i)(?:session_private_key|private_key|api_secret|cloudflare_api_token)\s*[:=]\s*['\"]?(?:0x)?[a-f0-9]{64}"),
)


def selected_files(root=ROOT):
    selected = {root / name for name in ROOT_FILES}
    selected.update(root / "scripts" / name for name in SCRIPTS)
    selected.add(root / "vendor/derive_v3/LICENSE")
    for directory, suffixes in TREES.items():
        selected.update(p for p in (root / directory).rglob("*") if p.suffix in suffixes and "__pycache__" not in p.parts)
    for path in selected:
        if path.is_symlink() or not path.is_file() or root.resolve() not in path.resolve().parents:
            raise ValueError(f"invalid_submission_path:{path.relative_to(root)}")
    return sorted(selected)


def inspect_files(paths, root):
    hashes = {}
    for path in paths:
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET_PATTERNS):
            # Never print matched credential values.
            raise ValueError(f"possible_secret_in_submission:{path.relative_to(root)}")
        hashes[str(path.relative_to(root))] = hashlib.sha256(data).hexdigest()
    return hashes


def git_metadata(root):
    """Optional provenance: extracted archives don't have .git; hashes remain truth."""
    if not (root / ".git").exists():
        return None, None
    # Trust only this explicitly selected checkout, never global git config.
    command = ["git", "-c", f"safe.directory={root.resolve()}"]
    head = subprocess.run(command + ["rev-parse", "HEAD"], cwd=root, text=True, capture_output=True)
    state = subprocess.run(command + ["status", "--porcelain"], cwd=root, text=True, capture_output=True)
    if head.returncode or state.returncode or not re.fullmatch(r"[a-f0-9]{40}", head.stdout.strip()):
        return None, None
    return head.stdout.strip(), bool(state.stdout)


def build(output, root=ROOT):
    validate_profiles(root)
    identity = validate_package(root)
    paths = selected_files(root)
    hashes = inspect_files(paths, root)
    head, dirty = git_metadata(root)
    manifest = {"schema": 1, "kind": "flyby_submission_candidate", "base_commit": head,
        "worktree_dirty": dirty, "artifact_identity": "file hashes, NOT the base commit when dirty",
        "submission_deadline_utc": "2026-10-04T00:00:00Z", "source_sha256": hashes,
        "condor": identity, "live_ready": False, "profitability_proven": False, "submitted": False,
        "strategy_profile_id": identity["profile_id"], "condor_loop_id": identity["loop_id"],
        "secret_scan": "bounded pattern scan passed; not a comprehensive security audit",
        "excludes": ["credentials", "runtime/account state", "raw traces", "old testnet harness", "images", "git metadata"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(hashes):
            payload = (root / name).read_bytes()
            if hashlib.sha256(payload).hexdigest() != hashes[name]:
                raise ValueError("source_changed_during_bundle")
            info = zipfile.ZipInfo("flyby-submission/" + name, date_time=(2026, 10, 2, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
        archive.writestr(zipfile.ZipInfo("flyby-submission/SUBMISSION_MANIFEST.json", (2026, 10, 2, 0, 0, 0)),
                         json.dumps(manifest, indent=2, sort_keys=True))
    return {"archive": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "files": len(hashes), "base_commit": head, "worktree_dirty": dirty,
            "live_ready": False, "submitted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))


if __name__ == "__main__":
    main()
