"""Whole-account HSA summaries use the nonposting value journey with masked context."""

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_statement_summary_review import V2StatementSummaryReview
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt

from .qt_journey_helpers import JourneyArtifacts
from .test_v2_document_browser import wait_for_inventory
from .test_v2_statement_summary_desktop import dispose
from .test_v2_summary_family_routing import prepare_family
from .v2_job_wait import wait_for_jobs


def test_hsa_summary_discovered_recorded_and_reopened_in_workspace(qtbot, qapp, tmp_path, journey_artifacts):
    path = tmp_path / "hsa-summary.db"
    _raw, evidence = prepare_family(path, "fidelity-hsa-summary-pilot-definition.json", "fidelity", "hsa")
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window)
    window.resize(1050, 700)
    window.show()
    wait_for_inventory(window)
    assert window.sources.select_source(evidence.source_sha256)
    assert "statement value" in window.review_document_button.text().lower()
    qtbot.mouseClick(window.review_document_button, Qt.LeftButton)
    view = window._review_widget
    assert isinstance(view, V2StatementSummaryReview)
    wait_for_jobs(view)
    assert view.action_button.isEnabled() and view.action_button.property("formState") == "ready"
    assert "145.00" in view.value.text()
    assert "123-456789" not in view.context.text()
    assert "6789" in view.context.text()
    assert "retirement" not in view.context.text().lower()
    assert view.table.rowCount() == 5
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("01-hsa-summary-review", window)
    qtbot.mouseClick(view.action_button, Qt.LeftButton)
    wait_for_jobs(view)
    wait_for_inventory(window)
    assert view.snapshot.complete
    assert view.action_button.property("formState") == "neutral"
    artifacts.capture("02-hsa-value-recorded", window)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.statement_summary_snapshot(evidence.source_sha256).complete
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM UnresolvedTransferLegs").fetchone() == (0,)
        assert store.load_import(evidence.source_sha256).evidence == evidence
    dispose(qtbot, window)
