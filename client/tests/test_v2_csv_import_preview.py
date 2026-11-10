"""CSV recognition is reviewed before retention; institution choices use managed names."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_creation import AccountCreationDraft
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_batch_import import V2BatchImportReport
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialogButtonBox, QFileDialog, QLineEdit, QMessageBox
from scripts.v2_catalog_release import signed_catalog_bytes

from .qt_account_import_helpers import new_import_account
from .qt_journey_helpers import (
    JourneyArtifacts,
    ModalSteps,
    choose_combo,
    close_dialog,
    enter_text,
    select_file,
)
from .qt_journey_scenarios import SOURCE, prepare_close


@pytest.fixture(autouse=True)
def non_native_pickers(qapp):
    previous = qapp.testAttribute(Qt.AA_DontUseNativeDialogs)
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    yield
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, previous)


def workspace_for(tmp_path, *, ambiguous=False):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    base = json.loads(
        (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()
    )
    (definitions / "cash-definition.json").write_text(json.dumps(base), encoding="utf-8")
    if ambiguous:
        alternate = {
            **base,
            "parser_id": "synthetic_balance_as_amount",
            "columns": {**base["columns"], "total": "ReportedBalance", "balance": "Amount"},
        }
        (definitions / "alternate-definition.json").write_text(json.dumps(alternate), encoding="utf-8")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    catalog, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "review.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(catalog, signature)
    source = tmp_path / "Checking-October.csv"
    source.write_bytes(SOURCE)
    return workspace, source


def open_window(qtbot, workspace, size=(1050, 700)):
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    return window


def begin_file(qtbot, window, source):
    modals = ModalSteps(qtbot)
    modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=15000)
    return window.import_preview


def settled(qtbot, window):
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_unique_csv_shows_full_file_validated_preview_then_explicit_local_import(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    workspace, source = workspace_for(tmp_path)
    window = open_window(qtbot, workspace, size)
    review = begin_file(qtbot, window, source)
    review.resize(*size)
    new_import_account(qtbot, review)
    preview = review.preview
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    assert not preview.format_selector.isVisible()
    assert "complete header matches a supported format" in preview.format_label.text()
    assert "posting" in preview.format_label.text().lower()
    assert preview.rows.rowCount() == 3 and preview.rows.item(0, 3).text() == "-$4.00"
    assert "observed" in preview.rows.item(0, 0).text()
    assert "Raw amount" in preview.rows.item(0, 3).toolTip()
    assert "row 2" in preview.rows.item(0, 5).text()
    assert "no transactions are posted" in " ".join(
        label.text() for label in preview.findChildren(type(preview.format_label))
    )
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.connection.execute("BEGIN IMMEDIATE")
        assert store.source_ids() == ()
        store.connection.rollback()
    artifacts.capture("01-single-candidate-check-evidence-before-import", review)
    qtbot.mouseClick(preview.details_toggle, Qt.LeftButton)
    assert "raw date" in preview.details.toPlainText() and "raw amount" in preview.details.toPlainText()
    artifacts.capture("02-raw-fields-and-source-locations", review)
    qtbot.mouseClick(review.import_button, Qt.LeftButton)
    settled(qtbot, window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1
        assert store.load_import(store.source_ids()[0]).source == SOURCE
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    assert window.sources.count() == 1 and window.install_catalog_button.isEnabled()
    artifacts.capture("03-imported-and-assigned-evidence-pending-review", window)


def test_same_header_conflicting_declarations_cannot_be_selected_by_the_user(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, source = workspace_for(tmp_path, ambiguous=True)
    window = open_window(qtbot, workspace)
    review = begin_file(qtbot, window, source)
    new_import_account(qtbot, review)
    preview = review.preview
    assert not preview.format_selector.isVisible() and preview.format_selector.count() == 0
    assert not review.import_button.isEnabled() and preview.rows.rowCount() == 0
    assert "more than one supported format" in review.status.text()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-same-header-catalog-conflict-blocks-import", review
    )
    qtbot.mouseClick(review.skip_button, Qt.LeftButton)
    settled(qtbot, window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.source_ids() and not store.financial_accounts()
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


def test_batch_reuses_one_surface_and_keeps_completed_files_when_skipping_and_cancelling(
    qtbot, qapp, tmp_path, journey_artifacts
):
    workspace, original = workspace_for(tmp_path)
    bad = tmp_path / "A-refused.csv"
    bad.write_bytes(b"Unsupported,Columns\nsynthetic,example\n")
    paths = [bad]
    for name in ("B-first", "C-skip", "D-cancel"):
        path = tmp_path / (name + ".csv")
        path.write_bytes(SOURCE.replace(b"Coffee", name.encode("ascii")))
        paths.append(path)
    window = open_window(qtbot, workspace)
    modals = ModalSteps(qtbot)

    def pick_many(dialog):
        field = dialog.findChild(QLineEdit, "fileNameEdit")
        enter_text(qtbot, field, " ".join('"' + path.resolve().as_posix() + '"' for path in paths))
        assert {Path(path).resolve() for path in dialog.selectedFiles()} == set(paths)
        qtbot.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Open), Qt.LeftButton)

    modals.arm((QFileDialog, pick_many))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(
        lambda: window.import_preview is not None and window.import_preview.request is not None,
        timeout=15000,
    )
    preview = window.import_preview
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    assert preview.request.path == paths[1] and "File 2 of 4" in preview.file_context.text()
    assert "1 failed" in preview.queue_status.text()
    artifacts.capture("01-queue-first-file-before-import", preview)
    new_import_account(qtbot, preview)
    qtbot.mouseClick(preview.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: preview.request.path == paths[2] and preview.skip_button.isEnabled(), timeout=15000)
    assert window.import_preview is preview
    assert "1 imported" in preview.queue_status.text()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1
    artifacts.capture("02-same-surface-next-file-can-skip", preview)
    qtbot.mouseClick(preview.skip_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: preview.request.path == paths[3] and preview.cancel_button.isEnabled(), timeout=15000)
    assert window.import_preview is preview
    assert "1 skipped" in preview.queue_status.text()
    artifacts.capture("03-same-surface-third-file-can-cancel", preview)

    def inspect_result(dialog):
        labels = [dialog.files.item(index).text() for index in range(dialog.files.count())]
        assert "failed" in labels[0] and "imported" in labels[1] and "skipped" in labels[2] and "cancelled" in labels[3]
        artifacts.capture("04-completed-import-retained-after-cancel", dialog)
        close_dialog(qtbot, dialog)

    modals.arm((V2BatchImportReport, inspect_result))
    qtbot.mouseClick(preview.cancel_button, Qt.LeftButton)
    modals.finish()
    settled(qtbot, window)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1
        assert store.load_import(store.source_ids()[0]).source == paths[1].read_bytes()
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    assert original.read_bytes() == SOURCE and window.install_catalog_button.isEnabled()


def test_preview_setup_failure_releases_worker_and_restores_controls(
    qtbot, qapp, tmp_path, journey_artifacts, monkeypatch
):
    workspace, source = workspace_for(tmp_path)
    window = open_window(qtbot, workspace)

    def fail_names():
        raise OSError("synthetic registry read failure")

    monkeypatch.setattr(workspace, "institutions", fail_names)
    modals = ModalSteps(qtbot)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))

    def acknowledge(dialog):
        assert "preview could not be opened" in dialog.text()
        assert "import_preview_unavailable" in dialog.text()
        artifacts.capture("01-preview-failure-is-not-user-cancel", dialog)
        qtbot.mouseClick(dialog.button(QMessageBox.Ok), Qt.LeftButton)

    modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)), (QMessageBox, acknowledge))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    settled(qtbot, window)
    assert window.import_button.isEnabled() and window.install_catalog_button.isEnabled()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == ()
    artifacts.capture("02-preview-failure-restores-recovery-actions", window)


def test_institution_names_search_unknown_and_unmatched_text_remain_distinct(qtbot, qapp, journey_artifacts):
    form = V2FinancialAccountDialog(draft=AccountCreationDraft())
    qtbot.addWidget(form)
    form.show()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (600, 700))
    enter_text(qtbot, form.name, "Everyday account")
    choose_combo(qtbot, form.product, "checking")
    assert form.scope.currentData() == "account_total"
    assert "U.S. Bank" in [form.institution.itemText(i) for i in range(form.institution.count())]
    assert "usbank" not in [form.institution.itemText(i) for i in range(form.institution.count())]
    enter_text(qtbot, form.institution.lineEdit(), "Unlisted bank")
    assert not form.save_button.isEnabled() and form.institution.property("formState") == "invalid"
    artifacts.capture("01-unmatched-typed-name-is-not-an-institution", form)
    choose_combo(qtbot, form.institution, "usbank")
    assert form.institution.currentText() == "U.S. Bank" and form.account().institution_key == "usbank"
    assert form.save_button.isEnabled()
    artifacts.capture("02-managed-display-name-selected", form)
    enter_text(qtbot, form.institution.lineEdit(), " chase ")
    qtbot.keyClick(form.institution.lineEdit(), Qt.Key_Tab)
    assert form.institution.currentData() == "chase" and form.institution.currentText() == "Chase"
    assert form.result() == 0 and form.isVisible()
    enter_text(qtbot, form.institution.lineEdit(), "Citi")
    qtbot.keyClick(form.institution.lineEdit(), Qt.Key_Return)
    assert form.institution.currentData() == "citi" and form.isVisible() and form.result() == 0
    choose_combo(qtbot, form.institution, None)
    assert form.account().institution_key is None and form.save_button.isEnabled()
    artifacts.capture("03-explicit-unknown-is-valid-but-not-a-matching-key", form)
