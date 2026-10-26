"""Transfer suggestions and whole-event corrections preserve dates and evidence."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_card_source_output import from_anchored_card

from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_statement_journal_comparison import _profile as bank_profile
from .test_v2_transfers import BANK_DEFINITION, _profile

PREFERENCES = V2Preferences()


def _snapshot(store, *, replacing=None, preferences=PREFERENCES):
    return store.transfer_review_snapshot(preferences=preferences, max_day_gap=31, replacing_event_id=replacing)


def _post(store, outgoing, incoming, *, preferences=PREFERENCES, reason="Reviewed transfer"):
    selected = _snapshot(store, preferences=preferences)
    return store.post_reviewed_transfer(
        outgoing, incoming, preferences=preferences, reason=reason, expected_basis_sha256=selected.basis_sha256
    )


def _alternative(store):
    source = b"Date,Account,Description,Amount,ReportedBalance\n01/06/2026,Savings B,Transfer in,$20.00,$1020.00\n"
    evidence = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    store.import_source(source, BANK_DEFINITION, evidence, suffix=".csv")
    store.add_financial_account(FinancialAccount("savings", "Savings", "asset", "synthetic"))
    store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "savings")
    return evidence.payload.rows[0].row_id


@pytest.mark.parametrize("bank_date,legs", [("01/05/2026", 1), ("01/03/2026", 2)])
def test_withdraw_whole_event_releases_allocations_and_repost_uses_fresh_identity(
    tmp_path: Path, bank_date: str, legs: int
) -> None:
    path = tmp_path / "withdraw.db"
    outgoing, incoming = _profile(path, bank_date=bank_date)
    with V2ProfileStore.open(path) as store:
        original = _post(store, outgoing, incoming)
        selected = _snapshot(store)
        cancelled = store.withdraw_reviewed_transfer(
            original, expected_basis_sha256=selected.basis_sha256, reason="Incorrect interpreted payment"
        )
        assert cancelled.status == "cancelled" and len(cancelled.entry_keys) == legs
        assert cancelled.replacement_event_id is None
        assert store._active_consumed() == {}
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (legs,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (legs * 2,)
        assert (
            store.withdraw_reviewed_transfer(
                original, expected_basis_sha256=selected.basis_sha256, reason="Incorrect interpreted payment"
            )
            == cancelled
        )
        for cutoff in (date(2026, 1, 3), date(2026, 1, 5), date(2026, 1, 31)):
            positions = store.account_positions(as_of=cutoff)
            assert positions.transfer_clearing_debit_minor == 0
            assert all(row.recorded_debit_minor == 0 for row in positions.accounts)
        spending = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert spending.total_minor == 0
        report = store.reviewed_journal_export(start=spending.start, end=spending.end)
        assert report.entries == () and len(report.retirements) == legs
        assert report.transfer_actions[0].event_id == original and report.transfer_actions[0].action == "cancel"
        workbook = load_workbook(write_reviewed_journal_workbook(report, tmp_path / "cancelled.xlsx"), read_only=True)
        try:
            assert list(workbook["Transfer Reviews"].values)[1][:3] == (original, "cancel", None)
        finally:
            workbook.close()
        reposted = _post(store, outgoing, incoming, reason="Fresh reviewed confirmation")
        assert reposted != original
        assert store._active_consumed() == {outgoing: -2_000, incoming: 2_000}
        assert [event.status for event in store.transfer_history()] == ["active", "cancelled"]
        assert store.transfer_history()[0].event_id == reposted
        history = store.transfer_history()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.transfer_history() == history


@pytest.mark.parametrize("bank_date", ["01/05/2026", "01/03/2026"])
def test_atomic_replacement_changes_destination_and_preserves_dated_clearing(tmp_path: Path, bank_date: str) -> None:
    path = tmp_path / "replace.db"
    outgoing, incoming = _profile(path, bank_date=bank_date)
    with V2ProfileStore.open(path) as store:
        savings = _alternative(store)
        original = _post(store, outgoing, incoming)
        selected = _snapshot(store, replacing=original)
        assert any(p.outgoing.row_id == outgoing and p.incoming.row_id == savings for p in selected.candidates)
        replacement = store.replace_reviewed_transfer(
            original,
            outgoing,
            savings,
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Correct destination account",
        )
        assert replacement != original
        assert (
            store.replace_reviewed_transfer(
                original,
                outgoing,
                savings,
                expected_basis_sha256=selected.basis_sha256,
                preferences=PREFERENCES,
                reason="Correct destination account",
            )
            == replacement
        )
        assert store._active_consumed() == {outgoing: -2_000, savings: 2_000}
        assert incoming not in store._active_consumed()
        events = store.transfer_history()
        assert events[0].status == "active" and events[0].pair.kind == "asset transfer"
        assert events[1].status == "replaced" and events[1].replacement_event_id == replacement
        at_five = store.account_positions(as_of=date(2026, 1, 5))
        assert at_five.transfer_clearing_debit_minor == 2_000
        assert next(row for row in at_five.accounts if row.account_id == "card").recorded_debit_minor == 0
        after = store.account_positions(as_of=date(2026, 1, 6))
        assert after.transfer_clearing_debit_minor == 0
        assert next(row for row in after.accounts if row.account_id == "savings").recorded_debit_minor == 2_000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        report = store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert {entry.event_id for entry in report.entries} == {replacement}
        assert report.transfer_actions[0].replacement_event_id == replacement


def test_dismiss_reopen_is_durable_nonposting_and_bound_to_reviewed_account_context(tmp_path: Path) -> None:
    path = tmp_path / "dismiss.db"
    outgoing, incoming = _profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        selected = _snapshot(store)
        dismissed = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Unrelated equal amounts",
        )
        assert dismissed.decision == "dismiss" and dismissed.context_current
        assert _snapshot(store).candidates == () and store._active_consumed() == {}
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert (
            store.record_transfer_pair_review(
                outgoing,
                incoming,
                decision="dismiss",
                expected_basis_sha256=selected.basis_sha256,
                preferences=PREFERENCES,
                reason="Unrelated equal amounts",
            )
            == dismissed
        )
        with pytest.raises(ProfileFormatError, match="transfer_review_changed_since_selection"):
            store.post_reviewed_transfer(
                outgoing,
                incoming,
                preferences=PREFERENCES,
                reason="Stale displayed pair",
                expected_basis_sha256=selected.basis_sha256,
            )
        selected = _snapshot(store)
        reopened = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="reopen",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Review again",
        )
        assert reopened.decision == "reopen" and len(_snapshot(store).candidates) == 1
        selected = _snapshot(store)
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Still unrelated",
        )
        store.add_financial_account(FinancialAccount("other", "Other checking", "asset", "synthetic"))
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
        store.bind_source_account(source_id, "Checking A", "opaque", "other")
        refreshed = _snapshot(store)
        assert len(refreshed.candidates) == 1 and refreshed.candidates[0].outgoing.account_id == "other"
        assert not refreshed.pair_reviews[0].context_current
        reviews = refreshed.pair_reviews
    with V2ProfileStore.open(path, read_only=True) as store:
        assert _snapshot(store).pair_reviews == reviews


@pytest.mark.parametrize("failure", ["second_leg", "new_post", "event_metadata", "action_metadata"])
def test_replacement_failures_leave_original_event_and_allocations_intact(tmp_path: Path, failure: str) -> None:
    path = tmp_path / "atomic.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        savings = _alternative(store)
        original = _post(store, outgoing, incoming)
        selected = _snapshot(store, replacing=original)
        if failure in {"second_leg", "new_post"}:
            condition = "NEW.original_key LIKE '%:in'" if failure == "second_leg" else "NEW.key LIKE '%:v2:%'"
            table = "JournalRetirements" if failure == "second_leg" else "JournalEntries"
            store.connection.execute(
                f"CREATE TRIGGER fail_transfer BEFORE INSERT ON {table} WHEN {condition} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
            )
        else:
            table = "TransferEvents" if failure == "event_metadata" else "TransferEventActions"
            store.connection.execute(
                f"CREATE TRIGGER fail_transfer BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
            )
        with pytest.raises(sqlite3.DatabaseError):
            store.replace_reviewed_transfer(
                original,
                outgoing,
                savings,
                expected_basis_sha256=selected.basis_sha256,
                preferences=PREFERENCES,
                reason="Atomic new destination",
            )
        store.connection.execute("DROP TRIGGER fail_transfer")
        assert not store.connection.in_transaction
        assert store._active_consumed() == {outgoing: -2_000, incoming: 2_000}
        assert store.transfer_history()[0].status == "active"
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (2,)
        assert len(store.transfer_history()) == 1


def test_stale_event_selection_and_read_only_nested_refusals(tmp_path: Path) -> None:
    path = tmp_path / "stale.db"
    outgoing, incoming = _profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        event = _post(store, outgoing, incoming)
        old = _snapshot(store)
        store.update_financial_account(FinancialAccount("checking", "Renamed checking", "asset", "synthetic"))
        with pytest.raises(ProfileFormatError, match="transfer_review_changed_since_selection"):
            store.withdraw_reviewed_transfer(event, expected_basis_sha256=old.basis_sha256, reason="Stale confirmation")
        current = _snapshot(store)
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="transfer_requires_committed_snapshot"):
            _snapshot(store)
        with pytest.raises(ProfileFormatError, match="transfer_requires_committed_snapshot"):
            store.withdraw_reviewed_transfer(event, expected_basis_sha256=current.basis_sha256, reason="Nested refused")
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.withdraw_reviewed_transfer(
                event, expected_basis_sha256=current.basis_sha256, reason="Readonly refused"
            )


def test_backup_retains_transfer_decisions_and_rejects_corrupt_event_manifest(tmp_path: Path) -> None:
    path, backup = tmp_path / "profile.db", tmp_path / "backup.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        event = _post(store, outgoing, incoming)
        selected = _snapshot(store)
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=selected.basis_sha256, reason="Withdraw whole event"
        )
        history = store.transfer_history()
    original_bytes = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == original_bytes
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.transfer_history() == history
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_TransferEvents_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_TransferEvents_update")
        connection.execute("UPDATE TransferEvents SET entry_versions='[]'")
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.transfer_history()
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_revision_thirteen_profile_is_refused_without_writes(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=13")
    original = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == original


def test_new_assumed_date_posting_requires_opt_in_but_existing_event_withdrawal_does_not(tmp_path: Path) -> None:
    path = tmp_path / "assumed.db"
    card = _chase_profile(path)
    source = b"Date,Account,Description,Amount,ReportedBalance\n04/01/2026,Checking A,Payment,-$5.00,$995.00\n"
    cash = build_source_evidence(source, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(source, BANK_DEFINITION, cash, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.bind_source_account(cash.source_sha256, "Checking A", "opaque", "checking")
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
        selected = _snapshot(store)
        pair = selected.candidates[0]
        assert pair.incoming.date_provenance == "assumed" and not pair.posting_allowed
        with pytest.raises(ProfileFormatError, match="transfer_assumed_date_disabled"):
            store.post_reviewed_transfer(
                pair.outgoing.row_id,
                pair.incoming.row_id,
                preferences=PREFERENCES,
                expected_basis_sha256=selected.basis_sha256,
                reason="Reviewed assumed date",
            )
        enabled = V2Preferences(False, True)
        event = _post(store, pair.outgoing.row_id, pair.incoming.row_id, preferences=enabled)
        selected = _snapshot(store, preferences=enabled)
        # The stored interpretation can be withdrawn even after the preference is disabled.
        assert _snapshot(store, preferences=PREFERENCES).basis_sha256 == selected.basis_sha256
        cancelled = store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=selected.basis_sha256, reason="Withdraw after disabling guesses"
        )
        assert cancelled.status == "cancelled" and store._active_consumed() == {}
        assert not _snapshot(store).candidates[0].posting_allowed


def test_composite_transfer_snapshot_stays_coherent_during_concurrent_withdrawal(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "concurrent.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        event = _post(store, outgoing, incoming)
        original = store._read_transfer_history
        changed = False

        def concurrent_withdrawal():
            nonlocal changed
            result = original()
            if not changed:
                changed = True
                with V2ProfileStore.open(path) as other:
                    selected = _snapshot(other)
                    other.withdraw_reviewed_transfer(
                        event, expected_basis_sha256=selected.basis_sha256, reason="Concurrent reviewed withdrawal"
                    )
            return result

        monkeypatch.setattr(store, "_read_transfer_history", concurrent_withdrawal)
        selected = _snapshot(store)
        assert selected.events[0].status == "active" and selected.candidates == ()
        monkeypatch.setattr(store, "_read_transfer_history", original)
        refreshed = _snapshot(store)
        assert refreshed.events[0].status == "cancelled" and len(refreshed.candidates) == 1
        assert selected.basis_sha256 != refreshed.basis_sha256
        assert not store.connection.in_transaction


@pytest.mark.parametrize("corruption", ["event", "action", "pair", "partial_retirement", "missing_event", "entry"])
def test_corrupt_transfer_history_refuses_common_reads_and_backup(tmp_path: Path, corruption: str) -> None:
    path = tmp_path / "corrupt.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        selected = _snapshot(store)
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Review candidate",
        )
        selected = _snapshot(store)
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="reopen",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Reconsider candidate",
        )
        event = _post(store, outgoing, incoming)
        selected = _snapshot(store)
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=selected.basis_sha256, reason="Withdraw whole interpretation"
        )
    with sqlite3.connect(path) as connection:
        if corruption == "event":
            table, action, sql = "TransferEvents", "update", "UPDATE TransferEvents SET reason='Altered reason'"
        elif corruption == "action":
            table, action, sql = (
                "TransferEventActions",
                "update",
                "UPDATE TransferEventActions SET reason='Altered action reason'",
            )
        elif corruption == "pair":
            table, action, sql = (
                "TransferPairReviews",
                "update",
                "UPDATE TransferPairReviews SET context_sha256='altered'",
            )
        elif corruption == "partial_retirement":
            table, action, sql = (
                "JournalRetirements",
                "delete",
                "DELETE FROM JournalRetirements WHERE original_key LIKE '%:in'",
            )
        elif corruption == "missing_event":
            table, action, sql = "TransferEvents", "delete", "DELETE FROM TransferEvents"
        else:
            table, action = "JournalEntries", "update"
            key, payload = connection.execute(
                "SELECT key,payload FROM JournalEntries WHERE key LIKE '%:out'"
            ).fetchone()
            data = json.loads(payload)
            data["postings"][1]["amount_minor"] = 1_999
            sql = None
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_{action}",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_{action}")
        if sql is None:
            connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(data), key))
        else:
            connection.execute(sql)
        connection.execute(trigger)
    if corruption == "missing_event":
        with pytest.raises(ProfileFormatError):
            V2ProfileStore.open(path, read_only=True)
        with pytest.raises(ProfileFormatError):
            V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
        return
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            lambda: _snapshot(store),
            store._active_consumed,
            lambda: store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1)),
        ):
            with pytest.raises(ProfileFormatError):
                read()
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


def test_transfer_history_tables_are_append_only(tmp_path: Path) -> None:
    path = tmp_path / "immutable.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        selected = _snapshot(store)
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Suggestion only",
        )
        selected = _snapshot(store)
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="reopen",
            expected_basis_sha256=selected.basis_sha256,
            preferences=PREFERENCES,
            reason="Reopen suggestion",
        )
        event = _post(store, outgoing, incoming)
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=_snapshot(store).basis_sha256, reason="Reviewed withdrawal"
        )
        for table in ("TransferEvents", "TransferEventActions", "TransferPairReviews"):
            for sql in (f"UPDATE {table} SET reason='rewrite'", f"DELETE FROM {table}"):
                with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                    store.connection.execute(sql)


def test_withdrawal_invalidates_saved_reconciliation_without_changing_spending_or_income(tmp_path: Path) -> None:
    path = tmp_path / "reconciled.db"
    bank = bank_profile(path)
    card = from_anchored_card(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.open(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        account = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, account.source_identity, account.source_identity_form, "card")
        for account_id, evidence in (("cash", bank), ("card", card)):
            store.record_statement_source_review(
                account_id,
                evidence.source_sha256,
                expected_revision_id=None,
                opening_origin="reported",
                closing_origin="reported",
                timing_confirmed=True,
                posting_dates="reported",
                source_reference="Synthetic printed endpoints and source dates",
            )
            store.post_reviewed_opening(account_id)
        interest, withdrawal = bank.payload.accounts[0].rows
        payment, purchase = card.payload.accounts[0].rows
        store.post_reviewed_cash_category(interest.row_id, "income:interest", reason="Reviewed interest")
        store.post_reviewed_card_purchase(
            purchase.row_id, "expense:other", reason="Reviewed purchase", preferences=PREFERENCES
        )
        event = _post(store, withdrawal.row_id, payment.row_id)
        check = next(check for check in store.statement_reconciliation_checks() if check.account_id == "cash")
        assert check.reconciled and check.posted_interpretations_reviewed
        saved = store.save_reconciliation_decision(
            "cash", bank.source_sha256, expected_input_version=check.input_version, reason="Reviewed exact statement"
        )
        # Card receipt precedes the cash debit: clearing is negative at the intermediate cutoff.
        assert store.account_positions(as_of=date(2026, 1, 5)).transfer_clearing_debit_minor == -2_000
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=_snapshot(store).basis_sha256, reason="Withdraw whole interpreted payment"
        )
        history = store.reconciliation_history("cash")[0]
        assert history.stale and history.check == saved.check
        position = next(
            row for row in store.account_positions(as_of=date(2026, 1, 31)).accounts if row.account_id == "cash"
        )
        assert position.latest_saved_reconciled_cutoff == saved.cutoff_date
        assert position.current_saved_reconciled_cutoff is None
        current = next(check for check in store.statement_reconciliation_checks() if check.account_id == "cash")
        assert not current.reconciled and "unallocated_source_movements" in current.exceptions
        assert store.account_positions(as_of=date(2026, 1, 5)).transfer_clearing_debit_minor == 0
        scope = {"start": date(2026, 1, 1), "end": date(2026, 2, 1)}
        assert store.reviewed_category_summary(kind="expense", **scope).total_minor == 1_000
        assert store.reviewed_category_summary(kind="income", **scope).total_minor == 1_000


@pytest.mark.parametrize(
    "table,column,value",
    [
        ("TransferEvents", "request_basis", sqlite3.Binary(b"malformed-basis")),
        ("TransferEvents", "sequence", 1.5),
        ("TransferEvents", "sequence", sqlite3.Binary(b"1")),
        ("TransferEvents", "pair_payload", "null"),
        ("TransferEvents", "entry_versions", sqlite3.Binary(b"[]")),
        ("TransferEvents", "record_sha256", sqlite3.Binary(b"checksum")),
        ("TransferEventActions", "request_basis", sqlite3.Binary(b"malformed-basis")),
        ("TransferEventActions", "reason", sqlite3.Binary(b"review-note")),
        ("TransferEventActions", "created_at", sqlite3.Binary(b"timestamp")),
        ("TransferPairReviews", "request_basis", sqlite3.Binary(b"malformed-basis")),
        ("TransferPairReviews", "pair_payload", "null"),
        ("TransferPairReviews", "context_sha256", sqlite3.Binary(b"context")),
    ],
)
def test_malformed_transfer_storage_uses_profile_errors_across_versioned_reads_and_backup(
    tmp_path: Path,
    table: str,
    column: str,
    value,
) -> None:
    path = tmp_path / "malformed.db"
    outgoing, incoming = _profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=_snapshot(store).basis_sha256,
            preferences=PREFERENCES,
            reason="Inspect suggestion",
        )
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="reopen",
            expected_basis_sha256=_snapshot(store).basis_sha256,
            preferences=PREFERENCES,
            reason="Reopen suggestion",
        )
        event = _post(store, outgoing, incoming)
        store.withdraw_reviewed_transfer(
            event, expected_basis_sha256=_snapshot(store).basis_sha256, reason="Whole event withdrawal"
        )
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_update")
        connection.execute(f"UPDATE {table} SET {column}=?", (value,))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            lambda: _snapshot(store),
            store.transfer_history,
            store._active_consumed,
            store._source_overlap_basis,
            store._reconciliation_rule_and_version,
            store.statement_reconciliation_checks,
        ):
            with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
                read()
        assert not store.connection.in_transaction
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()
