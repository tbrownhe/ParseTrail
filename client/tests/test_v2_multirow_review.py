"""Visible multi-selection authors a draft; only an exact batch posts money."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit

from .ordinary_staging_helpers import review_reason
from .qt_journey_helpers import JourneyArtifacts, ModalSteps, activate, choose_combo, close_dialog, enter_text
from .test_v2_card_purchase_review import _chase_profile
from .test_v2_ordinary_review_async import DEFINITION
from .test_v2_review_cues import open_review
from .test_v2_workspace_window import _workspace
from .v2_institution_helpers import add_test_financial_account


def workspace_rows(tmp_path, *, categories=True):
    workspace = _workspace(tmp_path)
    raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
        b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
        b"10/03/2026,Checking A,Tea,-$3.00,$1003.00\n"
        b"10/04/2026,Other,Unassigned,-$2.00,$1001.00\n"
        b"10/05/2026,Checking A,Snack,-$1.00,$1000.00\n"
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        add_test_financial_account(store, FinancialAccount("cash", "Everyday checking", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        if categories:
            store.add_category_account("expense:food", "Food", "expense")
    return workspace, evidence, raw


def select(qtbot, view, text, modifier=Qt.NoModifier):
    activate(qtbot, view.table)
    proxy = view.navigation.proxy
    index = next(
        proxy.index(i, col)
        for i in range(proxy.rowCount())
        for col in range(proxy.columnCount())
        if text in str(proxy.data(proxy.index(i, col)) or "")
    )
    view.table.scrollTo(index)
    qtbot.mouseClick(view.table.viewport(), Qt.LeftButton, modifier, pos=view.table.visualRect(index).center())
    qtbot.waitUntil(lambda: not view.review_pending)
    # Flush the membership update after Qt's current-index transition.
    qtbot.waitUntil(lambda: (len(view.navigation.selected()) > 1) == view._in_multi)


def choices(qtbot, view):
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, review_reason(view), "Checked each selected purchase against the original")


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_nonadjacent_selection_exact_preview_cancel_then_two_posts(
    qtbot, qapp, tmp_path, journey_artifacts, size, monkeypatch
):
    workspace, evidence, raw = workspace_rows(tmp_path)
    window, view = open_review(qtbot, workspace, size=size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    modals = ModalSteps(qtbot)
    select(qtbot, view, "Coffee")
    choices(qtbot, view)
    single_note = review_reason(view).text()
    select(qtbot, view, "Coffee", Qt.ControlModifier)
    assert not view.navigation.selected() and view._current() is None
    assert not view.action_button.isEnabled() and not view.batch.stage_button.isEnabled()
    assert view.status.property("formState") == "neutral"
    artifacts.capture("00-no-selection-preserves-draft-disables-post", window)
    select(qtbot, view, "Coffee")
    assert review_reason(view).text() == single_note and view.category.currentData() == "expense:food"
    select(qtbot, view, "Tea", Qt.ControlModifier)
    assert len(view.navigation.selected()) == 2
    assert "2 selected" in view.navigation.count.text()
    assert view.decision_group.title() == "Review 2 selected transactions"
    assert view.purpose.currentData() is None  # No inferred anchor purpose.
    choices(qtbot, view)
    shared_note = review_reason(view).text()
    select(qtbot, view, "Snack", Qt.ControlModifier)
    select(qtbot, view, "Snack", Qt.ControlModifier)
    assert len(view.navigation.selected()) == 2
    assert review_reason(view).text() == shared_note and view.category.currentData() == "expense:food"
    enter_text(qtbot, review_reason(view), shared_note)
    assert not view.table.hasFocus() and review_reason(view).hasFocus()
    assert view.table.palette().color(QPalette.Inactive, QPalette.Highlight).name() == "#dcebfa"
    assert view.table.palette().color(QPalette.Inactive, QPalette.HighlightedText).name() == "#172b4d"
    assert view.table.property("reviewSelectionFocus") is False
    view.table.scrollTo(view.navigation.proxy.index(0, 0))
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    view._act()  # Handler guard also blocks stale/direct activation.
    view._withdraw()
    artifacts.capture("01-two-nonadjacent-selected-common-draft", window)
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 2 and "2 staged" in view.batch.summary.text()
    staged = dict(view.batch.staged)

    def preview(dialog, accept):
        text = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "Coffee" in text and "Tea" in text and "Deposit" not in text
        assert "$4.00" in text and "$3.00" in text
        artifacts.capture("03-exact-confirmation" if accept else "02-cancel-exact-preview", dialog)
        box = dialog.findChild(QDialogButtonBox)
        button = (
            next(b for b in box.buttons() if b.text().startswith("Confirm and post"))
            if accept
            else box.button(QDialogButtonBox.Cancel)
        )
        qtbot.mouseClick(button, Qt.LeftButton)

    modals.arm((QDialog, lambda dialog: preview(dialog, False)))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending)
    assert view.batch.staged == staged
    assert "Preparing" not in view.operation_status.text() and "nothing posted" in view.operation_status.text()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    # Returning to one restores that row's independent proposal and review note.
    select(qtbot, view, "Coffee")
    assert view.purpose.currentData() == "expense" and review_reason(view).text() == single_note
    select(qtbot, view, "Tea", Qt.ControlModifier)
    assert view.purpose.currentData() == "expense" and view.category.currentData() == "expense:food"
    modals.arm((QDialog, lambda dialog: preview(dialog, True)))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (2,)
        rows = store.cash_activity_review_rows(evidence.source_sha256)
        assert {r.description for r in rows if r.entry_key} == {"Coffee", "Tea"}
        assert sum(-r.amount_minor for r in rows if r.entry_key) == 700
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 700
        )
        assert (
            store.reviewed_category_summary(kind="income", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )
        assert next(r for r in rows if r.description == "Deposit").entry_key is None
        assert hashlib.sha256(store.load_import(evidence.source_sha256).source).digest() == hashlib.sha256(raw).digest()
    artifacts.capture("04-two-posted-other-rows-pending", window)
    assert not view.has_unsaved_draft  # The consumed common proposal is now saved.
    choose_combo(qtbot, view.navigation.status_filter, "all")
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    assert not view.batch.stage_button.isEnabled() and view.status.property("formState") == "blocked"
    view.batch.stage_selected()
    assert not view.batch.staged and "None of 2" in view.batch.summary.text()
    artifacts.capture("05-saved-rows-cannot-bulk-correct", window)


def test_shift_mixed_blocked_scope_is_all_or_none_and_filter_selects_visible_only(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    workspace, _evidence, _raw = workspace_rows(tmp_path)
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    refusals = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: refusals.append(text))
    select(qtbot, view, "Snack")
    choices(qtbot, view)
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    prior = dict(view.batch.staged)
    select(qtbot, view, "Coffee")
    qtbot.keyClick(view.table, Qt.Key_Down, Qt.ShiftModifier)
    assert len(view.navigation.selected()) == 2 and view.status.property("formState") == "blocked"
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Unassigned", Qt.ShiftModifier)
    assert len(view.navigation.selected()) == 4
    assert view.status.property("formState") == "blocked"
    view.batch.stage_selected()
    assert view.batch.staged == prior and refusals
    assert "None of 4" in view.batch.summary.text()
    artifacts.capture("01-mixed-selection-none-added-prior-stage-kept", window)
    enter_text(qtbot, view.navigation.search, "Tea")
    activate(qtbot, view.table)
    qtbot.mouseClick(
        view.table.viewport(), Qt.LeftButton, pos=view.table.visualRect(view.navigation.proxy.index(0, 0)).center()
    )
    qtbot.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    assert [r.description for r in view.navigation.selected()] == ["Tea"]
    assert len(view.batch.staged) == 1
    assert "1 hidden" in view.batch.summary.text()
    select(qtbot, view, "Tea", Qt.ControlModifier)
    assert view._current() is None and not view.batch.stage_button.isEnabled()
    assert view.batch.stage_button.property("formState") == "neutral"
    assert view.batch.preview_button.isEnabled()  # Prior staged work remains reviewable at zero selected.
    artifacts.capture("02-filtered-ctrl-a-visible-only", window)


def test_card_multi_keeps_individually_staged_date_override(qtbot, qapp, tmp_path, monkeypatch, journey_artifacts):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
    (tmp_path / "workspace").mkdir()
    workspace = _workspace(tmp_path / "workspace")
    workspace.profile_path = path
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    qtbot.addWidget(view, before_close_func=lambda widget: widget.request_cancel())
    view.show()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    # The source has an assumed posting date; a distinct explicit date is retained.
    first = view._current()
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.accounting_date, "2026-03-17")
    enter_text(qtbot, review_reason(view), "Explicitly checked posting date")
    enter_text(qtbot, view.batch.reason, "Reviewed selected source dates")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert view.batch.staged[first.row_id].accounting_date == date(2026, 3, 17)
    # Ctrl+A uses actual Qt selection. Opposite-sign row cannot share expense purpose.
    activate(qtbot, view.table)
    qtbot.mouseClick(
        view.table.viewport(), Qt.LeftButton, pos=view.table.visualRect(view.navigation.proxy.index(0, 0)).center()
    )
    qtbot.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    qtbot.waitUntil(lambda: view._in_multi)
    assert view.status.property("formState") == "blocked"
    assert not view.accounting_date.isEnabled() and not view.accounting_date.text()
    before = dict(view.batch.staged)
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    assert not view.batch.stage_button.isEnabled()
    view.batch.stage_selected()
    assert view.batch.staged == before
    assert before[first.row_id].accounting_date == date(2026, 3, 17)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-card-multi-separate-dates-prior-override-kept", view
    )


def test_successful_card_multi_preserves_each_date_and_unstaged_override_refuses(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    from parsetrail.core.v2_card_lines import parse_card_lines
    from parsetrail.core.v2_card_source_output import from_card
    from parsetrail.core.v2_pdf_lines import page_lines

    from devtools.parser_engine_pilot.test_card_lines import pages

    from .test_v2_card_purchase_review import CHASE_DEFINITION

    workspace = _workspace(tmp_path)
    source = b"%PDF-synthetic-two-purchases"
    text = pages()
    text[0] = text[0].replace("New Balance $30.00", "New Balance $38.00")
    text[1] = text[1].replace("PAYMENT -5.00", "SECOND CHARGE 3.00")
    lines = page_lines(source, text, extraction_library="synthetic-pdf-1")
    evidence = from_card(parse_card_lines(CHASE_DEFINITION, lines), lines)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(source, CHASE_DEFINITION, evidence, suffix=".pdf")
        add_test_financial_account(store, FinancialAccount("card", "Card", "liability", "chase"))
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        store.add_category_account("expense:food", "Food", "expense")
    workspace.set_allow_assumed_posting_dates(True)
    window, view = open_review(qtbot, workspace)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    select(qtbot, view, "PRIOR-DAY")
    choices(qtbot, view)
    enter_text(qtbot, view.accounting_date, "2026-03-17")
    first_id = view._current().row_id
    select(qtbot, view, "SECOND", Qt.ControlModifier)
    choices(qtbot, view)
    refused = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: refused.append(text))
    assert not view.batch.stage_button.isEnabled()
    view.batch.stage_selected()
    assert not view.batch.staged and "individually" in refused[-1]
    select(qtbot, view, "PRIOR-DAY")
    assert view.accounting_date.text() == "2026-03-17"
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    select(qtbot, view, "SECOND", Qt.ControlModifier)
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 2
    assert view.batch.staged[first_id].accounting_date == date(2026, 3, 17)
    assert next(s for key, s in view.batch.staged.items() if key != first_id).accounting_date is None
    assert not view.accounting_date.isEnabled()
    artifacts.capture("01-card-two-staged-each-date-preserved", window)


def test_register_multiselect_keeps_fixed_dates_and_blocks_owner_actions(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

    from .test_v2_liability_register_dialog import profile

    case = next(case for case in family_sources() if case.definition_name == "yamaha-card-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    evidence = build_source_evidence(case.source, definition, suffix=case.suffix)
    workspace = _workspace(tmp_path)
    path = tmp_path / "register.db"
    profile(path, (case.source, definition, evidence))
    workspace.profile_path = path
    window, _view = open_review(qtbot, workspace)
    choose_combo(qtbot, window.review_document_selector, evidence.source_sha256)
    qtbot.waitUntil(
        lambda: window._review_widget.review_kind == "register" and not window._review_widget.review_pending,
        timeout=15000,
    )
    view = window._review_widget
    activate(qtbot, view.table)
    qtbot.mouseClick(
        view.table.viewport(), Qt.LeftButton, pos=view.table.visualRect(view.navigation.proxy.index(0, 0)).center()
    )
    qtbot.keyClick(view.table, Qt.Key_A, Qt.ControlModifier)
    qtbot.waitUntil(lambda: view._in_multi)
    assert view.status.property("formState") == "blocked"
    assert view.accounting_date.isReadOnly() and not view.accounting_date.isEnabled()
    assert view.purpose.findData("repayment") == -1
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    view._review_repayment()
    view._act()
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    view.batch.stage_selected()
    assert not view.batch.staged  # Charges and repayment cannot share expense purpose.
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-register-selected-no-shared-date-or-owner-action", window
    )


def test_multi_category_creation_and_cancel_keep_selection_proposal_and_staged(
    qtbot, qapp, tmp_path, journey_artifacts
):
    from parsetrail.gui.v2_categories import V2CategoryDialog

    workspace, _evidence, _raw = workspace_rows(tmp_path, categories=False)
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    selected = {row.row_id for row in view.navigation.selected()}
    choose_combo(qtbot, view.purpose, "expense")
    enter_text(qtbot, review_reason(view), "Keep this shared draft through category setup")
    assert view.category.count() == 1 and view.manage_categories_button.isEnabled()
    modals = ModalSteps(qtbot)

    def add(dialog):
        enter_text(qtbot, dialog.add_name, "Meals")
        qtbot.mouseClick(dialog.add_button, Qt.LeftButton)
        close_dialog(qtbot, dialog)

    modals.arm((V2CategoryDialog, add))
    qtbot.mouseClick(view.manage_categories_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    assert {row.row_id for row in view.navigation.selected()} == selected
    assert view.purpose.currentData() == "expense" and "Meals" in view.category.currentText()
    assert review_reason(view).text() == "Keep this shared draft through category setup"
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged, category = dict(view.batch.staged), view.category.currentData()
    before = workspace.profile_path.read_bytes()
    modals.arm((V2CategoryDialog, lambda dialog: close_dialog(qtbot, dialog)))
    qtbot.mouseClick(view.manage_categories_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    assert {row.row_id for row in view.navigation.selected()} == selected
    assert view.batch.staged == staged and view.category.currentData() == category
    assert review_reason(view).text() == "Keep this shared draft through category setup"
    assert workspace.profile_path.read_bytes() == before
    assert "ALL" in view.batch.reason_scope.text() and "hidden" in view.batch.reason_scope.text()
    assert view.batch.propose(
        tuple(replace(view.model.rows[0], row_id=f"synthetic-{i}") for i in range(2001)), "expense", category
    )[1]
    assert view.batch.staged == staged
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-category-setup-returned-two-selected-staged-draft", window
    )


def test_refused_proposal_keeps_prior_income_batch_note_and_zero_selection_preview(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts
):
    workspace, _evidence, _raw = workspace_rows(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("income:salary", "Salary", "income")
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Deposit")
    choose_combo(qtbot, view.purpose, "income")
    choose_combo(qtbot, view.category, "income:salary")
    enter_text(qtbot, review_reason(view), "A: Reviewed the deposited income")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged, note = dict(view.batch.staged), view.batch.note()
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    enter_text(qtbot, review_reason(view), "B: Unstaged expense proposal")
    assert view.batch.note() == note
    select(qtbot, view, "Unassigned", Qt.ControlModifier)
    monkeypatch.setattr(QMessageBox, "information", lambda *_: QMessageBox.Ok)
    view.batch.stage_selected()
    assert view.batch.staged == staged and view.batch.note() == note
    enter_text(qtbot, view.navigation.search, "no-visible-row")
    assert not view.navigation.selected() and view.batch.preview_button.isEnabled()
    modals = ModalSteps(qtbot)

    def inspect(dialog):
        text = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "Deposit" in text and note in text and "Unstaged expense proposal" not in text
        assert "Coffee" not in text and "Tea" not in text
        JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
            "01-prior-income-note-survives-refused-new-proposal", dialog
        )
        qtbot.mouseClick(dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Cancel), Qt.LeftButton)

    modals.arm((QDialog, inspect))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    assert view.batch.staged == staged and view.batch.note() == note
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


def test_latent_unstaged_common_proposal_guards_document_close_and_restores(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _evidence, _raw = workspace_rows(tmp_path)
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    note = review_reason(view).text()
    select(qtbot, view, "Coffee", Qt.ControlModifier)
    select(qtbot, view, "Tea", Qt.ControlModifier)
    assert not view.navigation.selected() and review_reason(view).text() == note and not view.batch.staged
    assert view.has_unsaved_draft
    modals = ModalSteps(qtbot)

    def keep(dialog):
        assert "review" in dialog.text().lower()
        qtbot.mouseClick(dialog.button(QMessageBox.No), Qt.LeftButton)

    modals.arm((QMessageBox, keep))
    window.close()
    modals.finish()
    assert window.isVisible() and not view.jobs._closed
    select(qtbot, view, "Deposit")
    assert view.has_unsaved_draft  # Unrelated single-row context cannot hide the proposal.
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    assert review_reason(view).text() == note and view.category.currentData() == "expense:food"
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-latent-proposal-retained-after-cancelled-close", window
    )


@pytest.mark.parametrize("bad_date", ["", "20260317", "2026-99-09"], ids=["blank", "compact", "invalid"])
def test_single_card_stage_rejects_noncanonical_dates_without_changing_prior_stage(
    qtbot, tmp_path, monkeypatch, bad_date
):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
    (tmp_path / "workspace").mkdir()
    workspace = _workspace(tmp_path / "workspace")
    workspace.profile_path = path
    workspace.set_allow_assumed_posting_dates(True)
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    qtbot.addWidget(view, before_close_func=lambda widget: widget.request_cancel())
    view.show()
    qtbot.waitUntil(lambda: not view.review_pending, timeout=15000)
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    enter_text(qtbot, view.accounting_date, "2026-03-17")
    enter_text(qtbot, review_reason(view), "Confirmed one source date")
    enter_text(qtbot, view.batch.reason, "Original staged note")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    staged, note = dict(view.batch.staged), view.batch.note()
    assert staged
    enter_text(qtbot, view.accounting_date, bad_date)
    if not bad_date:
        qtbot.keyClick(view.accounting_date, Qt.Key_Backspace)
    enter_text(qtbot, view.batch.reason, "Unstaged new note")
    assert not view.action_button.isEnabled() and not view.batch.stage_button.isEnabled()
    refused = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: refused.append(text))
    view.batch.stage_selected()
    assert "YYYY-MM-DD" in refused[-1]
    assert view.batch.staged == staged and view.batch.note() == note


def test_posting_prior_batch_preserves_unrelated_current_common_proposal(qtbot, tmp_path):
    workspace, _evidence, _raw = workspace_rows(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_category_account("income:salary", "Salary", "income")
    window, view = open_review(qtbot, workspace)
    select(qtbot, view, "Deposit")
    choose_combo(qtbot, view.purpose, "income")
    choose_combo(qtbot, view.category, "income:salary")
    enter_text(qtbot, review_reason(view), "A: Income already staged")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    select(qtbot, view, "Coffee")
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choices(qtbot, view)
    enter_text(qtbot, review_reason(view), "B: Keep these unstaged purchases")
    ids = {row.row_id for row in view.navigation.selected()}
    modals = ModalSteps(qtbot)

    def accept(dialog):
        text = dialog.findChild(QPlainTextEdit).toPlainText()
        assert "A: Income already staged" in text and "Keep these unstaged" not in text
        button = next(
            b for b in dialog.findChild(QDialogButtonBox).buttons() if b.text().startswith("Confirm and post")
        )
        qtbot.mouseClick(button, Qt.LeftButton)

    modals.arm((QDialog, accept))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: not view.review_pending and not window.inventory_pending, timeout=15000)
    assert {row.row_id for row in view.navigation.selected()} == ids
    assert review_reason(view).text() == "B: Keep these unstaged purchases"
    assert view.purpose.currentData() == "expense" and view.category.currentData() == "expense:food"
    assert view.has_unsaved_draft and not view.batch.staged
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (1,)
        assert (
            store.reviewed_category_summary(kind="income", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 1000
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 0
        )
