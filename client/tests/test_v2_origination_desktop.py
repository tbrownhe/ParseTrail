"""Origination acquisition, valuation and incomplete-funding journeys stay explicit."""

from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences, save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_loan_origination_review import V2LoanOriginationReview
from parsetrail.gui.v2_tangible_assets import V2TangibleAssets
from PySide6.QtCore import QDate, QPoint, Qt
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


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050", "1280"])
def test_origination_preview_requires_destination_and_date_then_posts_and_withdraws(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    workspace, _bank, row = prepared(tmp_path)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.resize(*size)
    view.show()
    wait_for_jobs(view)
    assert view.source_row.currentData() == row
    assert "Destination needed" in view.status.text() and not view.confirm.isEnabled()
    view.destination.setCurrentIndex(view.destination.findData("vehicle"))
    enter_text(qtbot, view.acquisition_value, "10000.00")
    wait_for_jobs(view)
    assert not view.confirm.isEnabled() and "assumed accounting date" in view.status.text()
    qtbot.mouseClick(view.assumed_dates, Qt.LeftButton, pos=QPoint(8, view.assumed_dates.height() // 2))
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and view.preview is not None, view.status.text()
    assert view.size().width() == size[0] and view.height() == size[1]
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    artifacts.capture("01-origination-exact-financing", view)
    before = workspace.profile_path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    assert workspace.profile_path.read_bytes() == before and view.acquisition_value.text() == "10000.00"
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    qtbot.mouseClick(view.confirm, Qt.LeftButton)
    wait_for_jobs(view)
    assert view._event() is not None and not view.withdraw.isEnabled()
    assert not view.correction_reason.text() and not view.acquisition_value.isEnabled()
    artifacts.capture("02-origination-saved", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store._active_journal_entries()) == 2
        assert store._active_consumed()[row] == 1000000
        assert not store.opening_decision_history("loan")
    enter_text(qtbot, view.correction_reason, "Correct the acquisition destination")
    qtbot.mouseClick(view.withdraw, Qt.LeftButton)
    wait_for_jobs(view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store._active_journal_entries() == ()
        assert len(store.origination_snapshot().events) == 1
    view.close()


def test_origination_incomplete_downpayment_is_explicit_and_exact_choice_enables(qtbot, tmp_path):
    workspace, bank, row = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(True)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    view.destination.setCurrentIndex(view.destination.findData("vehicle"))
    enter_text(qtbot, view.acquisition_value, "15000")
    wait_for_jobs(view)
    assert "Funding is incomplete" in view.status.text() and not view.confirm.isEnabled()
    view.downpayment.setCurrentIndex(view.downpayment.findData(bank))
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and len(view.preview.entries) == 3
    assert "bank downpayment $5,000.00" in view.effects.text()
    view.close()


def test_vehicle_creation_value_and_decline_are_nonposting(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _bank, _row = prepared(tmp_path)
    view = V2TangibleAssets(workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    enter_text(qtbot, view.name, "Primary vehicle")
    view.value_date.setDate(QDate(2026, 1, 1))
    enter_text(qtbot, view.amount, "20000")
    enter_text(qtbot, view.rate, "10")
    assert view.save.isEnabled()
    qtbot.mouseClick(view.save, Qt.LeftButton)
    wait_for_jobs(view)
    assert view.selected_account_id is not None
    JourneyArtifacts(journey_artifacts, qapp, (880, 620)).capture("vehicle-value-and-estimate", view)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        values = {value.account_id: value for value in store.tangible_asset_values(as_of=date(2027, 1, 1))}
        value = values[view.selected_account_id]
        assert value.amount_minor == 2000000 and 1799000 < value.estimated_minor < 1801000
        assert store._active_journal_entries() == ()
    view.close()
