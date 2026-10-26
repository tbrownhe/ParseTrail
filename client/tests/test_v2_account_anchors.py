"""Opening facts, dated observations and closure metadata retain independent meaning."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
)

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_opening_corrections import _review
from .test_v2_reviewed_openings import _profile
from .test_v2_source_overlap import setup, source
from .test_v2_transfers import _profile as transfer_profile


def manual(
    store,
    account="cash",
    amount=1200,
    day=date(2025, 12, 31),
    reference="Reviewed independent opening",
    reason="Explicit opening fact",
):
    frame = store.account_anchor_snapshot(account)
    return store.post_reviewed_manual_opening(
        account,
        amount_minor=amount,
        cutoff_date=day,
        tracking_scope=frame.account.tracking_scope,
        reference=reference,
        reason=reason,
        expected_decision_version=frame.opening.version if frame.opening else None,
        expected_basis_sha256=frame.basis_sha256,
    )


def value(store, account="cash", amount=0, day=date(2026, 1, 31), corrects=None):
    frame = store.account_anchor_snapshot(account)
    return store.record_reviewed_dated_value(
        account,
        amount_minor=amount,
        value_date=day,
        tracking_scope=frame.account.tracking_scope,
        reference="Reviewed dated observation",
        reason="Explicit value, no settlement claim",
        expected_basis_sha256=frame.basis_sha256,
        corrects_value_id=corrects,
    )


def lifecycle(store, account="cash", state="closed", day=date(2026, 1, 31)):
    frame = store.account_anchor_snapshot(account)
    return store.record_account_lifecycle(
        account,
        state=state,
        effective_date=day,
        reason="Reviewed tracking metadata",
        expected_version=frame.lifecycle.version if frame.lifecycle else None,
        expected_basis_sha256=frame.basis_sha256,
    )


def unknown_source(store, original):
    raw = b"synthetic unknown-period source"
    old = original.payload.accounts[0]
    section = old.model_copy(update={"rows": (), "closing": old.opening})
    payload = original.payload.model_copy(
        update={
            "accounts": (section,),
            "start": original.payload.start.model_copy(
                update={"raw": None, "iso": None, "provenance": "unknown", "locations": ()}
            ),
            "independent_balance_verified": True,
        }
    )
    evidence = original.model_copy(update={"source_sha256": hashlib.sha256(raw).hexdigest(), "payload": payload})
    saved = store.load_import(original.source_sha256)
    store.import_source(raw, saved.definition, evidence, suffix=".pdf")
    store.bind_source_account(evidence.source_sha256, old.source_identity, old.source_identity_form, "cash")
    return evidence


def empty_statement(store, original, *, known_start=True):
    section = original.payload.accounts[0]
    store.clear_source_account_binding(original.source_sha256, section.source_identity, section.source_identity_form)
    raw = f"synthetic zero-activity statement {known_start}".encode()
    payload = original.payload.model_copy(
        update={
            "accounts": (section.model_copy(update={"rows": (), "closing": section.opening}),),
            "independent_balance_verified": True,
        }
    )
    if not known_start:
        payload = payload.model_copy(
            update={
                "start": payload.start.model_copy(
                    update={"iso": None, "raw": None, "provenance": "unknown", "locations": ()}
                )
            }
        )
    evidence = original.model_copy(update={"source_sha256": hashlib.sha256(raw).hexdigest(), "payload": payload})
    store.import_source(raw, store.load_import(original.source_sha256).definition, evidence, suffix=".pdf")
    store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "cash")
    return evidence


@pytest.mark.parametrize("amount", [0, 10_000])
def test_source_opening_withdrawal_unavailable_basis_preserves_unknown_zero_and_fresh_identity(tmp_path, amount):
    path = tmp_path / "withdraw.db"
    evidence = _profile(path, amount_minor=amount)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        original = store.post_reviewed_opening("cash")
        unavailable = unknown_source(store, evidence)
        assert store.opening_decision("cash").stale
        withdrawn = store.withdraw_reviewed_opening(
            "cash", expected_decision_version=original.version, reason="Printed account assignment was wrong"
        )
        assert (
            withdrawn.state == "withdrawn"
            and withdrawn.amount_minor is withdrawn.cutoff_date is withdrawn.entry_key is None
        )
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert (
            position.opening_status == "withdrawn"
            and position.position_debit_minor is None
            and position.recorded_debit_minor == 0
        )
        if original.entry_key:
            inverse = store.connection.execute(
                "SELECT e.payload FROM JournalRetirements r JOIN JournalEntries e ON e.key=r.reversal_key WHERE r.original_key=?",
                (original.entry_key,),
            ).fetchone()[0]
            assert json.loads(inverse)["posting_date"] == "2025-12-31"
        assert (
            store._binding_opening_anchors(
                BindingCorrectionTarget(
                    evidence.source_sha256,
                    "source",
                    evidence.payload.accounts[0].source_identity,
                    evidence.payload.accounts[0].source_identity_form,
                ),
                ("cash",),
            )
            == ()
        )
        selected = BindingCorrectionTarget(
            unavailable.source_sha256,
            "source",
            unavailable.payload.accounts[0].source_identity,
            unavailable.payload.accounts[0].source_identity_form,
        )
        frame = store.binding_correction_snapshot(selected, destination_account_id=None)
        store.correct_reviewed_binding(
            selected,
            destination_account_id=None,
            expected_basis_sha256=frame.basis_sha256,
            reason="Clear unavailable reviewed assignment",
        )
        source_frame = store.opening_review_snapshot("cash")
        fresh = store.correct_reviewed_opening(
            "cash",
            expected_decision_version=withdrawn.version,
            expected_basis_sha256=source_frame.basis_sha256,
            reason="Fresh printed opening review",
        )
        assert fresh.state == "active" and fresh.amount_minor == amount and fresh.version != original.version
        if amount:
            assert fresh.entry_key != original.entry_key
        assert (
            store.withdraw_reviewed_opening(
                "cash", expected_decision_version=original.version, reason="Printed account assignment was wrong"
            )
            == withdrawn
        )
        assert store.opening_decision("cash") == fresh
    V2ProfileStore.snapshot_to(path, tmp_path / "withdraw-backup.db")


@pytest.mark.parametrize(
    "kind,scope,amount",
    [("asset", "account_total", 2500), ("liability", "principal_component", -55_000), ("asset", "cash_component", 0)],
)
def test_manual_opening_explicit_kind_scope_sign_zero_and_unknown_source_do_not_fabricate_evidence(
    tmp_path, kind, scope, amount
):
    path = tmp_path / "manual.db"
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(
            FinancialAccount("cash", "Tracked account", kind, "synthetic", tracking_scope=scope)
        )
        result = manual(store, amount=amount)
        assert result.origin == "manual" and not result.stale and result.tracking_scope == scope
        assert store.earliest_source_openings()[0].blockers == ("no_bound_statement",)
        position = store.account_positions(as_of=date(2026, 1, 1)).accounts[0]
        assert position.opening_status == "valid" and position.position_debit_minor == amount
        assert position.tracking_scope == scope and position.opening_origin == "manual"
        assert store.financial_account_scope_locked("cash")
        if amount:
            entry = json.loads(store.connection.execute("SELECT payload FROM JournalEntries").fetchone()[0])
            assert entry["postings"] == [
                {"account_id": "cash", "amount_minor": amount, "allocations": []},
                {"account_id": "internal:opening-equity:USD", "amount_minor": -amount, "allocations": []},
            ]
        else:
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2025, 12, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
    V2ProfileStore.snapshot_to(path, tmp_path / "manual-backup.db")


def test_manual_withdrawn_unknown_reestablished_zero_and_historical_retry_does_not_revive(tmp_path):
    with V2ProfileStore.create(tmp_path / "manual-zero.db") as store:
        setup(store)
        original = manual(store, amount=2500)
        withdrawn = store.withdraw_reviewed_opening(
            "cash", expected_decision_version=original.version, reason="Withdraw old manual fact"
        )
        assert store.account_positions(as_of=date(2026, 1, 1)).accounts[0].opening_status == "withdrawn"
        zero = manual(store, amount=0, reference="Fresh reviewed actual zero")
        assert zero.state == "active" and zero.amount_minor == 0 and zero.entry_key is None
        assert store.account_positions(as_of=date(2026, 1, 1)).accounts[0].position_debit_minor == 0
        before = store.connection.execute("SELECT * FROM JournalEntries").fetchall()
        assert (
            store.withdraw_reviewed_opening(
                "cash", expected_decision_version=original.version, reason="Withdraw old manual fact"
            )
            == withdrawn
        )
        assert store.opening_decision("cash") == zero
        assert store.connection.execute("SELECT * FROM JournalEntries").fetchall() == before
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.withdraw_reviewed_opening(
                "cash", expected_decision_version=original.version, reason="Different request"
            )


def test_stale_versions_readonly_nested_and_snapshot_restore_boundaries(tmp_path):
    path = tmp_path / "boundaries.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        stale = store.account_anchor_snapshot("cash")
        observation = value(store, amount=500)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.post_reviewed_manual_opening(
                "cash",
                amount_minor=1000,
                cutoff_date=date(2025, 12, 31),
                tracking_scope="account_total",
                reference="Stale fact",
                reason="Stale opening",
                expected_decision_version=None,
                expected_basis_sha256=stale.basis_sha256,
            )
        frame = store.account_anchor_snapshot("cash")
        closed = lifecycle(store)
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_reviewed_dated_value(
                "cash",
                amount_minor=0,
                value_date=date(2026, 2, 1),
                tracking_scope="account_total",
                reference="Stale observation",
                reason="Stale correction",
                corrects_value_id=observation.value_id,
                expected_basis_sha256=frame.basis_sha256,
            )
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            store.account_anchor_snapshot("cash")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            lifecycle(store)
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
        for table in ("AccountDatedValues", "AccountLifecycleDecisions"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store.connection.execute(f"DELETE FROM {table}")
    backup = tmp_path / "restored.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        frame = store.account_anchor_snapshot("cash")
        assert frame.latest_dated_value == observation and frame.lifecycle == closed
        with pytest.raises(ProfileFormatError, match="read_only"):
            value(store)
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=16")
    original_bytes = path.read_bytes()
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.open(path)
    assert path.read_bytes() == original_bytes


def test_lifecycle_same_state_correction_and_event_date_order_never_changes_books(tmp_path):
    with V2ProfileStore.create(tmp_path / "lifecycle.db") as store:
        setup(store)
        first = lifecycle(store, day=date(2026, 2, 1))
        corrected = lifecycle(store, day=date(2026, 3, 1))
        assert corrected.revision_id != first.revision_id
        assert store.account_positions(as_of=date(2026, 2, 15)).accounts[0].lifecycle is None
        assert store.account_positions(as_of=date(2026, 3, 1)).accounts[0].lifecycle == corrected
        with pytest.raises(ProfileFormatError, match="account_lifecycle_date_order"):
            lifecycle(store, state="open", day=date(2026, 2, 1))
        assert len(store.account_anchor_snapshot("cash").lifecycle_history) == 2
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_lifecycle_historical_retry_is_exact_receipt_and_same_state_date_preflight_preserves_current_phase(tmp_path):
    path = tmp_path / "phase-preflight.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        frame = store.account_anchor_snapshot("cash")
        first = lifecycle(store, day=date(2026, 2, 1))
        lifecycle(store, state="open", day=date(2026, 3, 1))
        current = lifecycle(store, day=date(2026, 4, 1))
        before = store.connection.execute("SELECT * FROM AccountLifecycleDecisions").fetchall()
        receipt = store.record_account_lifecycle(
            "cash",
            state="closed",
            effective_date=date(2026, 2, 1),
            reason="Reviewed tracking metadata",
            expected_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )
        assert receipt == first and store.account_anchor_snapshot("cash").lifecycle == current
        with pytest.raises(ProfileFormatError, match="account_lifecycle_date_order"):
            lifecycle(store, day=date(2026, 2, 15))  # Same-state correction cannot precede the March open phase.
        assert store.connection.execute("SELECT * FROM AccountLifecycleDecisions").fetchall() == before
        assert not store.connection.in_transaction
        trigger = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_AccountLifecycleDecisions_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER immutable_AccountLifecycleDecisions_update")
        store.connection.execute(
            "UPDATE AccountLifecycleDecisions SET effective_date='2026-02-15' WHERE revision_id=?",
            (current.revision_id,),
        )
        store.connection.execute(trigger)
        with pytest.raises(ProfileFormatError, match="account_lifecycle_history_integrity"):
            store.account_anchor_snapshot("cash")
    with pytest.raises(ProfileFormatError, match="account_lifecycle_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_anchor_snapshot_is_coherent_with_concurrent_writer_and_old_manual_frame_refuses(tmp_path, monkeypatch):
    path = tmp_path / "snapshot.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        setup(store)
        expected = store.account_anchor_snapshot("cash")
        original = store._account_anchor_basis
        fired = False

        def concurrent_value():
            nonlocal fired
            if not fired:
                fired = True
                with V2ProfileStore.open(path) as writer:
                    value(writer, amount=1250)
            return original()

        monkeypatch.setattr(store, "_account_anchor_basis", concurrent_value)
        snapshot = store.account_anchor_snapshot("cash")
        assert fired and snapshot == expected
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.post_reviewed_manual_opening(
                "cash",
                amount_minor=1000,
                cutoff_date=date(2025, 12, 31),
                tracking_scope="account_total",
                reference="Old displayed frame",
                reason="Stale manual fact",
                expected_decision_version=None,
                expected_basis_sha256=snapshot.basis_sha256,
            )
        assert store.account_anchor_snapshot("cash").latest_dated_value.amount_minor == 1250


def test_source_manual_switch_same_money_requires_explicit_version_and_never_revives_old_entry(tmp_path):
    path = tmp_path / "switch.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        _review(store, evidence)
        original = store.post_reviewed_opening("cash")
        independent = manual(store, amount=10_000)
        assert independent.origin == "manual" and independent.entry_key != original.entry_key
        with pytest.raises(ProfileFormatError, match="opening_already_decided"):
            store.post_reviewed_opening("cash")
        frame = store.opening_review_snapshot("cash")
        fresh = store.correct_reviewed_opening(
            "cash",
            expected_decision_version=independent.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Explicitly use printed source now",
        )
        assert fresh.origin == "source" and fresh.entry_key not in {original.entry_key, independent.entry_key}
        assert store.connection.execute("SELECT count(*) FROM JournalRetirements").fetchone() == (2,)
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0].position_debit_minor == 10_000
        assert [d.origin for d in store.opening_decision_history("cash")] == ["source", "manual", "source"]


def test_manual_opening_cannot_skip_earlier_source_activity_and_new_earlier_activity_makes_unknown(tmp_path):
    with V2ProfileStore.create(tmp_path / "early.db") as store:
        setup(store)
        source(store, "Known activity", source_date="10/01/2026")
        with pytest.raises(ProfileFormatError, match="earlier_activity_conflict"):
            manual(store, day=date(2026, 10, 1))
        initial = manual(store, day=date(2026, 9, 30))
        assert not initial.stale
        source(store, "New earlier actual activity", source_date="09/29/2026", amount="-$9.00")
        assert store.opening_decision("cash").stale
        assert store.account_positions(as_of=date(2026, 10, 31)).accounts[0].position_debit_minor is None
        corrected = manual(store, day=date(2026, 9, 28))
        assert not corrected.stale and corrected.entry_key != initial.entry_key


def test_manual_opening_and_withdrawn_history_do_not_lock_source_assignments(tmp_path):
    path = tmp_path / "manual-binding.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        independent = manual(store, amount=2500)
        assert not independent.stale
        unavailable = unknown_source(store, evidence)
        assert not store.opening_decision("cash").stale
        target = BindingCorrectionTarget(
            unavailable.source_sha256,
            "source",
            unavailable.payload.accounts[0].source_identity,
            unavailable.payload.accounts[0].source_identity_form,
        )
        frame = store.binding_correction_snapshot(target, destination_account_id=None)
        assert not frame.opening_blocker_account_ids
        store.correct_reviewed_binding(
            target,
            destination_account_id=None,
            expected_basis_sha256=frame.basis_sha256,
            reason="Manual opening does not authorize this source",
        )
        assert store.opening_decision("cash").origin == "manual"


def test_zero_dated_value_and_closure_never_settle_books_and_lifecycle_is_historical_as_of(tmp_path):
    path = tmp_path / "values.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        manual(store, amount=1250)
        before = store.connection.execute("SELECT * FROM JournalEntries").fetchall()
        first = value(store, amount=0)
        corrected = value(store, amount=100, day=date(2026, 2, 1), corrects=first.value_id)
        closed = lifecycle(store, day=date(2026, 2, 2))
        assert store.account_positions(as_of=date(2026, 2, 1)).accounts[0].lifecycle is None
        position = store.account_positions(as_of=date(2026, 2, 3)).accounts[0]
        assert position.latest_dated_value == corrected and position.lifecycle == closed
        assert (
            position.position_debit_minor
            == position.recorded_debit_minor
            == position.closure_residual_debit_minor
            == 1250
        )
        assert position.closure_residual_date == date(2026, 2, 3) and not position.closure_residual_unknown
        assert store.connection.execute("SELECT * FROM JournalEntries").fetchall() == before
        reopened = lifecycle(store, state="open", day=date(2026, 3, 1))
        assert store.account_positions(as_of=date(2026, 2, 15)).accounts[0].lifecycle == closed
        assert store.account_positions(as_of=date(2026, 3, 1)).accounts[0].lifecycle == reopened
        assert store.account_positions(as_of=date(2026, 3, 1)).accounts[0].closure_residual_debit_minor is None
        history = store.account_anchor_snapshot("cash").dated_values
        assert next(v for v in history if v.value_id == first.value_id).superseded_by_value_id == corrected.value_id
    V2ProfileStore.snapshot_to(path, tmp_path / "values-backup.db")


def test_nonposting_values_do_not_establish_opening_and_closed_unknown_remains_visible(tmp_path):
    with V2ProfileStore.create(tmp_path / "unknown.db") as store:
        setup(store)
        value(store, amount=0)
        lifecycle(store)
        position = store.account_positions(as_of=date(2026, 2, 1)).accounts[0]
        assert position.opening_status == "missing" and position.position_debit_minor is None
        assert position.latest_dated_value.amount_minor == 0 and position.closure_residual_unknown
        assert position.recorded_debit_minor == position.closure_residual_debit_minor == 0
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize(
    "table", ["JournalEntries", "OpeningDecisions", "AccountDatedValues", "AccountLifecycleDecisions"]
)
def test_failed_anchor_writes_leave_no_money_or_metadata_fragments(tmp_path, table):
    with V2ProfileStore.create(tmp_path / "atomic.db") as store:
        setup(store)
        before = store._account_anchor_basis()
        store.connection.execute(
            f"CREATE TRIGGER fail_anchor BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        operation = (
            manual
            if table in {"JournalEntries", "OpeningDecisions"}
            else value
            if table == "AccountDatedValues"
            else lifecycle
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            operation(store)
        assert not store.connection.in_transaction and store._account_anchor_basis() == before
        assert store.opening_decision("cash") is None
        assert (
            store.account_anchor_snapshot("cash").dated_values
            == store.account_anchor_snapshot("cash").lifecycle_history
            == ()
        )


@pytest.mark.parametrize("table", ["JournalRetirements", "OpeningDecisionRevisions"])
def test_failed_opening_withdrawal_preserves_active_money_and_decision(tmp_path, table):
    with V2ProfileStore.create(tmp_path / "withdraw-atomic.db") as store:
        setup(store)
        original = manual(store)
        before = store.connection.execute("SELECT * FROM JournalEntries").fetchall()
        store.connection.execute(
            f"CREATE TRIGGER fail_withdraw BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            store.withdraw_reviewed_opening(
                "cash", expected_decision_version=original.version, reason="Withdraw unsupported opening"
            )
        assert store.opening_decision("cash") == original
        assert store.connection.execute("SELECT * FROM JournalEntries").fetchall() == before


@pytest.mark.parametrize(
    "table,column,bad",
    [
        ("OpeningDecisions", "origin", sqlite3.Binary(b"manual")),
        ("OpeningDecisions", "reference", "changed"),
        ("AccountDatedValues", "amount_minor", 0.5),
        ("AccountDatedValues", "request_basis", sqlite3.Binary(b"wrong")),
        ("AccountLifecycleDecisions", "state", "settled"),
        ("AccountLifecycleDecisions", "prior_version", sqlite3.Binary(b"wrong")),
    ],
)
def test_malformed_retained_anchor_history_refuses_reports_and_backup(tmp_path, table, column, bad):
    path = tmp_path / "corrupt.db"
    with V2ProfileStore.create(path) as store:
        setup(store)
        manual(store)
        value(store)
        lifecycle(store)
        sql = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
        ).fetchone()[0]
        store.connection.execute(f"DROP TRIGGER immutable_{table}_update")
        store.connection.execute(f"UPDATE {table} SET {column}=?", (bad,))
        store.connection.execute(sql)
        for read in (
            lambda: store.account_anchor_snapshot("cash"),
            lambda: store.account_positions(as_of=date(2026, 2, 1)),
            store._reconciliation_rule_and_version,
            lambda: store.reviewed_journal_export(start=date(2025, 12, 1), end=date(2026, 3, 1)),
        ):
            with pytest.raises(ProfileFormatError):
                read()
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize("review_decision", ["dismiss", "reopen"])
def test_financial_tracking_scope_cannot_reinterpret_transfer_review_without_journal(tmp_path, review_decision):
    path = tmp_path / "scope.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/05/2026")
    with V2ProfileStore.open(path) as store:
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=frame.basis_sha256,
            preferences=V2Preferences(),
            reason="Reviewed candidate dismissal",
        )
        if review_decision == "reopen":
            frame = store.transfer_review_snapshot(preferences=V2Preferences())
            store.record_transfer_pair_review(
                outgoing,
                incoming,
                decision="reopen",
                expected_basis_sha256=frame.basis_sha256,
                preferences=V2Preferences(),
                reason="Explicit reopen",
            )
        account = next(a for a in store.financial_accounts() if a.id == "checking")
        before = store.connection.execute("SELECT * FROM TransferPairReviews").fetchall()
        assert store.financial_account_scope_locked(account.id)
        with pytest.raises(ProfileFormatError, match="financial_account_scope_locked"):
            store.update_financial_account(replace(account, tracking_scope="cash_component"))
        assert store.connection.execute("SELECT * FROM TransferPairReviews").fetchall() == before
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("amount", [True, 0.5, 2**63, -(2**63)])
def test_manual_money_requires_exact_supported_integer_range(tmp_path, amount):
    with V2ProfileStore.create(tmp_path / "typed.db") as store:
        setup(store)
        with pytest.raises(ProfileFormatError, match="value_invalid"):
            manual(store, amount=amount)
        with pytest.raises(ProfileFormatError, match="value_invalid"):
            value(store, amount=amount)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_scope_is_explicit_before_history_and_does_not_admit_component_source_posting(tmp_path):
    with V2ProfileStore.create(tmp_path / "scope-change.db") as store:
        setup(store)
        account = next(a for a in store.financial_accounts() if a.id == "cash")
        assert not store.financial_account_scope_locked("cash")
        store.update_financial_account(replace(account, tracking_scope="cash_component"))
        evidence = source(store, "Gross source movement")
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_cash_category(
                evidence.payload.rows[0].row_id, "expense:food", reason="Component source not admitted"
            )
        opening = manual(store, amount=2500)
        with pytest.raises(ProfileFormatError, match="scope_locked"):
            store.update_financial_account(account)
        store.withdraw_reviewed_opening(
            "cash", expected_decision_version=opening.version, reason="Withdraw manual component opening"
        )
        assert store.financial_account_scope_locked("cash")


def test_empty_known_statement_interval_blocks_later_manual_plug_after_source_withdrawal(tmp_path):
    path = tmp_path / "empty-interval.db"
    original = _profile(path)
    with V2ProfileStore.open(path) as store:
        evidence = empty_statement(store, original)
        _review(store, evidence)
        source_opening = store.post_reviewed_opening("cash")
        store.withdraw_reviewed_opening(
            "cash", expected_decision_version=source_opening.version, reason="Withdraw untrusted source opening"
        )
        frame = store.account_anchor_snapshot("cash")
        assert frame.earliest_known_activity_date is None
        assert frame.earliest_known_history_date == date(2026, 1, 1)
        assert any(b.kind == "statement_start" and not b.allows_equal for b in frame.opening_boundaries)
        for cutoff in (date(2026, 1, 1), date(2026, 1, 31)):
            with pytest.raises(ProfileFormatError, match="earlier_activity_conflict"):
                manual(store, amount=11_000, day=cutoff, reference="Unexplained later balance")
        assert manual(store, amount=10_000, day=date(2025, 12, 31)).state == "active"


def test_unknown_start_only_establishes_endpoint_point_equal_allowed_later_refused(tmp_path):
    path = tmp_path / "unknown-interval.db"
    original = _profile(path)
    with V2ProfileStore.open(path) as store:
        empty_statement(store, original, known_start=False)
        frame = store.account_anchor_snapshot("cash")
        assert frame.earliest_known_activity_date is None and frame.earliest_known_history_date == date(2026, 1, 31)
        assert all(b.kind == "statement_end" and b.allows_equal for b in frame.opening_boundaries)
        with pytest.raises(ProfileFormatError, match="earlier_activity_conflict"):
            manual(store, day=date(2026, 2, 1))
        opening = manual(store, day=date(2026, 1, 31))
        assert not opening.stale and store.earliest_source_openings()[0].earliest_period_start is None


@pytest.mark.parametrize("point_kind", ["dated_value", "lifecycle"])
def test_nonposting_point_equal_allowed_later_refused_and_corrected_point_replaces_wrong_date(tmp_path, point_kind):
    with V2ProfileStore.create(tmp_path / "point.db") as store:
        setup(store)
        if point_kind == "dated_value":
            first = value(store, day=date(2026, 1, 31))
        else:
            first = lifecycle(store, day=date(2026, 1, 31))
        with pytest.raises(ProfileFormatError, match="earlier_activity_conflict"):
            manual(store, day=date(2026, 2, 1))
        initial = manual(store, day=date(2026, 1, 31))
        assert not initial.stale
        if point_kind == "dated_value":
            value(store, day=date(2026, 3, 1), corrects=first.value_id)
        else:
            lifecycle(store, day=date(2026, 3, 1))
        frame = store.account_anchor_snapshot("cash")
        assert frame.earliest_known_history_date == date(2026, 3, 1)
        assert manual(store, day=date(2026, 3, 1)).state == "active"


def test_new_earlier_statement_or_corrected_value_makes_existing_manual_opening_stale(tmp_path):
    path = tmp_path / "arriving-history.db"
    original = _profile(path)
    with V2ProfileStore.open(path) as store:
        section = original.payload.accounts[0]
        store.clear_source_account_binding(
            original.source_sha256, section.source_identity, section.source_identity_form
        )
        known = value(store, day=date(2026, 2, 1))
        initial = manual(store, day=date(2026, 1, 31))
        assert not initial.stale
        value(store, day=date(2026, 1, 15), corrects=known.value_id)
        assert store.opening_decision("cash").stale
        corrected = manual(store, day=date(2026, 1, 15))
        assert not corrected.stale
        empty_statement(store, original)
        assert store.opening_decision("cash").stale
        assert store.account_positions(as_of=date(2026, 2, 1)).accounts[0].position_debit_minor is None


def test_actual_card_transaction_date_is_strict_boundary_even_when_primary_date_is_only_assumed(tmp_path):
    path = tmp_path / "card-boundary.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        section = evidence.payload.accounts[0]
        actual = section.rows[0].transaction_date or section.rows[0].date
        assert section.rows[0].date.provenance == "assumed" and section.rows[0].transaction_date is not None
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        day = date.fromisoformat(actual.iso)
        frame = store.account_anchor_snapshot("card")
        assert frame.earliest_known_activity_date == day
        actual_dates = {b.boundary_date for b in frame.opening_boundaries if b.kind == "activity"}
        assert day in actual_dates and date.fromisoformat(section.rows[0].date.iso) not in actual_dates
        with pytest.raises(ProfileFormatError, match="earlier_activity_conflict"):
            manual(store, "card", amount=-1000, day=day)
        before = date.fromordinal(frame.earliest_known_history_date.toordinal() - 1)
        assert manual(store, "card", amount=-1000, day=before).state == "active"
