import json
import sqlite3

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_candidates import create_candidates
from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review
from parsetrail.core.ledger_store import decode_entry
from parsetrail.core.recovery_bundle import digest
from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow
from PySide6.QtCore import QItemSelectionModel
from PySide6.QtWidgets import QApplication

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild


@pytest.fixture
def workspace(tmp_path, rebuild):
    accepted = accepted_folder(tmp_path, rebuild)
    candidates = tmp_path / "candidates"
    create_candidates(accepted, candidates)
    folder = tmp_path / "review"
    prepare_review(candidates, folder)
    return folder, candidates


def test_accept_post_and_reject_persist_without_changing_sources(workspace):
    folder, candidates = workspace
    original = digest(candidates / "candidates.db")
    with ProposalReview(folder) as review:
        c = review.store.connection
        categories = c.execute("SELECT * FROM CategoryAnnotations").fetchall()
        proposals = c.execute("SELECT * FROM JournalProposals").fetchall()
        review.decide(["proposal:bank_purchase", "proposal:card_refund"], "accepted", "Ordinary food spending")
        review.decide(["proposal:card_purchase"], "rejected", "Needs asset accounting")
        assert c.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (2,)
        assert c.execute("SELECT count(*) FROM LedgerAllocations").fetchone() == (2,)
        assert review.store.consumed() == {"source:bank_purchase": -1500, "source:card_refund": 500}
        for (payload,) in c.execute("SELECT payload FROM LedgerEntries"):
            entry = decode_entry(payload)
            assert entry.reviewed and entry.reason == "Ordinary food spending"
            assert sum(p.amount_minor for p in entry.postings) == 0
        assert c.execute("SELECT * FROM CategoryAnnotations").fetchall() == categories
        assert c.execute("SELECT * FROM JournalProposals").fetchall() == proposals
        for table in ("LedgerReconciliations", "LedgerCorrections"):
            assert c.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        before = list(c.iterdump())
        review.decide(["proposal:bank_purchase", "proposal:card_refund"], "accepted", "Ordinary food spending")
        assert list(c.iterdump()) == before
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM ProposalDecisions")
    with ProposalReview(folder) as reopened:
        assert len(reopened.decisions()) == 3
        assert reopened.decisions()["proposal:card_purchase"]["entry_key"] is None
    assert digest(candidates / "candidates.db") == original


@pytest.mark.parametrize(
    "ids,action,reason",
    [
        ([], "accepted", "reviewed"),
        (["proposal:bank_purchase"] * 2, "accepted", "reviewed"),
        (["proposal:bank_purchase"], "accepted", " "),
        (["proposal:bank_purchase"], "unknown", "reviewed"),
        (["proposal:bank_purchase", "missing"], "accepted", "reviewed"),
    ],
)
def test_invalid_batch_posts_nothing(workspace, ids, action, reason):
    with ProposalReview(workspace[0]) as review:
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            review.decide(ids, action, reason)
        assert list(review.store.connection.iterdump()) == before


def test_mid_batch_database_failure_rolls_back_decisions_and_entries(workspace):
    with ProposalReview(workspace[0]) as review:
        c = review.store.connection
        c.execute("""CREATE TRIGGER simulate_failure BEFORE INSERT ON ProposalDecisions
            WHEN (SELECT count(*) FROM ProposalDecisions) > 0
            BEGIN SELECT RAISE(ABORT,'simulated interruption'); END""")
        before = list(c.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="simulated interruption"):
            review.decide(["proposal:bank_purchase", "proposal:card_purchase"], "accepted", "reviewed")
        assert list(c.iterdump()) == before
        c.execute("DROP TRIGGER simulate_failure")
        review.decide(["proposal:bank_purchase", "proposal:card_purchase"], "accepted", "reviewed")
        assert len(review.decisions()) == 2


def test_conflicting_concurrent_decision_rolls_back_entire_batch(workspace):
    with ProposalReview(workspace[0]) as first, ProposalReview(workspace[0]) as second:
        first.decide(["proposal:card_purchase"], "rejected", "Asset")
        before = list(first.store.connection.iterdump())
        with pytest.raises(LedgerError, match="already has a decision"):
            second.decide(["proposal:bank_purchase", "proposal:card_purchase"], "accepted", "Ordinary spending")
        assert list(first.store.connection.iterdump()) == before


def test_kernel_rejects_previously_consumed_evidence(workspace):
    with ProposalReview(workspace[0]) as review:
        # Another future workflow has already consumed this observation.
        review.store.post(decode_entry(review.proposals["proposal:bank_purchase"]))
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="consumed more than once"):
            review.decide(["proposal:bank_purchase"], "accepted", "reviewed")
        assert list(review.store.connection.iterdump()) == before


def test_prepare_refuses_overwrite_tampering_and_unprepared_database(workspace, tmp_path):
    folder, candidates = workspace
    with pytest.raises(FileExistsError):
        prepare_review(candidates, folder)
    with pytest.raises(FileNotFoundError):
        ProposalReview(candidates)
    with (candidates / "proposals.json").open("ab") as f:
        f.write(b"changed")
    with pytest.raises(LedgerError, match="have changed"):
        prepare_review(candidates, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_review_manifest_must_match_database(workspace):
    folder, _ = workspace
    manifest = json.loads((folder / "review.json").read_text())
    manifest["proposal_hash"] = "wrong"
    (folder / "review.json").write_text(json.dumps(manifest))
    with pytest.raises(LedgerError, match="does not belong"):
        ProposalReview(folder)


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_filtered_selection_cancel_accept_and_reopen(app, workspace):
    folder, _ = workspace
    with ProposalReview(folder) as review:
        window = ProposalReviewWindow(review)
        window.show()
        window.page.search.setText("card_refund")
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        app.processEvents()
        assert "Card debt decreases by $5.00" in window.page.details.toPlainText()
        assert not window.accept.isEnabled()
        window.reason.setText("Refund confirmed")
        assert window.accept.isEnabled()
        window.confirm = lambda *_: False
        window.accept.click()
        assert review.decisions() == {}
        seen = []
        window.confirm = lambda action, rows, reason: seen.append((action, [r["key"] for r in rows], reason)) or True
        window.accept.click()
        assert seen == [("accepted", ["proposal:card_refund"], "Refund confirmed")]
        assert window.page.proxy.rowCount() == 0
        assert not window.accept.isEnabled()
        window.status_filter.setCurrentText("Posted")
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        window.reason.setText("Try again")
        assert not window.accept.isEnabled()
        window.close()
    with ProposalReview(folder) as review:
        window = ProposalReviewWindow(review)
        window.status_filter.setCurrentText("Posted")
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        assert "Decision reason: Refund confirmed" in window.page.details.toPlainText()
        window.close()


@pytest.mark.usefixtures("app")
def test_batch_reject_and_filter_clear_selection(workspace):
    with ProposalReview(workspace[0]) as review:
        window = ProposalReviewWindow(review)
        window.page.search.setText("bank_")
        selection = window.page.table.selectionModel()
        for row in range(window.page.proxy.rowCount()):
            selection.select(
                window.page.proxy.index(row, 0),
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
            )
        window.reason.setText("Needs different treatment")
        assert len(window.selected()) == 2 and window.reject.isEnabled()
        window.page.search.setText("bank_purchase")
        assert not window.selected() and not window.reject.isEnabled()
        window.page.search.setText("bank_")
        window.page.table.selectAll()
        window.confirm = lambda *_: True
        window.reject.click()
        assert len(review.decisions()) == 2
        assert review.store.consumed() == {}
        window.status_filter.setCurrentText("Rejected")
        assert window.page.proxy.rowCount() == 2
        window.page.table.selectRow(0)
        assert "Needs different treatment" in window.page.details.toPlainText()
        window.close()
