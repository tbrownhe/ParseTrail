import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from parsetrail.core.cluster import preprocess_text
from parsetrail.core.english_stopwords import ENGLISH_STOP_WORDS
from parsetrail.core.settings import settings
from parsetrail.gui import main_window


def test_bundled_stopwords_are_stable_and_need_no_corpus() -> None:
    assert len(ENGLISH_STOP_WORDS) == 178
    assert preprocess_text("We're not doing this payment at the store") == "payment store"
    assert preprocess_text("Keep every word", stopwords=set()) == "keep every word"


def test_extra_stopwords_use_the_same_normalization() -> None:
    assert preprocess_text("CARD-PAYMENT market", stopwords={"cardpayment"}) == "market"


def test_automatic_update_check_is_optional_and_delayed(monkeypatch) -> None:
    scheduled: list[tuple[int, object]] = []
    receiver = SimpleNamespace(check_for_client_updates_async=object())
    monkeypatch.setattr(
        main_window.QTimer,
        "singleShot",
        lambda delay, callback: scheduled.append((delay, callback)),
    )

    monkeypatch.setattr(settings, "automatic_update_checks", True)
    main_window.ParseTrail.schedule_automatic_update_check(receiver)
    assert scheduled == [(main_window.AUTOMATIC_UPDATE_DELAY_MS, receiver.check_for_client_updates_async)]
    assert scheduled[0][0] > 0

    scheduled.clear()
    monkeypatch.setattr(settings, "automatic_update_checks", False)
    main_window.ParseTrail.schedule_automatic_update_check(receiver)
    assert scheduled == []


def test_importing_every_client_module_attempts_no_network(tmp_path: Path) -> None:
    client_root = Path(__file__).parents[1]
    code = """
import importlib
import pkgutil
import socket
import urllib.request

calls = []
def deny(*args, **kwargs):
    calls.append((args, kwargs))
    raise AssertionError("network access during module import")

socket.create_connection = deny
socket.getaddrinfo = deny
socket.socket.connect = deny
urllib.request.urlopen = deny

import requests
requests.sessions.Session.request = deny

import parsetrail
for module in pkgutil.walk_packages(parsetrail.__path__, parsetrail.__name__ + "."):
    importlib.import_module(module.name)

if calls:
    raise AssertionError(f"network functions were called {len(calls)} time(s)")
print("offline imports ok")
"""
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "QT_QPA_PLATFORM": "offscreen",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=client_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "offline imports ok" in result.stdout


def test_first_launch_initializes_offline_with_a_fresh_database(tmp_path: Path) -> None:
    client_root = Path(__file__).parents[1]
    code = """
from pathlib import Path
import socket
import sys
import urllib.request

network_calls = []
def deny(*args, **kwargs):
    network_calls.append((args, kwargs))
    raise AssertionError("network access during first launch")

socket.create_connection = deny
socket.getaddrinfo = deny
socket.socket.connect = deny
urllib.request.urlopen = deny

import requests
requests.sessions.Session.request = deny

from PySide6.QtWidgets import QApplication, QMessageBox
from sqlalchemy import text
from parsetrail.core import initialize
from parsetrail.core.settings import settings
from parsetrail.gui.main_window import ParseTrail

db_path = Path.home() / "Documents" / "ParseTrail" / "offline-startup.db"
initialize._prompt_for_db_path = lambda default_path, parent=None: str(db_path)

dialogs = []
QMessageBox.information = lambda *args, **kwargs: dialogs.append("information")
QMessageBox.warning = lambda *args, **kwargs: dialogs.append("warning")
QMessageBox.critical = lambda *args, **kwargs: dialogs.append("critical")

app = QApplication([])
try:
    window = ParseTrail()
except Exception:
    sys.excepthook = sys.__excepthook__
    raise
app.processEvents()

assert settings.db_path == db_path.resolve()
assert db_path.exists()
with window.Session() as session:
    assert session.execute(text("SELECT 1")).scalar_one() == 1
assert "critical" not in dialogs
assert not network_calls

window.close()
app.quit()
print("offline first launch ok")
"""
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "QT_QPA_PLATFORM": "offscreen",
        }
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=client_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "offline first launch ok" in result.stdout
