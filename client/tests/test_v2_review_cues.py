"""Required choices, unsaved drafts and saved reviews have distinct UI states."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from threading import Event

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit, QPushButton

from .qt_journey_helpers import (
    JourneyArtifacts,
    ModalSteps,
    choose_combo,
    click_list_row,
    click_table_text,
    enter_text,
)
from .qt_journey_scenarios import prepare_close
from .test_v2_card_purchase_review import _chase_profile
from .test_v2_document_browser import _populated_workspace
from .test_v2_liability_register_dialog import profile as register_profile


def open_review(qtbot, workspace, *, size=(1050, 700)):
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    click_list_row(qtbot, window.navigation, 1)
    qtbot.waitUntil(
        lambda: (
            window.findChild(V2CashActivityReview) is not None or window.findChild(V2CardPurchaseReview) is not None
        ),
        timeout=15000,
    )
    view = window.findChild(V2CashActivityReview) or window.findChild(V2CardPurchaseReview)
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    return window, view


def confirm(qtbot, modals, view, *, accept=True):
    if view._current().entry_key is None:
        qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)

        def staged_decision(dialog):
            text = dialog.findChild(QPlainTextEdit).toPlainText()
            assert view._current().description in text
            assert view.batch.note() in text
            buttons = dialog.findChild(QDialogButtonBox)
            button = (
                next(button for button in buttons.buttons() if button.text().startswith("Confirm and post"))
                if accept
                else buttons.button(QDialogButtonBox.Cancel)
            )
            qtbot.mouseClick(button, Qt.LeftButton)

        modals.arm((QDialog, staged_decision))
        qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
        modals.finish()
        qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
        return

    def decide(dialog):
        assert "$4.00" in dialog.text() or "$10.00" in dialog.text()
        qtbot.mouseClick(dialog.button(QMessageBox.Yes if accept else QMessageBox.No), Qt.LeftButton)

    modals.arm((QMessageBox, decide))
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_cash_required_ready_saved_correction_and_staged_are_distinct(qtbot, qapp, tmp_path, journey_artifacts, size):
    workspace = _populated_workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:travel", "Travel", "expense")
        source_id = store.source_ids()[0]
        original = store.load_import(source_id)
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)
    assert view.decision_group.title() == "Review selected transaction"
    assert not view.decision_group.isAncestorOf(view.batch)
    assert [field.property("formState") for field in (view.purpose, view.category, view.reason)] == [
        "required",
        "required",
        "required",
    ]
    assert "Required:" in view.status.text() and not view.action_button.isEnabled()
    assert view.table.viewport().height() >= 4 * view.table.verticalHeader().defaultSectionSize()
    artifacts.capture("01-cash-required-fields", window)
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    assert view.purpose.property("formState") == view.category.property("formState") == "ready"
    assert view.reason.property("formState") == "required"
    enter_text(qtbot, view.reason, "Reviewed the original source")
    assert view.status.property("formState") == "ready"
    assert "Not saved" in view.status.text()
    assert "not saved" in view.category.accessibleDescription()
    artifacts.capture("02-cash-valid-choices-not-saved", window)
    confirm(qtbot, modals, view, accept=False)
    assert view.reason.text() == "Reviewed the original source"
    assert view.status.property("formState") == "ready"
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 1 and "Not saved" in view.batch.summary.text()
    artifacts.capture("03-staged-is-separate-and-not-saved", window)
    qtbot.mouseClick(view.batch.clear_button, Qt.LeftButton)
    enter_text(qtbot, view.reason, "Confirm reviewed source purchase")
    confirm(qtbot, modals, view)
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    qtbot.mouseClick(view.navigation.search, Qt.LeftButton)
    choose_combo(qtbot, view.navigation.status_filter, "all")
    click_table_text(qtbot, view.table, "Coffee")
    assert view.decision_group.title() == "Correct saved review"
    assert view.purpose.property("formState") == view.category.property("formState") == "saved"
    assert view.reason.property("formState") == "optional"
    assert "for changes" in view.form.labelForField(view.reason).text()
    assert view.status.property("formState") == "saved" and not view.action_button.isEnabled()
    artifacts.capture("04-saved-review-is-neutral", window)
    choose_combo(qtbot, view.category, "expense:travel")
    assert view.category.property("formState") == "ready"
    assert view.reason.property("formState") == "required"
    assert "*" in view.form.labelForField(view.reason).text()
    choose_combo(qtbot, view.category, "expense:food")
    assert view.category.property("formState") == "saved" and view.reason.property("formState") == "optional"
    assert view.status.property("formState") == "saved"
    choose_combo(qtbot, view.category, "expense:travel")
    enter_text(qtbot, view.reason, "Correct category, retain original money")
    assert view.status.property("formState") == "ready"
    artifacts.capture("05-correction-ready-still-not-saved", window)
    confirm(qtbot, modals, view)
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    click_table_text(qtbot, view.table, "Coffee")
    assert view.category.property("formState") == "saved" and view.reason.property("formState") == "optional"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(source_id) == original
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (1,)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
    artifacts.capture("06-correction-saved-neutral-source-unchanged", window)


def test_assumed_card_date_is_required_until_decided_and_invalid_edits_are_red(
    qtbot, qapp, tmp_path, journey_artifacts
):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.reason, "Review card purchase without accepting a guess")
    assert view.accounting_date.text() == "2026-03-16"
    assert view.accounting_date.property("formState") == "required"
    assert view.category.property("formState") == view.reason.property("formState") == "ready"
    assert view.status.property("formState") == "blocked" and "nothing can post" in view.status.text()
    assert not view.action_button.isEnabled()
    artifacts.capture("01-estimated-date-decision-blocks-posting", window)
    assert view.table.viewport().height() >= 3 * view.table.verticalHeader().defaultSectionSize()
    enter_text(qtbot, view.accounting_date, "2026-02-30")
    assert view.accounting_date.property("formState") == "invalid"
    assert not view.action_button.isEnabled()
    artifacts.capture("02-invalid-date-retains-other-draft-choices", window)
    enter_text(qtbot, view.accounting_date, "2026-03-17")
    assert view.accounting_date.property("formState") == "ready"
    assert view.status.property("formState") == "ready" and view.batch.stage_button.isEnabled()
    assert not workspace.preferences().allow_assumed_posting_dates
    artifacts.capture("03-explicit-date-choice-not-saved", window)
    confirm(qtbot, ModalSteps(qtbot), view)
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    qtbot.mouseClick(view.navigation.search, Qt.LeftButton)
    choose_combo(qtbot, view.navigation.status_filter, "all")
    click_table_text(qtbot, view.table, section.rows[0].description.text)
    assert view.accounting_date.property("formState") == "saved"
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (1,)
    artifacts.capture("04-saved-card-review-neutral", window)


def test_register_source_fixed_date_and_repayment_route_never_look_like_category_posting(
    qtbot, qapp, tmp_path, journey_artifacts
):
    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

    case = next(case for case in family_sources() if case.definition_name == "yamaha-card-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    evidence = build_source_evidence(case.source, definition, suffix=case.suffix)
    path = tmp_path / "register.db"
    register_profile(path, (case.source, definition, evidence))
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    window, _initial = open_review(qtbot, workspace)
    choose_combo(qtbot, window.review_document_selector, evidence.source_sha256)
    qtbot.waitUntil(lambda: window._review_widget.review_kind == "register", timeout=15000)
    view = window._review_widget
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:vehicle")
    enter_text(qtbot, view.reason, "Review whole-register charge without inventing interest")
    assert view.accounting_date.isReadOnly() and view.accounting_date.property("formState") == "readonly"
    assert view.purpose.property("formState") == view.category.property("formState") == "ready"
    assert view.batch.stage_button.isEnabled() and view.status.property("formState") == "ready"
    artifacts.capture("01-source-fixed-register-date-neutral", window)
    rows = evidence.payload.accounts[0].rows
    repayment = next(row for row in rows if row.amount.minor > 0)
    click_table_text(qtbot, view.table, repayment.description.text)
    choose_combo(qtbot, view.purpose, "repayment")
    assert view.action_button.isEnabled() and "repayment" in view.action_button.text().lower()
    assert view.action_button.property("formState") == "neutral"
    assert view.status.property("formState") == "neutral"
    assert all(field.property("formState") == "readonly" for field in (view.purpose, view.category, view.reason))
    artifacts.capture("02-repayment-navigation-is-not-category-readiness", window)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert store.load_import(evidence.source_sha256).evidence == evidence


def test_loading_cancel_and_reload_keep_draft_but_never_show_posting_ready(
    qtbot, qapp, tmp_path, journey_artifacts, monkeypatch
):
    workspace = _populated_workspace(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:food", "Food", "expense")
    window, view = open_review(qtbot, workspace)
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.reason, "Retain this unsaved decision through reload cancellation")
    started, release = Event(), Event()
    original = V2ProfileStore.source_interpretation_snapshot

    def gated(store, *args, **kwargs):
        started.set()
        assert release.wait(10), "Synthetic snapshot gate was not released"
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", gated)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.manifest["instrumentation"] = (
        "Read-only snapshot worker paused with an Event to inspect pending/cancel UI."
    )
    reload_button = next(button for button in view.findChildren(QPushButton) if button.text() == "Reload")
    try:
        qtbot.mouseClick(reload_button, Qt.LeftButton)
        qtbot.waitUntil(started.is_set, timeout=10000)
        assert all(field.property("formState") == "loading" for field in (view.purpose, view.category, view.reason))
        assert not view.reason.isEnabled() and not view.action_button.isEnabled()
        assert view.status.property("formState") == "loading"
        artifacts.capture("01-loading-snapshot-keeps-draft-neutral", window)
        qtbot.mouseClick(view.cancel_read_button, Qt.LeftButton)
        release.set()
        qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
        assert view.reason.text() == "Retain this unsaved decision through reload cancellation"
        assert not view.action_button.isEnabled()
        assert view.status.property("formState") == "blocked"
        artifacts.capture("02-cancelled-load-needs-reload-keeps-draft", window)
        qtbot.mouseClick(reload_button, Qt.LeftButton)
        qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
        assert view.purpose.currentData() == "expense" and view.category.currentData() == "expense:food"
        assert view.reason.text() == "Retain this unsaved decision through reload cancellation"
        assert view.batch.stage_button.isEnabled() and view.status.property("formState") == "ready"
        artifacts.capture("03-reloaded-draft-ready-but-not-saved", window)
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        release.set()
