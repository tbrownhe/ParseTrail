import importlib.util
import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.ledger import JournalEntry, LedgerError, Posting
from parsetrail.core.ledger_candidates import create_candidates
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_openings import build_opening_readiness
from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import LedgerStore, decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.core.recovery_bundle import digest

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_opening_review import attest
from .test_ledger_opening_review import workspace as workspace
from .test_ledger_openings import add_period


def finish_cash_card(review, readiness):
    openings = OpeningReview(review, readiness)
    attest(openings)
    attest(openings, "s2", posting_dates="estimated")
    openings.confirm_opening("account:1")
    openings.confirm_opening("account:2")
    review.decide(list(review.proposals), "accepted")
    transfers = TransferReview(review)
    pair = transfers.snapshot()["pairs"][0]
    transfers.decide([(pair["outgoing_id"], pair["incoming_id"])], "confirmed")
    return openings


def statement(report, sid="s1"):
    return next(r for r in report["statements"] if r["statement_id"] == sid)


def test_reviewed_balances_reconcile_without_promoting_raw_provenance(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        before = list(review.store.connection.iterdump())
        service = ReviewedReconciliation(review)
        result = service.snapshot()
        bank, card = statement(result), statement(result, "s2")
        assert bank["reconciled"] and bank["balance_check"]["reconciled"]
        assert bank["posted_interpretations_reviewed"]
        assert not bank["unresolved_observations"]
        assert card["balance_check"]["reconciled"] and not card["reconciled"]
        assert card["exceptions"] == ["posting_dates_not_verified"]
        assert set(card["date_uncertain_observations"].values()) == {"estimated"}
        assert result["outside_scope_statement_ids"] == ["s4"]
        assert {r["transaction_id"]: r["status"] for r in result["unmapped_movements"]} == {
            "loan": "outside_cash_card_scope",
            "zero": "zero_amount_evidence",
        }
        assert result["remaining_observations"] == {"source:interest": 10}
        assert service.is_current(result) and service.snapshot() == result
        assert list(review.store.connection.iterdump()) == before
        raw = json.loads(
            review.store.connection.execute("SELECT payload FROM LedgerStatements WHERE id='statement:s1'").fetchone()[
                0
            ]
        )
        assert raw["opening_provenance"] == raw["closing_provenance"] == "assumed"
        assert not result["ready_for_cutover"]


def test_fresh_unposted_workspace_exposes_exact_unresolved_movements(workspace):
    with ProposalReview(workspace[0]) as review:
        OpeningReview(review, workspace[1])
        row = statement(ReviewedReconciliation(review).snapshot())
        assert not row["reconciled"]
        assert {
            "opening_position_unverified_or_stale",
            "source_period_timing_unverified",
            "posting_dates_not_verified",
            "unallocated_evidence",
            "balance_evidence_not_independent",
        }.issubset(row["exceptions"])
        assert row["unresolved_observations"] == {
            "source:bank_purchase": -1500,
            "source:bank_payment": -1000,
            "source:bank_refund": 200,
        }
        assert row["balance_check"]["opening_difference_minor"] == -2500
        assert row["balance_check"]["source_difference_minor"] == 0


@pytest.mark.parametrize(
    "changes,exception",
    [
        ({"closing": "derived"}, "balance_evidence_not_independent"),
        ({"timing_confirmed": False}, "source_period_timing_unverified"),
        ({"posting_dates": "unknown"}, "posting_dates_not_verified"),
    ],
)
def test_revised_provenance_invalidates_reconciliation_even_without_new_postings(workspace, changes, exception):
    with ProposalReview(workspace[0]) as review:
        openings = finish_cash_card(review, workspace[1])
        service = ReviewedReconciliation(review)
        old = service.snapshot()
        attest(openings, **changes)
        assert not service.is_current(old)
        row = statement(service.snapshot())
        assert not row["reconciled"] and exception in row["exceptions"]
        assert row["opening_state"] == "stale_source_review"


def test_interpretation_review_and_balance_reconciliation_are_independent(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        service = ReviewedReconciliation(review)
        old = service.snapshot()
        review.store.review("accepted:proposal:bank_purchase", reviewed=False, reason="Reconsider interpretation")
        assert not service.is_current(old)
        row = statement(service.snapshot())
        assert row["reconciled"] and not row["posted_interpretations_reviewed"]
        assert row["unreviewed_entry_keys"] == ["accepted:proposal:bank_purchase"]


def test_correction_releases_old_allocation_and_invalidates_snapshot(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        service = ReviewedReconciliation(review)
        old = service.snapshot()
        payload = review.store.connection.execute(
            "SELECT payload FROM LedgerEntries WHERE key='accepted:proposal:bank_purchase'"
        ).fetchone()[0]
        replacement = replace(decode_entry(payload), key="replacement", description="Reviewed correction")
        review.store.correct("accepted:proposal:bank_purchase", replacement, reason="Correct description")
        assert not service.is_current(old)
        row = statement(service.snapshot())
        assert row["reconciled"] and not row["unresolved_observations"]
        assert not row["balance_check"]["uncovered_entry_keys"]


def test_unbacked_posting_is_visible_even_when_net_balances_cancel(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        service = ReviewedReconciliation(review)
        old = service.snapshot()
        for key, amount in (("extra", 20), ("offset", -20)):
            review.store.post(
                JournalEntry(
                    key,
                    key,
                    date(2026, 8, 21),
                    "Manual movement",
                    (Posting("account:1", amount), Posting("category:1", -amount)),
                    origin="manual",
                    reviewed=True,
                    reason="Synthetic fixture",
                )
            )
        assert not service.is_current(old)
        row = statement(service.snapshot())
        assert not row["reconciled"]
        assert row["balance_check"]["closing_difference_minor"] == 0
        assert row["balance_check"]["uncovered_entry_keys"] == ["extra", "offset"]


def test_zero_opening_decision_alone_changes_version(workspace):
    with ProposalReview(workspace[0]) as review:
        openings = OpeningReview(review, workspace[1])
        attest(openings, "s2", posting_dates="estimated")
        service = ReviewedReconciliation(review)
        old = service.snapshot()
        openings.confirm_opening("account:2")
        assert not service.is_current(old)
        assert review.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        assert statement(service.snapshot(), "s2")["opening_state"] == "confirmed_zero"


def test_partial_correction_exposes_remaining_evidence_and_exact_difference(workspace):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
        original = decode_entry(
            review.store.connection.execute(
                "SELECT payload FROM LedgerEntries WHERE key='accepted:proposal:bank_purchase'"
            ).fetchone()[0]
        )
        bank, expense = original.postings
        replacement = replace(
            original,
            key="partial",
            postings=(
                replace(bank, amount_minor=-1000, allocations=(replace(bank.allocations[0], amount_minor=-1000),)),
                replace(expense, amount_minor=1000),
            ),
        )
        review.store.correct(original.key, replacement, reason="Synthetic partial interpretation")
        row = statement(ReviewedReconciliation(review).snapshot())
        assert not row["reconciled"]
        assert row["unresolved_observations"] == {"source:bank_purchase": -500}
        assert row["balance_check"]["closing_difference_minor"] == 500


def prepare_custom(tmp_path, rebuild):
    for fid, file in rebuild["evidence"]["files"].items():
        file["filename"] = fid + ".pdf"
    source = accepted_folder(tmp_path, rebuild)
    candidates, folder, readiness = (tmp_path / name for name in ("candidates", "review", "readiness"))
    create_candidates(source, candidates)
    prepare_review(candidates, folder)
    plan = json.loads((candidates / "proposals.json").read_text())
    readiness.mkdir()
    (readiness / "readiness.json").write_text(encoded(build_opening_readiness(rebuild, plan)), encoding="utf-8")
    (readiness / "report.json").write_text(json.dumps({"readiness_sha256": digest(readiness / "readiness.json")}))
    return folder, readiness


def test_later_reconciliation_does_not_fill_equal_balance_coverage_gap(tmp_path, rebuild):
    add_period(rebuild, "prior", "2026-06-01", "2026-06-30")
    folder, readiness = prepare_custom(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        openings = OpeningReview(review, readiness)
        attest(openings, "prior")
        finish_cash_card(review, readiness)
        result = ReviewedReconciliation(review).snapshot()
        assert statement(result)["reconciled"]
        coverage = next(a for a in result["accounts"] if a["account_id"] == "account:1")
        assert coverage["has_coverage_gaps"]
        assert coverage["continuity_exceptions"][0]["endpoint_differences_minor"] == [0]
        assert not result["ready_for_cutover"]


def test_ineligible_source_and_overlap_are_not_silently_omitted(tmp_path, rebuild):
    add_period(rebuild, "bad", "2026-08-02", "2026-08-30", 0, 99)
    folder, readiness = prepare_custom(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        OpeningReview(review, readiness)
        result = ReviewedReconciliation(review).snapshot()
        row = statement(result, "bad")
        assert row["status"] == "unavailable" and not row["reconciled"]
        coverage = next(a for a in result["accounts"] if a["account_id"] == "account:1")
        assert coverage["unavailable_statement_ids"] == ["bad"]
        assert coverage["continuity_exceptions"][0]["status"] == "overlapping_periods"


def test_movement_without_membership_is_retained_as_unmapped(tmp_path, rebuild):
    rebuild["evidence"]["memberships"] = [
        m for m in rebuild["evidence"]["memberships"] if m["transaction_id"] != "bank_refund"
    ]
    folder, readiness = prepare_custom(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        OpeningReview(review, readiness)
        result = ReviewedReconciliation(review).snapshot()
        orphan = next(r for r in result["unmapped_movements"] if r["transaction_id"] == "bank_refund")
        assert orphan["status"] == "missing_statement_membership" and orphan["amount_minor"] == 200
        assert statement(result)["status"] == "unavailable"
        assert not result["ready_for_cutover"]


def test_month_crossing_transfer_reconciles_each_source_period_without_same_date_rewrite(tmp_path, rebuild):
    rebuild["evidence"]["transactions"]["bank_payment"]["PostingDate"] = "2026-08-31"
    rebuild["evidence"]["transactions"]["card_payment"]["PostingDate"] = "2026-09-01"
    rebuild["evidence"]["statements"]["s2"]["end"] = "2026-09-30"
    folder, readiness = prepare_custom(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        finish_cash_card(review, readiness)
        result = ReviewedReconciliation(review).snapshot()
        assert statement(result)["reconciled"]
        assert statement(result, "s2")["balance_check"]["reconciled"]
        assert statement(result, "s2")["exceptions"] == ["posting_dates_not_verified"]
        balances = review.store.balances(date(2026, 8, 31))
        clearing = [aid for aid, account in review.store.accounts().items() if account.purpose == "clearing"]
        assert len(clearing) == 1 and balances[clearing[0]] == 1000
        assert review.store.balances(date(2026, 9, 1))[clearing[0]] == 0


def test_read_only_open_and_committed_snapshot_requirement(workspace, tmp_path):
    with ProposalReview(workspace[0]) as review:
        OpeningReview(review, workspace[1])
    with ProposalReview(workspace[0], read_only=True) as review:
        service = ReviewedReconciliation(review)
        assert service.snapshot()
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            review.decide([next(iter(review.proposals))], "accepted")
        with review.store._transaction():
            with pytest.raises(LedgerError, match="own committed"):
                service.snapshot()
    with pytest.raises(LedgerError, match="read-only"):
        LedgerStore(tmp_path / "no.db", create=True, read_only=True)
    assert not (tmp_path / "no.db").exists()


def report_tool():
    path = Path(__file__).resolve().parents[2] / "devtools/ledger_audit/reconcile.py"
    spec = importlib.util.spec_from_file_location("reviewed_reconciliation_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_report


def test_report_replay_reopen_and_immutable_workspace(workspace, tmp_path):
    with ProposalReview(workspace[0]) as review:
        finish_cash_card(review, workspace[1])
    before = {p: p.read_bytes() for p in workspace[0].iterdir()}
    first = report_tool()(workspace[0], tmp_path / "first")
    assert first == report_tool()(workspace[0], tmp_path / "second")
    assert (tmp_path / "first/reconciliation.json").read_bytes() == (
        tmp_path / "second/reconciliation.json"
    ).read_bytes()
    with pytest.raises(FileExistsError):
        report_tool()(workspace[0], tmp_path / "first")
    assert all(p.read_bytes() == data for p, data in before.items())


def test_active_export_is_refused_without_output(workspace, tmp_path):
    (workspace[0] / "review.db-wal").touch()
    with pytest.raises(LedgerError, match="inactive"):
        report_tool()(workspace[0], tmp_path / "output")
    assert not (tmp_path / "output").exists()
