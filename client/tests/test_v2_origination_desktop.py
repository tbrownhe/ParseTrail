"""Principal-first financing and independent optional tangible value journeys."""

from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences, save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview
from parsetrail.gui.v2_loan_origination_review import V2LoanOriginationReview
from parsetrail.gui.v2_tangible_assets import V2TangibleAssets
from PySide6.QtCore import QDate, QPoint, Qt, QTimer
from PySide6.QtWidgets import QMessageBox

from .qt_journey_helpers import JourneyArtifacts, enter_text
from .test_v2_origination import origination_profile
from .v2_job_wait import wait_for_jobs


def prepared(tmp_path):
    path = tmp_path / "origination.db"
    bank, row = origination_profile(path)
    prefs = tmp_path / "prefs.json"
    save_preferences(prefs, V2Preferences())
    return V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs), bank, row


def check(qtbot, checkbox):
    qtbot.mouseClick(checkbox, Qt.LeftButton, pos=QPoint(8, checkbox.height() // 2))


@pytest.mark.parametrize("size", [(960, 540), (1050, 700), (1280, 800)], ids=["default", "1050", "1280"])
def test_principal_only_optional_destination_posts_reopens_and_withdraws(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    workspace, _bank, row = prepared(tmp_path)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view.source_row.currentData() == row
    assert view.destination.currentData() is None
    assert "assumed accounting date" in view.status.text() and not view.confirm.isEnabled()
    assert not hasattr(view, "acquisition_value") and not hasattr(view, "downpayment")
    check(qtbot, view.assumed_dates)
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and len(view.preview.entries) == 1, view.status.text()
    assert (view.width(), view.height()) == size
    assert "Full acquisition cost remains unknown" in view.effects.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-principal-only-optional-destination", view)
    before = workspace.profile_path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    assert workspace.profile_path.read_bytes() == before
    assert not view.initial_posting_succeeded
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    wait_for_jobs(view)
    assert view._event() is not None and not view.withdraw.isEnabled()
    assert view.initial_posting_succeeded and not view.destination.isEnabled()
    assert not view.correction.button.isChecked() and not view.correction_reason.text()
    artifacts.capture("02-principal-only-saved", view)
    view.close()
    reopened = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(reopened)
    reopened.show()
    wait_for_jobs(reopened)
    assert reopened._event() is not None and not reopened.initial_posting_succeeded
    check(qtbot, reopened.correction.button)
    enter_text(qtbot, reopened.correction_reason, "Correct the financing destination")
    qtbot.mouseClick(reopened.withdraw, Qt.LeftButton)
    wait_for_jobs(reopened)
    assert not reopened.initial_posting_succeeded
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store._active_journal_entries() == ()
        assert len(store.origination_snapshot().events) == 1
        assert not store.opening_decision_history("loan")
    reopened.close()


def test_financial_expectation_and_explicit_tangible_allocation(qtbot, qapp, tmp_path, monkeypatch, journey_artifacts):
    workspace, _bank, row = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(True)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    financial = next(a for a in view._accounts.values() if a.id != "vehicle")
    view.destination.setCurrentIndex(view.destination.findData(financial.id))
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and len(view.preview.entries) == 1
    assert "No transaction is posted there" in view.effects.text()
    view.destination.setCurrentIndex(view.destination.findData("vehicle"))
    wait_for_jobs(view)
    assert not view.asset_link.isChecked() and view.asset_link.isVisible()
    assert not view.confirm.isEnabled() and "or leave the destination not established" in view.status.text()
    check(qtbot, view.asset_link)
    view.allocation_date.setDate(QDate(2026, 1, 16))
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and len(view.preview.entries) == 2
    assert view.preview.acquisition_value_minor is None
    assert "Financed allocation $10,000.00" in view.effects.text()
    JourneyArtifacts(journey_artifacts, qapp, (960, 650)).capture("03-tangible-explicit-allocation", view)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        event = store.origination_snapshot().events[0]
        assert event.total_acquisition_cost_minor is None
        assert event.tangible_allocation_date == date(2026, 1, 16)
        assert len(store._active_journal_entries()) == 2
        assert store._active_consumed() == {row: 1000000}
    view.close()


def test_named_only_asset_then_optional_signed_estimate_and_numeric_sort(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _bank, _row = prepared(tmp_path)
    view = V2TangibleAssets(workspace, value_date=date(2026, 1, 16))
    qtbot.addWidget(view)
    view.resize(760, 620)
    view.show()
    wait_for_jobs(view)
    assert not view.save.isEnabled() and not view.valuation.isChecked()
    assert view.value_date.date().toPython() == date(2026, 1, 16)
    enter_text(qtbot, view.name, "Gold coins and equipment with a deliberately long descriptive nickname")
    assert view.save.isEnabled()
    qtbot.mouseClick(view.save, Qt.LeftButton)
    wait_for_jobs(view)
    account_id = view.selected_account_id
    assert "Asset saved. Value unknown" in view.status.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (760, 620))
    artifacts.capture("04a-named-asset-saved", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert next(a for a in store.financial_accounts() if a.id == account_id).product_type == "tangible_asset"
        assert not any(v.account_id == account_id for v in store.tangible_asset_values())
        assert store._active_journal_entries() == ()
    assert not view.save.isEnabled()
    view.valuation.setChecked(True)
    enter_text(qtbot, view.amount, "20000")
    enter_text(qtbot, view.rate, "-10")
    assert view.save.isEnabled()
    artifacts.capture("04-generic-asset-optional-estimate", view)
    qtbot.mouseClick(view.save, Qt.LeftButton)
    wait_for_jobs(view)
    assert "Estimate saved" in view.status.text()
    artifacts.capture("04b-estimate-saved", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        value = next(v for v in store.tangible_asset_values(as_of=date(2027, 1, 16)) if v.account_id == account_id)
        assert value.amount_minor == 2000000 and 1799000 < value.estimated_minor < 1801000
        assert store._active_journal_entries() == ()
    view.table.sortItems(2, Qt.AscendingOrder)
    assert view.table.item(0, 2).data(Qt.UserRole) == 1500000
    view.close()


@pytest.mark.parametrize(
    "rate, valid, expected",
    [
        ("", True, None),
        ("0", True, 0),
        ("+1000", True, 100000),
        ("-100", True, -10000),
        ("1000.01", False, None),
        ("-100.01", False, None),
        ("1.001", False, None),
        ("NaN", False, None),
    ],
)
def test_optional_annual_change_validation(qtbot, tmp_path, rate, valid, expected):
    workspace, _, _ = prepared(tmp_path)
    view = V2TangibleAssets(workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    view.name.setText("Equipment")
    view.valuation.setChecked(True)
    view.amount.setText("0")
    view.rate.setText(rate)
    assert view.save.isEnabled() is valid
    if valid:
        assert view._inputs() == (0, expected)
    view.close()


@pytest.mark.parametrize("succeeded", [False, True])
def test_document_relays_initial_post_only_after_modal_closes(qtbot, tmp_path, monkeypatch, succeeded):
    workspace, _, row = prepared(tmp_path)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        source = store.origination_snapshot().rows[0].source_sha256
    view = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    view.navigation.reveal_row(row)
    seen = []
    view.initial_posted.connect(lambda value: seen.append(value))
    original_exec = V2LoanOriginationReview.exec

    def modal(dialog):
        def close():
            assert not seen
            dialog.initial_posting_succeeded = succeeded
            dialog.reject()

        QTimer.singleShot(0, close)
        return original_exec(dialog)

    monkeypatch.setattr(V2LoanOriginationReview, "exec", modal)
    view._review_payment()
    assert seen == ([source] if succeeded else [])
    wait_for_jobs(view)
    view.request_cancel()
    view.close()


def test_empty_origination_and_named_asset_states(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "empty.db"
    with V2ProfileStore.create(path):
        pass
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2LoanOriginationReview(workspace)
    qtbot.addWidget(view)
    view.resize(760, 560)
    view.show()
    wait_for_jobs(view)
    assert not view.confirm.isEnabled() and "No supported origination" in view.status.text()
    assert all(
        not widget.isEnabled() for widget in (view.destination, view.create_asset, view.reason, view.assumed_dates)
    )
    JourneyArtifacts(journey_artifacts, qapp, (760, 560)).capture("05-empty-origination", view)
    view.close()
    assets = V2TangibleAssets(workspace)
    qtbot.addWidget(assets)
    assets.show()
    wait_for_jobs(assets)
    assert assets.table.rowCount() == 0 and not assets.save.isEnabled()
    assert assets.value_date.date().toPython() == date.today()
    assets.close()


def test_tangible_general_account_form_omits_institution_and_locks_product(qtbot):
    from parsetrail.core.v2_profile_store import FinancialAccount
    from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog

    view = V2FinancialAccountDialog()
    qtbot.addWidget(view)
    view.show()
    view.product.setCurrentIndex(view.product.findData("tangible_asset"))
    view.name.setText("Equipment")
    assert view.save_button.isEnabled()
    assert view.account().institution_key is None
    assert not view.institution.isVisible() and not view.number.isVisible()
    view.close()
    saved = V2FinancialAccountDialog(
        existing=FinancialAccount("equipment", "Equipment", "asset", None, product_type="tangible_asset")
    )
    qtbot.addWidget(saved)
    assert not saved.product.isEnabled()
    saved.close()


def test_refinancing_destination_label_and_asset_create_date_default(qtbot, tmp_path, monkeypatch):
    from parsetrail.core.v2_profile_store import FinancialAccount

    from .qt_journey_helpers import choose_combo

    workspace, _, row = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(True)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(
            FinancialAccount(
                "refinanced",
                "Loan principal",
                "liability",
                None,
                tracking_scope="principal_component",
                product_type="loan",
            )
        )
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    choose_combo(qtbot, view.destination, "refinanced")
    wait_for_jobs(view)
    assert "Loan" in view.destination.currentText() and "principal only" in view.destination.currentText()
    assert view.confirm.isEnabled() and len(view.preview.entries) == 1
    defaults = []

    def inspect(dialog):
        wait_for_jobs(dialog)
        defaults.append(dialog.value_date.date().toPython())
        dialog.reject()
        return 0

    monkeypatch.setattr(V2TangibleAssets, "exec", inspect)
    view.create_asset.click()
    wait_for_jobs(view)
    assert defaults == [date(2026, 1, 15)]
    view.close()


def test_payment_initial_success_distinguishes_post_cancel_and_saved_correction(qtbot, tmp_path, monkeypatch):
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

    from .test_v2_loan_payment_dialog import form
    from .test_v2_loan_payments import _profile

    path = tmp_path / "payment.db"
    bank, rows = _profile(path)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    view = V2LoanPaymentReview(workspace)
    qtbot.addWidget(view)
    wait_for_jobs(view)
    form(view, bank, rows)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.confirm.click()
    assert not view.initial_posting_succeeded
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    view.confirm.click()
    wait_for_jobs(view)
    assert view.initial_posting_succeeded
    event_id = view.selected_event.event_id
    view.close()
    saved = V2LoanPaymentReview(workspace, event_id=event_id)
    qtbot.addWidget(saved)
    wait_for_jobs(saved)
    assert not saved.initial_posting_succeeded
    saved.reason.setText("Correct saved payment")
    saved.withdraw.click()
    wait_for_jobs(saved)
    assert not saved.initial_posting_succeeded
    saved.close()


def test_saved_finite_acquisition_retains_known_cost_in_dialog_and_landing(qtbot, tmp_path):
    from .test_v2_origination import preview

    workspace, _, row = prepared(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        event = store.post_loan_origination(preview(store, row))
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert "Reviewed acquisition cost $10,000.00" in view.effects.text()
    assert "Full acquisition cost remains unknown" not in view.effects.text()
    assert "unknown" not in view.limits.text()
    assert view.allocation_date.isVisible()
    view.close()
    landing = V2LoanDocumentReview(workspace, event.source_sha256)
    qtbot.addWidget(landing)
    wait_for_jobs(landing)
    assert "Reviewed acquisition cost $10,000.00" in landing.status.text()
    landing.request_cancel()
    landing.close()


def test_named_asset_failed_save_retains_inputs_and_clear_retry_message(qtbot, tmp_path, monkeypatch):
    workspace, _, _ = prepared(tmp_path)
    view = V2TangibleAssets(workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    view.name.setText("Equipment")

    def fail(*_args, **_kwargs):
        raise OSError("Synthetic write failure")

    monkeypatch.setattr(V2ProfileStore, "add_financial_account", fail)
    view.save.click()
    wait_for_jobs(view)
    assert "Synthetic write failure" in view.status.text()
    assert view.name.text() == "Equipment" and view.save.isEnabled()
    view.name.setText("Equipment corrected")
    assert "Synthetic write failure" not in view.status.text()
    view.close()
