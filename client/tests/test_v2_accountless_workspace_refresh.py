"""Confirmed accountless rows refresh document and batch views without restart."""

from __future__ import annotations

import time

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
from parsetrail.gui.v2_batch_account_assignment import V2BatchAccountAssignment
from parsetrail.gui.v2_document_browser import document_account_association, profile_revision
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QDialog

from .test_v2_account_binding_review import DEFINITION, SOURCE
from .test_v2_document_browser import wait_for_inventory
from .test_v2_inline_account_creation import _workspace


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


@pytest.fixture
def accountless(tmp_path):
    source = SOURCE + b"10/03/2026,Payment,-$20.00,-$5.00,$0.00,-$25.00,\n"
    evidence = build_source_evidence(source, DEFINITION, suffix=".csv")
    workspace = _workspace(tmp_path, DEFINITION, evidence, institution="mohela", source=source)
    with V2ProfileStore.open(workspace.profile_path) as store:
        for index, name in enumerate(("Alpha loan", "Beta loan", "Zebra third account")):
            store.add_financial_account(FinancialAccount(str(index), name, "liability", "mohela"))
    return workspace, evidence


def _ready(app, dialog):
    deadline = time.monotonic() + 15
    while dialog.pending and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not dialog.pending and dialog.plan is not None


def test_return_from_actual_row_assignment_refreshes_documents_and_new_batch(app, accountless, monkeypatch):
    workspace, evidence = accountless
    window = V2WorkspaceWindow(workspace)
    batch = None
    try:
        wait_for_inventory(window)
        assert window.review_button.text() == "Assign rows without an account"

        def assign_all(dialog):
            dialog.table.selectAll()
            dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("0"))
            dialog.assign_rows_button.click()
            assert "Row assignments: 3 of 3" in dialog.status.text()
            dialog.reject()
            return QDialog.Rejected

        monkeypatch.setattr(V2AccountBindingReview, "exec", assign_all)
        window.review_button.click()
        wait_for_inventory(window)
        summary = window._document_summaries[evidence.source_sha256]
        assert summary.association_kind == "rows" and summary.association_complete
        assert summary.bound_account_names == ("Alpha loan",)
        assert "All 3 rows assigned individually to Alpha loan" in window.account_assignment_status.text()
        assert "All rows have accounts" in window.sources.item(0).text()
        assert window.review_button.text() == "Review row account assignments"
        assert window.sources.count() == 1
        batch = V2BatchAccountAssignment(workspace)
        _ready(app, batch)
        assert batch.plan.groups == ()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM FileAccountAssertions").fetchone() == (0,)
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        if batch is not None:
            batch.close()
        window.close()
        app.processEvents()


def test_existing_document_and_batch_views_refresh_changed_profile_on_activation(app, accountless, monkeypatch):
    workspace, evidence = accountless
    window = V2WorkspaceWindow(workspace)
    batch = V2BatchAccountAssignment(workspace)
    try:
        wait_for_inventory(window)
        _ready(app, batch)
        assert len(batch.plan.groups) == 1
        before = profile_revision(workspace.profile_path)
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.assign_rows_account(evidence.source_sha256, tuple(row.row_id for row in evidence.payload.rows), "0")
        assert profile_revision(workspace.profile_path) != before
        monkeypatch.setattr(window, "isActiveWindow", lambda: True)
        monkeypatch.setattr(batch, "isActiveWindow", lambda: True)
        QApplication.sendEvent(window, QEvent(QEvent.ActivationChange))
        QApplication.sendEvent(batch, QEvent(QEvent.ActivationChange))
        wait_for_inventory(window)
        _ready(app, batch)
        assert batch.plan.groups == ()
        assert window._document_summaries[evidence.source_sha256].association_complete
        assert "Alpha loan" in window.account_assignment_status.text()
        monkeypatch.setattr(
            V2ProfileStore, "open", lambda *_a, **_kw: pytest.fail("Unchanged activation must not reread")
        )
        QApplication.sendEvent(window, QEvent(QEvent.ActivationChange))
        QApplication.sendEvent(batch, QEvent(QEvent.ActivationChange))
        app.processEvents()
        assert not window.inventory_pending and not batch.pending
    finally:
        batch.close()
        window.close()
        app.processEvents()


def test_partial_and_multiaccount_rows_remain_qualified_and_search_every_account(app, accountless):
    workspace, evidence = accountless
    rows = evidence.payload.rows
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.assign_row_account(rows[0].row_id, "0")
        store.assign_row_account(rows[1].row_id, "1")
    window = V2WorkspaceWindow(workspace)
    try:
        wait_for_inventory(window)
        summary = window._document_summaries[evidence.source_sha256]
        assert document_account_association(summary).startswith("2/3 rows assigned · 1 still need an account")
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.assign_row_account(rows[2].row_id, "2")
        window._refresh_changed_profile()
        wait_for_inventory(window)
        summary = window._document_summaries[evidence.source_sha256]
        assert "All 3 rows assigned across 3 accounts" in window.selected_details.text()
        assert summary.association_complete
        assert "Zebra third account" not in window.sources.item(0).text()
        window.document_search.setText("Zebra third account")
        assert not window.sources.item(0).isHidden()
        assert window._selected_source() == evidence.source_sha256
    finally:
        window.close()
        app.processEvents()
