"""HSA cash scope and missing-receipt reviews use actual synthetic source facts."""

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .test_v2_settlement_review_dialog import _check
from .test_v2_transfers import BANK_DEFINITION


@pytest.fixture(scope="module")
def hsa_source():
    case = next(case for case in family_sources() if case.definition_name == "hsa-cash-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    return case.source, definition, build_source_evidence(case.source, definition, suffix=case.suffix)


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, message: pytest.fail(f"{title}: {message}"))
    return QApplication.instance() or QApplication([])


def profile(path, hsa_source, *, scope="cash_component"):
    content, definition, evidence = hsa_source
    with V2ProfileStore.create(path) as store:
        store.import_source(content, definition, evidence, suffix=".pdf")
        store.add_financial_account(
            FinancialAccount("hsa", "Health savings", "asset", "synthetic", tracking_scope=scope)
        )
        store.add_financial_account(
            FinancialAccount("investment", "Health savings", "asset", "synthetic", tracking_scope="account_total")
        )
        store.add_category_account("expense:review", "Reviewed expense", "expense")
        store.add_category_account("income:review", "Reviewed income", "income")
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "hsa")
    return evidence


def workspace(path):
    return V2Workspace.open(
        path, path.parent / "catalog", trusted_keys={}, preferences_path=path.parent / "preferences.json"
    )


def test_hsa_source_opening_review_is_component_only_cancel_and_withdraw(tmp_path, hsa_source, monkeypatch):
    from parsetrail.gui.v2_opening_review import V2OpeningReview
    from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview
    from PySide6.QtWidgets import QLabel, QMessageBox

    path = tmp_path / "opening.db"
    evidence = profile(path, hsa_source)
    with V2ProfileStore.open(path, read_only=True) as store:
        section = store.statement_source_review_snapshot("hsa", evidence.source_sha256).section
    review = V2StatementSourceReview(path, section)
    assert any("Cash-component assertions" in label.text() for label in review.findChildren(QLabel))
    review.opening.setCurrentIndex(review.opening.findData("reported"))
    review.closing.setCurrentIndex(review.closing.findData("reported"))
    review.timing.setChecked(True)
    review.posting_dates.setCurrentIndex(review.posting_dates.findData("reported"))
    review.reference.setText("Both cash component boundaries, exact printed dates")
    assert review.save.isEnabled()
    review.save.click()
    view = V2OpeningReview(workspace(path))
    assert "cash component" in view.candidate_label.text() and "whole HSA" in view.source_details.text()
    assert view.confirm.isEnabled()
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.confirm.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.confirm.click()
    assert "only the cash-component opening" in prompts[0]
    assert view.decision.amount_minor == 100000 and view.decision.tracking_scope == "cash_component"
    view.correction_reason.setText("Withdraw component opening independently")
    view.withdraw.click()
    assert view.decision.state == "withdrawn" and view.decision.amount_minor is None
    view.close()
    review.close()


@pytest.mark.parametrize(
    "row_index,purpose,category",
    [
        (1, "expense", "expense:review"),
        (1, "income_adjustment", "income:review"),
        (2, "income", "income:review"),
        (2, "expense_refund", "expense:review"),
    ],
)
def test_hsa_cash_purpose_explicit_unknown_source_text_and_withdrawal(
    tmp_path, hsa_source, monkeypatch, row_index, purpose, category
):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "cash.db"
    evidence = profile(path, hsa_source)
    view = V2CashActivityReview(path, evidence.source_sha256)
    assert len(view.model.rows) == 3
    assert all(row.status == "Ready for purpose review" for row in view.model.rows)
    assert "contributions" in view.note.text() and "cash-component" in view.note.text()
    view.table.selectRow(row_index)
    assert view.purpose.currentData() is None and not view.action_button.isEnabled()
    assert "cash component" in view.source_context.text()
    view.purpose.setCurrentIndex(view.purpose.findData(purpose))
    view.category.setCurrentIndex(view.category.findData(category))
    view.reason.setText("Explicit interpretation independent of source description")
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    assert view.action_button.isEnabled()
    view.action_button.click()
    assert "Only this cash component" in prompts[0]
    if row_index == 2:
        assert "Source description unavailable / unknown" in prompts[0]
        assert "Code-owned accounting label only" in prompts[0]
        assert "interest" not in prompts[0].lower()
        assert view.model.rows[2].description is None
        assert not view.model.rows[2].source_description_known
    with V2ProfileStore.open(path, read_only=True) as store:
        entry = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").entries[0]
        assert entry.posting_date.isoformat() == evidence.payload.accounts[0].rows[row_index].date.iso
        if row_index == 2:
            assert entry.description == "Reviewed HSA cash movement; source description unavailable"
        assert store.load_import(evidence.source_sha256).evidence == evidence
    view.reason.setText("Withdraw reviewed component interpretation")
    assert view.withdraw_button.isEnabled()
    view.withdraw_button.click()
    assert view.model.rows[row_index].entry_key is None
    view.close()


def test_hsa_whole_account_scope_is_refused_for_cash_and_source_opening(tmp_path, hsa_source):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
    from parsetrail.gui.v2_opening_review import V2OpeningReview

    path = tmp_path / "wrong-scope.db"
    evidence = profile(path, hsa_source, scope="account_total")
    cash = V2CashActivityReview(path, evidence.source_sha256)
    cash.table.selectRow(0)
    cash.reason.setText("Source scope must not become whole account")
    assert not cash.action_button.isEnabled()
    assert not cash.model.rows[0].allowed_purposes
    opening = V2OpeningReview(workspace(path))
    assert not opening.confirm.isEnabled()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    cash.close()
    opening.close()


def test_unbound_cash_row_has_unknown_scope_and_no_interpretation_controls(tmp_path, hsa_source):
    from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview

    path = tmp_path / "unbound.db"
    evidence = profile(path, hsa_source)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.clear_source_account_binding(
            evidence.source_sha256, section.source_identity, section.source_identity_form
        )
    view = V2CashActivityReview(path, evidence.source_sha256)
    view.table.selectRow(0)
    assert "unavailable until account assignment" in view.source_context.text()
    assert "Assign a financial account" in view.status.text()
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    view.close()


def settlement_view(path, event_id=None):
    from parsetrail.gui.v2_settlement_review import V2SettlementReview

    return V2SettlementReview(workspace(path), event_id=event_id)


def owned_form(view, outgoing):
    view.outgoing.setCurrentIndex(view.outgoing.findData(outgoing))
    view.expected_destination.setCurrentIndex(view.expected_destination.findData("investment"))
    view.expected_reference.setText("Independent owned investment account / transfer request")
    view.expected_ack.setChecked(True)
    view.reason.setText("Owned outflow observed; receipt history not yet available")


def receipt(path):
    content = (
        b"Date,Account,Description,Amount,ReportedBalance\n09/01/2026,Investment cash,Actual receipt,$100.00,$100.00\n"
    )
    evidence = build_source_evidence(content, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(content, BANK_DEFINITION, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Investment cash", "opaque", "investment")
    return evidence.payload.rows[0].row_id


def test_missing_receipt_requires_explicit_ownership_cancel_preview_post_reopen_and_legacy_history(
    tmp_path, hsa_source, monkeypatch
):
    from parsetrail.gui.v2_transfer_review import V2TransferReview
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "missing.db"
    evidence = profile(path, hsa_source)
    outgoing = evidence.payload.accounts[0].rows[1].row_id
    view = settlement_view(path)
    assert not view.expected_panel.isVisible() and view.expected_destination.currentData() is None
    view.outgoing.setCurrentIndex(view.outgoing.findData(outgoing))
    assert not view.expected_panel.isHidden() and view.expected_destination.currentData() is None
    assert view.expected_destination.findData("hsa") == -1
    assert (
        "account total" in view.expected_destination.itemText(view.expected_destination.findData("investment")).lower()
    )
    view.reason.setText("Explicit missing receipt review")
    view.expected_destination.setCurrentIndex(view.expected_destination.findData("investment"))
    view.expected_reference.setText("Independent ownership reference")
    assert view.preview is None and not view.confirm.isEnabled()
    view.expected_ack.setChecked(True)
    assert view.preview is not None and view.confirm.isEnabled()
    assert view.preview.settlement.incoming == () and len(view.preview.entries) == 1
    assert "NO RECEIPT EVIDENCE" in view.preview_details.toPlainText()
    assert "no destination receipt or positive destination posting" in view.preview_details.toPlainText()
    assert {p.account_id for p in view.preview.entries[0].postings} == {"hsa", "internal:transfer-clearing:USD"}
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.confirm.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.confirm.click()
    assert "NO RECEIPT EVIDENCE" in prompts[0] and "metadata, not a printed source fact" in prompts[0]
    event = view.selected_event
    assert event.settlement.expected_destination.account_id == "investment"
    assert event.settlement.expected_destination.tracking_scope == "account_total"
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_consumed() == {outgoing: -10000}
        assert not store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").entries
        assert not any(
            posting.account_id == "investment"
            for entry in store._active_journal_entries()
            for posting in entry.postings
        )
    view.close()
    reopened = settlement_view(path, event.event_id)
    assert reopened.expected_ack.isChecked() and reopened.expected_destination.currentData() == "investment"
    assert "NO RECEIPT EVIDENCE" in reopened.history_details.toPlainText()
    assert not reopened.confirm.isEnabled()
    legacy = V2TransferReview(workspace(path))
    legacy.event_table.selectRow(0)
    assert "Receipt missing" in legacy.event_table.item(0, 5).text()
    assert "investment" in legacy.event_details.toPlainText() and "account total" in legacy.event_details.toPlainText()
    assert "no destination receipt" in legacy.event_details.toPlainText()
    reopened.reason.setText("Withdraw the entire outflow awaiting receipt")
    reopened.withdraw.click()
    assert reopened.selected_event.status == "cancelled"
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_consumed() == {} and store._active_journal_entries() == ()
    reopened.close()
    legacy.close()


def test_later_actual_receipt_clears_expectation_and_replaces_whole_event_then_withdraws(
    tmp_path, hsa_source, monkeypatch
):
    from datetime import date

    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "replace.db"
    evidence = profile(path, hsa_source)
    outgoing = evidence.payload.accounts[0].rows[1].row_id
    view = settlement_view(path)
    owned_form(view, outgoing)
    view.confirm.click()
    old_id = view.selected_event.event_id
    incoming = receipt(path)
    view.refresh()
    _check(view, incoming)
    assert view.expected_panel.isHidden() and view.expected_destination.currentData() is None
    assert not view.expected_ack.isChecked() and not view.expected_reference.text()
    assert view.preview.settlement.expected_destination is None
    assert view.preview.settlement.residual_minor == 0
    view.reason.setText("Actual receipt now reviewed under exact source date")
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.confirm.click()
    assert "Inverse original" in prompts[0] and "Replacement entry effects only" in prompts[0]
    assert "2026-08-20" in prompts[0] and "2026-09-01" in prompts[0]
    assert view.selected_event.event_id != old_id and view.selected_event.settlement.expected_destination is None
    with V2ProfileStore.open(path, read_only=True) as store:
        history = store.transfer_history()
        assert history[1].status == "replaced" and history[1].settlement.expected_destination.account_id == "investment"
        positions = store.account_positions(as_of=date(2026, 9, 2))
        assert positions.transfer_clearing_debit_minor == 0
        assert {p.account_id: p.recorded_debit_minor for p in positions.accounts} == {
            "hsa": -10000,
            "investment": 10000,
        }
    view.reason.setText("Withdraw whole receipt replacement")
    view.withdraw.click()
    assert view.selected_event.status == "cancelled"
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_consumed() == {}
        assert all(p.recorded_debit_minor == 0 for p in store.account_positions(as_of=date(2026, 9, 2)).accounts)
    view.close()


def test_missing_receipt_failed_reload_clears_expected_destination_and_actions(tmp_path, hsa_source, monkeypatch):
    from parsetrail.core.v2_profile_store import ProfileFormatError

    path = tmp_path / "read-error.db"
    evidence = profile(path, hsa_source)
    view = settlement_view(path)
    owned_form(view, evidence.payload.accounts[0].rows[1].row_id)
    assert view.preview is not None and view.confirm.isEnabled()

    def unavailable(*_args, **_kwargs):
        raise ProfileFormatError("transfer_history_integrity")

    monkeypatch.setattr(V2ProfileStore, "settlement_review_snapshot", unavailable)
    view.refresh()
    assert view.snapshot is None and view.preview is None
    assert not view.confirm.isEnabled() and not view.withdraw.isEnabled()
    assert view.expected_panel.isHidden() and not view.expected_ack.isChecked()
    assert view.expected_destination.currentData() is None and not view.expected_reference.text()
    assert "unavailable" in view.status.text().lower()
    view.close()


def test_reconciliation_live_confirmation_and_saved_history_are_explicit_cash_component(
    tmp_path, hsa_source, monkeypatch
):
    from parsetrail.core.v2_preferences import V2Preferences
    from parsetrail.core.v2_settlements import ExpectedOwnedDestination
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
    from PySide6.QtWidgets import QLabel, QMessageBox

    path = tmp_path / "component-check.db"
    evidence = profile(path, hsa_source)
    rows = evidence.payload.accounts[0].rows
    with V2ProfileStore.open(path) as store:
        store.record_statement_source_review(
            "hsa",
            evidence.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Exact cash-component endpoints and observed posting dates",
        )
        store.post_reviewed_opening("hsa")
        for row in (rows[0], rows[2]):
            store.post_reviewed_cash_category(
                row.row_id,
                "income:review",
                purpose="income",
                reason="Explicit independently reviewed cash receipt purpose",
            )
        frame = store.settlement_review_snapshot(preferences=V2Preferences())
        store.post_reviewed_settlement(
            rows[1].row_id,
            (),
            preferences=V2Preferences(),
            expected_destination=ExpectedOwnedDestination(
                "investment", "Reviewed owned destination, receipt missing", True
            ),
            expected_basis_sha256=frame.basis_sha256,
            reason="Source cash outflow only; retain unresolved clearing",
        )
    view = V2StatementCoverageDialog(path)
    assert any("exact HSA cash-component rule" in label.text() for label in view.findChildren(QLabel))
    view.reconciliation_table.selectRow(0)
    check = view.reconciliation_model.rows[0]
    assert check.reconciled and check.balance_scope == check.tracking_scope == "cash_component"
    assert "Reconciled (cash component)" == view.reconciliation_model.data(view.reconciliation_model.index(0, 2))
    assert "only to the cash component" in view.reconciliation_details.text()
    assert "does not reconcile the whole HSA" in view.reconciliation_details.text()
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.save_reconciliation_button.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.save_reconciliation_button.click()
    assert "Source balance scope: cash component" in prompts[0] and "investment portfolio" in prompts[0]
    assert "only to the cash component" in view.reconciliation_history_details.text()
    view.close()
    reopened = V2StatementCoverageDialog(path)
    assert "tracked account scope: cash component" in reopened.reconciliation_history_details.text()
    reopened.close()


@pytest.mark.parametrize("change", ["preference", "destination"])
def test_missing_receipt_confirmation_stale_context_resets_without_posting(tmp_path, hsa_source, monkeypatch, change):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "stale.db"
    evidence = profile(path, hsa_source)
    view = settlement_view(path)
    owned_form(view, evidence.payload.accounts[0].rows[1].row_id)
    assert view.confirm.isEnabled()

    def concurrent_change(*_args):
        if change == "preference":
            view.workspace.set_allow_assumed_posting_dates(True)
        else:
            with V2ProfileStore.open(path) as store:
                store.update_financial_account(
                    FinancialAccount("investment", "Renamed independently", "asset", "synthetic")
                )
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent_change)
    view.confirm.click()
    assert not view.confirm.isEnabled() and view.preview is None
    assert not view.expected_ack.isChecked() and not view.expected_reference.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.transfer_history() == () and store._active_consumed() == {}
    if change == "preference":
        assert "preferences changed" in view.status.text()
    else:
        assert "not recorded" in view.status.text()
    view.close()
