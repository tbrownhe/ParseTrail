"""Finite HSA cash admission and missing-receipt settlement service boundaries."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_cash_source_policy import admitted_statement_scope
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
    _decode_reconciliation_check,
    _reconciliation_payload,
)
from parsetrail.core.v2_settlements import ExpectedOwnedDestination, SettlementFee
from parsetrail.core.v2_source_pipeline import build_source_evidence

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page
from devtools.parser_engine_pilot.test_hsa_cash_lines import pages

from .test_v2_settlements import profile as settlement_profile

PREFS = V2Preferences()
EXPECTED = ExpectedOwnedDestination("savings", "Reviewed ownership; receipt not yet available", True)


@pytest.fixture(scope="module")
def hsa_source():
    case = next(c for c in family_sources() if c.definition_name == "hsa-cash-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    return case.source, definition, build_source_evidence(case.source, definition, suffix=case.suffix)


def hsa_profile(path, source, *, kind="asset", scope="cash_component", opening=None):
    content, definition, evidence = source
    if opening is not None:
        assert opening == 0
        text = pages()
        text[0] = (
            text[0]
            .replace("BeginningBalance $1,000.00", "BeginningBalance $0.00")
            .replace("200.00 1,200.00", "200.00 200.00")
        )
        text[1] = text[1].replace("(100.00) 1,100.00", "(100.00) 100.00").replace("1,100.10", "100.10")
        content = pdf_document(tuple(text_page(*page.splitlines()) for page in text))
        evidence = build_source_evidence(content, definition, suffix=".pdf")
    with V2ProfileStore.create(path) as store:
        store.import_source(content, definition, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("hsa", "HSA cash", kind, "synthetic", tracking_scope=scope))
        store.add_financial_account(FinancialAccount("investment", "Investment", "asset", "synthetic"))
        store.add_category_account("expense:first", "Expense", "expense")
        store.add_category_account("expense:other", "Other expense", "expense")
        store.add_category_account("income:first", "Income", "income")
        store.add_category_account("income:other", "Other income", "income")
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "hsa")
    return evidence


def source_review(store, evidence, *, expected=None, reference="Exact printed cash-component endpoints"):
    return store.record_statement_source_review(
        "hsa",
        evidence.source_sha256,
        expected_revision_id=expected,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference=reference,
    )


def post_missing(store, outgoing, *, destination=EXPECTED, fees=(), basis=None, reason="Reviewed owned outflow"):
    basis = basis or store.settlement_review_snapshot(preferences=PREFS).basis_sha256
    return store.post_reviewed_settlement(
        outgoing,
        (),
        fees=fees,
        preferences=PREFS,
        expected_basis_sha256=basis,
        expected_destination=destination,
        reason=reason,
    )


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("asset", "account_total"),
        ("liability", "account_total"),
        ("liability", "cash_component"),
        ("liability", "principal_component"),
    ],
)
def test_hsa_wrong_kind_or_scope_never_admits_cash_or_source_opening(tmp_path, hsa_source, kind, scope):
    evidence = hsa_profile(tmp_path / "wrong.db", hsa_source, kind=kind, scope=scope)
    with V2ProfileStore.open(tmp_path / "wrong.db") as store:
        assert all(not row.allowed_purposes for row in store.cash_activity_review_rows(evidence.source_sha256))
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_cash_category(
                evidence.payload.accounts[0].rows[0].row_id,
                "income:first",
                purpose="income",
                reason="Refuse wrong scope",
            )
        assert next(c for c in store.earliest_source_openings() if c.account_id == "hsa").blockers
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("hsa")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_hsa_scope_policy_is_exact_and_preserves_existing_account_total_families():
    for source in ("account_total", "cash_component", "principal_component"):
        for tracking in ("account_total", "cash_component", "principal_component"):
            for kind in ("asset", "liability"):
                assert admitted_statement_scope("hsa_cash_line_pilot", source, kind, tracking) == (
                    kind == "asset" and source == tracking == "cash_component"
                )
    for family in ("fidelity_hsa", "fidelity_retirement", "unknown-family"):
        assert admitted_statement_scope(family, "account_total", "asset", "account_total")
        assert not admitted_statement_scope(family, "cash_component", "asset", "cash_component")


@pytest.mark.parametrize(
    "index,purpose,category",
    [
        (0, "income", "income:first"),
        (0, "expense_refund", "expense:first"),
        (1, "expense", "expense:first"),
        (1, "income_adjustment", "income:first"),
        (2, "income", "income:first"),
        (2, "expense_refund", "expense:first"),
    ],
)
def test_hsa_explicit_purpose_correction_and_withdrawal_preserve_source(tmp_path, hsa_source, index, purpose, category):
    path = tmp_path / "cash.db"
    evidence = hsa_profile(path, hsa_source)
    row = evidence.payload.accounts[0].rows[index]
    with V2ProfileStore.open(path) as store:
        key = store.post_reviewed_cash_category(row.row_id, category, purpose=purpose, reason="Explicit purpose review")
        assert (
            store.post_reviewed_cash_category(row.row_id, category, purpose=purpose, reason="Explicit purpose review")
            == key
        )
        replacement_category = category.replace("first", "other")
        corrected = store.correct_reviewed_cash_category(
            key, replacement_category, reason="Reviewed category correction"
        )
        entry = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").entries[0]
        assert entry.key == corrected and entry.posting_date.isoformat() == row.date.iso
        assert entry.postings[0].amount_minor == row.amount.minor
        if index == 2:
            assert row.description.text is None
            assert entry.description == "Reviewed HSA cash movement; source description unavailable"
        assert store._active_consumed() == {row.row_id: row.amount.minor}
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        store.withdraw_reviewed_interpretation(
            corrected, expected_basis_sha256=frame.basis_sha256, reason="Withdraw reviewed purpose"
        )
        assert store._active_consumed() == {} and store._active_journal_entries() == ()
        assert store.load_import(evidence.source_sha256).evidence == evidence
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_hsa_opening_reconciliation_scopes_staleness_and_withdrawal(tmp_path, hsa_source):
    path = tmp_path / "reconciled.db"
    evidence = hsa_profile(path, hsa_source)
    rows = evidence.payload.accounts[0].rows
    with V2ProfileStore.open(path) as store:
        assert store.opening_decision("hsa") is None
        revision = source_review(store, evidence)
        opening = store.post_reviewed_opening("hsa")
        assert opening.amount_minor == 100000 and opening.tracking_scope == "cash_component"
        for row in (rows[0], rows[2]):
            store.post_reviewed_cash_category(row.row_id, "income:first", purpose="income", reason="Reviewed receipt")
        post_missing(
            store, rows[1].row_id, destination=ExpectedOwnedDestination("investment", "Owned HSA investment", True)
        )
        check = store.statement_reconciliation_checks()[0]
        assert check.reconciled and check.exceptions == ()
        assert check.rule == "v2-statement-reconciliation-6"
        assert check.balance_scope == check.tracking_scope == "cash_component"
        assert _decode_reconciliation_check(_reconciliation_payload(check)) == check
        missing_scope = json.loads(_reconciliation_payload(check))
        missing_scope.pop("balance_scope")
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            _decode_reconciliation_check(json.dumps(missing_scope))
        with pytest.raises(ProfileFormatError, match="saved_reconciliation_integrity"):
            _decode_reconciliation_check(_reconciliation_payload(replace(check, balance_scope="account_total")))
        assert (check.journal_opening_minor, check.journal_closing_minor, check.closing_difference_minor) == (
            100000,
            110010,
            0,
        )
        store.save_reconciliation_decision(
            "hsa", evidence.source_sha256, expected_input_version=check.input_version, reason="Component-only check"
        )
        assert store.account_positions(as_of=date(2026, 9, 1)).transfer_clearing_debit_minor == 10000
        source_review(store, evidence, expected=revision, reference="Revised endpoint reference")
        assert store.opening_decision("hsa").stale
        assert store.reconciliation_history()[0].stale
        store.withdraw_reviewed_opening(
            "hsa", expected_decision_version=opening.version, reason="Withdraw cash component opening"
        )
        assert store.opening_decision("hsa").amount_minor is None
        assert store.account_positions(as_of=date(2026, 9, 1)).accounts[0].recorded_debit_minor == 10010
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


@pytest.mark.parametrize("opening", [0, None])
def test_hsa_zero_opening_is_not_unknown(tmp_path, hsa_source, opening):
    path = tmp_path / "zero.db"
    evidence = hsa_profile(path, hsa_source, opening=opening)
    with V2ProfileStore.open(path) as store:
        if opening is None:
            assert store.opening_decision("hsa") is None
        else:
            source_review(store, evidence)
            decision = store.post_reviewed_opening("hsa")
            assert decision.state == "active" and decision.amount_minor == 0 and decision.entry_key is None
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize(
    "destination",
    [
        None,
        ExpectedOwnedDestination("savings", "", True),
        ExpectedOwnedDestination("savings", "Reviewed", False),
        ExpectedOwnedDestination("checking", "Reviewed", True),
        ExpectedOwnedDestination("missing", "Reviewed", True),
        ExpectedOwnedDestination("expense:fees", "Reviewed", True),
    ],
)
def test_missing_receipt_requires_existing_distinct_owned_financial_destination(tmp_path, destination):
    path = tmp_path / "refused.db"
    _, outgoing, _ = settlement_profile(path)
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="settlement_expected_destination"):
            post_missing(store, outgoing, destination=destination)
        assert store.transfer_history() == () and store._active_consumed() == {}
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_expected_metadata_is_captured_not_fabricated_and_actual_receipt_cannot_have_expectation(tmp_path):
    path = tmp_path / "capture.db"
    _, outgoing, incoming = settlement_profile(path)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        basis = store.settlement_review_snapshot(preferences=PREFS).basis_sha256
        preview = store.preview_reviewed_settlement(
            outgoing, (), preferences=PREFS, expected_basis_sha256=basis, expected_destination=EXPECTED
        )
        assert preview.settlement.expected_destination == replace(
            EXPECTED, account_name="Savings", account_kind="asset", tracking_scope="account_total"
        )
        assert len(preview.entries) == 1 and preview.settlement.residual_minor == 10000
        assert {p.account_id: p.amount_minor for p in preview.entries[0].postings} == {
            "checking": -10000,
            "internal:transfer-clearing:USD": 10000,
        }
        with pytest.raises(ProfileFormatError, match="requires_missing_receipts"):
            store.preview_reviewed_settlement(
                outgoing, incoming, preferences=PREFS, expected_basis_sha256=basis, expected_destination=EXPECTED
            )
        with pytest.raises(ProfileFormatError, match="context_changed"):
            store.preview_reviewed_settlement(
                outgoing,
                (),
                preferences=PREFS,
                expected_basis_sha256=basis,
                expected_destination=replace(EXPECTED, account_name="Invented label"),
            )
    assert path.read_bytes() == before


@pytest.mark.parametrize("fee_minor", [0, 1000])
def test_missing_receipt_full_allocation_fee_pending_actual_replacement_retry_and_withdraw(tmp_path, fee_minor):
    path = tmp_path / "replace.db"
    evidence, outgoing, incoming = settlement_profile(
        path, receipts=(("10/03/2026", "9000" if fee_minor else "10000"),)
    )
    fees = (
        (SettlementFee(outgoing, "expense:fees", fee_minor, "Explicit sending fee", "Reviewed allocation"),)
        if fee_minor
        else ()
    )
    with V2ProfileStore.open(path) as store:
        initial_basis = store.settlement_review_snapshot(preferences=PREFS).basis_sha256
        original = post_missing(store, outgoing, fees=fees, basis=initial_basis)
        assert post_missing(store, outgoing, fees=fees, basis=initial_basis) == original
        assert store._active_consumed() == {outgoing: -10000}
        assert store.account_positions(as_of=date(2026, 10, 2)).transfer_clearing_debit_minor == 10000 - fee_minor
        assert all(p.account_id != "savings" for e in store._active_journal_entries() for p in e.postings)
        assert incoming[0] in {m.row_id for m in store.settlement_review_snapshot(preferences=PREFS).movements}
        basis = store.settlement_review_snapshot(preferences=PREFS, replacing_event_id=original).basis_sha256
        kwargs = {
            "fees": fees,
            "preferences": PREFS,
            "expected_basis_sha256": basis,
            "reason": "Later receipt reviewed",
        }
        replacement = store.replace_reviewed_settlement(original, outgoing, incoming, **kwargs)
        assert store.replace_reviewed_settlement(original, outgoing, incoming, **kwargs) == replacement
        assert store.transfer_history()[1].settlement.expected_destination is not None
        assert store.transfer_history()[0].settlement.expected_destination is None
        assert store.account_positions(as_of=date(2026, 10, 2)).transfer_clearing_debit_minor == 10000 - fee_minor
        assert store.account_positions(as_of=date(2026, 10, 3)).transfer_clearing_debit_minor == 0
        store.withdraw_reviewed_transfer(
            replacement,
            expected_basis_sha256=store.settlement_review_snapshot(preferences=PREFS).basis_sha256,
            reason="Withdraw whole replacement",
        )
        assert store._active_consumed() == {} and store._active_journal_entries() == ()
        assert store.financial_account_scope_locked("savings")
        with pytest.raises(ProfileFormatError, match="financial_account_scope_locked"):
            store.update_financial_account(
                FinancialAccount("savings", "Savings", "asset", "synthetic", tracking_scope="cash_component")
            )
        assert store.load_import(evidence.source_sha256).evidence == evidence
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert [event.status for event in store.transfer_history()] == ["cancelled", "replaced"]


@pytest.mark.parametrize("stage", ["initial", "replacement"])
def test_missing_receipt_stale_and_atomic_failure_leave_original_money_and_history(tmp_path, stage):
    path = tmp_path / "atomic.db"
    _, outgoing, incoming = settlement_profile(path)
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            post_missing(store, outgoing, basis="0" * 64)
        original = post_missing(store, outgoing) if stage == "replacement" else None
        history, consumed = store.transfer_history(), store._active_consumed()
        table = "TransferEventActions" if original else "TransferEvents"
        store.connection.execute(
            f"CREATE TEMP TRIGGER fail_hsa BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected failure"):
            if original:
                store.replace_reviewed_settlement(
                    original,
                    outgoing,
                    incoming,
                    preferences=PREFS,
                    expected_basis_sha256=store.settlement_review_snapshot(preferences=PREFS).basis_sha256,
                    reason="Atomic actual receipt",
                )
            else:
                post_missing(
                    store,
                    outgoing,
                    fees=(SettlementFee(outgoing, "builtin:loan-interest", 1000, "Explicit fee", "Reviewed fee"),),
                )
        assert store.transfer_history() == history and store._active_consumed() == consumed
        assert store.connection.execute("SELECT count(*) FROM JournalRetirements").fetchone() == (0,)
        assert store.connection.execute(
            "SELECT count(*) FROM Accounts WHERE id='builtin:loan-interest'"
        ).fetchone() == (0,)
        assert not store.connection.in_transaction


@pytest.mark.parametrize("payload", ["[]", "[" * 11000 + "0" + "]" * 11000, b"binary"])
def test_scope_edit_validates_bounded_history_and_rolls_back_malformed_payload(tmp_path, payload):
    path = tmp_path / "tampered.db"
    _, outgoing, _ = settlement_profile(path)
    with V2ProfileStore.open(path) as store:
        post_missing(store, outgoing)
        store.add_financial_account(FinancialAccount("spare", "Spare", "asset", "synthetic"))
        trigger = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_TransferEvents_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER immutable_TransferEvents_update")
        store.connection.execute("UPDATE TransferEvents SET pair_payload=?", (payload,))
        store.connection.execute(trigger)
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.update_financial_account(
                FinancialAccount("spare", "Spare", "asset", "synthetic", tracking_scope="cash_component")
            )
        assert not store.connection.in_transaction
        assert next(a for a in store.financial_accounts() if a.id == "spare").tracking_scope == "account_total"
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize("field,value", [("tracking_scope", "cash_component"), ("kind", "liability")])
def test_expected_destination_historical_scope_and_kind_tamper_refuse_reads_and_backup(tmp_path, field, value):
    path = tmp_path / "destination.db"
    _, outgoing, _ = settlement_profile(path)
    with V2ProfileStore.open(path) as store:
        event = post_missing(store, outgoing)
        store.withdraw_reviewed_transfer(
            event,
            expected_basis_sha256=store.settlement_review_snapshot(preferences=PREFS).basis_sha256,
            reason="Retain expectation only in history",
        )
        store.connection.execute(f"UPDATE Accounts SET {field}=? WHERE id='savings'", (value,))
        with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
            store.transfer_history()
    with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_schema_nineteen_is_refused_without_touching_profile(tmp_path):
    path = tmp_path / "schema19.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=19")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before
