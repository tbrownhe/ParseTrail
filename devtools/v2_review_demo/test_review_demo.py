"""Exercise signed imports, exact books and safe reuse of the review preparation tool."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

TOOL = Path(__file__).with_name("prepare_demo.py")


def test_prepare_reopen_and_refuse_existing_destination(tmp_path):
    destination = tmp_path / "review"
    prepared = subprocess.run(
        [sys.executable, str(TOOL), "--prepare-at", str(destination)],
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    result = json.loads(prepared.stdout)
    assert result["verification"]["source_count"] == 6
    assert result["verification"]["october_spending_minor"] == 400
    assert result["verification"]["transfer_clearing_minor"] == 10000
    profile = destination / "review.db"
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    reopened = subprocess.run(
        [sys.executable, str(TOOL), "--verify", str(destination)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(reopened.stdout) == result["verification"]
    pinned = subprocess.run(
        [
            sys.executable,
            str(destination / "runtime/devtools/v2_review_demo/prepare_demo.py"),
            "--verify",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(pinned.stdout) == result["verification"]
    startup = subprocess.run(
        [
            sys.executable,
            str(destination / "runtime/devtools/v2_review_demo/prepare_demo.py"),
            "--smoke-ui",
            str(destination),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    assert json.loads(startup.stdout)["profile_unchanged"] is True
    manifest = json.loads((destination / "runtime-manifest.json").read_text())
    assert manifest["schema_version"] == json.loads((destination / "demo.json").read_text())["schema"]
    for record in manifest["files"]:
        assert hashlib.sha256((destination / "runtime" / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    refused = subprocess.run(
        [sys.executable, str(TOOL), "--prepare-at", str(destination)], capture_output=True, text=True, timeout=60
    )
    assert refused.returncode != 0
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
    assert "FileExistsError" in refused.stderr
    assert (destination / "Open-review-demo.cmd").is_file()
    assert "last-launch.log" in (destination / "Open-review-demo.cmd").read_text()
    assert (destination / "WALKTHROUGH.txt").is_file()
    assert not list(destination.rglob("*.key"))
