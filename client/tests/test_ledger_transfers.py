import copy
import sqlite3
from datetime import date

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_candidates import create_candidates
from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review
from parsetrail.core.ledger_store import decode_entry
from parsetrail.core.ledger_transfers import TransferReview, pair_id

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_proposal_review import app as app

PAIR = ("source:bank_payment", "source:card_payment")


def workspace(tmp_path, rebuild):
    accepted = accepted_folder(tmp_path, rebuild)
    candidates = tmp_path / "candidates"
    create_candidates(accepted, candidates)
    folder = tmp_path / "review"
    prepare_review(candidates, folder)
    return folder


def extra_incoming(rebuild, tid="alternative", amount=1000):
    e = rebuild["evidence"]
    e["transactions"][tid] = {**e["transactions"]["interest"], "id": tid, "AmountMinor": amount}
    e["memberships"].append({"statement_id": "s3", "transaction_id": tid, "source": "bank", "row": 99})
    e["statements"]["s3"]["closing_minor"] += amount


def test_suggestions_are_deterministic_unposted_and_same_day_payment_has_no_expense(tmp_path, rebuild):
    folder = workspace(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        transfers = TransferReview(review)
        before = list(review.store.connection.iterdump())
        snapshot = transfers.snapshot()
        assert snapshot == transfers.snapshot()
        assert list(review.store.connection.iterdump()) == before
        assert snapshot["summary"] == {"unique_candidate": 1}
        assert snapshot["pairs"][0]["kind"] == "card_payment"
        assert any(m["status"] == "no_candidate" for m in snapshot["movements"])
        transfers.decide([PAIR], "confirmed")
        entries = [decode_entry(p) for (p,) in review.store.connection.execute("SELECT payload FROM LedgerEntries")]
        assert len(entries) == 1 and entries[0].reviewed
        assert {p.account_id for p in entries[0].postings} == {"account:1", "account:2"}
        assert review.store.consumed() == dict(zip(PAIR, (-1000, 1000), strict=True))
        before = list(review.store.connection.iterdump())
        transfers.decide([PAIR], "confirmed")
        assert list(review.store.connection.iterdump()) == before
        assert transfers.snapshot()["pairs"][0]["status"] == "confirmed"
    with ProposalReview(folder) as reopened:
        assert TransferReview(reopened).decisions()[pair_id(*PAIR)]["action"] == "confirmed"


@pytest.mark.parametrize(
    "bank_date,card_date,clearing_balance",
    [
        ("2026-08-31", "2026-09-02", 1000),
        ("2026-09-02", "2026-08-31", -1000),
    ],
)
def test_month_crossing_keeps_each_source_date_and_in_transit_balance(
    tmp_path, rebuild, bank_date, card_date, clearing_balance
):
    e = rebuild["evidence"]
    e["transactions"]["bank_payment"]["PostingDate"] = bank_date
    e["transactions"]["card_payment"]["PostingDate"] = card_date
    e["statements"]["s1"]["end"] = e["statements"]["s2"]["end"] = "2026-09-30"
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        assert not transfers.snapshot(1)["pairs"]
        assert transfers.snapshot(2)["pairs"]
        transfers.decide([PAIR], "confirmed")
        entries = [decode_entry(p) for (p,) in review.store.connection.execute("SELECT payload FROM LedgerEntries")]
        assert len(entries) == 2
        assert len({e.event_id for e in entries}) == 1
        assert {e.posting_date for e in entries} == {date.fromisoformat(bank_date), date.fromisoformat(card_date)}
        clearing = f"clearing:{pair_id(*PAIR)}"
        assert review.store.balances(date(2026, 8, 31))[clearing] == clearing_balance
        assert review.store.balances(date(2026, 9, 2))[clearing] == 0
        assert all(sum(p.amount_minor for p in entry.postings) == 0 for entry in entries)
        # Saved decisions remain visible after changing the search window.
        assert transfers.snapshot(0)["pairs"][0]["status"] == "confirmed"


def test_ambiguous_choices_never_auto_post_and_conflicting_batch_rolls_back(tmp_path, rebuild):
    extra_incoming(rebuild)
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        assert transfers.snapshot()["summary"] == {"ambiguous": 2}
        second = (PAIR[0], "source:alternative")
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError, match="allocated"):
            transfers.decide([PAIR, second], "confirmed")
        assert list(review.store.connection.iterdump()) == before
        transfers.decide([PAIR], "dismissed", "Not the same payment")
        assert review.store.consumed() == {}
        assert transfers.snapshot()["summary"] == {"dismissed": 1, "unique_candidate": 1}
        transfers.decide([second], "confirmed")
        assert review.store.balances(date(2026, 8, 31))["account:3"] == 1000


def test_pending_expense_requires_rejection_before_transfer_and_category_is_preserved(tmp_path, rebuild):
    extra_incoming(rebuild, amount=1500)
    pair = ("source:bank_purchase", "source:alternative")
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        categories = review.store.connection.execute("SELECT * FROM CategoryAnnotations").fetchall()
        assert any(p["status"] == "expense_conflict" for p in transfers.snapshot()["pairs"])
        with pytest.raises(LedgerError, match="Reject the conflicting"):
            transfers.decide([pair], "confirmed")
        review.decide(["proposal:bank_purchase"], "rejected", "This was a transfer")
        transfers.decide([pair], "confirmed")
        assert review.store.connection.execute("SELECT * FROM CategoryAnnotations").fetchall() == categories
        assert review.decisions()["proposal:bank_purchase"]["action"] == "rejected"


def test_consumed_and_partial_evidence_are_visible_and_cannot_be_reused(tmp_path, rebuild):
    extra_incoming(rebuild, amount=1500)
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        draft = decode_entry(review.proposals["proposal:bank_purchase"])
        from dataclasses import replace

        from parsetrail.core.ledger import Allocation, Posting

        partial = replace(
            draft,
            key="partial",
            postings=(
                Posting("account:1", -500, (Allocation("source:bank_purchase", -500),)),
                Posting("category:1", 500),
            ),
        )
        review.store.post(partial)
        assert any(p["status"] == "allocated" for p in transfers.snapshot()["pairs"])
        assert any(m["status"] == "partially_allocated" for m in transfers.snapshot()["movements"])
        with pytest.raises(LedgerError, match="allocated"):
            transfers.decide([("source:bank_purchase", "source:alternative")], "confirmed")


def test_database_failure_rolls_back_both_dated_entries_clearing_and_decision(tmp_path, rebuild):
    rebuild["evidence"]["transactions"]["card_payment"]["PostingDate"] = "2026-08-21"
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        c = review.store.connection
        c.execute("""CREATE TRIGGER simulate_failure BEFORE INSERT ON TransferDecisions
            BEGIN SELECT RAISE(ABORT,'interrupted'); END""")
        before = list(c.iterdump())
        with pytest.raises(sqlite3.IntegrityError, match="interrupted"):
            transfers.decide([PAIR], "confirmed")
        assert list(c.iterdump()) == before
        c.execute("DROP TRIGGER simulate_failure")
        transfers.decide([PAIR], "confirmed")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM TransferDecisions")


@pytest.mark.parametrize(
    "pairs,action,reason,window",
    [
        ([PAIR], "confirmed", "", -1),
        ([PAIR], "confirmed", "", True),
        ([PAIR], "dismissed", "", 7),
        ([PAIR, PAIR], "confirmed", "", 7),
        ([(PAIR[1], PAIR[0])], "confirmed", "", 7),
        ([(PAIR[0], "source:loan")], "confirmed", "", 7),
        ([(PAIR[0], "source:card_refund")], "confirmed", "", 7),
    ],
)
def test_invalid_requests_never_post(tmp_path, rebuild, pairs, action, reason, window):
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        transfers = TransferReview(review)
        before = list(review.store.connection.iterdump())
        with pytest.raises(LedgerError):
            transfers.decide(pairs, action, reason, window)
        assert list(review.store.connection.iterdump()) == before


def test_same_account_and_fee_difference_do_not_match(tmp_path, rebuild):
    e = rebuild["evidence"]
    e["transactions"]["card_payment"]["AmountMinor"] = 999
    e["statements"]["s2"]["closing_minor"] -= 1
    # An opposite row on the same account is not an internal transfer.
    e["transactions"]["same"] = {**e["transactions"]["bank_payment"], "id": "same", "AmountMinor": 1000}
    e["statements"]["s1"]["closing_minor"] += 1000
    e["memberships"].append({"statement_id": "s1", "transaction_id": "same", "source": "bank", "row": 99})
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        assert not TransferReview(review).snapshot()["pairs"]


def test_overlapping_statement_membership_does_not_duplicate_transfer(tmp_path, rebuild):
    e = rebuild["evidence"]
    e["statements"]["overlap"] = {**e["statements"]["s1"], "id": "overlap"}
    e["memberships"] += [
        {**r, "statement_id": "overlap"} for r in copy.deepcopy(e["memberships"]) if r["statement_id"] == "s1"
    ]
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        assert len(TransferReview(review).snapshot()["pairs"]) == 1


def test_transfer_window_cancel_confirm_filter_and_reopen(app, tmp_path, rebuild):
    from parsetrail.gui.ledger_transfer_review import TransferReviewWindow

    folder = workspace(tmp_path, rebuild)
    with ProposalReview(folder) as review:
        window = TransferReviewWindow(review)
        window.show()
        window.page.search.setText("Card payment")
        window.page.table.selectRow(0)
        app.processEvents()
        assert window.confirm_button.isEnabled()
        assert not window.dismiss_button.isEnabled()
        assert "Spending effect if confirmed: $0.00" in window.page.details.toPlainText()
        window.confirm = lambda *_: False
        window.confirm_button.click()
        assert not window.transfers.decisions()
        seen = []
        window.confirm = lambda action, row, reason: seen.append(row["pair"]["id"]) or True
        window.confirm_button.click()
        assert seen == [pair_id(*PAIR)]
        assert window.page.proxy.rowCount() == 0
        window.filter.setCurrentText("Confirmed")
        window.page.table.selectRow(0)
        assert not window.confirm_button.isEnabled()
        window.tabs.setCurrentIndex(1)
        window.movements.search.setText("bank_payment")
        assert window.movements.proxy.rowCount() == 1
        window.movements.table.selectRow(0)
        assert "Remaining unallocated: $0.00" in window.movements.details.toPlainText()
        window.close()
    with ProposalReview(folder) as review:
        window = TransferReviewWindow(review)
        window.filter.setCurrentText("Confirmed")
        assert window.page.proxy.rowCount() == 1
        window.close()


@pytest.mark.usefixtures("app")
def test_conflicting_expense_tab_must_be_resolved_before_confirmation(tmp_path, rebuild):
    from parsetrail.gui.ledger_transfer_review import TransferReviewWindow

    extra_incoming(rebuild, amount=1500)
    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        window = TransferReviewWindow(review)
        window.filter.setCurrentText("Expense conflict")
        window.page.table.selectRow(0)
        assert not window.confirm_button.isEnabled()
        window.tabs.setCurrentIndex(2)
        window.ordinary.page.search.setText("bank_purchase")
        window.ordinary.page.table.selectRow(0)
        window.ordinary.reason.setText("Transfer interpretation instead")
        window.ordinary.confirm = lambda *_: True
        window.ordinary.reject.click()
        window.tabs.setCurrentIndex(0)
        assert window.page.proxy.rowCount() == 0
        window.filter.setCurrentText("Ready for review")
        window.page.search.setText("Cash transfer")
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        assert window.confirm_button.isEnabled()
        window.confirm = lambda *_: True
        window.confirm_button.click()
        assert (
            window.transfers.decisions()[pair_id("source:bank_purchase", "source:alternative")]["action"] == "confirmed"
        )
        window.close()


@pytest.mark.usefixtures("app")
def test_dismissal_requires_note_and_filter_change_clears_selection(tmp_path, rebuild):
    from parsetrail.gui.ledger_transfer_review import TransferReviewWindow

    with ProposalReview(workspace(tmp_path, rebuild)) as review:
        window = TransferReviewWindow(review)
        window.page.table.selectRow(0)
        window.note.setText("Different events")
        assert window.dismiss_button.isEnabled()
        window.page.search.setText("not-a-match")
        assert not window.confirm_button.isEnabled() and not window.dismiss_button.isEnabled()
        window.page.search.clear()
        window.page.table.selectRow(0)
        window.confirm = lambda *_: True
        window.dismiss_button.click()
        assert review.store.consumed() == {}
        window.filter.setCurrentText("Dismissed")
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        assert "Different events" in window.page.details.toPlainText()
        window.close()
