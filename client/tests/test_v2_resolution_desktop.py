"""Source review can finish before counterpart resolution without hidden prerequisites."""

from dataclasses import replace

import pytest
from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest
from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview
from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CHASE_DEFINITION

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, choose_combo
from .test_v2_document_browser import wait_for_inventory
from .test_v2_import_automation import known_pdf as known_pdf
from .test_v2_import_automation import review_for
from .test_v2_loan_payments import PREFERENCES, _post, _profile
from .test_v2_multirow_review import select, workspace_rows
from .test_v2_origination import origination_profile
from .test_v2_origination import preview as origination_preview
from .test_v2_workspace_window import DEFINITION, _workspace
from .v2_institution_helpers import add_test_financial_account
from .v2_job_wait import wait_for_jobs


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050", "1280"])
def test_loan_posts_with_counterpart_unresolved_and_reference_explained(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    path = tmp_path / "loan.db"
    _bank, rows = _profile(path)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    workspace.set_allow_assumed_posting_dates(True)
    view = V2LoanPaymentReview(workspace)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert (view.width(), view.height()) == size
    assert view.bank.currentData() is None and "later" in view.bank.currentText()
    assert not view.rules.content.isVisible() and view.rules.button.text() == "Show details"
    qtbot.mouseClick(view.rules.button, Qt.LeftButton)
    assert view.rules.content.isVisible() and view.rules.button.text() == "Hide details"
    qtbot.mouseClick(view.rules.button, Qt.LeftButton)
    item = view.components.item(0, 0)
    qtbot.mouseClick(view.components.viewport(), Qt.LeftButton, pos=view.components.visualItemRect(item).center())
    wait_for_jobs(view)
    assert item.checkState() == Qt.Checked and view.preview.manifest.bank is None
    assert view.reference.text() and view.reason.text() == "Initial Review"
    assert view.confirm.isEnabled()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-lender-only-ready", view)
    view.reference.clear()
    assert not view.confirm.isEnabled() and "reference" in view.status.text().lower()
    artifacts.capture("02-reference-needed", view)
    view.reference.setText("Reviewed printed payment")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history() == ()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    wait_for_jobs(view)
    assert view.selected_event is not None and view.selected_event.manifest.bank is None
    assert "unresolved" in view.status.text().lower() and view.resolve_button.isVisible()
    artifacts.capture("03-lender-only-posted", view)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store._active_journal_entries()) == 1
        assert store._active_consumed()[rows[0]] == -22000
    requested = []
    view.transfers_requested.connect(requested.append)
    qtbot.mouseClick(view.resolve_button, Qt.LeftButton)
    assert requested == [rows[0]]
    view.close()


def test_identical_staged_choices_disable_stage_and_edits_reenable_it(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    workspace, evidence, _raw = workspace_rows(tmp_path)
    view = V2CashActivityReview(workspace.profile_path, evidence.source_sha256, workspace=workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    select(qtbot, view, "Coffee")
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    assert view.batch.stage_button.isEnabled()
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert not view.batch.stage_button.isEnabled() and view.batch.preview_button.isEnabled()
    view.batch.reason.setText("Reviewed again")
    assert view.batch.stage_button.isEnabled() and "Update" in view.batch.stage_button.text()
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert not view.batch.stage_button.isEnabled()
    select(qtbot, view, "Tea", Qt.ControlModifier)
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:food")
    assert view.batch.stage_button.isEnabled()
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    assert len(view.batch.staged) == 2 and not view.batch.stage_button.isEnabled()
    view.batch.clear()
    view.close()


def test_unique_account_assignment_goes_directly_to_required_preview(qtbot, known_pdf):
    workspace, source = known_pdf
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    review = review_for(workspace, source)
    assert all(group.automatic for group in review.groups)
    candidate = replace(review.recognition.candidates[0], attention_codes=("balance_verification_unavailable",))
    review = replace(review, recognition=replace(review.recognition, candidates=(candidate,)))
    request = ImportAccountReviewRequest(source, review, 1, 1)
    view = V2ImportAccountReview(review.institutions)
    qtbot.addWidget(view)
    view.present(request)
    assert view.pages.currentIndex() == 1 and view.import_button.isEnabled()
    assert not request.decided.is_set()
    assert all(view._states[group.group_id]["choice"] == group.suggested_account_id for group in review.groups)
    qtbot.mouseClick(view.back_button, Qt.LeftButton)
    assert view.pages.currentIndex() == 0
    view.finish_queue()


def test_pdf_import_identity_is_readonly_but_name_remains_editable(qtbot, tmp_path):
    path = tmp_path / "identity.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        account = next(item for item in store.financial_accounts() if item.id == "loan")
        account = replace(account, product_type="loan")
        store.update_financial_account(account)
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceAccountBindings WHERE ledger_account_id='loan'"
        ).fetchone()[0]
        store.lock_pdf_import_account(account.id, source)
    view = V2FinancialAccountDialog(existing=account, profile=path)
    qtbot.addWidget(view)
    view.show()
    assert not view.product.isEnabled() and view.institution.isReadOnly()
    assert not view.name.isReadOnly() and not view.save_button.isEnabled()
    view.name.setText("My vehicle loan")
    assert view.save_button.isEnabled()
    changed = view.account()
    assert changed.product_type == account.product_type and changed.institution_key == account.institution_key
    view.close()


def test_zero_review_mixed_with_expense_and_fresh_correction_reason(qtbot, tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Membership fee,$0.00,$1000.00\n"
        b"10/02/2026,Checking A,Coffee,-$4.00,$996.00\n"
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        add_test_financial_account(store, FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:fees", "Fees", "expense")
    view = V2CashActivityReview(workspace.profile_path, evidence.source_sha256, workspace=workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    for description in ("Membership fee", "Coffee"):
        select(qtbot, view, description)
        choose_combo(qtbot, view.purpose, "expense")
        choose_combo(qtbot, view.category, "expense:fees" if description == "Membership fee" else "expense:food")
        assert view.batch.stage_button.isEnabled()
        qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    modals = ModalSteps(qtbot)

    def confirm(dialog):
        assert "No journal entry" in dialog.findChild(QPlainTextEdit).toPlainText()
        button = next(
            button for button in dialog.findChild(QDialogButtonBox).buttons() if button.text().startswith("Confirm and")
        )
        qtbot.mouseClick(button, Qt.LeftButton)

    modals.arm((QDialog, confirm))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store._active_journal_entries()) == 1
        assert len(store.zero_amount_review_history()) == 1
    choose_combo(qtbot, view.navigation.status_filter, "all")
    select(qtbot, view, "Membership fee")
    assert view._zero_review(view._current()) is not None
    assert not view.reason.text() and view.saved_review_note.toPlainText() == "Initial Review"
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    choose_combo(qtbot, view.category, "expense:food")
    view.reason.setText("Correct fee classification")
    assert view.action_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    assert view.reason.text() == "Correct fee classification"
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert not view.reason.text() and view._zero_review(view._current()).category_id == "expense:food"
    view.reason.setText("Return to initial review")
    qtbot.mouseClick(view.withdraw_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert view._zero_review(view._current()) is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store._active_journal_entries()) == 1
        assert len(store.zero_amount_review_history()) == 3
    view.close()


def test_resolve_from_loan_modal_closes_it_and_opens_transfers_workspace(qtbot, tmp_path):
    path = tmp_path / "handoff.db"
    _bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, None, rows)
        source = event.manifest.components[0].source_sha256
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.show()
    wait_for_inventory(window)
    window._review_report_source(source, rows[0])
    landing = window._review_widget
    wait_for_jobs(landing)
    modals = ModalSteps(qtbot)

    def resolve(dialog):
        wait_for_jobs(dialog)
        assert "principal component" in dialog.context.text() and "2026-01-01" in dialog.context.text()
        assert dialog.resolve_button.isVisible()
        qtbot.mouseClick(dialog.resolve_button, Qt.LeftButton)

    modals.arm((V2LoanPaymentReview, resolve))
    qtbot.mouseClick(landing.action_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.navigation.currentRow() == window.TRANSFERS, timeout=15000)
    assert window._transfers_view is not None
    assert qapp_no_modal()
    window.close()


def qapp_no_modal():
    from PySide6.QtWidgets import QApplication

    return QApplication.activeModalWidget() is None


def test_card_zero_fee_needs_no_accounting_date_permission(qtbot, qapp, tmp_path, journey_artifacts):
    raw = b"%PDF-synthetic-zero-card"
    source_pages = pages()
    source_pages[0] = source_pages[0].replace("New Balance $30.00", "New Balance $20.00")
    source_pages[1] = source_pages[1].replace("PRIOR-DAY CHARGE 10.00", "MEMBERSHIP FEE 0.00")
    lines = page_lines(raw, source_pages, extraction_library="synthetic-pdf-1")
    evidence = from_card(parse_card_lines(CHASE_DEFINITION, lines), lines)
    path = tmp_path / "zero-card.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(raw, CHASE_DEFINITION, evidence, suffix=".pdf")
        add_test_financial_account(store, FinancialAccount("card", "Airline card", "liability", "chase"))
        store.add_category_account("expense:fees", "Fees", "expense")
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2CardPurchaseReview(workspace, evidence.source_sha256)
    qtbot.addWidget(view)
    view.resize(1050, 700)
    view.show()
    wait_for_jobs(view)
    select(qtbot, view, "MEMBERSHIP FEE")
    assert not view.accounting_date.isVisible() and not workspace.preferences().allow_assumed_posting_dates
    choose_combo(qtbot, view.purpose, "expense")
    choose_combo(qtbot, view.category, "expense:fees")
    qtbot.mouseClick(view.batch.stage_button, Qt.LeftButton)
    modals = ModalSteps(qtbot)

    def confirm(dialog):
        assert "No journal entry" in dialog.findChild(QPlainTextEdit).toPlainText()
        qtbot.mouseClick(
            next(
                button
                for button in dialog.findChild(QDialogButtonBox).buttons()
                if button.text().startswith("Confirm and")
            ),
            Qt.LeftButton,
        )

    modals.arm((QDialog, confirm))
    qtbot.mouseClick(view.batch.preview_button, Qt.LeftButton)
    modals.finish()
    wait_for_jobs(view)
    choose_combo(qtbot, view.navigation.status_filter, "all")
    select(qtbot, view, "MEMBERSHIP FEE")
    assert view._current().status == "Reviewed zero amount"
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("04-zero-card-fee-reviewed", view)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_journal_entries() == () and len(store.zero_amount_review_history()) == 1
    assert not workspace.preferences().allow_assumed_posting_dates
    view.close()


def test_origination_landing_tracks_posted_and_withdrawn_acquisition(qtbot, tmp_path):
    path = tmp_path / "origin-landing.db"
    _bank, row_id = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        source = store.origination_snapshot().rows[0].source_sha256
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert view._current().row_id == row_id and view.action_button.text() == "Review loan origination…"
    with V2ProfileStore.open(path) as store:
        event = store.post_loan_origination(origination_preview(store, row_id))
    view.refresh()
    wait_for_jobs(view)
    assert view.action_button.text() == "View loan origination"
    assert view.table.item(0, 5).text() == "Posted origination" and "Posted origination" in view.status.text()
    with V2ProfileStore.open(path) as store:
        store.withdraw_loan_origination(
            event.event_id, expected_version=event.version, reason="Review destination again"
        )
    view.refresh()
    wait_for_jobs(view)
    assert view.action_button.text() == "Review loan origination…" and "Review where" in view.status.text()
    assert view.request_cancel()
    view.close()


def test_matched_lender_only_manifest_displays_current_resolution_and_protects_correction(qtbot, tmp_path):
    path = tmp_path / "matched.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, None, rows)
        state = store.resolution_snapshot(preferences=PREFERENCES)
        store.resolve_transfer(
            "row:" + bank,
            event.event_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Matched selected bank payment",
        )
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2LoanPaymentReview(workspace, event_id=event.event_id)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert "transfer matched" in view.status.text() and "unresolved" not in view.status.text()
    assert view.resolve_button.text() == "View in Transfers…"
    view.reason.setText("Change reviewed lender posting")
    assert not view.confirm.isEnabled() and not view.withdraw.isEnabled()
    assert "Unlink" in view.status.text()
    assert "current bank relationship is tracked in Transfers" in view.history_details.toPlainText()
    view.close()


def test_vehicle_product_is_fixed_by_value_history(qtbot, tmp_path):
    path = tmp_path / "vehicle-identity.db"
    origination_profile(path)
    with V2ProfileStore.open(path, read_only=True) as store:
        account = next(item for item in store.financial_accounts() if item.id == "vehicle")
    view = V2FinancialAccountDialog(existing=account, profile=path)
    qtbot.addWidget(view)
    view.show()
    assert not view.product.isEnabled() and not view.name.isReadOnly()
    assert "Tangible asset classification" in view.product.toolTip()
    view.close()
