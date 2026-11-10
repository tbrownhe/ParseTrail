"""Synthetic correction states driven through actual Qt widget events.

Non-discovered filename is intentional: each exact node is run by the process
wrapper, without retries or changing garbage collection. Saved starting entries
are authored through the headless service only as isolated fixture setup.
"""

from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_categories import V2CategoryDialog
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, activate, choose_combo, click_table_text, enter_text
from .test_v2_card_purchase_review import _chase_profile
from .test_v2_liability_register_dialog import profile as register_profile
from .test_v2_multirow_review import select, workspace_rows
from .test_v2_review_cues import open_review

LONG_NOTE = ("Original saved review: matched source amount and merchant. " * 10)[:485] + " END SAVED NOTE"
assert len(LONG_NOTE) <= 500
TEA_NOTE = "Tea saved note,\nseparate entry"


def cash_workspace(tmp_path):
    workspace, evidence, raw = workspace_rows(tmp_path)
    rows = {row.description.text: row for row in evidence.payload.rows}
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("expense:travel", "Travel", "expense")
        store.add_category_account("income:salary", "Salary", "income")
        store.post_reviewed_cash_category(rows["Coffee"].row_id, "expense:food", purpose="expense", reason=LONG_NOTE)
        store.post_reviewed_cash_category(rows["Tea"].row_id, "expense:food", purpose="expense", reason=TEA_NOTE)
        store.post_reviewed_cash_category(
            rows["Deposit"].row_id, "income:salary", purpose="income", reason="Unrelated income stays saved"
        )
        original = store.load_import(evidence.source_sha256)
    return workspace, evidence, raw, original


def settled(qtbot, window, view):
    qtbot.waitUntil(
        lambda: not view.review_pending and not window.inventory_pending and not window.profile_jobs.pending,
        timeout=20000,
    )


def saved_row(qtbot, view, description):
    activate(qtbot, view)
    if QApplication.focusWidget() is None:
        # Native confirmation may have disabled its previously focused action.
        # Exercise the same Tab recovery available to a keyboard user.
        qtbot.keyClick(view.window(), Qt.Key_Tab)
        assert QApplication.focusWidget() is not None
    choose_combo(qtbot, view.navigation.status_filter, "all")
    click_table_text(qtbot, view.table, description)


def blank(qtbot, field):
    enter_text(qtbot, field, "")
    qtbot.keyClick(field, Qt.Key_Backspace)
    assert field.text() == ""


def assert_idle(view, note):
    assert view.decision_group.title() == "Correct saved review"
    assert view.saved_review_note.isVisible() and view.saved_review_note.isReadOnly()
    assert view.saved_review_note.toPlainText() == note
    assert view.saved_review_note.accessibleName() == "Saved review note"
    assert view.saved_review_note.property("formState") == "readonly"
    assert view.reason.text() == "" and "Reason for correction" in view.form.labelForField(view.reason).text()
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    assert "Not saved" not in view.status.text() and "No changes to save" in view.status.text()


def decision(qtbot, window, view, *, accept, withdraw=False, artifacts=None, name="confirmation"):
    modals = ModalSteps(qtbot)
    new_note = view.reason.text()

    def respond(dialog):
        text = dialog.text()
        assert f"Reason: {new_note}" in text
        assert "Inverse effects" in text if withdraw else "Replacement entry effects only" in text
        if artifacts is not None:
            artifacts.capture(name, dialog)
        qtbot.mouseClick(dialog.button(QMessageBox.Yes if accept else QMessageBox.No), Qt.LeftButton)

    modals.arm((QMessageBox, respond))
    qtbot.mouseClick(view.withdraw_button if withdraw else view.action_button, Qt.LeftButton)
    modals.finish()
    settled(qtbot, window, view)


def check_source(workspace, evidence, original, *, entries, corrections):
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(evidence.source_sha256) == original
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (entries,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalCorrections").fetchone() == (corrections,)


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_cash_saved_note_context_and_new_reason(qtbot, qapp, tmp_path, journey_artifacts, size):
    workspace, evidence, _raw, original = cash_workspace(tmp_path)
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    saved_row(qtbot, view, "Coffee")
    assert_idle(view, LONG_NOTE)
    assert not view.has_unsaved_draft
    assert not view.batch.isVisible()
    assert view.table.viewport().height() >= 4 * view.table.verticalHeader().defaultSectionSize()
    artifacts.capture("01-saved-long-note-empty-new-reason", window)

    # The full bounded note is keyboard-reachable, scrollable and selectable.
    activate(qtbot, view.manage_categories_button)
    view.manage_categories_button.setFocus()
    qtbot.keyClick(view.manage_categories_button, Qt.Key_Tab)
    assert view.saved_review_note.hasFocus()
    qtbot.keyClick(view.saved_review_note, Qt.Key_End, Qt.ControlModifier)
    assert view.saved_review_note.verticalScrollBar().maximum() > 0
    assert view.saved_review_note.verticalScrollBar().value() == view.saved_review_note.verticalScrollBar().maximum()
    qtbot.keyClick(view.saved_review_note, Qt.Key_A, Qt.ControlModifier)
    assert view.saved_review_note.textCursor().selectedText() == LONG_NOTE
    qtbot.keyClick(view.saved_review_note, Qt.Key_Tab)
    assert view.reason.hasFocus()
    assert not view.has_unsaved_draft  # Selecting saved context is not authoring.

    # Deliberately typing the same words is a fresh reason, never rejected by
    # text inequality with historical evidence. Reason alone cannot correct.
    enter_text(qtbot, view.reason, LONG_NOTE)
    assert view.has_unsaved_draft and view.withdraw_button.isEnabled() and not view.action_button.isEnabled()
    blank(qtbot, view.reason)
    assert not view.has_unsaved_draft and not view.withdraw_button.isEnabled()
    choose_combo(qtbot, view.category, "expense:travel")
    assert view.reason.property("formState") == "required" and not view.action_button.isEnabled()
    enter_text(qtbot, view.reason, "New correction: this purchase belongs to Travel")
    assert view.action_button.isEnabled() and view.withdraw_button.isEnabled()
    assert view.saved_review_note.toPlainText() == LONG_NOTE
    decision(qtbot, window, view, accept=False, artifacts=artifacts, name="02-correction-cancel-confirmation")
    assert view.reason.text() == "New correction: this purchase belongs to Travel"
    assert view.category.currentData() == "expense:travel"
    artifacts.capture("03-cancel-retains-new-reason-and-saved-context", window)

    modals = ModalSteps(qtbot)
    modals.arm(
        (
            V2CategoryDialog,
            lambda dialog: qtbot.mouseClick(
                dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Close), Qt.LeftButton
            ),
        )
    )
    qtbot.mouseClick(view.manage_categories_button, Qt.LeftButton)
    modals.finish()
    settled(qtbot, window, view)
    assert view.reason.text() == "New correction: this purchase belongs to Travel"
    assert view.category.currentData() == "expense:travel"
    click_table_text(qtbot, view.table, "Tea")
    assert_idle(view, TEA_NOTE)
    assert view.saved_review_note.height() >= 2 * view.saved_review_note.fontMetrics().lineSpacing()
    assert view.has_unsaved_draft  # The unrelated Coffee proposal is retained.
    click_table_text(qtbot, view.table, "Coffee")
    assert view.reason.text() == "New correction: this purchase belongs to Travel"
    assert view.category.currentData() == "expense:travel"
    view.refresh_preserving_draft()
    settled(qtbot, window, view)
    assert view.reason.text() == "New correction: this purchase belongs to Travel"
    choose_combo(qtbot, view.category, "expense:food")
    blank(qtbot, view.reason)
    assert_idle(view, LONG_NOTE)
    assert not view.has_unsaved_draft
    check_source(workspace, evidence, original, entries=3, corrections=0)


def test_cash_save_withdraw_and_unrelated_row_draft(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, evidence, _raw, original = cash_workspace(tmp_path)
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    saved_row(qtbot, view, "Snack")
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.reason, "Unrelated Snack draft must stay")
    click_table_text(qtbot, view.table, "Coffee")
    assert_idle(view, LONG_NOTE)
    choose_combo(qtbot, view.category, "expense:travel")
    enter_text(qtbot, view.reason, "Correct Coffee category after checking source")
    decision(qtbot, window, view, accept=True)
    saved_row(qtbot, view, "Coffee")
    assert_idle(view, "Correct Coffee category after checking source")
    assert view.category.currentData() == "expense:travel" and view.has_unsaved_draft
    artifacts.capture("01-correction-saved-note-updated-new-reason-empty", window)
    check_source(workspace, evidence, original, entries=5, corrections=1)
    click_table_text(qtbot, view.table, "Snack")
    assert view.reason.text() == "Unrelated Snack draft must stay"
    assert view.category.currentData() == "expense:food" and not view.saved_review_note.isVisible()
    click_table_text(qtbot, view.table, "Coffee")
    assert_idle(view, "Correct Coffee category after checking source")
    view._withdraw()  # Direct activation also cannot reuse the saved note.
    check_source(workspace, evidence, original, entries=5, corrections=1)
    enter_text(qtbot, view.reason, "Withdraw only Coffee after another source check")
    assert not view.action_button.isEnabled() and view.withdraw_button.isEnabled()
    decision(qtbot, window, view, accept=False, withdraw=True, artifacts=artifacts, name="02-cancel-withdrawal")
    assert view.reason.text() == "Withdraw only Coffee after another source check"
    decision(qtbot, window, view, accept=True, withdraw=True)
    saved_row(qtbot, view, "Coffee")
    assert view._current().entry_key is None and view.reason.text() == ""
    assert not view.saved_review_note.isVisible()
    assert not view.withdraw_button.isEnabled()
    check_source(workspace, evidence, original, entries=6, corrections=1)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute(
            "SELECT reason FROM SourceInterpretationActions WHERE kind='withdraw'"
        ).fetchall() == [("Withdraw only Coffee after another source check",)]
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 300
        )
        assert (
            store.reviewed_category_summary(kind="income", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 1000
        )
    artifacts.capture("03-withdrawn-row-pending-unrelated-saved-and-draft-retained", window)
    click_table_text(qtbot, view.table, "Snack")
    assert view.reason.text() == "Unrelated Snack draft must stay"


def test_stale_replacement_drops_only_the_old_entry_draft(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, evidence, _raw, original = cash_workspace(tmp_path)
    window, view = open_review(qtbot, workspace)
    saved_row(qtbot, view, "Tea")
    enter_text(qtbot, view.reason, "Retain this independent Tea explanation")
    click_table_text(qtbot, view.table, "Coffee")
    old_key = view._current().entry_key
    choose_combo(qtbot, view.category, "expense:travel")
    enter_text(qtbot, view.reason, "Old Coffee draft must not follow external replacement")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.correct_reviewed_cash_category(old_key, "expense:travel", reason="External replacement saved note")
    view.refresh_preserving_draft()
    settled(qtbot, window, view)
    assert view._current().entry_key != old_key
    assert_idle(view, "External replacement saved note")
    assert view.category.currentData() == "expense:travel"
    click_table_text(qtbot, view.table, "Tea")
    assert view.reason.text() == "Retain this independent Tea explanation"
    blank(qtbot, view.reason)
    click_table_text(qtbot, view.table, "Coffee")
    assert_idle(view, "External replacement saved note")
    assert not view.has_unsaved_draft
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-stale-entry-new-note-no-inherited-correction", window
    )
    check_source(workspace, evidence, original, entries=5, corrections=1)


def test_card_date_correction_requires_new_reason_and_preserves_date_policy(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        store.post_reviewed_card_purchase(
            section.rows[0].row_id,
            "expense:food",
            reason="Saved card date review",
            preferences=V2Preferences(),
            accounting_date=date(2026, 3, 17),
        )
        original = store.load_import(evidence.source_sha256)
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    saved_row(qtbot, view, section.rows[0].description.text)
    assert_idle(view, "Saved card date review")
    assert not view.has_unsaved_draft and not workspace.preferences().allow_assumed_posting_dates
    assert view.accounting_date.text() == "2026-03-17"
    assert view.table.viewport().height() >= 3 * view.table.verticalHeader().defaultSectionSize()
    artifacts.capture("01-card-saved-note-and-date-neutral", window)
    activate(qtbot, view.manage_categories_button)
    view.manage_categories_button.setFocus()
    qtbot.keyClick(view.manage_categories_button, Qt.Key_Tab)
    assert view.accounting_date.hasFocus()
    qtbot.keyClick(view.accounting_date, Qt.Key_Tab)
    assert view.saved_review_note.hasFocus()
    qtbot.keyClick(view.saved_review_note, Qt.Key_Tab)
    assert view.reason.hasFocus()
    enter_text(qtbot, view.accounting_date, "2026-02-30")
    enter_text(qtbot, view.reason, "New card date explanation")
    assert not view.action_button.isEnabled() and view.accounting_date.property("formState") == "invalid"
    enter_text(qtbot, view.accounting_date, "2026-03-18")
    blank(qtbot, view.reason)
    assert not view.action_button.isEnabled()
    enter_text(qtbot, view.reason, "New card date explanation")
    assert view.action_button.isEnabled()
    decision(qtbot, window, view, accept=False, artifacts=artifacts, name="02-card-date-correction-cancel")
    assert view.reason.text() == "New card date explanation" and view.accounting_date.text() == "2026-03-18"
    decision(qtbot, window, view, accept=True)
    saved_row(qtbot, view, section.rows[0].description.text)
    assert_idle(view, "New card date explanation")
    assert view.accounting_date.text() == "2026-03-18" and not view.has_unsaved_draft
    check_source(workspace, evidence, original, entries=3, corrections=1)
    artifacts.capture("03-card-new-saved-note-empty-correction-reason", window)


def test_register_category_correction_keeps_fixed_date_and_new_reason(qtbot, qapp, tmp_path, journey_artifacts):
    case = next(case for case in family_sources() if case.definition_name == "yamaha-card-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    evidence = build_source_evidence(case.source, definition, suffix=case.suffix)
    path = tmp_path / "register.db"
    register_profile(path, (case.source, definition, evidence))
    charge = next(row for row in evidence.payload.accounts[0].rows if row.amount.minor < 0)
    with V2ProfileStore.open(path) as store:
        store.post_reviewed_register_category(
            charge.row_id, "expense:vehicle", purpose="expense", reason="Saved register review"
        )
        original = store.load_import(evidence.source_sha256)
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    window, _initial = open_review(qtbot, workspace)
    choose_combo(qtbot, window.review_document_selector, evidence.source_sha256)
    qtbot.waitUntil(lambda: window._review_widget.review_kind == "register", timeout=15000)
    view = window._review_widget
    settled(qtbot, window, view)
    saved_row(qtbot, view, charge.description.text)
    assert_idle(view, "Saved register review")
    fixed_date = view.accounting_date.text()
    assert view.accounting_date.isReadOnly() and not view.has_unsaved_draft
    choose_combo(qtbot, view.category, "expense:other")
    assert not view.action_button.isEnabled()
    enter_text(qtbot, view.reason, "New register category explanation")
    decision(qtbot, window, view, accept=True)
    saved_row(qtbot, view, charge.description.text)
    assert_idle(view, "New register category explanation")
    assert view.accounting_date.text() == fixed_date and view.accounting_date.isReadOnly()
    check_source(workspace, evidence, original, entries=3, corrections=1)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-register-correction-note-with-fixed-date", window
    )
    repayment = next(row for row in evidence.payload.accounts[0].rows if row.amount.minor > 0)
    click_table_text(qtbot, view.table, repayment.description.text)
    choose_combo(qtbot, view.purpose, "repayment")
    assert not view.saved_review_note.isVisible() and view.reason.text() == ""
    assert not view.withdraw_button.isEnabled()


def test_pending_and_multi_selection_keep_separate_notes(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _evidence, _raw, _original = cash_workspace(tmp_path)
    window, view = open_review(qtbot, workspace)
    saved_row(qtbot, view, "Coffee")
    enter_text(qtbot, view.reason, "Coffee-only authored explanation")
    click_table_text(qtbot, view.table, "Snack")
    assert not view.saved_review_note.isVisible() and view.reason.text() == ""
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.reason, "Independent pending review note")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged_note = view.batch.note()
    staged_rows = dict(view.batch.staged)
    select(qtbot, view, "Coffee", Qt.ControlModifier)
    assert len(view.navigation.selected()) == 2
    assert not view.saved_review_note.isVisible() and view.reason.text() == ""
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    assert view.batch.note() == staged_note and view.batch.staged == staged_rows
    select(qtbot, view, "Snack")
    assert view.reason.text() == "Independent pending review note"
    select(qtbot, view, "Coffee")
    assert view.reason.text() == "Coffee-only authored explanation" and view.saved_review_note.isVisible()
    assert view.batch.isVisible() and view.batch.note() == staged_note and view.batch.staged == staged_rows
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-row-specific-reasons-survive-multi-return", window
    )
