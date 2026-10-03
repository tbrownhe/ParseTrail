import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.ledger import JournalEntry, LedgerError, Posting
from parsetrail.core.ledger_candidates import create_candidates
from parsetrail.core.ledger_opening_review import OpeningReview, observation_date_provenance
from parsetrail.core.ledger_openings import build_opening_readiness
from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.recovery_bundle import digest
from parsetrail.gui.ledger_opening_review import OpeningReviewWindow

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_proposal_review import app as app


@pytest.fixture
def workspace(tmp_path, rebuild, request):
    for fid, f in rebuild["evidence"]["files"].items():
        f["filename"] = fid + ".pdf"
    rebuild["evidence"]["statements"]["s1"]["opening_minor"] += 2500
    rebuild["evidence"]["statements"]["s1"]["closing_minor"] += 2500
    if hasattr(request, "param"):
        rebuild["evidence"]["statements"]["s2"]["opening_minor"] += request.param
        rebuild["evidence"]["statements"]["s2"]["closing_minor"] += request.param
    source = accepted_folder(tmp_path, rebuild)
    candidates = tmp_path / "candidates"
    create_candidates(source, candidates)
    folder, readiness = tmp_path / "review", tmp_path / "readiness"
    prepare_review(candidates, folder)
    plan = json.loads((candidates / "proposals.json").read_text())
    result = build_opening_readiness(rebuild, plan)
    readiness.mkdir()
    (readiness / "readiness.json").write_text(encoded(result), encoding="utf-8")
    (readiness / "report.json").write_text(json.dumps({"readiness_sha256": digest(readiness / "readiness.json")}))
    return folder, readiness


def attest(openings, sid="s1", **changes):
    payload = {
        "opening": "reported",
        "closing": "reported",
        "timing_confirmed": True,
        "posting_dates": "reported",
        "reference": "Page 1, balance summary",
        "reason": "Source inspected",
    }
    payload.update(changes)
    openings.assert_source(sid, **payload)


def test_confirmed_nonzero_opening_uses_equity_and_preserves_raw_evidence(workspace):
    folder, readiness = workspace
    with ProposalReview(folder) as review:
        c = review.store.connection
        originals = {
            table: c.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("SourceStatements", "LedgerStatements", "LedgerObservations", "CategoryAnnotations")
        }
        openings = OpeningReview(review, readiness)
        with pytest.raises(LedgerError, match="blocked"):
            openings.confirm_opening("account:1")
        attest(openings)
        assert openings.effective_statement("s1").opening_provenance == "reported"
        openings.confirm_opening("account:1")
        entry = decode_entry(c.execute("SELECT payload FROM LedgerEntries").fetchone()[0])
        assert entry.origin == "opening" and entry.reviewed
        assert str(entry.posting_date) == "2026-07-31"
        assert [(p.account_id, p.amount_minor) for p in entry.postings] == [
            ("account:1", 2500),
            ("equity:opening", -2500),
        ]
        assert review.store.consumed() == {}
        for table, rows in originals.items():
            assert c.execute(f"SELECT * FROM {table}").fetchall() == rows
        before = list(c.iterdump())
        attest(openings)
        openings.confirm_opening("account:1")
        assert list(c.iterdump()) == before
    with ProposalReview(folder) as review:
        assert OpeningReview(review).status("account:1")["state"] == "posted"


def test_zero_opening_and_chase_estimates_are_separate_assertions(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        assert openings.provenance("s2")["posting_dates"] == "estimated"
        with pytest.raises(LedgerError, match="must remain estimated"):
            attest(openings, "s2")
        attest(openings, "s2", posting_dates="estimated")
        openings.confirm_opening("account:2")
        assert openings.status("account:2")["state"] == "confirmed_zero"
        assert openings.provenance("s2")["posting_dates"] == "estimated"
        assert review.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        assert "equity:opening" not in review.store.accounts()


@pytest.mark.parametrize("workspace", [-1000], indirect=True)
def test_credit_card_opening_preserves_liability_sign(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings, "s2", posting_dates="estimated")
        openings.confirm_opening("account:2")
        entry = decode_entry(review.store.connection.execute("SELECT payload FROM LedgerEntries").fetchone()[0])
        assert [(p.account_id, p.amount_minor) for p in entry.postings] == [
            ("account:2", -1000),
            ("equity:opening", 1000),
        ]


def test_opening_cannot_offset_earlier_posting(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings)
        review.store.post(
            JournalEntry(
                "earlier",
                "earlier",
                date(2026, 7, 30),
                "Earlier adjustment",
                (Posting("account:1", 50), Posting("category:1", -50)),
                origin="manual",
                reviewed=True,
                reason="Explicit prior adjustment",
            )
        )
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="Earlier postings"):
            openings.confirm_opening("account:1")
        assert list(review.store.connection.iterdump()) == before


def test_changed_assertion_during_confirmation_requires_refresh(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings)
        basis = openings.status("account:1")["provenance_hash"]
        attest(openings, reference="Page 2, updated source reference")
        with pytest.raises(LedgerError, match="changed since selection"):
            openings.confirm_opening("account:1", expected_provenance_hash=basis)
        assert not openings.decisions()


def test_date_provenance_is_available_to_ordinary_and_transfer_consumers(app, workspace):
    from parsetrail.core.ledger_transfers import TransferReview
    from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow

    with ProposalReview(workspace[0]) as review:
        # Older prepared copies also disclose known estimates before adding opening tables.
        assert observation_date_provenance(review.store)["source:card_payment"] == "estimated"
        openings = OpeningReview(review, workspace[1])
        attest(openings, posting_dates="estimated")
        assert observation_date_provenance(review.store)["source:bank_payment"] == "estimated"
        attest(openings, posting_dates="reported")
        assert TransferReview(review).snapshot()["pairs"][0]["posting_date_basis"] == ["reported", "estimated"]
        window = ProposalReviewWindow(review)
        app.processEvents()
        card_records = [r for r in window.records if r["cells"][0] == "Credit Card"]
        assert card_records
        assert all("Posting-date provenance: estimated" in r["details"] for r in card_records)
        window.close()


@pytest.mark.parametrize("changes", [{"opening": "derived"}, {"timing_confirmed": False}, {"opening": "assumed"}])
def test_unverified_derived_or_unknown_timing_cannot_authorize_opening(workspace, changes):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings, **changes)
        with pytest.raises(LedgerError, match="blocked"):
            openings.confirm_opening("account:1")
        assert not openings.decisions()


def test_later_review_marks_opening_stale_without_rewriting_it(workspace):
    with ProposalReview(workspace[0]) as first, ProposalReview(workspace[0]) as second:
        openings = OpeningReview(first, workspace[1])
        other = OpeningReview(second)
        attest(openings)
        openings.confirm_opening("account:1")
        before = first.store.connection.execute("SELECT * FROM LedgerEntries").fetchall()
        attest(other, opening="derived", reason="Rechecked: balance was reconstructed")
        assert openings.status("account:1")["state"] == "stale_source_review"
        with pytest.raises(LedgerError, match="requires a correction"):
            openings.confirm_opening("account:1")
        assert first.store.connection.execute("SELECT * FROM LedgerEntries").fetchall() == before


def test_opening_failure_rolls_back_equity_journal_and_decision(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings)
        c = review.store.connection
        c.execute(
            "CREATE TRIGGER fail_opening BEFORE INSERT ON OpeningDecisions BEGIN SELECT RAISE(ABORT,'interrupted'); END"
        )
        before = list(c.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="interrupted"):
            openings.confirm_opening("account:1")
        assert list(c.iterdump()) == before
        c.execute("DROP TRIGGER fail_opening")
        openings.confirm_opening("account:1")
        for table in ("SourceAssertions", "OpeningDecisions", "SourceDateProvenance"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                c.execute(f"DELETE FROM {table}")


def test_tampered_or_conflicting_plan_cannot_authorize_wrong_opening(workspace):
    folder, readiness = workspace
    path = readiness / "readiness.json"
    plan = json.loads(path.read_text())
    plan["anchors"][0]["proposed_amount_minor"] += 1
    path.write_text(encoded(plan))
    with ProposalReview(folder) as review:
        with pytest.raises(LedgerError, match="artifact changed"):
            OpeningReview(review, readiness)
        (readiness / "report.json").write_text(json.dumps({"readiness_sha256": digest(path)}))
        with pytest.raises(LedgerError, match="earliest source evidence"):
            OpeningReview(review, readiness)


@pytest.mark.parametrize(
    "changes", [{"reference": " "}, {"reason": ""}, {"posting_dates": "guessed"}, {"timing_confirmed": 1}]
)
def test_invalid_source_assertions_are_not_recorded(workspace, changes):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            attest(openings, **changes)
        assert list(review.store.connection.iterdump()) == before


def test_ui_source_review_cancel_post_and_persistence(app, workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        window = OpeningReviewWindow(openings)
        window.show()
        window.page.search.setText("Checking")
        window.page.table.selectRow(0)
        app.processEvents()
        assert not window.post.isEnabled()
        window.opening.setCurrentIndex(window.opening.findData("reported"))
        window.timing.setChecked(True)
        window.reference.setText("Page 1 summary (workflow test)")
        window.confirm = lambda *_: False
        window.save.click()
        assert openings.provenance("s1")["sequence"] is None
        window.confirm = lambda *_: True
        window.save.click()
        assert window.post.isEnabled()
        # Unsaved changes cannot silently confirm using an older saved assertion.
        window.timing.setChecked(False)
        assert not window.post.isEnabled()
        window.timing.setChecked(True)
        window.confirm = lambda *_: False
        window.post.click()
        assert not openings.decisions()
        window.confirm = lambda *_: True
        window.post.click()
        assert openings.status("account:1")["state"] == "posted"
        window.page.search.setText("no-result")
        assert not window.post.isEnabled() and not window.save.isEnabled()
        window.close()
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review)
        assert openings.status("account:1")["state"] == "posted"
        window = OpeningReviewWindow(openings)
        window.page.search.setText("Credit Card")
        window.page.table.selectRow(0)
        assert window.dates.currentData() == "estimated" and not window.dates.isEnabled()
        window.close()
