"""Explicit saved reconciliation retains exact historical inputs and stale state."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels

from .test_v2_statement_journal_comparison import _profile
from .test_v2_statement_reconciliation import _review_and_post


def _save(store: V2ProfileStore, source: str, *, reason: str = "Reviewed exact synthetic endpoints"):
    check = next(item for item in store.statement_reconciliation_checks() if item.source_sha256 == source)
    return store.save_reconciliation_decision("cash", source, expected_input_version=check.input_version, reason=reason)


def test_saved_check_is_exact_idempotent_and_does_not_invalidate_itself(tmp_path: Path) -> None:
    path = tmp_path / "saved.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        check = store.statement_reconciliation_checks()[0]
        saved = _save(store, evidence.source_sha256)
        assert saved.decision_id == 1 and not saved.stale
        assert saved.check == check
        assert saved.cutoff_date == date(2026, 1, 31)
        assert saved.rule == check.rule and saved.input_version == check.input_version
        assert saved.check.printed_closing_minor == saved.check.journal_closing_minor == 9_000
        assert saved.check.coverage_warnings == ("source_capture_incomplete",)
        assert saved.created_at and saved.reason == "Reviewed exact synthetic endpoints"
        assert saved.journal_versions == tuple(
            (key, hashlib.sha256(payload.encode()).hexdigest())
            for key, payload in store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key")
        )
        assert store.statement_reconciliation_checks()[0] == check
        assert _save(store, evidence.source_sha256, reason="Repeat save with a new note") == saved
        assert store.reconciliation_history() == store.reconciliation_history("cash") == (saved,)
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert position.latest_saved_reconciled_cutoff == position.current_saved_reconciled_cutoff == saved.cutoff_date
        assert position.live_reconciled_cutoff == saved.cutoff_date
        earlier = store.account_positions(as_of=date(2026, 1, 30)).accounts[0]
        assert earlier.latest_saved_reconciled_cutoff is earlier.current_saved_reconciled_cutoff is None
        assert not store.connection.in_transaction


def test_correction_retains_stale_history_and_can_save_a_new_input_version(tmp_path: Path) -> None:
    path = tmp_path / "corrected.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        first = _save(store, evidence.source_sha256)
        withdrawal = evidence.payload.accounts[0].rows[1]
        store.correct_reviewed_cash_category(
            f"review:cash:expense:{withdrawal.row_id}", "expense:travel", reason="Correct synthetic classification"
        )
        old = store.reconciliation_history()[0]
        assert old.stale and old.check == first.check and old.journal_versions == first.journal_versions
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert position.position_debit_minor == 9_000
        assert position.latest_saved_reconciled_cutoff == position.live_reconciled_cutoff == first.cutoff_date
        assert position.current_saved_reconciled_cutoff is None
        second = _save(store, evidence.source_sha256, reason="Rechecked after correction")
        assert second.decision_id == 2 and second.input_version != first.input_version and not second.stale
        assert len(second.journal_versions) == len(first.journal_versions) + 2
        assert store.reconciliation_history() == (second, old)


def test_stale_selection_and_failed_check_cannot_be_saved(tmp_path: Path) -> None:
    path = tmp_path / "stale.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        pending = store.statement_reconciliation_checks()[0]
        with pytest.raises(ProfileFormatError, match="reconciliation_check_not_successful"):
            store.save_reconciliation_decision(
                "cash", evidence.source_sha256, expected_input_version=pending.input_version, reason="Attempt pending"
            )
        _review_and_post(store, evidence)
        selected = store.statement_reconciliation_checks()[0]
        # Another review form commits between display and the explicit save.
        with V2ProfileStore.open(path) as other:
            revision = other.statement_source_reviews("cash")[0].revision_id
            other.record_statement_source_review(
                "cash",
                evidence.source_sha256,
                expected_revision_id=revision,
                opening_origin="reported",
                closing_origin="reported",
                timing_confirmed=True,
                posting_dates="reported",
                source_reference="Rechecked by another form",
            )
        with pytest.raises(ProfileFormatError, match="reconciliation_changed_since_selection"):
            store.save_reconciliation_decision(
                "cash", evidence.source_sha256, expected_input_version=selected.input_version, reason="Stale form"
            )
        assert store.reconciliation_history() == ()
        with pytest.raises(ProfileFormatError, match="reconciliation_check_not_successful"):
            _save(store, evidence.source_sha256)
        assert not store.connection.in_transaction


def test_save_holds_immediate_transaction_and_failed_insert_is_atomic(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "atomic.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        before = store.statement_reconciliation_checks()[0]
        original = store._statement_reconciliation_checks
        observed = []
        statements = []
        store.connection.set_trace_callback(statements.append)

        def check_inside_transaction():
            observed.append(store.connection.in_transaction)
            return original()

        monkeypatch.setattr(store, "_statement_reconciliation_checks", check_inside_transaction)

        def deny_decision_insert(action, table, _column, _database, _trigger):
            if action == sqlite3.SQLITE_INSERT and table == "ReconciliationDecisions":
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        store.connection.set_authorizer(deny_decision_insert)
        with pytest.raises(sqlite3.DatabaseError):
            store.save_reconciliation_decision(
                "cash", evidence.source_sha256, expected_input_version=before.input_version, reason="Atomic save"
            )
        store.connection.set_authorizer(None)
        assert not store.connection.in_transaction
        assert store.connection.execute("SELECT COUNT(*) FROM ReconciliationDecisions").fetchone() == (0,)
        assert original()[0] == before
        saved = _save(store, evidence.source_sha256)
        assert not saved.stale and observed and all(observed)
        assert "BEGIN IMMEDIATE" in statements


def test_reason_input_and_nested_transaction_validation_preserve_caller_state(tmp_path: Path) -> None:
    path = tmp_path / "validation.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        version = store.statement_reconciliation_checks()[0].input_version
        for reason in (None, "", " ", "x" * 501):
            with pytest.raises(ProfileFormatError, match="reconciliation_reason_required"):
                store.save_reconciliation_decision(
                    "cash", evidence.source_sha256, expected_input_version=version, reason=reason
                )
        for invalid in (None, "", "invalid", "A" * 64):
            with pytest.raises(ProfileFormatError, match="reconciliation_input_version_required"):
                store.save_reconciliation_decision(
                    "cash", evidence.source_sha256, expected_input_version=invalid, reason="Explicit review"
                )
        with pytest.raises(ProfileFormatError, match="reconciliation_check_missing"):
            store.save_reconciliation_decision(
                "cash", "f" * 64, expected_input_version=version, reason="Missing source"
            )
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="reconciliation_requires_committed_snapshot"):
            store.save_reconciliation_decision(
                "cash", evidence.source_sha256, expected_input_version=version, reason="Nested save"
            )
        with pytest.raises(ProfileFormatError, match="reconciliation_requires_committed_snapshot"):
            store.reconciliation_history()
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")


def test_append_only_reopen_and_verified_backup_restore_preserve_history(tmp_path: Path) -> None:
    path, backup, restored = (tmp_path / name for name in ("profile.db", "backup.dbb", "restored.db"))
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        saved = _save(store, evidence.source_sha256)
        for sql in (
            "UPDATE ReconciliationDecisions SET reason='rewrite' WHERE decision_id=1",
            "DELETE FROM ReconciliationDecisions WHERE decision_id=1",
        ):
            with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                store.connection.execute(sql)
        assert store.reconciliation_history() == (saved,)
    original_bytes = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    V2ProfileStore.snapshot_to(backup, restored)
    for checked in (path, backup, restored):
        with V2ProfileStore.open(checked, read_only=True) as store:
            assert store.reconciliation_history() == (saved,)
            with pytest.raises(ProfileFormatError, match="profile_read_only"):
                _save(store, evidence.source_sha256)
    with V2ProfileStore.open(restored) as store:
        store.rename_category_account("expense:other", "Independent restored category")
        assert store.reconciliation_history()[0].stale
    assert path.read_bytes() == original_bytes
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert not store.reconciliation_history()[0].stale


def test_revision_eleven_profile_is_refused_before_any_write(tmp_path: Path) -> None:
    path = tmp_path / "old-pilot.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=11")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


def test_history_reads_one_snapshot_and_uses_conservative_global_version(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "concurrent.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        _review_and_post(store, evidence)
        saved = _save(store, evidence.source_sha256)
        original = store._statement_reconciliation_checks

        def mutate_after_version_is_read():
            result = original()
            with V2ProfileStore.open(path) as other:
                other.add_financial_account(FinancialAccount("other", "Other", "asset", "synthetic"))
            return result

        monkeypatch.setattr(store, "_statement_reconciliation_checks", mutate_after_version_is_read)
        assert store.reconciliation_history() == (saved,)
        monkeypatch.setattr(store, "_statement_reconciliation_checks", original)
        assert store.reconciliation_history()[0].stale
        assert not store.connection.in_transaction


def test_corrupt_saved_snapshot_refuses_read_and_backup_publication(tmp_path: Path) -> None:
    path = tmp_path / "corrupt-history.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        check = store.statement_reconciliation_checks()[0]
        store.connection.execute(
            "INSERT INTO ReconciliationDecisions "
            "(account_id,source_sha256,cutoff_date,rule,input_version,check_payload,journal_versions,snapshot_sha256,reason) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "cash",
                evidence.source_sha256,
                "2026-01-31",
                check.rule,
                check.input_version,
                "{}",
                "[]",
                "0" * 64,
                "Corrupt fixture",
            ),
        )
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            store.reconciliation_history()
        assert not store.connection.in_transaction
    backup = tmp_path / "refused.db"
    with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
        V2ProfileStore.snapshot_to(path, backup)
    assert not backup.exists() and not tuple(tmp_path.glob("*.partial"))


def test_zero_opening_and_empty_statement_can_save_without_journal_versions(tmp_path: Path) -> None:
    path = tmp_path / "zero.db"
    evidence = from_anchored_bank(DEFINITION, *bank_channels())
    zero = evidence.payload.accounts[0].opening.model_copy(update={"raw": "$0.00", "minor": 0})
    account = evidence.payload.accounts[0].model_copy(update={"opening": zero, "closing": zero, "rows": ()})
    payload = evidence.payload.model_copy(update={"accounts": (account,), "independent_balance_verified": True})
    evidence = evidence.model_copy(update={"payload": payload})
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Zero cash", "asset", "lendingclub"))
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
        store.record_statement_source_review(
            "cash",
            evidence.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Printed zero endpoints and no activity",
        )
        store.post_reviewed_opening("cash")
        saved = _save(store, evidence.source_sha256)
        assert not saved.stale and saved.journal_versions == ()
        assert saved.check.journal_opening_minor == saved.check.journal_closing_minor == 0


def test_successful_arithmetic_with_unreviewed_interpretations_cannot_be_saved(tmp_path: Path) -> None:
    path = tmp_path / "unreviewed.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        # Equal and opposite pre-period entries leave balance arithmetic unchanged
        # while the independent interpretation-review dimension remains unresolved.
        for key, amount in (("unreviewed:one", 1), ("unreviewed:two", -1)):
            store.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)",
                (
                    key,
                    json.dumps(
                        {
                            "key": key,
                            "event_id": key,
                            "posting_date": "2025-12-30",
                            "description": "Synthetic unresolved interpretation",
                            "origin": "manual",
                            "reviewed": False,
                            "reason": "Synthetic test of independent review dimension",
                            "postings": [
                                {"account_id": "cash", "amount_minor": amount, "allocations": []},
                                {
                                    "account_id": "internal:opening-equity:USD",
                                    "amount_minor": -amount,
                                    "allocations": [],
                                },
                            ],
                        }
                    ),
                ),
            )
        check = store.statement_reconciliation_checks()[0]
        assert check.reconciled and check.exceptions == () and not check.posted_interpretations_reviewed
        with pytest.raises(ProfileFormatError, match="reconciliation_check_not_successful"):
            _save(store, evidence.source_sha256)
        assert store.reconciliation_history() == ()


def test_saved_entry_versions_detect_modified_historical_payload(tmp_path: Path) -> None:
    path = tmp_path / "modified-journal.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        saved = _save(store, evidence.source_sha256)
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        key = saved.journal_versions[0][0]
        payload = json.loads(connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0])
        # Keep the financial/source shape valid so this case specifically proves
        # the saved manifest also binds nonfinancial historical review metadata.
        payload["reason"] = "Tampered synthetic historical review reason"
        connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), key))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            store.reconciliation_history()


def _add_ambiguous_source(store: V2ProfileStore, original):
    """Admitted two-section evidence explicitly bound to one authored account."""
    source = SOURCE + b"-ambiguous-bound-sections"
    account = original.payload.accounts[0]
    accounts = tuple(
        account.model_copy(
            update={
                "source_identity": identity,
                "source_identity_form": "opaque",
                "closing": account.opening,
                "rows": (),
            }
        )
        for identity in ("synthetic-section-a", "synthetic-section-b")
    )
    payload = original.payload.model_copy(update={"accounts": accounts, "independent_balance_verified": True})
    evidence = original.model_copy(update={"source_sha256": hashlib.sha256(source).hexdigest(), "payload": payload})
    store.import_source(source, DEFINITION, evidence, suffix=".pdf")
    for section in accounts:
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "cash")
    return evidence


@pytest.mark.parametrize("with_history", [False, True])
def test_backup_preserves_ambiguous_pending_sections_without_requiring_live_reconciliation(
    tmp_path: Path,
    monkeypatch,
    with_history: bool,
) -> None:
    path, backup = tmp_path / "ambiguous.db", tmp_path / "backup.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        if with_history:
            _review_and_post(store, evidence)
            saved = _save(store, evidence.source_sha256)
        _add_ambiguous_source(store, evidence)
        if with_history:
            history = store.reconciliation_history()
            assert history[0].stale and history[0].check == saved.check
        else:

            def refuse_live():
                raise AssertionError("Empty history must not recompute live reconciliation")

            monkeypatch.setattr(store, "_statement_reconciliation_checks", refuse_live)
            assert store.reconciliation_history() == ()
        snapshot = V2ProfileStore.reconciliation_snapshot(store) if with_history else None
        if snapshot is not None:
            assert snapshot.checks == () and snapshot.history[0].stale
            assert snapshot.unavailable_reason == "statement_review_requires_one_bound_section"
    before = path.read_bytes()
    V2ProfileStore.snapshot_to(path, backup)
    assert path.read_bytes() == before
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert len(store.source_ids()) == 2
        history = store.reconciliation_history()
        assert len(history) == int(with_history)
        if with_history:
            assert history[0].stale and history[0].check == saved.check


def test_composite_reconciliation_read_is_coherent_during_a_concurrent_review(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "composite.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        _review_and_post(store, evidence)
        saved = _save(store, evidence.source_sha256)
        original = store._statement_reconciliation_checks

        def mutate_after_live_read():
            checks = original()
            with V2ProfileStore.open(path) as other:
                other.record_statement_source_review(
                    "cash",
                    evidence.source_sha256,
                    expected_revision_id=other.statement_source_reviews("cash")[0].revision_id,
                    opening_origin="reported",
                    closing_origin="reported",
                    timing_confirmed=True,
                    posting_dates="reported",
                    source_reference="Concurrent changed review",
                )
            return checks

        def refuse_standalone(*_args):
            raise AssertionError("Composite read must use private queries in one snapshot")

        monkeypatch.setattr(store, "_statement_reconciliation_checks", mutate_after_live_read)
        monkeypatch.setattr(store, "statement_reconciliation_checks", refuse_standalone)
        monkeypatch.setattr(store, "reconciliation_history", refuse_standalone)
        snapshot = store.reconciliation_snapshot()
        assert snapshot.checks[0].reconciled and snapshot.history == (saved,)
        assert snapshot.checks[0].input_version == snapshot.history[0].input_version
        monkeypatch.setattr(store, "_statement_reconciliation_checks", original)
        changed = store.reconciliation_snapshot()
        assert not changed.checks[0].reconciled and changed.history[0].stale
        assert changed.history[0].check == saved.check
        assert not store.connection.in_transaction


@pytest.mark.parametrize("stale", [False, True])
@pytest.mark.parametrize("corruption", ["closing", "manifest", "warning", "name"])
def test_current_and_stale_snapshot_corruption_refuses_history_and_backup(
    tmp_path: Path,
    stale: bool,
    corruption: str,
) -> None:
    path = tmp_path / "damaged.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        _save(store, evidence.source_sha256)
        if stale:
            store.rename_category_account("expense:other", "Changed after reconciliation")
    with sqlite3.connect(path) as connection:
        payload, versions = connection.execute(
            "SELECT check_payload,journal_versions FROM ReconciliationDecisions"
        ).fetchone()
        data = json.loads(payload)
        if corruption == "closing":
            data["printed_closing_minor"] = 123456789
        elif corruption == "manifest":
            versions = "[]"
        elif corruption == "warning":
            data["coverage_warnings"].append("unknown_future_reason")
        else:
            data["account_name"] = "Corrupted saved account label"
        payload = json.dumps(data)
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_ReconciliationDecisions_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_ReconciliationDecisions_update")
        connection.execute("UPDATE ReconciliationDecisions SET check_payload=?,journal_versions=?", (payload, versions))
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            store.reconciliation_history()
    backup = tmp_path / "refused.db"
    with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
        V2ProfileStore.snapshot_to(path, backup)
    assert not backup.exists() and not tuple(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("corruption", ["closing", "manifest", "warning", "name"])
def test_recomputed_digest_does_not_bypass_success_semantics_or_current_exact_comparison(
    tmp_path: Path,
    corruption: str,
) -> None:
    from parsetrail.core.v2_profile_store import _reconciliation_snapshot_digest

    path = tmp_path / "inconsistent.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        _save(store, evidence.source_sha256)
    with sqlite3.connect(path) as connection:
        payload, versions = connection.execute(
            "SELECT check_payload,journal_versions FROM ReconciliationDecisions"
        ).fetchone()
        data = json.loads(payload)
        if corruption == "closing":
            data["printed_closing_minor"] = 123456789
        elif corruption == "manifest":
            versions = "[]"
        elif corruption == "warning":
            data["coverage_warnings"].append("unknown_future_reason")
        else:
            data["account_name"] = "Wrong saved name with valid financial values"
        payload = json.dumps(data)
        digest = _reconciliation_snapshot_digest(payload, versions)
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_ReconciliationDecisions_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_ReconciliationDecisions_update")
        connection.execute(
            "UPDATE ReconciliationDecisions SET check_payload=?,journal_versions=?,snapshot_sha256=?",
            (payload, versions, digest),
        )
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            store.reconciliation_history()
