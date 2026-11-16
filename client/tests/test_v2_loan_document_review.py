"""Loan source review exposes printed components without implying a posting."""

import pytest
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_preferences import save_preferences
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_loan_document_review import V2LoanDocumentReview
from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt

from devtools.parser_engine_pilot import test_loan_history_lines as capital
from devtools.parser_engine_pilot import test_wells_loan_lines as wells

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_document_browser import wait_for_inventory
from .test_v2_loan_payments import PREFERENCES, _post, _profile
from .v2_job_wait import wait_for_jobs


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050", "1280"])
def test_printed_components_and_exact_source_handoff_without_date_permission(
    qtbot, qapp, tmp_path, monkeypatch, journey_artifacts, size
):
    path = tmp_path / "loan.db"
    _bank, rows = _profile(path)
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    with V2ProfileStore.open(path, read_only=True) as store:
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (rows[0],)
        ).fetchone()[0]
    before = path.read_bytes()
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(*size)
    window.show()
    wait_for_inventory(window)
    window._review_report_source(source, rows[0])
    view = window._review_widget
    assert isinstance(view, V2LoanDocumentReview)
    wait_for_jobs(view)
    assert view._current().row_id == rows[0]
    assert view.table.rowCount() == 1
    assert "220.00" in view.components.text() and "200.00" in view.components.text()
    assert "20.00" in view.components.text() and "Components match total" in view.components.text()
    assert "assumed" in view.status.text() and view.action_button.isEnabled()
    assert not workspace.preferences().allow_assumed_posting_dates
    assert not view.has_unsaved_draft
    JourneyArtifacts(journey_artifacts, qapp, size).capture("loan-components", window)

    inspected = []

    def inspect(dialog):
        wait_for_jobs(dialog)
        assert len(dialog.rows) == 1 and dialog.rows[0].row_id == rows[0]
        assert dialog.components.currentRow() == 0
        assert dialog.components.item(0, 0).checkState() == Qt.Unchecked
        assert dialog.bank.currentData() is None and not dialog.confirm.isEnabled()
        assert dialog.reason.text() == "Initial Review"
        inspected.append(True)
        return 0

    monkeypatch.setattr(V2LoanPaymentReview, "exec", inspect)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    assert inspected == [True] and path.read_bytes() == before
    evidence_opened = []

    def inspect_evidence(dialog):
        assert dialog.saved.evidence.source_sha256 == source
        evidence_opened.append(True)
        return 0

    monkeypatch.setattr(V2EvidencePreview, "exec", inspect_evidence)
    qtbot.mouseClick(view.source_button, Qt.LeftButton)
    assert evidence_opened == [True] and path.read_bytes() == before
    assert view.request_cancel()
    window.close()


def test_missing_equal_bank_outflow_explains_waiting_without_hiding_components(qtbot, tmp_path):
    path = tmp_path / "waiting.db"
    _profile(path, amount=12345)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    with V2ProfileStore.open(path, read_only=True) as store:
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceAccountBindings WHERE ledger_account_id='loan'"
        ).fetchone()[0]
    view = V2LoanDocumentReview(workspace, source)
    qtbot.addWidget(view)
    wait_for_jobs(view)
    assert "Waiting for matching paying-account evidence" in view.status.text()
    assert "Components match total" in view.components.text()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.loan_history() == () and store._active_journal_entries() == ()
    assert view.request_cancel()


def test_source_history_retains_whole_event_siblings_and_excludes_other_sources(qtbot, tmp_path):
    path = tmp_path / "history.db"
    bank, rows = _profile(
        path, amount=2100, evidence=wells.parse(), definition=wells.DEFINITION, raw=b"%PDF-synthetic-loan"
    )
    evidence = parse_loan_history(capital.DEFINITION, capital.lines())
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        source = event.manifest.components[0].source_sha256
        store.import_source(b"%PDF-synthetic", capital.DEFINITION, evidence, suffix=".pdf")
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "loan")
    prefs = tmp_path / "prefs.json"
    save_preferences(prefs, PREFERENCES)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=prefs)
    before = path.read_bytes()
    view = V2LoanPaymentReview(workspace, source_sha256=source, event_id=event.event_id)
    qtbot.addWidget(view)
    wait_for_jobs(view)
    checked = {
        view.components.item(i, 0).data(Qt.UserRole)
        for i in range(view.components.rowCount())
        if view.components.item(i, 0).checkState() == Qt.Checked
    }
    assert checked == set(rows) and len(checked) == 2
    assert not view.reason.text()
    view.close()
    other = V2LoanPaymentReview(workspace, source_sha256=evidence.source_sha256, event_id=event.event_id)
    qtbot.addWidget(other)
    wait_for_jobs(other)
    assert other.mode.findData(event.event_id) == -1 and other.selected_event is None
    assert other.bank.currentData() is None and not other.confirm.isEnabled()
    assert other.reason.text() == "Initial Review" and path.read_bytes() == before
    other.close()
