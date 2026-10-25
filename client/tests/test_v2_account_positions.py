"""As-of journal positions keep opening validity and source limits explicit."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_category_reports import DEFINITION, SOURCE
from .test_v2_reviewed_openings import _profile as opening_profile
from .test_v2_source_openings import _variant
from .test_v2_statement_journal_comparison import _profile
from .test_v2_statement_reconciliation import _review_and_post
from .test_v2_transfers import _profile as transfer_profile


def test_inclusive_cutoff_missing_future_valid_and_stale_opening(tmp_path: Path) -> None:
    path = tmp_path / "positions.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        pending = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert pending.recorded_debit_minor == 0 and pending.position_debit_minor is None
        assert pending.opening_status == "missing" and pending.pending_activity_rows == 2
        _review_and_post(store, evidence)
        future = store.account_positions(as_of=date(2025, 12, 30)).accounts[0]
        assert future.opening_status == "future" and future.position_debit_minor is None
        assert future.history == () and future.recorded_debit_minor == 0
        opening = store.account_positions(as_of=date(2025, 12, 31)).accounts[0]
        assert opening.opening_status == "valid" and opening.position_debit_minor == 10_000
        assert opening.opening_cutoff == date(2025, 12, 31)
        assert len(opening.history) == 1 and opening.history[0].position_debit_minor == 10_000
        assert store.account_positions(as_of=date(2026, 1, 4)).accounts[0].position_debit_minor == 10_000
        assert store.account_positions(as_of=date(2026, 1, 5)).accounts[0].position_debit_minor == 11_000
        report = store.account_positions(as_of=date(2026, 1, 31))
        position = report.accounts[0]
        assert report.currency == position.currency == "USD"
        assert position.position_debit_minor == position.recorded_debit_minor == 9_000
        assert position.pending_activity_rows == 0 and position.excluded_unreviewed_entries == 0
        assert position.latest_source_cutoff == position.live_reconciled_cutoff == date(2026, 1, 31)
        assert position.latest_activity_date == date(2026, 1, 10)
        assert position.coverage_warnings == ("source_capture_incomplete",)
        assert (
            "source_cutoff_before_as_of"
            in store.account_positions(as_of=date(2026, 2, 1)).accounts[0].coverage_warnings
        )
        assert "source_period_extends_after_as_of" in opening.coverage_warnings
        store.record_statement_source_review(
            "cash",
            evidence.source_sha256,
            expected_revision_id=store.statement_source_reviews("cash")[0].revision_id,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Rechecked source basis",
        )
        stale = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert stale.opening_status == "stale" and stale.position_debit_minor is None
        assert stale.recorded_debit_minor == 9_000 and stale.live_reconciled_cutoff is None
        assert all(row.position_debit_minor is None for row in stale.history)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0] == stale
        assert not store.connection.in_transaction
    assert path.read_bytes() == before


def test_zero_opening_is_known_without_a_journal_entry(tmp_path: Path) -> None:
    path = tmp_path / "zero.db"
    evidence = opening_profile(path, amount_minor=0)
    with V2ProfileStore.open(path) as store:
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Printed zero",
        )
        store.post_reviewed_opening("cash")
        position = store.account_positions(as_of=date(2025, 12, 31)).accounts[0]
        assert position.opening_status == "valid"
        assert position.opening_minor == position.position_debit_minor == 0
        assert position.history == ()


def test_transfer_keeps_liability_debit_sign_and_in_transit_clearing(tmp_path: Path) -> None:
    path = tmp_path / "transfer.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        # Only the card statement can establish an opening; the cash export cannot.
        card_source = next(
            binding.source_sha256 for binding in store.statement_coverage() if binding.account_id == "card"
        )
        store.record_opening_source_review(
            "card", card_source, opening_origin="reported", timing_confirmed=True, source_reference="Printed card debt"
        )
        store.post_reviewed_opening("card")
        store.post_reviewed_transfer(outgoing, incoming, preferences=V2Preferences(), reason="Reviewed payment")
        transit = store.account_positions(as_of=date(2026, 1, 3))
        positions = {row.account_id: row for row in transit.accounts}
        assert positions["checking"].recorded_debit_minor == -2_000
        assert positions["checking"].position_debit_minor is None
        assert positions["card"].position_debit_minor == -10_000  # liability owed displays as +100.00
        assert transit.transfer_clearing_debit_minor == 2_000
        received = store.account_positions(as_of=date(2026, 1, 5))
        assert received.transfer_clearing_debit_minor == 0
        card = next(row for row in received.accounts if row.account_id == "card")
        assert card.kind == "liability" and card.position_debit_minor == -8_000
        assert card.pending_activity_rows == 1  # unreviewed purchase, not the fully allocated payment


def test_date_corrections_restate_accounting_history_and_keep_all_audit_rows(tmp_path: Path) -> None:
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        original = store.post_reviewed_card_purchase(
            account.rows[0].row_id, "expense:food", reason="Reviewed date", preferences=V2Preferences(False, True)
        )
        replacement = store.correct_reviewed_card_purchase(
            original, "expense:food", reason="Correct accounting date", accounting_date=date(2026, 4, 1)
        )
        store.correct_reviewed_card_purchase(replacement, "expense:travel", reason="Correct category")
        march = store.account_positions(as_of=date(2026, 3, 31)).accounts[0]
        assert march.recorded_debit_minor == 0 and march.position_debit_minor is None
        assert {row.correction_role for row in march.history} == {"original", "reversal"}
        april = store.account_positions(as_of=date(2026, 4, 1)).accounts[0]
        assert april.recorded_debit_minor == -1_000
        assert len(april.history) == 5
        assert {row.correction_role for row in april.history} == {
            "original",
            "reversal",
            "replacement",
            "superseded_replacement",
        }
        assert sum(row.debit_change_minor for row in april.history) == april.recorded_debit_minor
        assert april.pending_activity_rows == 1


def test_pending_counts_keep_unbound_and_repeated_sources_visible(tmp_path: Path) -> None:
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    path = tmp_path / "pending.db"
    evidence = _profile(path)
    extra = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(SOURCE, DEFINITION, extra, suffix=".csv")
        source = b"%PDF-repeat-for-positions"
        repeated = _variant(evidence, source)
        store.import_source(source, store.load_import(evidence.source_sha256).definition, repeated, suffix=".pdf")
        account = repeated.payload.accounts[0]
        store.bind_source_account(repeated.source_sha256, account.source_identity, account.source_identity_form, "cash")
        report = store.account_positions(as_of=date(2025, 1, 1))
        assert report.unbound_activity_rows == 3
        assert report.activity_rows_without_full_allocation == 7
        assert report.sources_with_incomplete_activity == 3
        cash = report.accounts[0]
        assert cash.pending_activity_rows == 4  # whole-profile dates, conservative supporting-evidence scope
        assert cash.latest_activity_date == date(2026, 1, 10)


def test_posting_before_opening_after_review_is_a_position_conflict(tmp_path: Path) -> None:
    path = tmp_path / "conflict.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)",
            (
                "earlier",
                json.dumps(
                    {
                        "key": "earlier",
                        "event_id": "earlier",
                        "posting_date": "2025-12-30",
                        "description": "Synthetic earlier entry",
                        "origin": "manual",
                        "reviewed": True,
                        "reason": "Simulated future admitted workflow",
                        "postings": [
                            {"account_id": "cash", "amount_minor": 1, "allocations": []},
                            {"account_id": "internal:opening-equity:USD", "amount_minor": -1, "allocations": []},
                        ],
                    }
                ),
            ),
        )
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert position.opening_status == "conflict" and position.position_debit_minor is None
        assert position.recorded_debit_minor == 9_001


def test_as_of_validation_and_existing_transaction_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.db"
    with V2ProfileStore.create(path) as store:
        assert store.account_positions(as_of=date.max).accounts == ()
        for invalid in (None, "2026-01-01", datetime(2026, 1, 1)):
            with pytest.raises(ProfileFormatError, match="report_as_of_invalid"):
                store.account_positions(as_of=invalid)
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="positions_requires_committed_snapshot"):
            store.account_positions(as_of=date(2026, 1, 1))
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")


def test_positions_pin_one_snapshot_across_concurrent_profile_changes(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "concurrent.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        store.add_financial_account(FinancialAccount("first", "First", "asset", "synthetic"))
        original = store._statement_reconciliation_checks

        def mutate_between_reads():
            with V2ProfileStore.open(path) as writer:
                writer.add_financial_account(FinancialAccount("second", "Second", "asset", "synthetic"))
            return original()

        monkeypatch.setattr(store, "_statement_reconciliation_checks", mutate_between_reads)
        report = store.account_positions(as_of=date(2026, 1, 1))
        assert [row.account_id for row in report.accounts] == ["first"]
        assert len(store.financial_accounts()) == 2
        assert not store.connection.in_transaction


def test_unreviewed_postings_do_not_enter_positions_or_history(tmp_path: Path) -> None:
    path = tmp_path / "unreviewed.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        for index, posting_date in enumerate(("2026-01-20", "2026-02-20")):
            key = f"unreviewed:{index}"
            store.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)",
                (
                    key,
                    json.dumps(
                        {
                            "key": key,
                            "event_id": key,
                            "posting_date": posting_date,
                            "description": "Unreviewed synthetic journal",
                            "origin": "manual",
                            "reviewed": False,
                            "reason": "Simulated future workflow",
                            "postings": [
                                {"account_id": "cash", "amount_minor": 100, "allocations": []},
                                {"account_id": "internal:opening-equity:USD", "amount_minor": -100, "allocations": []},
                            ],
                        }
                    ),
                ),
            )
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert position.position_debit_minor == position.recorded_debit_minor == 9_000
        assert position.excluded_unreviewed_entries == 1
        assert not any(row.entry_key.startswith("unreviewed:") for row in position.history)
        assert position.live_reconciled_cutoff is None


def test_query_failure_releases_its_own_snapshot(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "failure.db"
    with V2ProfileStore.create(path) as store:

        def fail():
            raise RuntimeError("Synthetic read failure")

        monkeypatch.setattr(store, "_statement_reconciliation_checks", fail)
        with pytest.raises(RuntimeError, match="Synthetic read failure"):
            store.account_positions(as_of=date(2026, 1, 31))
        assert not store.connection.in_transaction
        store.add_financial_account(FinancialAccount("cash", "Cash", "asset", "synthetic"))
