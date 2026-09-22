import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _run_probe(command, *, report_file, timeout=75, **kwargs):
    def diagnostic_tail():
        log = report_file.with_name(report_file.name + ".log")
        return log.read_text(encoding="utf-8")[-16000:] if log.exists() else "No diagnostic log was created."

    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired carries bytes even with text=True. Expose the child output
        # and independent stack dump instead of pytest's truncated exception repr.
        stderr = exc.stderr or b""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        pytest.fail(
            f"Offline probe exceeded {timeout}s.\nChild stderr:\n{stderr[-8000:]}\n"
            f"Progress / stack dump:\n{diagnostic_tail()}",
            pytrace=False,
        )
    if completed.returncode != 0:
        completed.stderr += "\nProgress / stack dump:\n" + diagnostic_tail()
    return completed


@pytest.mark.parametrize(
    ("mode", "untitled_message"),
    [("fresh", False), ("cached", False), ("network-failure", False), ("fresh", True)],
    ids=["fresh", "cached", "network-failure", "untitled-message"],
)
def test_real_entrypoint_offline_session_ignores_existing_profile(tmp_path, mode, untitled_message):
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
    command = [sys.executable, "src/parsetrail/main.py"]
    if untitled_message:
        # Qt's QMessageBox::setWindowTitle is a no-op on macOS. Simulate that
        # observable behavior on every host while retaining the real startup.
        command = [
            sys.executable,
            "-c",
            "import runpy, sys; from PySide6.QtWidgets import QMessageBox; "
            "QMessageBox.windowTitle = lambda self: ''; "
            "sys.argv[0] = 'src/parsetrail/main.py'; runpy.run_path(sys.argv[0], run_name='__main__')",
        ]
    completed = _run_probe(
        command
        + [
            "--offline-session-smoke-test",
            mode,
            "--offline-smoke-report",
            str(report_file),
        ],
        report_file=report_file,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
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


@pytest.mark.parametrize("dialog_type", ["dialog", "message"])
def test_startup_failure_unwinds_modal_dialogs_before_main_event_loop(tmp_path, dialog_type):
    report = tmp_path / "failure.json"
    completed = _run_probe(
        [
            sys.executable,
            "-c",
            """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from parsetrail.core.offline_smoke import run_offline_session_smoke

def entrypoint():
    app = QApplication(sys.argv)
    # Constructors can open another modal after the first one returns. Neither
    # that nested loop nor the subsequent main loop may lose the failed result.
    for title in ("Unexpected startup dialog", "Subsequent startup dialog"):
        if sys.argv[2] == "message":
            dialog = QMessageBox(QMessageBox.Critical, "New Database Created", "Synthetic startup failure")
        else:
            dialog = QDialog()
            dialog.setWindowTitle(title)
        dialog.exec()
    raise SystemExit(app.exec())

raise SystemExit(run_offline_session_smoke("fresh", entrypoint, report_path=Path(sys.argv[1])))
""",
            str(report),
            dialog_type,
        ],
        report_file=report,
    )
    assert completed.returncode == 1, completed.stderr
    result = json.loads(report.read_bytes())
    assert result["passed"] is False
    expected_error = "Unexpected startup dialog" if dialog_type == "dialog" else "Unexpected startup message"
    assert expected_error in result["error"]
    log = report.with_name(report.name + ".log").read_text(encoding="utf-8")
    assert f"GUI failure: {expected_error}" in log
    assert "entering main event loop" not in log


def test_stack_dump_does_not_depend_on_gui_event_loop(tmp_path):
    report = tmp_path / "watchdog.json"
    completed = _run_probe(
        [
            sys.executable,
            "-c",
            """
import sys
import threading
from pathlib import Path
from parsetrail.core import offline_smoke

offline_smoke.STACK_DUMP_SECONDS = 0.1
with offline_smoke._Diagnostics(Path(sys.argv[1])) as diagnostics:
    diagnostics.mark("deliberately stalled without Qt")
    threading.Event().wait(0.3)
""",
            str(report),
        ],
        report_file=report,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    log = report.with_name(report.name + ".log").read_text(encoding="utf-8")
    assert "deliberately stalled without Qt" in log
    assert "Timeout" in log
    assert "threading.py" in log


def test_diagnostic_log_cannot_overwrite_an_existing_file(tmp_path):
    report = tmp_path / "report.json"
    log = tmp_path / "report.json.log"
    log.write_bytes(b"preserve diagnostic evidence")
    completed = _run_probe(
        [
            sys.executable,
            "src/parsetrail/main.py",
            "--offline-session-smoke-test",
            "fresh",
            "--offline-smoke-report",
            str(report),
        ],
        report_file=report,
        timeout=15,
    )
    assert completed.returncode == 1
    assert log.read_bytes() == b"preserve diagnostic evidence"
    assert json.loads(report.read_bytes())["passed"] is False
