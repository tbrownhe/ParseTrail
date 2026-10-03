import json

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reconciliation_view import ReconciliationView
from parsetrail.gui.ledger_reconciliation_review import ReconciliationReviewWindow, SourceReviewDialog
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_opening_review import attest
from .test_ledger_opening_review import workspace as workspace
from .test_ledger_openings import add_period
from .test_ledger_proposal_review import app as app
from .test_ledger_reviewed_reconciliation import finish_cash_card, prepare_custom


def prepared(workspace):
    review = ProposalReview(workspace[0])
    OpeningReview(review, workspace[1])
    return review


def select(window, sid):
    for i in range(window.page.proxy.rowCount()):
        source = window.page.proxy.mapToSource(window.page.proxy.index(i, 0)).row()
        if window.page.model.records[source]["row"]["statement_id"] == sid:
            window.page.table.selectRow(i)
            return
    raise AssertionError(sid)


def fill(dialog):
    dialog.opening.setCurrentIndex(dialog.opening.findData("reported"))
    dialog.closing.setCurrentIndex(dialog.closing.findData("reported"))
    dialog.timing.setChecked(True)
    dialog.reference.setText("Workflow test, page 1")


def test_cancel_save_stale_reopen_and_recheck(app, workspace):
    with prepared(workspace) as review:
        before = list(review.store.connection.iterdump())
        window = ReconciliationReviewWindow(review, workspace[0])
        window.show()
        select(window, "s1")
        app.processEvents()
        assert window.current and window.edit.isEnabled()
        assert "difference -$25.00" in window.page.details.toPlainText()
        assert window.evidence.model.records
        assert list(review.store.connection.iterdump()) == before
        old = window.view.report["input_version"]

        def interact(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, SourceReviewDialog)
            fill(dialog)
            dialog.save.click() if save else dialog.reject()

        QTimer.singleShot(0, lambda: interact(False))
        window.edit.click()
        assert window.openings.provenance("s1")["sequence"] is None and window.current
        QTimer.singleShot(0, lambda: interact(True))
        window.edit.click()
        assert not window.current and "STALE" in window.banner.text()
        assert window.view.report["input_version"] == old
        window.close()
    with ProposalReview(workspace[0]) as review:
        window = ReconciliationReviewWindow(review, workspace[0])
        assert not window.current
        select(window, "s1")
        dialog = SourceReviewDialog(window.openings, "s1", window)
        assert dialog.reference.text() == "Workflow test, page 1"
        assert dialog.closing.currentData() == "reported"
        dialog.reject()
        window.check.click()
        assert window.current and window.view.report["input_version"] != old
        assert window.selected()["row"]["statement_id"] == "s1"
        assert not window.selected()["row"]["reconciled"]  # Source review alone does not post evidence.
        assert review.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        window.close()


def test_chase_estimates_are_locked_and_filter_clears_selected_evidence(app, workspace):
    with prepared(workspace) as review:
        window = ReconciliationReviewWindow(review, workspace[0])
        select(window, "s2")
        app.processEvents()
        dialog = SourceReviewDialog(window.openings, "s2", window)
        assert dialog.dates.currentData() == "estimated" and not dialog.dates.isEnabled()
        assert not dialog.save.isEnabled()
        fill(dialog)
        dialog.save.click()
        assert dialog.result() == QDialog.DialogCode.Accepted
        assert window.openings.provenance("s2")["posting_dates"] == "estimated"
        window.page.search.setText("NO-MATCH")
        assert not window.selected() and not window.edit.isEnabled()
        assert not window.evidence.model.records and not window.page.details.toPlainText()
        window.close()


def test_concurrent_source_edit_is_rejected_and_external_change_marks_view_stale(app, workspace):
    with prepared(workspace) as review, ProposalReview(workspace[0]) as other:
        window = ReconciliationReviewWindow(review, workspace[0])
        dialog = SourceReviewDialog(window.openings, "s1", window)
        fill(dialog)
        attest(OpeningReview(other), reference="Another window's review")
        dialog.save.click()
        app.processEvents()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "changed while editing" in dialog.error.text()
        assert window.openings.provenance("s1")["reference"] == "Another window's review"
        window.check_current()
        assert not window.current and "STALE" in window.banner.text()
        dialog.reject()
        window.close()


def test_later_source_review_and_unavailable_source_control(app, tmp_path, rebuild):
    add_period(rebuild, "later", "2026-10-01", "2026-10-31", -2300, -2300)
    add_period(rebuild, "bad", "2026-09-01", "2026-09-30", 0, 99)
    workspace = prepare_custom(tmp_path, rebuild)
    with prepared(workspace) as review:
        window = ReconciliationReviewWindow(review, workspace[0])
        select(window, "later")
        app.processEvents()
        assert window.edit.isEnabled()
        dialog = SourceReviewDialog(window.openings, "later", window)
        fill(dialog)
        dialog.save.click()
        assert window.openings.provenance("later")["sequence"] is not None
        assert not window.openings.decisions()
        select(window, "bad")
        assert not window.edit.isEnabled()
        assert "source balance difference" in window.page.details.toPlainText()
        window.close()


def test_independent_states_and_coverage_details_are_visible(app, tmp_path, rebuild):
    add_period(rebuild, "prior", "2026-06-01", "2026-06-30")
    workspace = prepare_custom(tmp_path, rebuild)
    with prepared(workspace) as review:
        attest(OpeningReview(review), "prior")
        finish_cash_card(review, workspace[1])
        window = ReconciliationReviewWindow(review, workspace[0])
        select(window, "s1")
        app.processEvents()
        assert window.selected()["cells"][3:5] == ["Agrees", "Reconciled"]
        select(window, "s2")
        assert window.selected()["cells"][3:5] == ["Agrees", "Needs review"]
        assert "estimated" in window.page.details.toPlainText()
        bank = next(r for r in window.coverage.model.records if r["cells"][0] == "Checking")
        assert bank["cells"][3] == "Yes" and "coverage gap" in bank["details"]
        assert any(r["cells"][-1] == "outside cash card scope" for r in window.unmapped.model.records)
        window.close()


def test_unadmitted_zero_evidence_does_not_invent_reported_dates(app, workspace):
    with prepared(workspace) as review:
        window = ReconciliationReviewWindow(review, workspace[0])
        select(window, "s3")
        app.processEvents()
        zero = next(r for r in window.evidence.model.records if r["cells"][1] == "zero")
        assert zero["cells"][3:] == ["Not admitted", "unknown"]
        window.close()


def test_failed_currentness_check_retries_without_another_database_change(app, workspace, monkeypatch):
    with prepared(workspace) as review:
        window = ReconciliationReviewWindow(review, workspace[0])
        original = window.view.is_current

        def fail():
            raise LedgerError("Temporary check failure")

        monkeypatch.setattr(window.view, "is_current", fail)
        window.check_current(force=True)
        app.processEvents()
        assert not window.current and "Could not verify" in window.banner.text()
        monkeypatch.setattr(window.view, "is_current", original)
        window.check_current()
        assert window.current
        window.close()


def test_failed_snapshot_save_preserves_last_view_and_database(workspace, monkeypatch):
    with prepared(workspace) as review:
        view = ReconciliationView(review, workspace[0])
        view.check()
        before, report = view.path.read_bytes(), view.report
        database = list(review.store.connection.iterdump())

        def fail(*_):
            raise OSError("Interrupted replace")

        monkeypatch.setattr("parsetrail.core.ledger_reconciliation_view.os.replace", fail)
        with pytest.raises(OSError, match="Interrupted"):
            view.check()
        assert view.path.read_bytes() == before and view.report == report
        assert not list(workspace[0].glob("*.tmp"))
        assert list(review.store.connection.iterdump()) == database


@pytest.mark.parametrize("change", ["checksum", "binding", "rule"])
def test_saved_view_rejects_tampering_and_wrong_binding(workspace, change):
    with prepared(workspace) as review:
        view = ReconciliationView(review, workspace[0])
        view.check()
        saved = json.loads(view.path.read_text())
        if change == "checksum":
            saved["sha256"] = "changed"
        else:
            saved["report"]["candidate_hash" if change == "binding" else "rule"] = "changed"
            saved["sha256"] = key(saved["report"])
        view.path.write_text(json.dumps(saved))
        with pytest.raises(LedgerError, match="different evidence"):
            ReconciliationView(review, workspace[0])


def test_malformed_saved_view_is_not_silently_replaced(workspace):
    with prepared(workspace) as review:
        path = workspace[0] / "reconciliation-view.json"
        path.write_text("{")
        with pytest.raises(LedgerError, match="malformed"):
            ReconciliationView(review, workspace[0])
        assert path.read_text() == "{"
