"""Full source allocations, explicit fees and open clearing remain recoverable."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from parsetrail.core.ledger import Allocation, JournalEntry, Posting
from parsetrail.core.source_evidence import ComponentEvidence
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
    _transfer_record_digest,
)
from parsetrail.core.v2_settlements import SettlementFee
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_transfers import BANK_DEFINITION, _profile

PREFS = V2Preferences()
START, END = date(2026, 10, 1), date(2026, 11, 1)


def profile(path, *, receipts=(("10/03/2026", "6000"),), outgoing_date="10/01/2026", component_leg=None):
    # Source amounts are exact printed cents converted to decimal source fields.
    rows = [f"{outgoing_date},Checking A,Transfer sent,-$100.00,$900.00\n"]
    rows += [
        f"{day},Savings B,Receipt {index},${int(amount) // 100}.{int(amount) % 100:02},$1000.00\n"
        for index, (day, amount) in enumerate(receipts)
    ]
    content = ("Date,Account,Description,Amount,ReportedBalance\n" + "".join(rows)).encode()
    evidence = build_source_evidence(content, BANK_DEFINITION, suffix=".csv")
    if component_leg is not None:
        source_rows = list(evidence.payload.rows)
        row = source_rows[component_leg]
        source_rows[component_leg] = row.model_copy(
            update={"components": (ComponentEvidence(role="principal", amount=row.amount),)}
        )
        evidence = evidence.model_copy(
            update={"payload": evidence.payload.model_copy(update={"rows": tuple(source_rows)})}
        )
    with V2ProfileStore.create(path) as store:
        store.import_source(content, BANK_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("checking", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("savings", "Savings", "asset", "synthetic"))
        store.add_category_account("expense:fees", "Fees", "expense")
        store.add_category_account("income:pay", "Pay", "income")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "checking")
        store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "savings")
    return evidence, evidence.payload.rows[0].row_id, tuple(row.row_id for row in evidence.payload.rows[1:])


def fee(row, amount, category="expense:fees"):
    return SettlementFee(
        row, category, amount, "Reviewed source fee allocation", "Explicit allocation, not inferred difference"
    )


def post(store, outgoing, incoming, *, fees=(), reason="Explicit settlement review"):
    snapshot = store.settlement_review_snapshot(preferences=PREFS)
    return store.post_reviewed_settlement(
        outgoing, incoming, fees=fees, preferences=PREFS, expected_basis_sha256=snapshot.basis_sha256, reason=reason
    )


@pytest.mark.parametrize(
    ("receipt", "out_fee", "in_fee", "sent", "gross", "residual"),
    [
        (6000, 1000, 0, 9000, 6000, 3000),
        (9000, 0, 1000, 10000, 10000, 0),
        (6000, 500, 500, 9500, 6500, 3000),
        (6000, 0, 0, 10000, 6000, 4000),
    ],
)
def test_explicit_fee_sides_and_partial_residual_use_exact_dated_full_source_legs(
    tmp_path, receipt, out_fee, in_fee, sent, gross, residual
):
    path = tmp_path / "settlement.db"
    evidence, outgoing, incoming = profile(path, receipts=(("10/03/2026", str(receipt)),))
    fees = tuple([fee(outgoing, out_fee)] if out_fee else []) + tuple([fee(incoming[0], in_fee)] if in_fee else [])
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        snapshot = store.settlement_review_snapshot(preferences=PREFS)
        preview = store.preview_reviewed_settlement(
            outgoing, incoming, fees=fees, preferences=PREFS, expected_basis_sha256=snapshot.basis_sha256
        )
        assert (
            preview.settlement.sent_principal_minor,
            preview.settlement.received_gross_minor,
            preview.settlement.residual_minor,
        ) == (sent, gross, residual)
        assert len(preview.entries) == 2 and [e.posting_date for e in preview.entries] == [
            date(2026, 10, 1),
            date(2026, 10, 3),
        ]
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert not any(a.id == "internal:transfer-clearing:USD" for a in store.financial_accounts())
    assert path.read_bytes() == before
    with V2ProfileStore.open(path) as store:
        event_id = post(store, outgoing, incoming, fees=fees)
        event = store.transfer_history()[0]
        assert event.event_id == event_id and event.pair is None and event.settlement == preview.settlement
        assert store._active_consumed() == {outgoing: -10000, incoming[0]: receipt}
        positions = store.account_positions(as_of=date(2026, 10, 2))
        assert positions.transfer_clearing_debit_minor == sent
        assert store.account_positions(as_of=date(2026, 10, 3)).transfer_clearing_debit_minor == residual
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == out_fee + in_fee
        report = store.reviewed_journal_export(start=date(2026, 10, 3), end=date(2026, 10, 4))
        assert len(report.entries) == 1 and report.settlements == (event,)
        assert store.load_import(evidence.source_sha256).evidence == evidence
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_same_day_multiple_receipts_keep_one_exact_entry_per_raw_source_leg(tmp_path):
    path = tmp_path / "same.db"
    evidence, outgoing, incoming = profile(path, receipts=(("10/01/2026", "6000"), ("10/01/2026", "3000")))
    with V2ProfileStore.open(path) as store:
        event_id = post(store, outgoing, tuple(reversed(incoming)), fees=(fee(outgoing, 1000),))
        event = store.transfer_history()[0]
        assert event_id == event.event_id and len(event.entry_keys) == 3 and event.settlement.residual_minor == 0
        assert store.account_positions(as_of=START).transfer_clearing_debit_minor == 0
        assert store._active_consumed() == {row.row_id: row.amount.minor for row in evidence.payload.rows}
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == 1000


def test_source_receipt_can_precede_outflow_without_inventing_common_date(tmp_path):
    path = tmp_path / "receipt_first.db"
    _, outgoing, incoming = profile(path, outgoing_date="10/03/2026", receipts=(("10/01/2026", "9000"),))
    with V2ProfileStore.open(path) as store:
        post(store, outgoing, incoming, fees=(fee(incoming[0], 1000),))
        assert store.account_positions(as_of=START).transfer_clearing_debit_minor == -10000
        assert store.account_positions(as_of=date(2026, 10, 3)).transfer_clearing_debit_minor == 0


@pytest.mark.parametrize(
    "bad_fee",
    [
        "over_out",
        "over_in",
        "zero",
        "negative",
        "bool",
        "wrong_class",
        "missing_reference",
        "missing_reason",
        "unknown_leg",
        "duplicate",
    ],
)
def test_fee_refusals_and_overallocation_leave_no_journal_or_internal_accounts(tmp_path, bad_fee):
    path = tmp_path / "refusal.db"
    _, outgoing, incoming = profile(path, receipts=(("10/03/2026", "9000"),))
    cases = {
        "over_out": (fee(outgoing, 1001),),
        "over_in": (fee(incoming[0], 1001),),
        "zero": (fee(outgoing, 0),),
        "negative": (fee(outgoing, -1),),
        "bool": (fee(outgoing, True),),
        "wrong_class": (fee(outgoing, 500, "income:pay"),),
        "missing_reference": (SettlementFee(outgoing, "expense:fees", 500, "", "Review"),),
        "missing_reason": (SettlementFee(outgoing, "expense:fees", 500, "Statement", ""),),
        "unknown_leg": (fee("other:row", 500),),
        "duplicate": (fee(outgoing, 100), fee(outgoing, 100)),
    }
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="settlement_"):
            post(store, outgoing, incoming, fees=cases[bad_fee])
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM Accounts WHERE role='internal'").fetchone() == (0,)


def test_full_manifest_replacement_adds_later_receipt_and_retry_preserves_all_dated_history(tmp_path):
    path = tmp_path / "replace.db"
    _, outgoing, incoming = profile(path, receipts=(("10/03/2026", "6000"), ("10/08/2026", "3000")))
    with V2ProfileStore.open(path) as store:
        original = post(store, outgoing, (incoming[0],), fees=(fee(outgoing, 1000),))
        snapshot = store.settlement_review_snapshot(preferences=PREFS, replacing_event_id=original)
        replacement = store.replace_reviewed_settlement(
            original,
            outgoing,
            incoming,
            fees=(fee(outgoing, 1000),),
            preferences=PREFS,
            expected_basis_sha256=snapshot.basis_sha256,
            reason="Add evidenced later receipt",
        )
        assert (
            store.replace_reviewed_settlement(
                original,
                outgoing,
                tuple(reversed(incoming)),
                fees=(fee(outgoing, 1000),),
                preferences=PREFS,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Add evidenced later receipt",
            )
            == replacement
        )
        events = store.transfer_history()
        assert [(e.status, e.settlement.residual_minor) for e in events] == [("active", 0), ("replaced", 3000)]
        assert store.account_positions(as_of=date(2026, 10, 2)).transfer_clearing_debit_minor == 9000
        assert store.account_positions(as_of=date(2026, 10, 4)).transfer_clearing_debit_minor == 3000
        assert store.account_positions(as_of=date(2026, 10, 8)).transfer_clearing_debit_minor == 0
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == 1000
        selected = store.settlement_review_snapshot(preferences=PREFS)
        withdrawn = store.withdraw_reviewed_transfer(
            replacement, expected_basis_sha256=selected.basis_sha256, reason="Withdraw all interpreted legs"
        )
        assert withdrawn.status == "cancelled" and store._active_consumed() == {}
        assert store.reviewed_category_summary(kind="expense", start=START, end=END).total_minor == 0
        assert store.account_positions(as_of=date(2026, 10, 4)).transfer_clearing_debit_minor == 0
        assert len(store.reviewed_journal_export(start=START, end=END).settlements) == 2
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_stale_selection_and_post_failure_roll_back_builtin_clearing_and_every_source_use(tmp_path):
    path = tmp_path / "atomic.db"
    _, outgoing, incoming = profile(path)
    with V2ProfileStore.open(path) as store:
        snapshot = store.settlement_review_snapshot(preferences=PREFS)
        fees = (fee(outgoing, 1000, "builtin:loan-interest"),)
        with pytest.raises(ProfileFormatError, match="transfer_review_changed_since_selection"):
            store.post_reviewed_settlement(
                outgoing, incoming, fees=fees, preferences=PREFS, expected_basis_sha256="0" * 64, reason="Stale"
            )
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_manifest BEFORE INSERT ON TransferEvents BEGIN SELECT RAISE(ABORT,'manifest failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="manifest failure"):
            store.post_reviewed_settlement(
                outgoing,
                incoming,
                fees=fees,
                preferences=PREFS,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Explicit review",
            )
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute(
            "SELECT count(*) FROM Accounts WHERE id IN ('builtin:loan-interest','internal:transfer-clearing:USD')"
        ).fetchone() == (0,)
        store.connection.execute("DROP TRIGGER fail_manifest")
        event_id = store.post_reviewed_settlement(
            outgoing,
            incoming,
            fees=fees,
            preferences=PREFS,
            expected_basis_sha256=snapshot.basis_sha256,
            reason="Explicit review",
        )
        assert (
            store.post_reviewed_settlement(
                outgoing,
                incoming,
                fees=fees,
                preferences=PREFS,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Explicit review",
            )
            == event_id
        )


def test_replacement_failure_rolls_back_old_retirements_new_receipts_and_action(tmp_path):
    path = tmp_path / "atomic_replace.db"
    _, outgoing, incoming = profile(path, receipts=(("10/03/2026", "6000"), ("10/08/2026", "3000")))
    with V2ProfileStore.open(path) as store:
        original = post(store, outgoing, (incoming[0],), fees=(fee(outgoing, 1000),))
        selected = store.settlement_review_snapshot(preferences=PREFS, replacing_event_id=original)
        before = store.transfer_history()
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_action BEFORE INSERT ON TransferEventActions BEGIN SELECT RAISE(ABORT,'action failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="action failure"):
            store.replace_reviewed_settlement(
                original,
                outgoing,
                incoming,
                fees=(fee(outgoing, 1000),),
                preferences=PREFS,
                expected_basis_sha256=selected.basis_sha256,
                reason="Add later receipt",
            )
        assert store.transfer_history() == before
        assert store.connection.execute("SELECT count(*) FROM JournalRetirements").fetchone() == (0,)
        assert store._active_consumed() == {outgoing: -10000, incoming[0]: 6000}


@pytest.mark.parametrize("generic", [False, True])
def test_active_transfer_refuses_an_extra_pending_allocation_of_any_member(tmp_path, generic):
    path = tmp_path / "duplicated.db"
    if generic:
        _, outgoing, incoming = profile(path)
        with V2ProfileStore.open(path) as store:
            post(store, outgoing, incoming)
        financial, amount, posted_date = "checking", -10000, START
    else:
        outgoing, incoming_row = _profile(path, bank_date="01/03/2026")
        with V2ProfileStore.open(path) as store:
            store.post_reviewed_transfer(outgoing, incoming_row, preferences=PREFS, reason="Reviewed pair")
        financial, amount, posted_date = "checking", -2000, date(2026, 1, 3)
    with sqlite3.connect(path) as connection:
        extra = JournalEntry(
            "pending:duplicate",
            "pending:duplicate",
            posted_date,
            "Pending copied source",
            (
                Posting(financial, amount, (Allocation(outgoing, amount),)),
                Posting("expense:food" if not generic else "expense:fees", -amount),
            ),
            origin="manual",
            reviewed=False,
        )
        connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (extra.key, json.dumps(extra.payload()))
        )
        connection.execute("INSERT INTO JournalAllocations VALUES (?,?,?)", (extra.key, outgoing, amount))
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.transfer_history()
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.account_positions(as_of=date(2026, 10, 31))
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


@pytest.mark.parametrize("generic", [False, True])
def test_clearing_account_cannot_be_reclassified_as_expense_in_history_or_backup(tmp_path, generic):
    path = tmp_path / "clearing.db"
    if generic:
        _, outgoing, incoming = profile(path)
        with V2ProfileStore.open(path) as store:
            post(store, outgoing, incoming)
    else:
        outgoing, incoming = _profile(path, bank_date="01/03/2026")
        with V2ProfileStore.open(path) as store:
            store.post_reviewed_transfer(outgoing, incoming, preferences=PREFS, reason="Reviewed pair")
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE Accounts SET kind='expense' WHERE id='internal:transfer-clearing:USD'")
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="transfer_clearing_integrity"):
            store.transfer_history()
        with pytest.raises(ProfileFormatError, match="transfer_clearing_integrity"):
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=END)
    with pytest.raises(ProfileFormatError, match="transfer_clearing_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_tampered_manifest_refuses_reports_and_backup_without_publishing(tmp_path):
    path = tmp_path / "tampered.db"
    _, outgoing, incoming = profile(path)
    with V2ProfileStore.open(path) as store:
        event_id = post(store, outgoing, incoming, fees=(fee(outgoing, 1000),))
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_TransferEvents_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_TransferEvents_update")
        payload = json.loads(
            connection.execute("SELECT pair_payload FROM TransferEvents WHERE event_id=?", (event_id,)).fetchone()[0]
        )
        payload["fees"][0]["amount_minor"] = 2000
        connection.execute("UPDATE TransferEvents SET pair_payload=? WHERE event_id=?", (json.dumps(payload), event_id))
        connection.execute(trigger)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.reviewed_journal_export(start=START, end=END)
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert path.read_bytes() == before and not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize("leg", [0, 1])
def test_component_bearing_raw_rows_stay_outside_ordinary_settlement_admission(tmp_path, leg):
    path = tmp_path / "components.db"
    _, outgoing, incoming = profile(path, component_leg=leg)
    with V2ProfileStore.open(path) as store:
        snapshot = store.settlement_review_snapshot(preferences=PREFS)
        excluded = outgoing if leg == 0 else incoming[0]
        assert excluded not in {m.row_id for m in snapshot.movements}
        with pytest.raises(ProfileFormatError, match="settlement_movement_unavailable_or_already_posted"):
            post(store, outgoing, incoming)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_unreviewed_overlap_on_later_receipt_blocks_replacement_and_preserves_old_event(tmp_path):
    path = tmp_path / "overlap.db"
    _, outgoing, incoming = profile(path, receipts=(("10/03/2026", "6000"), ("10/08/2026", "3000")))
    content = b"Date,Account,Description,Amount,ReportedBalance\n10/08/2026,Savings B,Supporting receipt export,$30.00,$1030.00\n"
    duplicate = build_source_evidence(content, BANK_DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        original = post(store, outgoing, (incoming[0],))
        store.import_source(content, BANK_DEFINITION, duplicate, suffix=".csv")
        store.bind_source_account(duplicate.source_sha256, "Savings B", "opaque", "savings")
        snapshot = store.settlement_review_snapshot(preferences=PREFS, replacing_event_id=original)
        with pytest.raises(ProfileFormatError, match="settlement_movement_unavailable_or_already_posted"):
            store.replace_reviewed_settlement(
                original,
                outgoing,
                incoming,
                preferences=PREFS,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Cannot consume unresolved repeat",
            )
        assert store.transfer_history()[0].event_id == original and store.transfer_history()[0].status == "active"
        assert store._active_consumed() == {outgoing: -10000, incoming[0]: 6000}


def test_all_receipt_bindings_lock_until_whole_withdrawal_then_history_retains_original_accounts(tmp_path):
    path = tmp_path / "binding.db"
    evidence, outgoing, incoming = profile(path, receipts=(("10/03/2026", "6000"), ("10/08/2026", "3000")))
    with V2ProfileStore.open(path) as store:
        store.add_financial_account(FinancialAccount("other", "Other savings", "asset", "synthetic"))
        original = post(store, outgoing, incoming, fees=(fee(outgoing, 1000),))
        target = BindingCorrectionTarget(evidence.source_sha256, "source", "Savings B", "opaque")
        selected = store.binding_correction_snapshot(target, destination_account_id="other")
        assert "active_source_consumption" in selected.blockers
        with pytest.raises(ProfileFormatError, match="active_source_consumption"):
            store.correct_reviewed_binding(
                target,
                destination_account_id="other",
                expected_basis_sha256=selected.basis_sha256,
                reason="Must withdraw whole event",
            )
        store.withdraw_reviewed_transfer(
            original,
            expected_basis_sha256=store.settlement_review_snapshot(preferences=PREFS).basis_sha256,
            reason="Retire old account interpretation",
        )
        selected = store.binding_correction_snapshot(target, destination_account_id="other")
        store.correct_reviewed_binding(
            target,
            destination_account_id="other",
            expected_basis_sha256=selected.basis_sha256,
            reason="Reviewed correct destination account",
        )
        fresh = post(store, outgoing, incoming, fees=(fee(outgoing, 1000),), reason="Fresh account review")
        events = store.transfer_history()
        assert events[0].event_id == fresh and all(m.account_id == "other" for m in events[0].settlement.incoming)
        assert events[1].event_id == original and all(m.account_id == "savings" for m in events[1].settlement.incoming)
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


@pytest.mark.parametrize("case", ["duplicate", "outgoing_in_receipts", "empty", "too_many_receipts", "too_many_fees"])
def test_finite_manifest_selection_limits_refuse_before_writes(tmp_path, case):
    path = tmp_path / "bounds.db"
    _, outgoing, incoming = profile(path)
    selections = {
        "duplicate": (incoming[0], incoming[0]),
        "outgoing_in_receipts": (outgoing,),
        "empty": (),
        "too_many_receipts": tuple(f"row{i}" for i in range(33)),
        "too_many_fees": incoming,
    }
    fees = tuple(fee(outgoing, i + 1) for i in range(65)) if case == "too_many_fees" else ()
    with V2ProfileStore.open(path) as store:
        with pytest.raises(
            ProfileFormatError,
            match="settlement_expected_destination_required" if case == "empty" else "settlement_manifest_invalid",
        ):
            post(store, outgoing, selections[case], fees=fees)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_prior_pilot_schema_seventeen_is_refused_before_write(tmp_path):
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=17")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["pair_payload", "entry_versions"])
def test_deeply_nested_manifest_json_is_a_controlled_history_refusal_even_with_matching_digest(tmp_path, field):
    path = tmp_path / "nested.db"
    _, outgoing, incoming = profile(path)
    with V2ProfileStore.open(path) as store:
        event_id = post(store, outgoing, incoming)
    nested = "[" * 11000 + "0" + "]" * 11000
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_TransferEvents_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_TransferEvents_update")
        connection.execute(f"UPDATE TransferEvents SET {field}=? WHERE event_id=?", (nested, event_id))
        fields = connection.execute(
            "SELECT event_id,sequence,outgoing_row_id,incoming_row_id,pair_payload,entry_versions,reason,request_basis FROM TransferEvents WHERE event_id=?",
            (event_id,),
        ).fetchone()
        connection.execute(
            "UPDATE TransferEvents SET record_sha256=? WHERE event_id=?", (_transfer_record_digest(*fields), event_id)
        )
        connection.execute(trigger)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.transfer_history()
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize(
    "account_id", ["internal:transfer-clearing:USD", "internal:opening-equity:USD", "internal:future"]
)
def test_authored_accounts_cannot_claim_the_reserved_internal_namespace(tmp_path, account_id):
    path = tmp_path / "reserved.db"
    with V2ProfileStore.create(path) as store:
        with pytest.raises(ProfileFormatError, match="invalid_category_account"):
            store.add_category_account(account_id, "Custom category", "expense")
        with pytest.raises(ProfileFormatError, match="invalid_financial_account"):
            store.add_financial_account(FinancialAccount(account_id, "Custom cash", "asset", "synthetic"))
        assert store.connection.execute("SELECT count(*) FROM Accounts").fetchone() == (0,)
        assert store.category_accounts() == () and store.financial_accounts() == ()
