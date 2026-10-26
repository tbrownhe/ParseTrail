"""Disposable V2 runtime diagnostics require no checkout fixtures or legacy setup."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode,action", [("fresh", "create"), ("cached", "open"), ("network-failure", "restore")])
def test_embedded_diagnostic_exercises_v2_without_checkout_resources(tmp_path, mode, action):
    report = tmp_path / "report.json"
    legacy = tmp_path / "owner-canary.db"
    legacy.write_bytes(b"never inspect or modify this canary")
    env = os.environ | {
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "DB_PATH": str(legacy),
        "PARSETRAIL_PROFILE": "invalid-legacy-profile",
        "PLUGIN_DIR": str(legacy),
        "MODEL_PATH": str(legacy),
        "SERVER_URL": "https://unreachable.example.invalid/api/v1",
        "PYTHON_KEYRING_BACKEND": "invalid.backend",
    }
    code = """
import sys
from pathlib import Path
from parsetrail.main import run_v2_workspace
from parsetrail.core.v2_offline_smoke import run_offline_session_smoke
raise SystemExit(run_offline_session_smoke(sys.argv[1],lambda:run_v2_workspace(["--v2"]),report_path=Path(sys.argv[2])))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, mode, str(report)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=75,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    result = json.loads(report.read_text())
    assert result == json.loads(completed.stdout.splitlines()[-1])
    assert result["passed"] and result["runtime"] == "v2" and result["schema_version"] == 2
    assert result["mode"] == mode and result["chooser_action"] == action
    assert result["network_requests"] == 0 and result["display_suppressed"]
    assert result["ui_responsive"] and result["heartbeat_ticks"] >= 35
    assert all(result["paint_events"].values())
    assert set(result["first_paint_ms"]) == set(result["paint_events"])
    assert result["total_elapsed_seconds"] >= result["elapsed_seconds"]
    assert result["local_import_and_review"] and result["import_retry"]
    assert result["reviewed_expense_minor"] == 5743 and result["backup_reopen_recovery"]
    assert legacy.read_bytes() == b"never inspect or modify this canary"
    assert {path.name for path in tmp_path.iterdir()} == {"report.json", "owner-canary.db"}


@pytest.mark.parametrize("failure", ["network", "dialog"])
def test_v2_diagnostic_refuses_network_attempts_and_unwinds_unexpected_modal_loops(tmp_path, failure):
    report = tmp_path / "failure.json"
    code = """
import sys,socket
from pathlib import Path
from PySide6.QtWidgets import QApplication,QDialog
from parsetrail.main import run_v2_workspace
from parsetrail.core.v2_offline_smoke import run_offline_session_smoke
def entrypoint():
    if sys.argv[2]=="network":
        try:socket.getaddrinfo("unreachable.example.invalid",443)
        except OSError:pass
        return run_v2_workspace(["--v2"])
    app=QApplication.instance()
    for _ in range(2):QDialog().exec()
    return app.exec()
raise SystemExit(run_offline_session_smoke("fresh",entrypoint,report_path=Path(sys.argv[1])))
"""
    env = os.environ | {"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", code, str(report), failure],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 1, completed.stderr + completed.stdout
    result = json.loads(report.read_text())
    assert not result["passed"] and result["runtime"] == "v2"
    if failure == "network":
        assert result["network_requests"] == 1 and "network" in result["error"]
    else:
        assert "Unexpected startup" in result["error"]
    assert report.with_name(report.name + ".log").is_file()


def test_diagnostic_refuses_preexisting_qapplication_without_driving_or_closing_windows(tmp_path):
    report = tmp_path / "failure.json"
    code = """
import sys,json
from pathlib import Path
from PySide6.QtWidgets import QApplication,QWidget
from parsetrail.core.v2_offline_smoke import run_offline_session_smoke
app=QApplication([])
window=QWidget();window.show()
def unexpected():raise AssertionError("Must not drive a preexisting application")
code=run_offline_session_smoke("fresh",unexpected,report_path=Path(sys.argv[1]))
assert code==1 and window.isVisible()
assert "existing QApplication" in json.loads(Path(sys.argv[1]).read_text())["error"]
window.close()
"""
    env = os.environ | {"QT_QPA_PLATFORM": "offscreen", "PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", code, str(report)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr


def test_diagnostic_report_created_during_session_refuses_publication_without_overwriting(tmp_path):
    report = tmp_path / "collision.json"
    code = """
import sys
from pathlib import Path
from unittest.mock import patch
from parsetrail.core.v2_offline_smoke import run_offline_session_smoke
report=Path(sys.argv[1])
other_writer=b'{"unrelated_report":true}\\n'
def session(*args):
    report.write_bytes(other_writer)
    return {"passed":True,"runtime":"v2","mode":"fresh"}
with patch("parsetrail.core.v2_offline_smoke._session",side_effect=session) as run:
    result=run_offline_session_smoke("fresh",lambda:0,report_path=report)
assert run.call_count==1 and result==1
assert report.read_bytes()==other_writer
assert report.with_name(report.name+".log").is_file()
"""
    env = os.environ | {"PYTHONPATH": str(Path(__file__).parents[1] / "src")}
    completed = subprocess.run(
        [sys.executable, "-c", code, str(report)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    assert "V2 diagnostic report could not be written: FileExistsError" in completed.stderr
    assert not completed.stdout.strip()
