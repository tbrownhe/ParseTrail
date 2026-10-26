"""Reviewed opening corrections retain decisions, exact inverses and zero states."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from openpyxl import load_workbook
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE

from .test_v2_reviewed_openings import _profile
from .test_v2_statement_journal_comparison import _profile as journal_profile
from .test_v2_statement_reconciliation import _review_and_post


def _review(store, evidence, *, reference="Printed synthetic opening"):
    existing = next(
        (r for r in store.statement_source_reviews("cash") if r.source_sha256 == evidence.source_sha256), None
    )
    return store.record_statement_source_review(
        "cash",
        evidence.source_sha256,
        expected_revision_id=existing.revision_id if existing else None,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference=reference,
    )


def _new_source(
    store, original, *, amount=0, start="2026-01-01", end="2026-01-31", replace_binding=True, label="changed"
):
    source = SOURCE + f"-{label}-{amount}-{start}".encode()
    old = original.payload.accounts[0]
    money = old.opening.model_copy(update={"raw": str(amount), "minor": amount})
    account = old.model_copy(update={"opening": money, "closing": money, "rows": ()})
    payload = original.payload.model_copy(
        update={
            "start": original.payload.start.model_copy(update={"raw": start, "iso": start}),
            "end": original.payload.end.model_copy(update={"raw": end, "iso": end}),
            "accounts": (account,),
            "independent_balance_verified": True,
        }
    )
    evidence = original.model_copy(update={"source_sha256": hashlib.sha256(source).hexdigest(), "payload": payload})
    store.import_source(source, DEFINITION, evidence, suffix=".pdf")
    if replace_binding:
        store.clear_source_account_binding(original.source_sha256, old.source_identity, old.source_identity_form)
    store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
    _review(store, evidence)
    return evidence


def _correct(store, *, reason="Correct reviewed source opening"):
    snapshot = store.opening_review_snapshot("cash")
    return store.correct_reviewed_opening(
        "cash",
        expected_decision_version=snapshot.decision.version,
        expected_basis_sha256=snapshot.basis_sha256,
        reason=reason,
    )


def test_nonzero_zero_nonzero_keeps_initial_history_and_no_dummy_replacement(tmp_path: Path) -> None:
    path = tmp_path / "corrections.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        assert initial.revision_id == 0 and initial.version
        zero_source = _new_source(store, evidence)
        selected = store.opening_review_snapshot("cash")
        assert selected.decision.stale and selected.candidate.printed_opening_minor == 0
        zero = _correct(store)
        assert zero.amount_minor == 0 and zero.entry_key is None and not zero.stale
        assert zero.revision_id > 0 and zero.version != initial.version
        assert store.post_reviewed_opening("cash") == zero
        assert (
            store.correct_reviewed_opening(
                "cash",
                expected_decision_version=initial.version,
                expected_basis_sha256=selected.basis_sha256,
                reason="Correct reviewed source opening",
            )
            == zero
        )
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (2,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (1,)
        assert store._active_journal_entries() == ()
        assert store._active_consumed() == {}
        position = store.account_positions(as_of=date(2025, 12, 31)).accounts[0]
        assert position.position_debit_minor == 0 and position.opening_status == "valid"
        assert {row.correction_role for row in position.history} == {"retired", "retirement_reversal"}
        movement = store.financial_journal_summary(start=date(2025, 12, 1), end=date(2026, 1, 1)).accounts[0]
        assert movement.nonopening_change_minor == movement.opening_minor == 0
        report = store.reviewed_journal_export(start=date(2025, 12, 1), end=date(2026, 1, 1))
        assert report.entries == () and len(report.retirements) == 1
        assert report.excluded_opening_entries == 2
        workbook = load_workbook(write_reviewed_journal_workbook(report, tmp_path / "opening.xlsx"), read_only=True)
        try:
            assert len(list(workbook["Reviewed Entries"].values)) == 1
            assert list(workbook["Retirements"].values)[1][:2] == (
                initial.entry_key,
                report.retirements[0].reversal_key,
            )
        finally:
            workbook.close()
        later = _new_source(store, zero_source, amount=5_000, label="nonzero")
        updated = _correct(store, reason="Source now supports nonzero opening")
        assert updated.amount_minor == 5_000 and updated.entry_key != initial.entry_key
        assert store.post_reviewed_opening("cash") == updated
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (1,)
        assert store.account_positions(as_of=date(2025, 12, 31)).accounts[0].position_debit_minor == 5_000
        assert [row.amount_minor for row in store.opening_decision_history("cash")] == [5_000, 0, 10_000]
        assert store.load_import(later.source_sha256).evidence == later
        with pytest.raises(ProfileFormatError, match="opening_decision_changed_since_selection"):
            store.correct_reviewed_opening(
                "cash",
                expected_decision_version=initial.version,
                expected_basis_sha256=store.opening_review_basis("cash"),
                reason="Obsolete form",
            )
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.opening_decision("cash") == updated
        assert store.connection.execute("SELECT amount_minor FROM OpeningDecisions").fetchone() == (10_000,)


def test_changed_cutoff_reverses_at_original_date_and_preserves_as_of_math(tmp_path: Path) -> None:
    path = tmp_path / "cutoff.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=8_000, start="2025-12-01", end="2025-12-31", replace_binding=False)
        updated = _correct(store)
        assert updated.cutoff_date == date(2025, 11, 30)
        inverse = store.connection.execute("SELECT reversal_key FROM JournalRetirements").fetchone()[0]
        payload = json.loads(
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (inverse,)).fetchone()[0]
        )
        assert payload["posting_date"] == initial.cutoff_date.isoformat()
        assert payload["postings"][0]["amount_minor"] == -10_000
        assert store.account_positions(as_of=date(2025, 11, 29)).accounts[0].position_debit_minor is None
        for cutoff in (date(2025, 11, 30), date(2025, 12, 31), date(2026, 1, 31)):
            position = store.account_positions(as_of=cutoff).accounts[0]
            assert position.position_debit_minor == position.recorded_debit_minor == 8_000


def test_basis_only_refresh_retains_journal_and_refuses_stale_forms(tmp_path: Path) -> None:
    path = tmp_path / "basis.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        old = store.opening_review_snapshot("cash")
        _review(store, evidence, reference="Rechecked source basis")
        with pytest.raises(ProfileFormatError, match="opening_review_changed_since_selection"):
            store.correct_reviewed_opening(
                "cash",
                expected_decision_version=initial.version,
                expected_basis_sha256=old.basis_sha256,
                reason="Stale source selection",
            )
        current = store.opening_review_snapshot("cash")
        refreshed = _correct(store, reason="Confirm rechecked basis")
        assert refreshed.entry_key == initial.entry_key and not refreshed.stale
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (1,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (0,)
        with pytest.raises(ProfileFormatError, match="opening_decision_changed_since_selection"):
            store.correct_reviewed_opening(
                "cash",
                expected_decision_version=initial.version,
                expected_basis_sha256=current.basis_sha256,
                reason="Different concurrent decision",
            )
        with pytest.raises(ProfileFormatError, match="opening_correction_requires_changed_basis"):
            _correct(store)


@pytest.mark.parametrize("fail_at", ["retirement", "replacement", "revision"])
def test_failed_correction_rolls_back_inverse_replacement_and_revision(tmp_path: Path, fail_at: str) -> None:
    path = tmp_path / "atomic.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        _new_source(store, evidence, amount=7_000)
        if fail_at == "replacement":
            store.connection.execute(
                "CREATE TRIGGER refuse_opening_replacement BEFORE INSERT ON JournalEntries "
                "WHEN NEW.key LIKE 'review:opening:correction:%' "
                "BEGIN SELECT RAISE(ABORT,'synthetic replacement failure'); END"
            )

        def deny(action, table, _column, _database, _trigger):
            if action == sqlite3.SQLITE_INSERT:
                if (fail_at == "retirement" and table == "JournalRetirements") or (
                    fail_at == "revision" and table == "OpeningDecisionRevisions"
                ):
                    return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        store.connection.set_authorizer(deny)
        with pytest.raises(sqlite3.DatabaseError):
            _correct(store)
        store.connection.set_authorizer(None)
        if fail_at == "replacement":
            store.connection.execute("DROP TRIGGER refuse_opening_replacement")
        assert not store.connection.in_transaction
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (1,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalRetirements").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM OpeningDecisionRevisions").fetchone() == (0,)
        assert store.opening_decision("cash").version == initial.version
        assert _correct(store).amount_minor == 7_000


def test_conflicting_tied_sources_and_preopening_activity_refuse_correction(tmp_path: Path) -> None:
    path = tmp_path / "blocked.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        conflicting = _new_source(store, evidence, amount=2_000, replace_binding=False)
        assert "conflicting_earliest_openings" in store.opening_review_snapshot("cash").candidate.blockers
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            _correct(store)
        account = evidence.payload.accounts[0]
        store.clear_source_account_binding(
            evidence.source_sha256, account.source_identity, account.source_identity_form
        )
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)",
            (
                "earlier",
                json.dumps(
                    {
                        "key": "earlier",
                        "event_id": "earlier",
                        "posting_date": "2025-12-30",
                        "description": "Synthetic active earlier movement",
                        "origin": "manual",
                        "reviewed": True,
                        "reason": "Synthetic conflict check",
                        "postings": [
                            {"account_id": "cash", "amount_minor": 1, "allocations": []},
                            {"account_id": "internal:opening-equity:USD", "amount_minor": -1, "allocations": []},
                        ],
                    }
                ),
            ),
        )
        with pytest.raises(ProfileFormatError, match="opening_earlier_posting_conflict"):
            _correct(store)
        assert store.opening_decision("cash").version == initial.version
        assert store.load_import(conflicting.source_sha256).evidence == conflicting


def test_correction_invalidates_saved_reconciliation_and_backup_preserves_revisions(tmp_path: Path) -> None:
    path, backup = tmp_path / "profile.db", tmp_path / "backup.db"
    evidence = journal_profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        check = store.statement_reconciliation_checks()[0]
        saved = store.save_reconciliation_decision(
            "cash",
            evidence.source_sha256,
            expected_input_version=check.input_version,
            reason="Reviewed source",
        )
        overlap_before = store._source_overlap_basis()
        _review(store, evidence, reference="Rechecked exact opening")
        updated = _correct(store)
        assert store.reconciliation_history()[0].stale
        assert store.reconciliation_history()[0].check == saved.check
        assert store.statement_reconciliation_checks()[0].reconciled
        assert store._source_overlap_basis() != overlap_before
        history = store.opening_decision_history("cash")
    before = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == before
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.opening_decision("cash") == updated
        assert store.opening_decision_history("cash") == history
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            _correct(store)


def test_opening_snapshot_and_nested_refusal_preserve_caller_transaction(tmp_path: Path) -> None:
    path = tmp_path / "nested.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
        selected = store.opening_review_snapshot("cash")
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="opening_requires_committed_snapshot"):
            store.opening_review_snapshot("cash")
        with pytest.raises(ProfileFormatError, match="opening_requires_committed_snapshot"):
            store.correct_reviewed_opening(
                "cash",
                expected_decision_version=selected.decision.version,
                expected_basis_sha256=selected.basis_sha256,
                reason="Nested refused",
            )
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")


@pytest.mark.parametrize("revised", [False, True])
def test_persisted_decision_digest_refuses_unconfirmed_basis_in_initial_or_revision(
    tmp_path: Path, revised: bool
) -> None:
    path = tmp_path / "basis-corruption.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
        if revised:
            _review(store, evidence, reference="First recheck")
            _correct(store)
        _review(store, evidence, reference="New unconfirmed review basis")
        assert store.opening_decision("cash").stale
        basis = store.opening_review_basis("cash")
    table = "OpeningDecisionRevisions" if revised else "OpeningDecisions"
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_update")
        connection.execute(f"UPDATE {table} SET basis_sha256=?", (basis,))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (
            lambda: store.opening_decision("cash"),
            lambda: store.opening_decision_history("cash"),
            lambda: store.account_positions(as_of=date(2026, 1, 31)),
        ):
            with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
                read()
    with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


def test_latest_opening_cannot_point_at_retired_money_without_a_revision(tmp_path: Path) -> None:
    from parsetrail.core.v2_profile_store import _decode_journal

    path = tmp_path / "retired-latest.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
        payload = store.connection.execute(
            "SELECT payload FROM JournalEntries WHERE key=?", (initial.entry_key,)
        ).fetchone()[0]
        store.connection.execute("BEGIN")
        store._retire_journal_entry(_decode_journal(payload), reason="Synthetic invalid incomplete lifecycle")
        store.connection.execute("COMMIT")
        with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
            store.opening_decision("cash")
    with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


@pytest.mark.parametrize("corruption", ["counterpart", "account", "payload_allocation", "index_allocation"])
def test_linked_initial_opening_requires_full_balanced_shape_without_allocations(
    tmp_path: Path, corruption: str
) -> None:
    path = tmp_path / "linked-opening.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        initial = store.post_reviewed_opening("cash")
    with sqlite3.connect(path) as connection:
        if corruption == "index_allocation":
            connection.execute(
                "INSERT INTO JournalAllocations VALUES (?,?,?)",
                (initial.entry_key, evidence.payload.accounts[0].rows[0].row_id, 10_000),
            )
        else:
            payload = json.loads(
                connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (initial.entry_key,)).fetchone()[0]
            )
            if corruption == "counterpart":
                payload["postings"][1]["amount_minor"] = -9_999
            elif corruption == "account":
                payload["postings"][1]["account_id"] = "cash"
            else:
                payload["postings"][0]["allocations"] = [{"observation_id": "invented", "amount_minor": 10_000}]
            trigger = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
            ).fetchone()[0]
            connection.execute("DROP TRIGGER immutable_JournalEntries_update")
            connection.execute(
                "UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), initial.entry_key)
            )
            connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
            store.opening_decision_history("cash")
        with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
            store.account_positions(as_of=date(2026, 1, 31))
        for report in (
            lambda: store.financial_journal_summary(start=date(2025, 12, 1), end=date(2026, 2, 1)),
            lambda: store.reviewed_category_summary(kind="expense", start=date(2025, 12, 1), end=date(2026, 2, 1)),
            lambda: store.reviewed_journal_export(start=date(2025, 12, 1), end=date(2026, 2, 1)),
        ):
            with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
                report()
    with pytest.raises(ProfileFormatError, match="opening_decision_history_invalid"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()
