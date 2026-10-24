"""Desktop shell keeps imports pending and routes only explicit 2.0 profiles."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from threading import Event
from time import sleep

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.review_accountless_export import DEFINITION as MOHELA_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import SOURCE as MOHELA_SOURCE

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def _workspace(tmp_path: Path) -> V2Workspace:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "cash-definition.json").write_bytes(DEFINITION)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(snapshot, signature)
    return workspace


def _app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _wait_finished(worker, app) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    timed_out = []
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: (timed_out.append(True), loop.quit()))
    worker.finished.connect(loop.quit)
    timer.start(10_000)
    if not worker.isFinished():
        loop.exec()
    app.processEvents()
    assert not timed_out


def test_window_imports_pending_evidence_and_reuses_exact_source(tmp_path: Path, monkeypatch) -> None:
    app = _app()
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    workspace = _workspace(tmp_path)
    source = tmp_path / "cash.csv"
    source.write_bytes(SOURCE)
    window = V2WorkspaceWindow(workspace)
    try:
        assert window.sources.count() == 0
        assert window.import_button.isEnabled()
        window.start_import(source)
        _wait_finished(window.import_worker, app)
        assert window.sources.count() == 1
        assert window.preview_button.isEnabled()
        assert not window.review_button.isEnabled()
        assert window.source_review_button.isEnabled()
        assert "pending review" in window.status.text()
        opened = []
        monkeypatch.setattr(V2SourceAccountReview, "exec", lambda dialog: opened.append(dialog.identities.count()))
        window.source_review_button.click()
        assert opened == [1]
        window.start_import(source)
        _wait_finished(window.import_worker, app)
        assert window.sources.count() == 1
        assert "already imported" in window.status.text()
    finally:
        window.close()
        app.processEvents()
    assert len(workspace.source_ids()) == 1


def test_window_cancel_reaches_worker_and_saves_nothing(tmp_path: Path, monkeypatch) -> None:
    app = _app()
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    workspace = _workspace(tmp_path)
    started = Event()

    def wait_for_cancel(_path, *, cancelled):
        started.set()
        while not cancelled():
            sleep(0.001)
        raise ImportCancelled("cancelled")

    monkeypatch.setattr(workspace, "import_file", wait_for_cancel)
    window = V2WorkspaceWindow(workspace)
    try:
        window.start_import(tmp_path / "unused.csv")
        worker = window.import_worker
        assert started.wait(2)
        from PySide6.QtWidgets import QPushButton

        cancel_button = next(
            button for button in window.progress.findChildren(QPushButton) if "Cancel" in button.text()
        )
        cancel_button.click()
        _wait_finished(worker, app)
        assert "cancelled" in window.status.text()
        assert workspace.source_ids() == ()
    finally:
        window.close()
        app.processEvents()


def test_window_installs_local_signed_catalog_before_enabling_import(tmp_path: Path, monkeypatch) -> None:
    app = _app()
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QFileDialog

    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "cash-definition.json").write_bytes(DEFINITION)
    snapshot, signature, _verified = signed_catalog_bytes(
        definitions, private, release_sequence=1, source_revision="a" * 40
    )
    release = tmp_path / "release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *_args: str(release))
    window = V2WorkspaceWindow(workspace)
    try:
        assert not window.import_button.isEnabled()
        assert "No verified catalog" in window.catalog_label.text()
        window.install_catalog_button.click()
        assert window.import_button.isEnabled()
        assert "Verified catalog release 1" in window.catalog_label.text()
    finally:
        window.close()
        app.processEvents()


def test_v2_argument_dispatch_precedes_legacy_profile(monkeypatch) -> None:
    from parsetrail import main

    called = []
    monkeypatch.setattr(main, "run_v2_workspace", lambda args: called.append(args) or 17)
    monkeypatch.setattr(sys, "argv", ["parsetrail", "--v2", "--profile", "fresh.db", "--catalog-cache", "catalog"])
    assert main.main() == 17
    assert called == [["--v2", "--profile", "fresh.db", "--catalog-cache", "catalog"]]


def test_accountless_source_opens_review_and_account_creation(tmp_path: Path, monkeypatch) -> None:
    app = _app()
    from parsetrail.gui.v2_workspace_window import V2FinancialAccountDialog, V2WorkspaceWindow
    from PySide6.QtWidgets import QDialog

    workspace = _workspace(tmp_path)
    definition = MOHELA_DEFINITION.read_bytes()
    evidence = build_source_evidence(MOHELA_SOURCE, definition, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(MOHELA_SOURCE, definition, evidence, suffix=".csv")
    window = V2WorkspaceWindow(workspace)
    opened = []

    def accept_account(dialog):
        dialog.name.setText("Loan A")
        dialog.kind.setCurrentIndex(1)
        dialog.institution.setText("mohela")
        return QDialog.Accepted

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept_account)
    monkeypatch.setattr(
        "parsetrail.gui.v2_workspace_window.V2AccountBindingReview.exec",
        lambda dialog: opened.append(dialog.model.rowCount()),
    )
    try:
        assert window.review_button.isEnabled()
        window.account_button.click()
        window.review_button.click()
        assert opened == [6]
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert [(account.name, account.kind) for account in store.financial_accounts()] == [("Loan A", "liability")]
    finally:
        window.close()
        app.processEvents()


def test_v2_entry_refuses_missing_profile_without_creating_it(tmp_path: Path) -> None:
    from parsetrail.main import run_v2_workspace

    profile = tmp_path / "missing.db"
    assert run_v2_workspace(["--v2", "--profile", str(profile), "--catalog-cache", str(tmp_path / "catalog")]) == 2
    assert not profile.exists()
