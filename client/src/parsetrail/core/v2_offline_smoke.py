"""Explicit disposable V2 startup diagnostic; never a production trust override."""

from __future__ import annotations

import base64
import faulthandler
import hashlib
import json
import os
import socket
import sys
import tempfile
import time
import traceback
from collections.abc import Callable
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch

MODES = ("fresh", "cached", "network-failure")
GUI_TIMEOUT_SECONDS = 35
STACK_DUMP_SECONDS = 60
DEFINITION = json.dumps(
    {
        "schema_version": 1,
        "parser_id": "v2_offline_cash_fixture",
        "revision": "1",
        "suffix": ".csv",
        "kind": "activity_export",
        "capabilities": ["table_rows_v1"],
        "header": ["Date", "Account", "Description", "Amount", "ReportedBalance"],
        "columns": {
            "account": "Account",
            "date": "Date",
            "description": "Description",
            "total": "Amount",
            "balance": "ReportedBalance",
        },
        "date_format": "MM/DD/YYYY",
        "date_role": "posting_date",
        "money_format": "usd_symbol_2dp",
        "unknown_balance_literals": ["Unavailable"],
    },
    sort_keys=True,
).encode()
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Reviewed receipt,$1200.00,Unavailable\n"
    b"10/02/2026,Checking A,Groceries,-$57.43,Unavailable\n"
)


def _require(condition, message):
    if not condition:
        raise RuntimeError(message)


class _Diagnostics:
    """Progress and a stack timer remain available if Qt stops responding."""

    def __init__(self, report_path):
        self.path = report_path.with_name(report_path.name + ".log") if report_path else None
        self.stream = None
        self.started = time.monotonic()

    def __enter__(self):
        self.stream = self.path.open("x", encoding="utf-8") if self.path else sys.stderr
        _require(self.stream is not None, "Windowed diagnostics require --offline-smoke-report")
        faulthandler.dump_traceback_later(STACK_DUMP_SECONDS, file=self.stream)
        self.mark("starting isolated V2 diagnostic")
        return self

    def mark(self, stage):
        print(f"V2 offline diagnostic +{time.monotonic() - self.started:.2f}s: {stage}", file=self.stream, flush=True)

    def __exit__(self, exc_type, exc, tb):
        faulthandler.cancel_dump_traceback_later()
        if exc is not None:
            traceback.print_exception(exc_type, exc, tb, file=self.stream)
        if self.path:
            self.stream.close()


def _fixture_release(root):
    """The private test key stays in memory; only public trust enters the workspace."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from parsetrail.core.v2_data_catalog import key_id_for_public_key

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": "a" * 40,
            "key_id": key_id,
            "definitions": [
                {
                    "parser_id": "v2_offline_cash_fixture",
                    "revision": "1",
                    "suffix": ".csv",
                    "size": len(DEFINITION),
                    "sha256": hashlib.sha256(DEFINITION).hexdigest(),
                    "content_base64": base64.b64encode(DEFINITION).decode("ascii"),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    release = root / "fixture-release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(private.sign(snapshot))
    return release, {key_id: public}


def _deny_network(patches, attempts):
    import http.client
    import urllib.request

    import requests.sessions
    from PySide6.QtNetwork import QNetworkAccessManager

    def deny(*_args, **_kwargs):
        attempts.append("blocked network API")
        raise OSError("V2 diagnostic forbids every network attempt")

    for owner, attribute in (
        (socket, "create_connection"),
        (socket, "getaddrinfo"),
        (socket.socket, "connect"),
        (socket.socket, "connect_ex"),
        (socket.socket, "sendto"),
        (urllib.request, "urlopen"),
        (requests.sessions.Session, "request"),
        (http.client.HTTPConnection, "connect"),
        (http.client.HTTPSConnection, "connect"),
        *(
            (QNetworkAccessManager, method)
            for method in ("get", "post", "put", "head", "deleteResource", "sendCustomRequest", "createRequest")
        ),
    ):
        patches.enter_context(patch.object(owner, attribute, deny))


def _local_work(window, root, release, diagnostics, app, result):
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import QMessageBox

    from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog

    work = window.workspace
    diagnostics.mark("verify local signed catalog and import/retry embedded CSV")
    work.install_catalog_release(release)
    _require(work.catalog_cache.load_current() is not None, "Signed catalog was not cached")
    statement = root / "synthetic.csv"
    statement.write_bytes(SOURCE)
    imported = work.import_file(statement)
    retry = work.import_file(statement)
    _require(
        imported.status == "imported" and retry.status == "already_imported", "Import/retry did not preserve one source"
    )
    with V2ProfileStore.open(work.profile_path) as store:
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.bind_source_account(imported.source_sha256, "Checking A", "opaque", "cash")
    window.refresh(select_source=imported.source_sha256)
    diagnostics.mark("exercise actual expense review and report widgets")
    cash = V2CashActivityReview(work.profile_path, imported.source_sha256, window)
    cash.setAttribute(Qt.WA_DontShowOnScreen)
    cash.show()
    cash.table.selectRow(next(index for index, row in enumerate(cash.model.rows) if row.amount_minor == -5743))
    cash.purpose.setCurrentIndex(cash.purpose.findData("expense"))
    cash.category.setCurrentIndex(cash.category.findData("expense:food"))
    cash.reason.setText("Explicit synthetic offline expense review")
    app.processEvents()
    _require(cash.action_button.isEnabled(), "Expense review did not become actionable")
    with patch.object(QMessageBox, "question", lambda *_args: QMessageBox.Yes):
        cash.action_button.click()
    _require(cash._current().entry_key is not None, "Expense review did not persist")
    cash.close()
    reports = V2ReviewedReportsDialog(work.profile_path, window)
    reports.setAttribute(Qt.WA_DontShowOnScreen)
    reports.start.setDate(QDate(2026, 10, 1))
    reports.end.setDate(QDate(2026, 11, 1))
    reports.show()
    app.processEvents()
    with V2ProfileStore.open(work.profile_path, read_only=True) as store:
        summary = store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1))
        _require(summary.total_minor == 5743, "Reviewed expense is not exact")
        _require(len(store.source_ids()) == 1, "Source retry duplicated evidence")
    reports.close()
    diagnostics.mark("verify backup/reopen and immutable original recovery")
    backup, restored = root / "backup.dbb", root / "restored.db"
    V2ProfileStore.snapshot_to(work.profile_path, backup)
    V2ProfileStore.snapshot_to(backup, restored)
    reopened = V2Workspace.open(
        restored,
        work.catalog_cache.root,
        trusted_keys=work.catalog_cache.trusted_keys,
        preferences_path=work.preferences_path,
    )
    recovery = root / "recovered.csv"
    reopened.recover_source_original(imported.source_sha256, recovery)
    _require(recovery.read_bytes() == SOURCE, "Recovered original differs")
    with V2ProfileStore.open(restored, read_only=True) as store:
        _require(
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 5743,
            "Backup/reopen lost the reviewed entry",
        )
    result.update(
        local_catalog=True,
        local_import_and_review=True,
        import_retry=True,
        reviewed_expense_minor=5743,
        backup_reopen_recovery=True,
    )


def _session(mode, entrypoint, root, patches, diagnostics, attempts):
    from PySide6.QtCore import QEvent, QObject, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_profile_startup import V2ProfileStartupDialog
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    _require(QApplication.instance() is None, "V2 diagnostic requires a fresh process without an existing QApplication")
    release, keys = _fixture_release(root)
    catalog, prefs, profile = root / "catalog", root / "preferences.json", root / "profile.db"
    action = {"fresh": "create", "cached": "open", "network-failure": "restore"}[mode]
    if mode != "fresh":
        cached = V2Workspace.create(profile, catalog, trusted_keys=keys, preferences_path=prefs)
        cached.install_catalog_release(release)
        if mode == "network-failure":
            V2ProfileStore.snapshot_to(profile, root / "startup-backup.dbb")
            profile = root / "startup-restored.db"
    _deny_network(patches, attempts)
    result = {
        "schema_version": 2,
        "runtime": "v2",
        "mode": mode,
        "frozen": bool(getattr(sys, "frozen", False)),
        "profile": "temporary",
        "chooser_action": action,
        "display_suppressed": True,
        "network_policy": "all attempts denied; V2 has no remote catalog channel",
        "timing_scope": "Observed GUI event loop after diagnostic/fixture setup; not a cold-process startup benchmark",
    }
    original_startup, original_window = V2ProfileStartupDialog.__init__, V2WorkspaceWindow.__init__

    def startup_init(dialog, _catalog, **kwargs):
        kwargs.update(trusted_keys=keys, preferences_path=prefs)
        original_startup(dialog, catalog, **kwargs)
        dialog.setAttribute(Qt.WA_DontShowOnScreen)

    def window_init(window, *args, **kwargs):
        original_window(window, *args, **kwargs)
        window.setAttribute(Qt.WA_DontShowOnScreen)

    patches.enter_context(patch.object(V2ProfileStartupDialog, "__init__", startup_init))
    patches.enter_context(patch.object(V2WorkspaceWindow, "__init__", window_init))
    patches.enter_context(patch.object(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(profile), "")))
    selected = root / "startup-backup.dbb" if mode == "network-failure" else profile
    patches.enter_context(patch.object(QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(selected), "")))
    app = QApplication(sys.argv[:1])
    app.setQuitOnLastWindowClosed(False)
    started = time.monotonic()
    state = {
        "chosen": False,
        "worked": False,
        "working": False,
        "error": None,
        "ticks": 0,
        "last": started,
        "max_gap": 0.0,
    }
    paints = {"chooser": 0, "workspace": 0, "cash_review": 0, "reports": 0}
    first_paint_ms = {}

    class Paints(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Paint:
                name = {
                    "V2ProfileStartupDialog": "chooser",
                    "V2WorkspaceWindow": "workspace",
                    "V2CashActivityReview": "cash_review",
                    "V2ReviewedReportsDialog": "reports",
                }.get(type(watched).__name__)
                if name:
                    paints[name] += 1
                    first_paint_ms.setdefault(name, round((time.monotonic() - started) * 1000, 2))
            return False

    observer = Paints()
    app.installEventFilter(observer)

    def heartbeat():
        now = time.monotonic()
        state["max_gap"] = max(state["max_gap"], now - state["last"])
        state["last"] = now
        state["ticks"] += 1

    def fail(message):
        state["error"] = state["error"] or message
        diagnostics.mark("GUI failure: " + state["error"])
        for widget in app.topLevelWidgets():
            if isinstance(widget, QDialog):
                widget.reject()
            else:
                widget.close()
        app.exit(1)

    def inspect():
        if state["working"]:
            modal = app.activeModalWidget()
            if isinstance(modal, QMessageBox):
                fail("Unexpected startup message during local review")
            return
        if state["error"]:
            fail(state["error"])
            return
        try:
            _require(time.monotonic() - started < GUI_TIMEOUT_SECONDS, "V2 GUI diagnostic timed out")
            visible = [widget for widget in app.topLevelWidgets() if widget.isVisible()]
            unexpected = next(
                (
                    widget
                    for widget in visible
                    if isinstance(widget, QMessageBox)
                    or (isinstance(widget, QDialog) and not isinstance(widget, V2ProfileStartupDialog))
                ),
                None,
            )
            _require(
                unexpected is None,
                "Unexpected startup message" if isinstance(unexpected, QMessageBox) else "Unexpected startup dialog",
            )
            startup = next((widget for widget in visible if isinstance(widget, V2ProfileStartupDialog)), None)
            if startup is not None and not state["chosen"] and paints["chooser"]:
                state["chosen"] = True
                diagnostics.mark("actual V2 chooser: " + action)
                getattr(
                    startup, {"create": "create_button", "open": "open_button", "restore": "restore_button"}[action]
                ).click()
            window = next((widget for widget in visible if isinstance(widget, V2WorkspaceWindow)), None)
            if window is not None and paints["workspace"] and not state["worked"]:
                state["working"] = True
                _local_work(window, root, release, diagnostics, app, result)
                state["worked"], state["working"] = True, False
            if state["worked"] and state["ticks"] >= 35:
                app.exit(0)
        except BaseException as exc:
            state["working"] = False
            fail(f"{type(exc).__name__}: {exc}")

    ticker, poller = QTimer(), QTimer()
    ticker.timeout.connect(heartbeat)
    poller.timeout.connect(inspect)
    ticker.start(10)
    poller.start(15)
    try:
        diagnostics.mark("entering real ordinary V2 entrypoint")
        code = entrypoint()
        _require(code in (None, 0), state["error"] or "V2 entrypoint failed")
        _require(state["error"] is None, state["error"])
        _require(state["chosen"] and state["worked"], "Chooser/workspace workflow was not exercised")
        _require(all(paints.values()), "A required V2 review/report surface did not paint")
        _require(not attempts, "V2 attempted network access")
        _require(state["ticks"] >= 35, "UI heartbeat did not run")
        _require(state["max_gap"] < 5.0, "V2 UI heartbeat stalled for at least five seconds")
        result.update(
            passed=True,
            network_requests=len(attempts),
            heartbeat_ticks=state["ticks"],
            max_heartbeat_gap_ms=round(state["max_gap"] * 1000, 2),
            paint_events=paints,
            first_paint_ms=first_paint_ms,
            total_elapsed_seconds=round(time.monotonic() - diagnostics.started, 3),
            elapsed_seconds=round(time.monotonic() - started, 3),
            qt_platform=app.platformName(),
            ui_responsive=True,
        )
        return result
    finally:
        ticker.stop()
        poller.stop()
        app.removeEventFilter(observer)
        for widget in app.topLevelWidgets():
            widget.close()
        app.processEvents()


def run_offline_session_smoke(mode: str, entrypoint: Callable[[], int], *, report_path: Path | None = None) -> int:
    """Only explicit diagnostics inject fixture trust, paths, UI driving or denial hooks."""
    if mode not in MODES:
        raise ValueError("unsupported_offline_mode")
    if "parsetrail.core.settings" in sys.modules:
        if sys.stderr is not None:
            print("V2 diagnostic requires a fresh process without legacy settings", file=sys.stderr)
        return 2
    diagnostics = None
    attempts = []
    try:
        if report_path is not None:
            report_path = report_path.expanduser().resolve()
            _require(
                not report_path.exists() and report_path.parent.is_dir(),
                "Diagnostic report must use a new file in an existing directory",
            )
        with (
            _Diagnostics(report_path) as diagnostics,
            tempfile.TemporaryDirectory(prefix="parsetrail-v2-offline-") as temporary,
            ExitStack() as patches,
        ):
            root = Path(temporary)
            patches.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "HOME": temporary,
                        "USERPROFILE": temporary,
                        "APPDATA": str(root / "appdata"),
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "XDG_DATA_HOME": str(root / "data"),
                        "XDG_CACHE_HOME": str(root / "cache"),
                    },
                )
            )
            report = _session(mode, entrypoint, root, patches, diagnostics, attempts)
    except BaseException as exc:
        report = {
            "schema_version": 2,
            "runtime": "v2",
            "mode": mode,
            "passed": False,
            "network_requests": len(attempts),
            "error": f"{type(exc).__name__}: {exc}",
        }
        if sys.stderr is not None:
            print("V2 offline smoke failed: " + report["error"], file=sys.stderr)
    if report_path is not None:
        try:
            with report_path.open("x", encoding="utf-8") as stream:
                json.dump(report, stream, sort_keys=True)
                stream.write("\n")
        except OSError as exc:
            if sys.stderr is not None:
                print(f"V2 diagnostic report could not be written: {type(exc).__name__}", file=sys.stderr)
            return 1
    if sys.stdout is not None:
        print(json.dumps(report, sort_keys=True), flush=True)
    if report["passed"] and diagnostics is not None and diagnostics.path:
        diagnostics.path.unlink()
    return 0 if report["passed"] else 1
