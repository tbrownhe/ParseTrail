"""Bounded Yamaha source facts remain separate from reviewed register purposes."""

from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources


@pytest.fixture(scope="module")
def source():
    case = next(case for case in family_sources() if case.definition_name == "yamaha-card-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    return case.source, definition, build_source_evidence(case.source, definition, suffix=case.suffix)


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, text: pytest.fail(f"{title}: {text}"))
    return QApplication.instance() or QApplication([])


def profile(path, source, *, kind="liability", scope="account_total", bind=True):
    content, definition, evidence = source
    bank_definition = (
        Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
    ).read_bytes()
    bank_raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n02/08/2026,Checking A,Owned repayment,-$20.00,Unavailable\n"
    )
    bank = build_source_evidence(bank_raw, bank_definition, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(content, definition, evidence, suffix=".pdf")
        store.import_source(bank_raw, bank_definition, bank, suffix=".csv")
        store.add_financial_account(
            FinancialAccount(
                "register",
                "Motor account",
                "liability" if kind == "liability" else "asset",
                "synthetic",
                tracking_scope=scope,
            )
        )
        store.add_financial_account(FinancialAccount("bank", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:vehicle", "Vehicle", "expense")
        store.add_category_account("expense:other", "Other expense", "expense")
        store.add_category_account("income:other", "Other income", "income")
        if bind:
            section = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "register"
            )
        store.bind_source_account(bank.source_sha256, "Checking A", "opaque", "bank")
    return evidence, bank.payload.rows[0].row_id


def workspace(path):
    return V2Workspace.open(
        path, path.parent / "catalog", trusted_keys={}, preferences_path=path.parent / "preferences.json"
    )


def dialog(path, source_sha256):
    from parsetrail.gui.v2_liability_register_review import V2LiabilityRegisterReview

    return V2LiabilityRegisterReview(workspace(path), source_sha256)


def form(view, *, row=0, purpose="expense", category="expense:vehicle"):
    view.table.selectRow(row)
    view.purpose.setCurrentIndex(view.purpose.findData(purpose))
    view.category.setCurrentIndex(view.category.findData(category))
    view.reason.setText("Explicit register purpose and category; components remain unavailable")


def test_both_actual_dates_fixed_posting_no_assumptions_cancel_post_reopen(tmp_path, source, monkeypatch):
    from types import SimpleNamespace

    from parsetrail.gui import v2_card_purchase_review as shared
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "register.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    assert not view.workspace.preferences().allow_assumed_posting_dates
    assert not view.assumed_dates.isVisible() and view.accounting_date.isReadOnly()
    assert "register" in view.windowTitle().lower()
    view.table.selectRow(0)
    assert view.model.data(view.model.index(0, 0)) == "2026-02-05"
    assert "2026-02-07" in view.model.data(view.model.index(0, 1))
    assert "derived" in view.model.data(view.model.index(0, 1))
    assert view.purpose.currentData() is None and view.category.currentData() is None
    assert "principal" in view.source_context.text() and "unavailable" in view.source_context.text()
    assert view.source_context.textFormat() == Qt.PlainText
    previews = []
    monkeypatch.setattr(
        shared,
        "preview_saved_source",
        lambda *args, **kwargs: previews.append(args[1]) or SimpleNamespace(exec=lambda: None),
    )
    view.preview_source_button.click()
    assert previews == [evidence.source_sha256]
    form(view)
    assert view.action_button.isEnabled()
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.action_button.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: prompts.append(text) or QMessageBox.Yes)
    view.action_button.click()
    assert "2026-02-05" in prompts[0] and "2026-02-07" in prompts[0] and "derived" in prompts[0]
    assert "reviewed card" not in prompts[0] and "principal/interest" in prompts[0]
    with V2ProfileStore.open(path, read_only=True) as store:
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="register")
        assert frame.entries[0].posting_date == date(2026, 2, 7)
        assert frame.entries[0].postings[0].amount_minor == -1000
        assert frame.entries[0].postings[1].amount_minor == 1000
        assert all(category.id != "builtin:loan-interest" for category in store.category_accounts())
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.loan_history() == ()
    view.close()
    reopened = dialog(path, evidence.source_sha256)
    reopened.table.selectRow(0)
    assert reopened.model.rows[0].entry_key.startswith("review:register:")
    assert reopened.purpose.currentData() == "expense" and not reopened.purpose.isEnabled()
    assert not reopened.workspace.preferences().allow_assumed_posting_dates
    reopened.close()


def test_register_category_correction_preserves_class_date_and_whole_liability_then_withdraw_repost(
    tmp_path, source, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "correction.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)
    view.action_button.click()
    first = view.model.rows[0].entry_key
    view.category.setCurrentIndex(view.category.findData("expense:other"))
    view.reason.setText("Explicit category-only register correction")
    assert view.purpose.currentData() == "expense" and not view.purpose.isEnabled()
    view.accounting_date.setText("2026-02-06")
    assert not view.action_button.isEnabled()
    view.accounting_date.setText("2026-02-07")
    assert view.action_button.isEnabled()
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: prompts.append(text) or QMessageBox.Yes)
    view.action_button.click()
    assert "Replacement entry effects only" in prompts[0] and "$0.00 net account movement" in prompts[0]
    assert "principal/interest" in prompts[0]
    assert view.model.rows[0].entry_key != first
    with V2ProfileStore.open(path, read_only=True) as store:
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 1000
        )
        assert all(entry.posting_date == date(2026, 2, 7) for entry in store._active_journal_entries())
    view.reason.setText("Withdraw register interpretation before fresh review")
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.withdraw_button.click()
    assert path.read_bytes() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    view.withdraw_button.click()
    assert view.model.rows[0].entry_key is None and view.purpose.isEnabled()
    assert "withdraw" in view.history_details.text().lower()
    form(view, purpose="income_adjustment", category="income:other")
    view.action_button.click()
    assert view.model.rows[0].purpose == "income_adjustment" and view.model.rows[0].entry_key != first
    view.close()


@pytest.mark.parametrize("purpose,category", [("expense_refund", "expense:vehicle"), ("income", "income:other")])
def test_positive_register_credit_never_infers_refund_or_repayment(tmp_path, source, purpose, category):
    path = tmp_path / "credit.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    view.table.selectRow(1)
    assert view.purpose.currentData() is None and not view.action_button.isEnabled()
    assert view.accounting_date.text() == "2026-02-10"
    form(view, row=1, purpose=purpose, category=category)
    assert view.action_button.isEnabled()
    view.action_button.click()
    assert view.model.rows[1].purpose == purpose
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.transfer_history() == () and store.loan_history() == ()
        assert store._active_journal_entries()[0].postings[0].amount_minor == 2000
    view.close()


@pytest.mark.parametrize(
    "kind,scope,bind",
    [
        ("asset", "account_total", True),
        ("liability", "principal_component", True),
        ("liability", "account_total", False),
    ],
)
def test_register_wrong_financial_scope_or_unbound_is_visible_and_blocked(tmp_path, source, kind, scope, bind):
    path = tmp_path / "blocked.db"
    evidence, _bank = profile(path, source, kind=kind, scope=scope, bind=bind)
    before = path.read_bytes()
    view = dialog(path, evidence.source_sha256)
    view.table.selectRow(0)
    view.reason.setText("Source scope must be explicitly eligible")
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    assert view.purpose.currentData() is None
    assert path.read_bytes() == before
    assert (
        "unavailable" in view.source_context.text().lower()
        if not bind
        else scope.replace("_", " ") in view.source_context.text()
    )
    view.close()


def test_register_stale_confirmation_and_failed_read_clear_authoring_state(tmp_path, source, monkeypatch):
    from parsetrail.core.v2_profile_store import ProfileFormatError
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "stale.db"
    evidence, _bank = profile(path, source)
    view = dialog(path, evidence.source_sha256)
    form(view)

    def concurrent(*_args):
        with V2ProfileStore.open(path) as store:
            store.update_financial_account(
                FinancialAccount("register", "Changed register name", "liability", "synthetic")
            )
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: warnings.append(text))
    view.action_button.click()
    assert warnings and view.model.rows[0].entry_key is None
    assert not view.action_button.isEnabled() and not view.reason.text()

    def unavailable(*_args, **_kwargs):
        raise ProfileFormatError("source_interpretation_history_integrity")

    monkeypatch.setattr(V2ProfileStore, "source_interpretation_snapshot", unavailable)
    view.refresh()
    assert view.basis is None and view.model.rowCount() == 0
    assert not view.action_button.isEnabled() and not view.withdraw_button.isEnabled()
    view.close()


def test_owned_register_repayment_is_neutral_whole_liability_with_separate_dates_no_extra_expense(
    tmp_path, source, monkeypatch
):
    from parsetrail.gui.v2_settlement_review import V2SettlementReview
    from parsetrail.gui.v2_transfer_review import V2TransferReview
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "repayment.db"
    evidence, bank = profile(path, source)
    register = dialog(path, evidence.source_sha256)
    form(register)
    register.action_button.click()
    register.close()
    view = V2TransferReview(workspace(path))
    assert not view.assumed_dates.isChecked()
    assert len(view.candidates) == 1 and view.candidates[0].kind == "liability payment"
    pair = view.candidates[0]
    assert pair.outgoing.row_id == bank and pair.incoming.row_id == evidence.payload.accounts[0].rows[1].row_id
    view.table.selectRow(0)
    view.note.setText("Owned whole-liability repayment from both actual sources")
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: prompts.append(text) or QMessageBox.Yes)
    view.confirm.click()
    assert "liability payment" in prompts[0] and "card payment" not in prompts[0]
    assert "2026-02-08" in prompts[0] and "2026-02-10" in prompts[0] and "derived" in prompts[0]
    with V2ProfileStore.open(path, read_only=True) as store:
        event = store.transfer_history()[0]
        assert event.pair.kind == event.settlement.kind == "liability payment"
        assert store.account_positions(as_of=date(2026, 2, 9)).transfer_clearing_debit_minor == 2000
        assert store.account_positions(as_of=date(2026, 2, 10)).transfer_clearing_debit_minor == 0
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 1000
        )
        assert store.loan_history() == () and all(
            category.id != "builtin:loan-interest" for category in store.category_accounts()
        )
    full = V2SettlementReview(workspace(path), event_id=event.event_id)
    assert "liability payment" in full.mode.currentText()
    from PySide6.QtWidgets import QLabel

    assert any("principal/interest split" in label.text() for label in full.findChildren(QLabel))
    assert "liability owed" in full.history_details.toPlainText() or "amount owed" in full.history_details.toPlainText()
    full.reason.setText("Withdraw whole register repayment")
    full.withdraw.click()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.transfer_history()[0].status == "cancelled"
        assert store._active_consumed() == {evidence.payload.accounts[0].rows[0].row_id: -1000}
    full.close()
    view.close()


def test_workspace_register_action_has_exact_source_and_import_busy_guard(tmp_path, source, monkeypatch):
    from parsetrail.gui.v2_liability_register_review import V2LiabilityRegisterReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    path = tmp_path / "workspace.db"
    evidence, _bank = profile(path, source)
    window = V2WorkspaceWindow(workspace(path))
    window.refresh(select_source=evidence.source_sha256)
    opened = []
    monkeypatch.setattr(V2LiabilityRegisterReview, "exec", lambda view: opened.append(view.source_sha256) or 0)
    assert window.register_review_action.isEnabled() and not window.card_review_button.isEnabled()
    window.register_review_action.trigger()
    assert opened == [evidence.source_sha256]
    window.import_worker = object()
    window.refresh(select_source=evidence.source_sha256)
    assert not window.register_review_action.isEnabled()
    window._review_register_activity()
    assert opened == [evidence.source_sha256]
    window.import_worker = None
    with V2ProfileStore.open(path, read_only=True) as store:
        bank_source = next(source_id for source_id in store.source_ids() if source_id != evidence.source_sha256)
    window.refresh(select_source=bank_source)
    assert not window.register_review_action.isEnabled()
    window._review_register_activity()
    assert opened == [evidence.source_sha256]
    window.close()


def test_wrong_family_register_entry_stays_pending_without_card_alias_admission(tmp_path, source):
    path = tmp_path / "wrong-family.db"
    evidence, _bank = profile(path, source)
    with V2ProfileStore.open(path, read_only=True) as store:
        bank_source = next(source_id for source_id in store.source_ids() if source_id != evidence.source_sha256)
    before = path.read_bytes()
    view = dialog(path, bank_source)
    view.table.selectRow(0)
    assert "Outside supported liability register scope" in view.status.text()
    assert view.purpose.currentData() is None and not view.action_button.isEnabled()
    assert path.read_bytes() == before
    view.close()


def test_register_historical_withdrawal_retry_preserves_fresh_interpretation(tmp_path, source):
    path = tmp_path / "retry.db"
    evidence, _bank = profile(path, source)
    current = dialog(path, evidence.source_sha256)
    form(current)
    current.action_button.click()
    oldkey = current.model.rows[0].entry_key
    stale = dialog(path, evidence.source_sha256)
    stale.table.selectRow(0)
    stale.reason.setText("Withdraw this exact register interpretation")
    current.reason.setText("Withdraw this exact register interpretation")
    current.withdraw_button.click()
    form(current)
    current.action_button.click()
    freshkey = current.model.rows[0].entry_key
    assert freshkey != oldkey
    stale.withdraw_button.click()
    assert stale.model.rows[0].entry_key == freshkey and "current posting state" in stale.status.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_consumed() == {evidence.payload.accounts[0].rows[0].row_id: -1000}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 1000
        )
    current.close()
    stale.close()
