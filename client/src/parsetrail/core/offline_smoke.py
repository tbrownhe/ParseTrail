"""Opt-in release diagnostic: real startup and synthetic local use in a disposable profile.

Only the entry point invokes this module's runner, before settings are imported.
It cannot select an existing profile or accept external statements/plugins/models.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

MODES = ("fresh", "cached", "network-failure")

PARSER_SOURCE = """
from datetime import date
from decimal import Decimal
from parsetrail.core.validation import Account, Statement, Transaction

class Parser:
    PLUGIN_NAME = "offline_fixture"
    VERSION = "1.0.0"
    MIN_CLIENT_VERSION = "1.0.0"
    SUFFIX = ".csv"
    COMPANY = "Synthetic Bank"
    STATEMENT_TYPE = "Checking"
    SEARCH_STRING = '"offline smoke"'
    INSTRUCTIONS = "Synthetic release acceptance fixture only."

    def parse(self, rows):
        transactions = [Transaction(date.fromisoformat(row[0]), date.fromisoformat(row[0]),
                                    Decimal(row[1]), row[2]) for row in rows[1:]]
        return Statement(date(2026, 1, 1), date(2026, 1, 31), [
            Account("SYNTHETIC", Decimal("1000.00"), Decimal("970.00"), transactions)
        ])
"""
STATEMENT_BYTES = (
    b"offline smoke,amount,description\n2026-01-02,-10.00,grocery apples\n2026-01-03,-20.00,electric power\n"
)


def _require(condition: object, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _install_fixture(root: Path):
    import hashlib
    import py_compile
    from datetime import datetime, timezone

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from parsetrail.core.plugin_manifest import (
        PluginArtifact,
        PluginManifest,
        current_python_magic,
        current_python_tag,
        key_id_for_public_key,
        serialize_manifest,
        verify_manifest,
    )
    from parsetrail.core.plugin_store import install_plugin_release

    source = root / "offline_fixture.py"
    source.write_text(PARSER_SOURCE, encoding="utf-8")
    compiled = root / "offline_fixture.pyc"
    py_compile.compile(str(source), cfile=str(compiled), doraise=True)
    payload = compiled.read_bytes()
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(raw)
    keys = {key_id: key.public_key()}
    artifact = PluginArtifact(
        filename=compiled.name,
        plugin_name="offline_fixture",
        version="1.0.0",
        minimum_client_version="1.0.0",
        python_tag=current_python_tag(),
        python_magic=current_python_magic(),
        size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        company="Synthetic Bank",
        statement_suffix=".csv",
        statement_type="Checking",
    )
    manifest = PluginManifest(
        release_sequence=1,
        published_at=datetime.now(timezone.utc),
        key_id=key_id,
        source_commit="a" * 40,
        artifacts=(artifact,),
    )
    data = serialize_manifest(manifest)
    release = verify_manifest(data, key.sign(data), keys)
    from parsetrail.core.settings import settings

    install_plugin_release(settings.plugin_dir, release, lambda _name: [payload])
    return keys


def _training_data():
    import pandas as pd

    return pd.DataFrame(
        [
            {"Company": "Synthetic Bank", "AccountType": "Checking", "Description": description, "Category": category}
            for description, category in [
                ("grocery apples", "Food"),
                ("grocery oranges", "Food"),
                ("grocery bread", "Food"),
                ("electric power", "Utilities"),
                ("electric meter", "Utilities"),
                ("electric bill", "Utilities"),
            ]
        ]
    )


def _exercise_local_work(window) -> None:
    from sqlalchemy import select

    from parsetrail.core import learn, orm
    from parsetrail.core.parse import parse_any
    from parsetrail.core.settings import settings
    from parsetrail.core.statements import SourceFileAction, StatementImportService

    _require(window.plugin_manager.active_release is not None, "Signed cached release was not loaded")
    _require(set(window.plugin_manager.plugins) == {"offline_fixture"}, "Cached parser was not authenticated/loaded")
    with window.Session() as session:
        account = orm.Accounts(AccountName="Synthetic Checking", AccountTypeID=1, Company="Synthetic Bank")
        session.add(account)
        session.flush()
        session.add(orm.AccountNumbers(AccountID=account.AccountID, AccountNumber="SYNTHETIC"))
        session.commit()
    statement = settings.import_dir / "synthetic.csv"
    statement.write_bytes(STATEMENT_BYTES)
    parsed = parse_any(window.plugin_manager, statement)
    _require(not parsed.diagnostics, "Synthetic statement did not validate cleanly")
    service = StatementImportService(window.Session, window.plugin_manager)
    _require(service.import_one(statement, source_action=SourceFileAction.COPY) == "success", "Local import failed")
    _require(statement.exists(), "Copy import did not preserve its source")
    with window.Session() as session:
        rows = session.scalars(select(orm.Transactions).order_by(orm.Transactions.PostingDate)).all()
        _require([row.AmountMinor for row in rows] == [-1000, -2000], "Imported amounts are incorrect")
    _require(
        service.import_one(statement, source_action=SourceFileAction.COPY) == "duplicate",
        "Duplicate import changed data",
    )
    # Verify the model present at startup, then exercise a fresh local training/save/load cycle.
    training = _training_data()
    probe = training.iloc[[0, 3]].drop(columns="Category")
    for retrain in (False, True):
        if retrain:
            learn.train_pipeline_save(training, settings.model_path)
        predicted = learn.predict(settings.model_path, probe, current_categories=["Food", "Utilities"])
        _require(predicted["Category"].tolist() == ["Food", "Utilities"], "Local model predictions are incorrect")
    window.update_main_gui()


def _session(mode: str, entrypoint: Callable[[], int], root: Path, patches: ExitStack) -> dict[str, object]:
    import requests

    state = {"ticks": 0, "paint": None, "ready": None, "pages": set(), "requests": [], "errors": [], "done": False}
    main_thread = threading.get_ident()

    def deny(*_args, **_kwargs):
        state["errors"].append("Unexpected lower-level network attempt")
        raise OSError("Offline diagnostic denies all connections")

    def fail_request(_session, method, url, **_kwargs):
        started = time.monotonic()
        ticks = state["ticks"]
        path = urlsplit(url).path
        state["requests"].append((path, threading.get_ident(), started))
        threading.Event().wait(0.4)
        if state["ticks"] - ticks < 3 or method != "GET":
            state["errors"].append("Update request blocked the GUI heartbeat or used an unexpected method")
        raise requests.ConnectionError("Synthetic offline connection failure")

    for owner, name in (
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (urllib.request, "urlopen"),
    ):
        patches.enter_context(patch.object(owner, name, deny))
    patches.enter_context(patch.object(requests.sessions.Session, "request", fail_request))

    from PySide6.QtCore import QEvent, QObject, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QWizard

    from parsetrail.core import initialize, learn
    from parsetrail.core.onboarding import CURRENT_ONBOARDING_VERSION
    from parsetrail.core.plugin_manager import PluginManager
    from parsetrail.core.plugin_manifest import load_trusted_plugin_keys
    from parsetrail.core.settings import save_settings, settings
    from parsetrail.core.utils import resource_path
    from parsetrail.gui import main_window
    from parsetrail.gui.onboarding import FirstRunGuide

    # No source-checkout resource override: this uses the actual source or frozen layout.
    for resource in ("assets/parsetrail_128px.ico", "alembic.ini", "migrations/env.py"):
        _require(resource_path(resource).is_file(), f"Missing application resource: {resource}")
    _require(load_trusted_plugin_keys(), "Bundled public trust store is missing")
    for path in (settings.config_path, settings.db_path, settings.plugin_dir, settings.model_path, settings.log_file):
        _require(path.resolve().is_relative_to(root.resolve()), "Diagnostic profile escaped its temporary directory")
    settings.automatic_update_checks = mode == "network-failure"
    save_settings(settings)
    initialize.initialize_dirs()
    if mode != "fresh":
        keys = _install_fixture(root)
        patches.enter_context(patch.object(main_window, "PluginManager", lambda: PluginManager(trusted_keys=keys)))
        learn.train_pipeline_save(_training_data(), settings.model_path)
    patches.enter_context(
        patch.object(initialize, "_prompt_for_db_path", lambda default_path, parent=None: str(default_path))
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    started = time.monotonic()
    window_holder = []

    class PaintProbe(QObject):
        def eventFilter(self, watched, event):
            if isinstance(watched, main_window.ParseTrail) and event.type() == QEvent.Paint:
                state["paint"] = state["paint"] or time.monotonic()
            return False

    probe = PaintProbe(app)
    app.installEventFilter(probe)

    def tick():
        state["ticks"] += 1
        try:
            _require(time.monotonic() - started < 35, "Offline GUI session timed out")
            for widget in app.topLevelWidgets():
                if not widget.isVisible():
                    continue
                if isinstance(widget, QMessageBox):
                    _require(widget.windowTitle() == "New Database Created", "Unexpected startup message")
                    widget.accept()
                elif isinstance(widget, FirstRunGuide):
                    state["pages"].add(widget.currentId())
                    button = QWizard.FinishButton if widget.currentPage().isFinalPage() else QWizard.NextButton
                    widget.button(button).click()
                elif isinstance(widget, main_window.ParseTrail) and hasattr(widget, "Session"):
                    if not window_holder:
                        window_holder.append(widget)
                elif isinstance(widget, QDialog):
                    raise RuntimeError("Unexpected startup dialog")
            if not window_holder or settings.onboarding_version != CURRENT_ONBOARDING_VERSION:
                return
            window = window_holder[0]
            if state["ready"] is None:
                state["ready"] = time.monotonic()
            if time.monotonic() - state["ready"] < main_window.AUTOMATIC_UPDATE_DELAY_MS / 1000 + 1.5:
                return
            if any(
                getattr(window, name, None) and getattr(window, name).isRunning()
                for name in ("client_update_thread", "plugin_update_thread")
            ):
                return
            _require(
                state["paint"] is not None and len(state["pages"]) == 5,
                "Startup/onboarding did not paint all expected pages",
            )
            _require(not state["errors"], str(state["errors"]))
            if mode == "network-failure":
                expected_paths = {f"/api/v1/clients/{settings.platform}/manifest", "/api/v1/plugins/manifest"}
                _require(
                    {item[0] for item in state["requests"]} == expected_paths, "Unexpected background update requests"
                )
                _require(
                    all(thread != main_thread and when > state["paint"] for _, thread, when in state["requests"]),
                    "Networking started before paint or on the GUI thread",
                )
                _require(
                    min(when for _, _, when in state["requests"])
                    >= state["ready"] + main_window.AUTOMATIC_UPDATE_DELAY_MS / 1000 - 0.2,
                    "Automatic networking started before its configured delay",
                )
            else:
                _require(not state["requests"], "Disabled update checks attempted networking")
            timer.stop()  # update_main_gui processes events; prevent a reentrant import.
            if mode == "fresh":
                _require(
                    not window.plugin_manager.plugins and not settings.model_path.exists(),
                    "Fresh profile contains unexpected prerequisites",
                )
            else:
                _exercise_local_work(window)
            _require(not state["errors"], str(state["errors"]))
            state["done"] = True
            timer.stop()
            window.close()
            app.exit(0)
        except Exception as exc:
            state["errors"].append(str(exc))
            timer.stop()
            app.exit(1)

    timer = QTimer(app)
    timer.timeout.connect(tick)
    timer.start(25)
    # main() still owns icon setup, UI hooks, real window construction, and app.exec().
    entry_module = sys.modules[entrypoint.__module__]
    patches.enter_context(patch.object(entry_module, "QApplication", lambda _argv: app))
    try:
        entrypoint()
    except SystemExit as exc:
        _require(exc.code in (None, 0), f"Client entry point exited with {exc.code}: {state['errors']}")
    finally:
        timer.stop()
        for window in window_holder:
            for name in ("client_update_thread", "plugin_update_thread"):
                worker = getattr(window, name, None)
                if worker is not None:
                    worker.wait(2000)
            window.close()
        app.closeAllWindows()
        from parsetrail.core.logging import logger

        logger.remove()
    _require(state["done"] and not state["errors"], f"Offline session did not complete: {state['errors']}")
    _require(not app.windowIcon().isNull(), "Application icon resource did not load")
    saved = json.loads(settings.config_path.read_text(encoding="utf-8"))
    _require(saved["onboarding_version"] == CURRENT_ONBOARDING_VERSION, "Onboarding completion did not persist")
    return {
        "mode": mode,
        "passed": True,
        "frozen": bool(getattr(sys, "frozen", False)),
        "onboarding_pages": len(state["pages"]),
        "heartbeat_ticks": state["ticks"],
        "network_requests": len(state["requests"]),
        "local_import_and_model": mode != "fresh",
    }


def run_offline_session_smoke(mode: str, entrypoint: Callable[[], int], *, report_path: Path | None = None) -> int:
    if mode not in MODES or "parsetrail.core.settings" in sys.modules:
        return 2
    try:
        if report_path is not None:
            report_path = report_path.expanduser().resolve()
            _require(
                not report_path.exists() and report_path.parent.is_dir(),
                "Report requires a new file in an existing directory",
            )
        with tempfile.TemporaryDirectory(prefix="parsetrail-offline-") as temporary, ExitStack() as patches:
            root = Path(temporary)
            keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
            env = {
                name: value
                for name, value in os.environ.items()
                if name.upper() in keep or name.startswith(("_PYI", "QT_"))
            }
            env.update(
                {
                    "HOME": str(root),
                    "USERPROFILE": str(root),
                    "QT_QPA_PLATFORM": "offscreen",
                    "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
                }
            )
            patches.enter_context(patch.dict(os.environ, env, clear=True))
            try:
                report = _session(mode, entrypoint, root, patches)
            finally:
                from loguru import logger

                logger.remove()
    except Exception as exc:
        report = {"mode": mode, "passed": False, "error": f"{type(exc).__name__}: {exc}"}
        if sys.stderr is not None:
            print(f"Offline session smoke failed: {report['error']}", file=sys.stderr)
    try:
        if report_path is not None:
            with report_path.open("x", encoding="utf-8") as output:
                output.write(json.dumps(report, sort_keys=True) + "\n")
        if sys.stdout is not None:
            print(json.dumps(report, sort_keys=True))
    except OSError:
        return 1
    return 0 if report["passed"] else 1
