import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["fresh", "cached", "network-failure"])
def test_real_entrypoint_offline_session_ignores_existing_profile(tmp_path, mode):
    # A settings environment override must never redirect this diagnostic into
    # the operator's existing database, profile, or credential backend.
    canary = tmp_path / "existing.db"
    canary.write_bytes(b"existing data must be untouched")
    report_file = tmp_path / "report.json"
    env = os.environ | {
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "DB_PATH": str(canary),
        "PLUGIN_DIR": str(tmp_path / "plugins"),
        "MODEL_PATH": str(canary),
        "SERVER_URL": "https://unreachable.example.invalid/api/v1",
        "PARSETRAIL_PROFILE": "invalid-profile",
        "PYTHON_KEYRING_BACKEND": "invalid.backend",
        "QT_QPA_PLATFORM": "offscreen",
    }
    completed = subprocess.run(
        [
            sys.executable,
            "src/parsetrail/main.py",
            "--offline-session-smoke-test",
            mode,
            "--offline-smoke-report",
            str(report_file),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=75,
    )
    assert completed.returncode == 0, completed.stderr[-5000:]
    report = json.loads(completed.stdout.splitlines()[-1])
    assert json.loads(report_file.read_bytes()) == report
    assert report["passed"] is True
    assert report["frozen"] is False
    assert report["mode"] == mode
    assert report["onboarding_pages"] == 5
    assert report["heartbeat_ticks"] > 30
    assert report["network_requests"] == (2 if mode == "network-failure" else 0)
    assert report["local_import_and_model"] is (mode != "fresh")
    assert canary.read_bytes() == b"existing data must be untouched"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["existing.db", "report.json"]


def test_diagnostic_report_cannot_overwrite_an_existing_file(tmp_path):
    report = tmp_path / "existing.json"
    report.write_bytes(b"preserve me")
    completed = subprocess.run(
        [
            sys.executable,
            "src/parsetrail/main.py",
            "--offline-session-smoke-test",
            "fresh",
            "--offline-smoke-report",
            str(report),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 1
    assert report.read_bytes() == b"preserve me"


def test_offline_diagnostic_cannot_reuse_already_loaded_settings():
    # Other suite modules have already imported the isolated pytest settings.
    import parsetrail.core.settings  # noqa: F401
    from parsetrail.core.offline_smoke import run_offline_session_smoke

    assert run_offline_session_smoke("fresh", lambda: pytest.fail("Must not run with loaded settings")) == 2
