"""Full evidenced loan review uses actual services and disposable synthetic profiles."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core.v2_loan_payments import INTEREST
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources
from devtools.parser_engine_pilot.test_wells_loan_lines import DEFINITION as WELLS_DEFINITION
from devtools.parser_engine_pilot.test_wells_loan_lines import parse as wells_evidence

from .test_v2_loan_payments import _profile


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, text: pytest.fail(f"{title}: {text}"))
    return QApplication.instance() or QApplication([])


def workspace(path):
    return V2Workspace.open(
        path, path.parent / "catalog", trusted_keys={}, preferences_path=path.parent / "preferences.json"
    )


def dialog(path, event_id=None):
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

    return V2LoanPaymentReview(workspace(path), event_id=event_id)


def check(view, row_id):
    from PySide6.QtCore import Qt

    for index in range(view.components.rowCount()):
        item = view.components.item(index, 0)
        if item.data(Qt.UserRole) == row_id:
            item.setCheckState(Qt.Checked)
            return
    pytest.fail("Exact loan row must be reachable")


def form(view, bank_id, loan_ids):
    if not view.assumed_dates.isChecked():
        view.assumed_dates.click()
    view.bank.setCurrentIndex(view.bank.findData(bank_id))
    for row_id in loan_ids:
        check(view, row_id)
    view.reference.setText("Inspected bank outflow and full printed principal / interest")
    view.reason.setText("Explicit loan payment review; no inferred counterpart or opening")


def test_empty_profile_and_unavailable_read_clear_all_actions_without_writes(tmp_path, monkeypatch):
    path = tmp_path / "empty.db"
    with V2ProfileStore.create(path):
        pass
    before = path.read_bytes()
    view = dialog(path)
    assert view.snapshot is not None and view.components.rowCount() == 0
    assert view.bank.currentData() is None and not view.assumed_dates.isChecked()
    assert not view.confirm.isEnabled() and not view.withdraw.isEnabled()
    assert not view.open_bank.isEnabled() and not view.open_component.isEnabled()
    assert view.profile_path.isReadOnly() and path.read_bytes() == before

    def unavailable(*_args, **_kwargs):
        raise ProfileFormatError("loan_history_integrity")

    monkeypatch.setattr(V2ProfileStore, "loan_review_snapshot", unavailable)
    view.refresh()
    assert view.snapshot is None and view.preview is None and view.components.rowCount() == 0
    assert not view.confirm.isEnabled() and not view.withdraw.isEnabled()
    assert not view.open_history_source.isEnabled()
    assert "could not be verified" in view.status.text()
    view.close()


def test_capital_date_preference_exact_preview_source_inspection_cancel_post_and_reopen(tmp_path, monkeypatch):
    from parsetrail.gui import v2_loan_payment_review as module
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "capital.db"
    bank, rows = _profile(path)
    view = dialog(path)
    assert not view.assumed_dates.isChecked() and view.bank.currentData() is None
    assert "default-off" in view.components.item(0, 7).text()
    assert not view.components.item(0, 0).flags() & Qt.ItemIsEnabled
    view.components.selectRow(0)
    assert "observed activity date" in view.source_details.toPlainText()
    assert "NOT a reported posting date" in view.source_details.toPlainText()
    form(view, bank, rows)
    assert view.confirm.isEnabled()
    assert (view.preview.manifest.principal_minor, view.preview.manifest.interest_minor) == (20000, 2000)
    assert [entry.posting_date for entry in view.preview.entries] == [date(2026, 1, 14), date(2026, 1, 15)]
    view.components.selectRow(0)
    assert "signed raw gross -$220.00" in view.source_details.toPlainText()
    assert "derived principal allocation" in view.source_details.toPlainText()
    assert "Normalized financial principal debit $200.00" in view.source_details.toPlainText()
    previews = []
    monkeypatch.setattr(
        module,
        "preview_saved_source",
        lambda *args, **kwargs: previews.append(args[1]) or SimpleNamespace(exec=lambda: None),
    )
    view.open_bank.click()
    view.open_component.click()
    assert previews == [view.preview.manifest.bank.source_sha256, view.preview.manifest.components[0].source_sha256]
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.confirm.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: prompts.append(text) or QMessageBox.Yes)
    view.confirm.click()
    event = view.selected_event
    assert event is not None and event.status == "active"
    assert "NOT reported posting" in prompts[0] and "gross payment is not a second expense" in prompts[0]
    assert not view.confirm.isEnabled()
    with V2ProfileStore.open(path, read_only=True) as store:
        positions = store.account_positions(as_of=date(2026, 1, 14))
        assert positions.transfer_clearing_debit_minor == 22000
        assert all(account.position_debit_minor is None for account in positions.accounts)
        assert store._active_consumed() == {bank: -22000, rows[0]: -22000}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 2000
        )
    view.close()
    reopened = dialog(path, event.event_id)
    assert "Full raw source use -$220.00" in reopened.history_details.toPlainText()
    assert (
        event.event_id in reopened.history_details.toPlainText()
        and "principal component" in reopened.history_details.toPlainText()
    )
    assert reopened.history_source.count() == 2 and reopened.open_history_source.isEnabled()
    reopened.close()


@pytest.mark.parametrize("variant", ["wells", "wells_interest_only", "mohela", "mohela_zero_interest"])
def test_explicit_complete_source_shapes_and_zero_components(tmp_path, variant):
    path = tmp_path / "shape.db"
    if variant.startswith("wells"):
        bank, rows = _profile(
            path,
            amount=100 if variant.endswith("only") else 2100,
            evidence=wells_evidence(),
            definition=WELLS_DEFINITION,
            raw=b"%PDF-synthetic-loan",
        )
        selected = (rows[0],) if variant.endswith("only") else rows
        expected = (0, 100) if variant.endswith("only") else (2000, 100)
    else:
        name = (
            "mohela-pilot-definition.json" if variant.endswith("interest") else "mohela-account-history-definition.json"
        )
        case = next(case for case in family_sources() if case.definition_name == name)
        definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / name).read_bytes()
        evidence = build_source_evidence(case.source, definition, suffix=case.suffix)
        zero = variant.endswith("interest")
        bank, rows = _profile(
            path, amount=5000 if zero else 10000, evidence=evidence, definition=definition, raw=case.source
        )
        selected = (rows[1],) if zero else (rows[0],)
        expected = (5000, 0) if zero else (8000, 2000)
    view = dialog(path)
    form(view, bank, selected)
    assert (
        view.confirm.isEnabled()
        and (view.preview.manifest.principal_minor, view.preview.manifest.interest_minor) == expected
    )
    assert len(view.preview.manifest.components) == len(selected)
    view.confirm.click()
    assert view.selected_event.status == "active"
    with V2ProfileStore.open(path, read_only=True) as store:
        entries = store._active_journal_entries()
        assert not any(posting.amount_minor == 0 for entry in entries for posting in entry.postings)
        assert any(posting.account_id == INTEREST for entry in entries for posting in entry.postings) == bool(
            expected[1]
        )
        if not expected[1]:
            assert all(category.id != INTEREST for category in store.category_accounts())
        if not expected[0]:
            assert store.connection.execute("SELECT count(*) FROM JournalDerivedAllocations").fetchone() == (0,)
    view.close()


@pytest.mark.parametrize("mutation", ["preference", "binding", "read_failure"])
def test_confirmation_changed_context_or_failure_clears_stale_controls(tmp_path, monkeypatch, mutation):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "stale.db"
    bank, rows = _profile(path)
    view = dialog(path)
    form(view, bank, rows)

    def concurrent(*_args):
        if mutation == "preference":
            view.workspace.set_allow_assumed_posting_dates(False)
        elif mutation == "binding":
            with V2ProfileStore.open(path) as store:
                account = store.financial_accounts()[0]
                store.update_financial_account(
                    FinancialAccount(
                        account.id,
                        "Renamed after loaded preview",
                        account.kind,
                        account.institution_key,
                        tracking_scope=account.tracking_scope,
                    )
                )
        else:
            monkeypatch.setattr(
                V2ProfileStore,
                "post_reviewed_loan_payment",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(ProfileFormatError("loan_history_integrity")),
            )
            monkeypatch.setattr(
                V2ProfileStore,
                "loan_review_snapshot",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(ProfileFormatError("loan_history_integrity")),
            )
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent)
    view.confirm.click()
    assert not view.confirm.isEnabled() and view.preview is None and view.bank.currentData() is None
    assert not view.reference.text() and not view.reason.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history() == () and store._active_consumed() == {}
    if mutation == "preference":
        assert not view.assumed_dates.isChecked() and "preferences changed" in view.status.text()
    view.close()


def test_wrong_scope_and_unbound_sources_stay_inspectable_without_posting(tmp_path):
    path = tmp_path / "scope.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        store.update_financial_account(
            FinancialAccount("loan", "Whole obligation", "liability", "synthetic", tracking_scope="account_total")
        )
    view = dialog(path)
    view.assumed_dates.click()
    view.components.selectRow(0)
    assert "principal component" in view.components.item(0, 7).text()
    assert "unavailable components" in view.source_details.toPlainText()
    assert view.open_component.isEnabled() and not view.confirm.isEnabled()
    view.close()


def test_workspace_menu_busy_guard_and_preference_synchronization(tmp_path, monkeypatch):
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

    path = tmp_path / "workspace.db"
    _profile(path)
    work = workspace(path)
    window = V2WorkspaceWindow(work)
    opened = []

    def inspect(view):
        opened.append(view.workspace.profile_path)
        view.workspace.set_allow_assumed_posting_dates(True)
        return 0

    monkeypatch.setattr(V2LoanPaymentReview, "exec", inspect)
    window.loan_payment_action.trigger()
    assert opened == [path] and window.assumed_posting_action.isChecked()
    window.import_worker = object()
    window.refresh()
    assert not window.loan_payment_action.isEnabled()
    window._review_loan_payments()
    assert opened == [path]
    window.import_worker = None
    window.close()


def second_bank_source(path):
    definition = (
        Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
    ).read_bytes()
    raw = b"Date,Account,Description,Amount,ReportedBalance\n01/13/2026,Corrected checking,Loan payment,-$220.00,Unavailable\n"
    evidence = build_source_evidence(raw, definition, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.add_financial_account(
            FinancialAccount("other-bank", "Checking", "asset", "synthetic", full_account_number="2222")
        )
        store.import_source(raw, definition, evidence, suffix=".csv")
        store.bind_source_account(evidence.source_sha256, "Corrected checking", "opaque", "other-bank")
    return evidence.payload.rows[0].row_id


def test_whole_replacement_retains_dates_proofs_inverses_and_fresh_derived_ids(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "replace.db"
    bank, rows = _profile(path)
    other = second_bank_source(path)
    view = dialog(path)
    form(view, bank, rows)
    view.confirm.click()
    original = view.selected_event
    with V2ProfileStore.open(path, read_only=True) as store:
        old_ids = {link.derived_observation_id for link in store.loan_source_links()}
    view.bank.setCurrentIndex(view.bank.findData(other))
    view.reference.setText("Corrected bank source; same complete printed loan components")
    view.reason.setText("Replace the whole incorrectly attributed payment")
    assert view.confirm.isEnabled() and "2222" in view.bank.currentText()
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.confirm.click()
    assert path.read_bytes() == before
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, text: prompts.append(text) or QMessageBox.Yes)
    view.confirm.click()
    replacement = view.selected_event
    assert replacement.event_id != original.event_id and replacement.manifest.bank.row_id == other
    assert "Inverse original entries at their original dates" in prompts[0]
    assert "Replacement entry effects only" in prompts[0] and "2026-01-14" in prompts[0] and "2026-01-13" in prompts[0]
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history()[1].status == "replaced"
        assert store._active_consumed() == {other: -22000, rows[0]: -22000}
        active_ids = {link.derived_observation_id for link in store.loan_source_links() if link.active}
        assert not active_ids & old_ids
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 2000
        )
    view.assumed_dates.click()
    assert not view.assumed_dates.isChecked()
    view.reason.setText("Withdraw whole replaced payment with preference now off")
    assert view.withdraw.isEnabled()
    before = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.withdraw.click()
    assert path.read_bytes() == before
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    view.withdraw.click()
    assert view.selected_event.status == "cancelled"
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store._active_consumed() == {} and store._active_journal_entries() == ()
    assert "Retained whole-event action" in view.history_details.toPlainText()
    view.close()


def test_context_change_before_preview_resets_cached_selection_and_reference(tmp_path):
    path = tmp_path / "preview-race.db"
    bank, rows = _profile(path)
    view = dialog(path)
    view.assumed_dates.click()
    view.bank.setCurrentIndex(view.bank.findData(bank))
    view.reference.setText("Loaded old account context")
    view.reason.setText("Loaded old review context")
    with V2ProfileStore.open(path) as store:
        store.update_financial_account(
            FinancialAccount(
                "loan", "Updated principal name", "liability", "synthetic", tracking_scope="principal_component"
            )
        )
    check(view, rows[0])
    assert view.preview is None and view.bank.currentData() is None
    assert not view.reference.text() and not view.reason.text() and not view.confirm.isEnabled()
    assert "draft was reset" in view.status.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history() == ()
    view.close()


def test_historical_withdrawal_retry_cannot_retire_fresh_payment(tmp_path):
    path = tmp_path / "retry.db"
    bank, rows = _profile(path)
    first = dialog(path)
    form(first, bank, rows)
    first.confirm.click()
    old = first.selected_event
    stale = dialog(path, old.event_id)
    stale.reason.setText("Withdraw loaded whole payment")
    first.reason.setText("Withdraw loaded whole payment")
    first.withdraw.click()
    fresh = dialog(path)
    form(fresh, bank, rows)
    fresh.confirm.click()
    new = fresh.selected_event
    assert new.event_id != old.event_id
    stale.withdraw.click()
    assert stale.selected_event.status == "cancelled" and not stale.withdraw.isEnabled()
    assert "Refreshed history shows current state" in stale.status.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history()[0].event_id == new.event_id and store.loan_history()[0].status == "active"
        assert store._active_consumed() == {bank: -22000, rows[0]: -22000}
    first.close()
    stale.close()
    fresh.close()


def test_stale_selected_event_cannot_be_replaced_after_concurrent_withdrawal(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "event-race.db"
    bank, rows = _profile(path)
    other = second_bank_source(path)
    view = dialog(path)
    form(view, bank, rows)
    view.confirm.click()
    old = view.selected_event
    view.bank.setCurrentIndex(view.bank.findData(other))
    view.reference.setText("Whole correction reference")
    view.reason.setText("Whole correction reason")
    assert view.confirm.isEnabled()

    def concurrent(*_args):
        with V2ProfileStore.open(path) as store:
            store.withdraw_reviewed_loan(
                old.event_id, expected_event_version=old.version, reason="Other complete withdrawal"
            )
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", concurrent)
    view.confirm.click()
    assert view.selected_event.status == "cancelled" and not view.confirm.isEnabled() and not view.withdraw.isEnabled()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.loan_history()) == 1 and store._active_consumed() == {}
    view.close()


@pytest.mark.parametrize("case", ["unknown_interest", "nonzero_fee", "unbound", "gross_mismatch"])
def test_incomplete_unsupported_or_unbound_components_remain_pending_without_money(tmp_path, case):
    from parsetrail.core.v2_loan_history_lines import parse_loan_history

    from devtools.parser_engine_pilot.test_loan_history_lines import DEFINITION, lines

    path = tmp_path / "pending.db"
    evidence = parse_loan_history(DEFINITION, lines())
    definition, raw, amount = DEFINITION, b"%PDF-synthetic", 22000
    if case == "unknown_interest":
        evidence = parse_loan_history(
            DEFINITION, lines(interest=False, changes={4: "01/15/2026 Payment Received -$200.00 = -$200.00"})
        )
        amount = 20000
    elif case == "nonzero_fee":
        name = "mohela-account-history-definition.json"
        family = next(item for item in family_sources() if item.definition_name == name)
        raw = family.source.replace(b"-$20.00,$0.00", b"-$19.00,-$1.00")
        definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / name).read_bytes()
        evidence = build_source_evidence(raw, definition, suffix=".csv")
        amount = 10000
    bank, rows = _profile(
        path, amount=21999 if case == "gross_mismatch" else amount, evidence=evidence, definition=definition, raw=raw
    )
    if case == "unbound":
        section = evidence.payload.accounts[0]
        with V2ProfileStore.open(path) as store:
            store.clear_source_account_binding(
                evidence.source_sha256, section.source_identity, section.source_identity_form
            )
    original = path.read_bytes()
    view = dialog(path)
    view.assumed_dates.click()
    view.components.selectRow(0)
    if case == "gross_mismatch":
        form(view, bank, rows)
        assert view.preview is None and "exact bank gross equality" in view.summary.text()
    else:
        assert not view.rows[0].eligible and view.rows[0].proof is None
        assert view.open_component.isEnabled()
        assert "Printed component facts" in view.source_details.toPlainText()
        if case == "unknown_interest":
            assert (
                "interest:" not in view.source_details.toPlainText()
                and "incomplete" in view.source_details.toPlainText()
            )
        elif case == "unbound":
            assert "Assign this source" in view.source_details.toPlainText()
        else:
            assert "nonzero fee" in view.source_details.toPlainText()
    assert not view.confirm.isEnabled() and path.read_bytes() == original
    view.close()
