"""Applicable required choices and creation commands stay distinct from posting."""

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview
from parsetrail.gui.v2_loan_origination_review import V2LoanOriginationReview
from parsetrail.gui.v2_tangible_assets import V2TangibleAssets
from PySide6.QtCore import Qt

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_origination_desktop import check, prepared
from .v2_job_wait import wait_for_jobs


def test_primary_and_conditional_financing_cues(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _bank, row = prepared(tmp_path)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        source = store.origination_snapshot().rows[0].source_sha256
    landing = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(landing)
    landing.resize(1050, 700)
    landing.show()
    wait_for_jobs(landing)
    assert landing.action_button.isEnabled() and landing.action_button.property("formState") == "ready"
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("01-primary-loan-action", landing)
    assert landing.request_cancel()
    landing.close()
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert view.destination.property("formState") == "optional"
    assert view.reason.property("formState") == "ready"
    assert view.assumed_dates.property("formState") == "required" and not view.confirm.isEnabled()
    view.destination.setCurrentIndex(view.destination.findData("vehicle"))
    assert view.asset_link.property("formState") == "required"
    artifacts.capture("02-applicable-required-choices", view)
    check(qtbot, view.asset_link)
    assert view.asset_link.property("formState") == "ready"
    check(qtbot, view.assumed_dates)
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and view.confirm.property("formState") == "ready"
    assert view.allocation_date.property("formState") == "ready"
    artifacts.capture("03-valid-financing-choices", view)
    view.reason.clear()
    assert view.reason.property("formState") == "required" and not view.confirm.isEnabled()
    view.reason.setText("Initial Review")
    wait_for_jobs(view)
    view.destination.setCurrentIndex(view.destination.findData(None))
    wait_for_jobs(view)
    assert view.confirm.isEnabled() and view.destination.property("formState") == "optional"
    assert not view.asset_link.isVisible() and view.asset_link.property("formState") == "neutral"
    artifacts.capture("04-valid-unresolved-destination", view)
    view.close()


@pytest.mark.parametrize("previous", [None, "bank"])
def test_keyboard_create_cancel_restores_destination_and_never_posts(qtbot, tmp_path, monkeypatch, previous):
    workspace, _bank, row = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(True)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    view.destination.setCurrentIndex(view.destination.findData(previous))
    wait_for_jobs(view)
    before = workspace.profile_path.read_bytes()
    seen = []

    def cancel(dialog):
        wait_for_jobs(dialog)
        seen.append(dialog.value_date.date().toPython())
        dialog.reject()
        return 0

    monkeypatch.setattr(V2TangibleAssets, "exec", cancel)
    view.destination.setFocus()
    qtbot.keyClick(view.destination, Qt.Key_Down, Qt.AltModifier)
    popup = view.destination.view()
    qtbot.waitUntil(popup.isVisible)
    qtbot.keyClick(popup, Qt.Key_End)
    qtbot.keyClick(popup, Qt.Key_Return)
    qtbot.waitUntil(lambda: bool(seen) and not view.jobs.pending, timeout=15000)
    assert view.destination.currentData() == previous
    assert view.preview.destination_account_id == previous and view.confirm.isEnabled()
    assert workspace.profile_path.read_bytes() == before
    assert not hasattr(view, "create_asset")
    view.close()


def test_create_selects_saved_asset_and_requires_funding_confirmation(qtbot, tmp_path, monkeypatch):
    workspace, _bank, row = prepared(tmp_path)
    workspace.set_allow_assumed_posting_dates(True)
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    created = []

    def create(dialog):
        wait_for_jobs(dialog)
        dialog.name.setText("Equipment purchased with financing")
        dialog.save.click()
        wait_for_jobs(dialog)
        created.append(dialog.selected_account_id)
        dialog.reject()
        return 0

    monkeypatch.setattr(V2TangibleAssets, "exec", create)
    view.destination.setCurrentIndex(view.destination.count() - 1)
    qtbot.waitUntil(lambda: bool(created) and not view.jobs.pending, timeout=15000)
    assert view.destination.currentData() == created[0]
    assert not view.asset_link.isChecked() and view.asset_link.property("formState") == "required"
    assert not view.confirm.isEnabled()
    check(qtbot, view.asset_link)
    wait_for_jobs(view)
    assert view.preview.destination_account_id == created[0]
    assert view.confirm.isEnabled()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store._active_journal_entries() == ()
    view.close()


def test_asset_required_and_optional_estimate_cues(qtbot, qapp, tmp_path, journey_artifacts):
    workspace, _, _ = prepared(tmp_path)
    view = V2TangibleAssets(workspace)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert view.name.property("formState") == "required" and not view.save.isEnabled()
    view.name.setText("Family vehicle")
    assert view.name.property("formState") == "ready" and view.save.property("formState") == "ready"
    view.valuation.setChecked(True)
    assert view.amount.property("formState") == "required" and not view.save.isEnabled()
    view.amount.setText("-1")
    assert view.amount.property("formState") == "invalid" and not view.save.isEnabled()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (880, 620))
    artifacts.capture("05-estimate-needs-correction", view)
    view.amount.setText("20000")
    assert view.amount.property("formState") == "ready" and view.rate.property("formState") == "optional"
    assert view.save.isEnabled() and view.save.property("formState") == "ready"
    view.rate.setText("NaN")
    assert view.rate.property("formState") == "invalid" and not view.save.isEnabled()
    view.rate.setText("-14")
    assert view.rate.property("formState") == "ready" and view.save.isEnabled()
    artifacts.capture("06-valid-asset-estimate", view)
    view.close()


def test_saved_financing_has_only_fresh_correction_requirement(qtbot, qapp, tmp_path, journey_artifacts):
    from .test_v2_flexible_funding import funding

    workspace, _, row = prepared(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.post_loan_origination(funding(store, row))
    assert not workspace.preferences().allow_assumed_posting_dates
    view = V2LoanOriginationReview(workspace, focus_row_id=row)
    qtbot.addWidget(view)
    view.show()
    wait_for_jobs(view)
    assert view.assumed_dates.property("formState") == "readonly"
    assert view.destination.property("formState") == "saved" and not view.confirm.isVisible()
    check(qtbot, view.correction.button)
    assert view.correction_reason.property("formState") == "required" and not view.withdraw.isEnabled()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (960, 540))
    artifacts.capture("07-saved-correction-requires-reason", view)
    view.correction_reason.setText("Correct the destination")
    assert view.correction_reason.property("formState") == "ready"
    assert view.withdraw.isEnabled() and view.withdraw.property("formState") == "ready"
    artifacts.capture("08-valid-correction-reason", view)
    view.close()
