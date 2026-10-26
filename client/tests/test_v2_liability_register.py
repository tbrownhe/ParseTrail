"""Synthetic account-total Yamaha register facts are not principal components."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_liability_register import REGISTER_PARSER, register_posting_date, register_review_scopes
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_settlements import SettlementFee
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card

from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha
from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .test_v2_card_purchase_review import _chase_profile


def test_finite_register_policy_preserves_printed_dates_and_full_signed_effect():
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    assert evidence.parser_id == REGISTER_PARSER
    account = evidence.payload.accounts[0]
    assert account.balance_scope == "account_total"
    assert (account.opening.minor, account.closing.minor) == (-100000, -99000)
    assert all(register_review_scopes(evidence).values())
    assert [(r.transaction_date.iso, register_posting_date(r).iso, r.amount.minor) for r in account.rows] == [
        ("2026-02-05", "2026-02-07", -1000),
        ("2026-02-09", "2026-02-10", 2000),
    ]
    assert all(not r.components for r in account.rows)
    assert not register_review_scopes(evidence.model_copy(update={"parser_id": "pdf_capitaloneauto_202402"}))


def test_register_policy_refuses_assumed_dates_and_component_scope():
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    row = evidence.payload.accounts[0].rows[0]
    guessed = row.model_copy(update={"date": row.date.model_copy(update={"provenance": "assumed"})})
    assert register_posting_date(guessed) is None
    section = evidence.payload.accounts[0].model_copy(update={"balance_scope": "principal_component"})
    wrong = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"accounts": (section,)})})
    assert not any(register_review_scopes(wrong).values())


@pytest.fixture(scope="module")
def yamaha_source():
    case = next(c for c in family_sources() if c.definition_name == "yamaha-card-pilot-definition.json")
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / case.definition_name).read_bytes()
    return case.source, definition, build_source_evidence(case.source, definition, suffix=".pdf")


def _profile(
    path,
    source,
    *,
    kind="liability",
    scope="account_total",
    bank_date="02/09/2026",
    bank_amount=2000,
    second_bank_date=None,
):
    raw, definition, evidence = source
    bank_definition = (
        Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
    ).read_bytes()
    bank_raw = f"Date,Account,Description,Amount,ReportedBalance\n{bank_date},Checking A,Owned repayment,-${bank_amount // 100}.{bank_amount % 100:02d},Unavailable\n".encode()
    if second_bank_date:
        bank_raw += f"{second_bank_date},Checking A,Other owned repayment,-${bank_amount // 100}.{bank_amount % 100:02d},Unavailable\n".encode()
    bank = build_source_evidence(bank_raw, bank_definition, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(raw, definition, evidence, suffix=".pdf")
        store.import_source(bank_raw, bank_definition, bank, suffix=".csv")
        store.add_financial_account(
            FinancialAccount("register", "Yamaha register", kind, "synthetic", tracking_scope=scope)
        )
        store.add_financial_account(FinancialAccount("bank", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:first", "Expense", "expense")
        store.add_category_account("expense:other", "Other expense", "expense")
        store.add_category_account("income:first", "Income", "income")
        section = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, section.source_identity, section.source_identity_form, "register"
        )
        store.bind_source_account(bank.source_sha256, "Checking A", "opaque", "bank")
    return evidence, bank.payload.rows[0].row_id


def _post(store, source, row_id, category="expense:first", purpose="expense", **kwargs):
    frame = store.source_interpretation_snapshot(source, kind="register")
    return store.post_reviewed_register_category(
        row_id,
        category,
        purpose=purpose,
        reason="Explicit reviewed register purpose",
        expected_basis_sha256=frame.basis_sha256,
        **kwargs,
    )


def test_actual_yamaha_category_repayment_opening_closing_and_no_principal_invention(tmp_path, yamaha_source):
    path = tmp_path / "register.db"
    evidence, bank = _profile(path, yamaha_source)
    charge, payment = evidence.payload.accounts[0].rows
    with V2ProfileStore.open(path) as store:
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="register")
        assert frame.kind == "register"
        row = next(r for r in frame.rows if r.row_id == charge.row_id)
        assert (
            row.transaction_date,
            row.posting_date,
            row.transaction_date_provenance,
            row.posting_date_provenance,
        ) == (date(2026, 2, 5), "2026-02-07", "derived", "derived")
        assert (row.financial_account_id, row.financial_account_kind, row.tracking_scope) == (
            "register",
            "liability",
            "account_total",
        )
        assert set(row.allowed_purposes) == {"expense", "income_adjustment"}
        store.record_statement_source_review(
            "register",
            evidence.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Printed register endpoints and dates",
        )
        opening = store.post_reviewed_opening("register")
        assert opening.amount_minor == -100000 and opening.cutoff_date == date(2026, 1, 31)
        key = _post(store, evidence.source_sha256, charge.row_id)
        assert key.startswith("review:register:expense:")
        candidate = next(
            c for c in store.transfer_candidates(preferences=V2Preferences()) if c.incoming.row_id == payment.row_id
        )
        assert candidate.kind == "liability payment" and candidate.posting_allowed
        event = store.post_reviewed_transfer(
            bank, payment.row_id, preferences=V2Preferences(), reason="Reviewed owned liability repayment"
        )
        assert event
        assert store.account_positions(as_of=date(2026, 2, 9)).transfer_clearing_debit_minor == 2000
        positions = store.account_positions(as_of=date(2026, 2, 10))
        assert positions.transfer_clearing_debit_minor == 0
        assert next(a for a in positions.accounts if a.account_id == "register").position_debit_minor == -99000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 1000
        )
        check = next(c for c in store.statement_reconciliation_checks() if c.account_id == "register")
        assert check.reconciled and check.rule == "v2-statement-reconciliation-6"
        assert store.loan_history() == ()
        assert store.connection.execute(
            "SELECT count(*) FROM Accounts WHERE id='builtin:loan-interest'"
        ).fetchone() == (0,)
        assert store._active_consumed() == {bank: -2000, charge.row_id: -1000, payment.row_id: 2000}
        assert store.load_import(evidence.source_sha256).evidence == evidence
    restored = tmp_path / "restored.db"
    V2ProfileStore.snapshot_to(path, restored)
    with V2ProfileStore.open(restored, read_only=True) as store:
        assert store.register_activity_review_rows(evidence.source_sha256)[0].entry_key == key


@pytest.mark.parametrize("kind,scope", [("asset", "account_total"), ("liability", "principal_component")])
def test_register_wrong_kind_scope_and_card_api_do_not_admit_yamaha(tmp_path, yamaha_source, kind, scope):
    path = tmp_path / "wrong.db"
    evidence, _bank = _profile(path, yamaha_source, kind=kind, scope=scope)
    with V2ProfileStore.open(path) as store:
        assert all(not r.allowed_purposes for r in store.register_activity_review_rows(evidence.source_sha256))
        with pytest.raises(ProfileFormatError):
            _post(store, evidence.source_sha256, evidence.payload.accounts[0].rows[0].row_id)
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_card_purchase(
                evidence.payload.accounts[0].rows[0].row_id,
                "expense:first",
                preferences=V2Preferences(),
                reason="Wrong family",
            )
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_register_category_correction_withdrawal_fresh_repost_and_source_dates(tmp_path, yamaha_source):
    path = tmp_path / "correction.db"
    evidence, _ = _profile(path, yamaha_source)
    charge = evidence.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="register")
        first = _post(store, evidence.source_sha256, charge.row_id)
        assert (
            store.post_reviewed_register_category(
                charge.row_id,
                "expense:first",
                purpose="expense",
                reason="Explicit reviewed register purpose",
                expected_basis_sha256=frame.basis_sha256,
            )
            == first
        )
        basis = store.source_interpretation_snapshot(evidence.source_sha256, kind="register").basis_sha256
        corrected = store.correct_reviewed_register_category(
            first, "expense:other", reason="Correct reviewed expense category", expected_basis_sha256=basis
        )
        assert corrected.startswith("review:register:correction:")
        assert (
            store.correct_reviewed_register_category(
                first, "expense:other", reason="Correct reviewed expense category", expected_basis_sha256=basis
            )
            == corrected
        )
        with pytest.raises(ProfileFormatError):
            store.correct_reviewed_register_category(
                corrected, "income:first", reason="No purpose change by correction"
            )
        rows = store.register_activity_review_rows(evidence.source_sha256)
        current = next(r for r in rows if r.row_id == charge.row_id)
        assert (
            current.entry_key == corrected
            and current.effective_date == "2026-02-07"
            and current.transaction_date == date(2026, 2, 5)
        )
        basis = store.source_interpretation_snapshot(evidence.source_sha256, kind="register").basis_sha256
        receipt = store.withdraw_reviewed_interpretation(
            corrected, expected_basis_sha256=basis, reason="Withdraw current category interpretation"
        )
        assert store._active_consumed().get(charge.row_id, 0) == 0
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 0
        )
        fresh = _post(store, evidence.source_sha256, charge.row_id)
        assert fresh != first and fresh.startswith(first + ":repost:")
        assert (
            store.withdraw_reviewed_interpretation(
                corrected, expected_basis_sha256=basis, reason="Withdraw current category interpretation"
            )
            == receipt
        )
        assert store._active_consumed()[charge.row_id] == -1000
    V2ProfileStore.snapshot_to(path, tmp_path / "restore.db")


def test_register_purpose_is_required_and_positive_row_never_automatically_classified(tmp_path, yamaha_source):
    path = tmp_path / "purpose.db"
    evidence, _ = _profile(path, yamaha_source)
    payment = evidence.payload.accounts[0].rows[1]
    with V2ProfileStore.open(path) as store:
        row = next(r for r in store.register_activity_review_rows(evidence.source_sha256) if r.row_id == payment.row_id)
        assert row.purpose is None and set(row.allowed_purposes) == {"expense_refund", "income"}
        with pytest.raises(TypeError):
            store.post_reviewed_register_category(payment.row_id, "income:first", reason="Purpose not selected")
        with pytest.raises(ProfileFormatError):
            _post(store, evidence.source_sha256, payment.row_id, purpose="expense")
        key = _post(store, evidence.source_sha256, payment.row_id, purpose="expense_refund")
        assert key.startswith("review:register:expense_refund:")
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == -2000
        )


@pytest.mark.parametrize("table", ["JournalEntries", "JournalAllocations"])
def test_register_stale_and_failure_roll_back_before_any_partial_interpretation(tmp_path, yamaha_source, table):
    path = tmp_path / "atomic.db"
    evidence, _ = _profile(path, yamaha_source)
    row = evidence.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        basis = store.source_interpretation_snapshot(evidence.source_sha256, kind="register").basis_sha256
        store.add_category_account("expense:new", "New expense", "expense")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.post_reviewed_register_category(
                row.row_id, "expense:first", purpose="expense", reason="Stale selection", expected_basis_sha256=basis
            )
        store.connection.execute(
            f"CREATE TEMP TRIGGER fail_register BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected register failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected register failure"):
            _post(store, evidence.source_sha256, row.row_id)
        assert store._active_consumed() == {}
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert not store.connection.in_transaction


def test_register_common_reads_refuse_corrupted_initial_posting_and_backup(tmp_path, yamaha_source):
    path = tmp_path / "corrupt.db"
    evidence, _ = _profile(path, yamaha_source)
    with V2ProfileStore.open(path) as store:
        key = _post(store, evidence.source_sha256, evidence.payload.accounts[0].rows[0].row_id)
        payload = json.loads(
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
        )
        payload["postings"][0]["amount_minor"] = -999
        payload["postings"][1]["amount_minor"] = 999
        trigger = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        store.connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), key))
        store.connection.execute(trigger)
        with pytest.raises(ProfileFormatError):
            store.reviewed_journal_export(start=date(2026, 2, 1), end=date(2026, 3, 1))
        with pytest.raises(ProfileFormatError):
            store.account_positions(as_of=date(2026, 2, 28))
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_register_api_never_admits_an_already_posted_card_interpretation(tmp_path):
    path = tmp_path / "card.db"
    evidence = _chase_profile(path)
    with V2ProfileStore.open(path) as store:
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        row = section.rows[0]
        store.post_reviewed_card_purchase(
            row.row_id, "expense:food", preferences=V2Preferences(False, True), reason="Actual card review"
        )
        assert all(
            r.entry_key is None and not r.allowed_purposes
            for r in store.register_activity_review_rows(evidence.source_sha256)
        )
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_register_category(
                row.row_id, "expense:food", purpose="expense", reason="Wrong register family"
            )


@pytest.mark.parametrize("sending_fee", [False, True])
def test_register_receipt_fee_settlement_is_neutral_liability_payment_and_withdraws_whole(
    tmp_path, yamaha_source, sending_fee
):
    path = tmp_path / "settlement.db"
    evidence, bank = _profile(path, yamaha_source, bank_amount=2100)
    payment = evidence.payload.accounts[0].rows[1]
    with V2ProfileStore.open(path) as store:
        basis = store.settlement_review_snapshot(preferences=V2Preferences()).basis_sha256
        fee = SettlementFee(
            bank if sending_fee else payment.row_id,
            "expense:other",
            100,
            "Printed/reviewed exact fee",
            "Explicit allocation; no inferred interest",
        )
        event = store.post_reviewed_settlement(
            bank,
            (payment.row_id,),
            fees=(fee,),
            preferences=V2Preferences(),
            expected_basis_sha256=basis,
            reason="Owned repayment with explicit fee",
        )
        saved = next(e for e in store.transfer_history() if e.event_id == event)
        assert saved.settlement.kind == "liability payment"
        assert saved.settlement.residual_minor == 0
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 100
        )
        assert store._active_consumed() == {bank: -2100, payment.row_id: 2000}
        assert store.loan_history() == ()
        store.withdraw_reviewed_transfer(
            event,
            expected_basis_sha256=store.settlement_review_snapshot(preferences=V2Preferences()).basis_sha256,
            reason="Withdraw full settlement",
        )
        assert store._active_consumed() == {}
    V2ProfileStore.snapshot_to(path, tmp_path / "restore.db")


def test_register_repayment_whole_replacement_preserves_all_source_dates(tmp_path, yamaha_source):
    path = tmp_path / "transfer.db"
    evidence, bank = _profile(path, yamaha_source, second_bank_date="02/08/2026")
    payment = evidence.payload.accounts[0].rows[1]
    with V2ProfileStore.open(path) as store:
        candidates = store.transfer_candidates(preferences=V2Preferences())
        other = next(c.outgoing.row_id for c in candidates if c.outgoing.row_id != bank)
        original = store.post_reviewed_transfer(
            bank, payment.row_id, preferences=V2Preferences(), reason="Initial selected owned repayment"
        )
        basis = store.transfer_review_snapshot(preferences=V2Preferences()).basis_sha256
        replacement = store.replace_reviewed_transfer(
            original,
            other,
            payment.row_id,
            expected_basis_sha256=basis,
            preferences=V2Preferences(),
            reason="Explicit different cash source",
        )
        assert replacement != original
        assert store._active_consumed() == {other: -2000, payment.row_id: 2000}
        assert all(e.pair.kind == "liability payment" for e in store.transfer_history())
        assert store.account_positions(as_of=date(2026, 2, 8)).transfer_clearing_debit_minor == 2000
        assert store.account_positions(as_of=date(2026, 2, 10)).transfer_clearing_debit_minor == 0
        store.withdraw_reviewed_transfer(
            replacement,
            expected_basis_sha256=store.transfer_review_snapshot(preferences=V2Preferences()).basis_sha256,
            reason="Withdraw all replacement legs",
        )
        assert store._active_consumed() == {}
    V2ProfileStore.snapshot_to(path, tmp_path / "restore.db")


def test_register_posted_repeat_repair_retires_only_redundant_supported_interpretation(tmp_path, yamaha_source):
    path = tmp_path / "repeat.db"
    evidence, _ = _profile(path, yamaha_source)
    raw, definition, _ = yamaha_source
    repeated_raw = raw + b"\n% second synthetic export copy\n"
    repeated = build_source_evidence(repeated_raw, definition, suffix=".pdf")
    left = evidence.payload.accounts[0].rows[0]
    right = repeated.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        first = _post(store, evidence.source_sha256, left.row_id)
        store.import_source(repeated_raw, definition, repeated, suffix=".pdf")
        section = repeated.payload.accounts[0]
        store.bind_source_account(
            repeated.source_sha256, section.source_identity, section.source_identity_form, "register"
        )
        candidate = store.source_overlap_pair(left.row_id, right.row_id)
        store.record_source_overlap_review(
            left.row_id,
            right.row_id,
            decision="distinct",
            reason="Initially reviewed as distinct purchases",
            expected_basis_sha256=candidate.basis_sha256,
        )
        second = _post(store, repeated.source_sha256, right.row_id)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 2000
        )
        proof = store.repair_posted_repeat(
            left.row_id,
            right.row_id,
            expected_basis_sha256=store.source_overlap_pair(left.row_id, right.row_id).basis_sha256,
            reason="Compared originals; same register occurrence",
        )
        assert proof.retained_entry_key == first and proof.redundant_entry_key == second
        assert store._active_consumed().get(right.row_id, 0) == 0
        assert store._active_consumed()[left.row_id] == -1000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1)).total_minor
            == 1000
        )
        assert store.source_overlap_pair(left.row_id, right.row_id).state == "repeat"
    V2ProfileStore.snapshot_to(path, tmp_path / "repaired.db")


def test_register_correction_failure_is_atomic_and_fixed_date_has_no_override(tmp_path, yamaha_source):
    path = tmp_path / "correction-atomic.db"
    evidence, _ = _profile(path, yamaha_source)
    row = evidence.payload.accounts[0].rows[0]
    with V2ProfileStore.open(path) as store:
        key = _post(store, evidence.source_sha256, row.row_id)
        with pytest.raises(TypeError):
            store.correct_reviewed_register_category(
                key, "expense:other", reason="No date override", accounting_date=date(2026, 2, 8)
            )
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_register BEFORE INSERT ON JournalCorrections BEGIN SELECT RAISE(ABORT,'injected correction failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected correction failure"):
            store.correct_reviewed_register_category(key, "expense:other", reason="Atomic category correction")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (1,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (0,)
        assert store._active_consumed() == {row.row_id: -1000}


def test_register_original_date_tamper_refuses_common_report_and_backup(tmp_path, yamaha_source):
    path = tmp_path / "date-corrupt.db"
    evidence, _ = _profile(path, yamaha_source)
    with V2ProfileStore.open(path) as store:
        key = _post(store, evidence.source_sha256, evidence.payload.accounts[0].rows[0].row_id)
        payload = json.loads(
            store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
        )
        payload["posting_date"] = "2026-02-08"
        trigger = store.connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_JournalEntries_update'"
        ).fetchone()[0]
        store.connection.execute("DROP TRIGGER immutable_JournalEntries_update")
        store.connection.execute("UPDATE JournalEntries SET payload=? WHERE key=?", (json.dumps(payload), key))
        store.connection.execute(trigger)
        with pytest.raises(ProfileFormatError):
            store.reviewed_journal_export(start=date(2026, 2, 1), end=date(2026, 3, 1))
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")


def test_schema_twenty_one_refuses_before_any_write(tmp_path):
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=21")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before
