"""Synthetic printed loan components preserve raw use and financial principal separately."""

import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.ledger import AccountKind, LedgerAccount, LedgerError, Observation, validate_entry
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_loan_payments import (
    CLEARING,
    INTEREST,
    LoanPaymentManifest,
    component_entry,
    component_proof,
    decode_manifest,
    manifest_payload,
    payment_entries,
    principal_id,
    validate_component,
    validate_component_postings,
)
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
    _reconciliation_payload,
    _reconciliation_snapshot_digest,
)
from parsetrail.core.v2_settlements import ExpectedOwnedDestination, TransferMovement
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_wells_loan_lines import parse_wells_loan

from devtools.parser_engine_pilot import test_loan_history_lines as capital
from devtools.parser_engine_pilot import test_wells_loan_lines as wells
from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .test_v2_hsa_cash import hsa_profile, post_missing, source_review
from .test_v2_hsa_cash import hsa_source as hsa_source


def _proof():
    evidence = parse_loan_history(capital.DEFINITION, capital.lines())
    return component_proof(
        evidence.payload.accounts[0].rows[0],
        source_sha256=evidence.source_sha256,
        parser_id=evidence.parser_id,
        account_id="loan",
        account_name="Car principal",
    )


def _manifest(proof=None):
    proof = proof or _proof()
    return LoanPaymentManifest(
        TransferMovement(
            "a" * 64,
            "b" * 64,
            "bank",
            "Checking",
            "asset",
            "2026-01-14",
            "observed",
            True,
            -proof.gross_minor,
            "Loan payment",
        ),
        (proof,),
    )


def _accounts():
    return {
        a.id: a
        for a in (
            LedgerAccount("bank", "Checking", AccountKind.ASSET, source_account_id="bank"),
            LedgerAccount("loan", "Car", AccountKind.LIABILITY, source_account_id="loan"),
            LedgerAccount(INTEREST, "Loan interest", AccountKind.EXPENSE),
            LedgerAccount(CLEARING, "Transfer clearing", AccountKind.ASSET, purpose="clearing"),
        )
    }


def test_component_proof_principal_is_not_raw_gross_and_roundtrip_is_exact():
    proof = _proof()
    assert (proof.raw_amount_minor, proof.principal_minor, proof.interest_minor) == (-22000, 20000, 2000)
    manifest = _manifest(proof)
    assert decode_manifest(manifest_payload(manifest)) == manifest
    bank, loan = payment_entries(manifest, "event", "Reviewed printed payment")
    assert bank.posting_date == date(2026, 1, 14)
    assert loan.posting_date == date(2026, 1, 15)
    assert [(p.account_id, p.amount_minor) for p in loan.postings] == [
        ("loan", 20000),
        (INTEREST, 2000),
        (CLEARING, -22000),
    ]
    assert loan.postings[0].allocations[0].observation_id == principal_id("event", proof.row_id)
    validate_component_postings(proof, loan, _accounts())
    assert Observation(principal_id("event", proof.row_id), "loan", 20000, loan.posting_date).amount_minor == 20000


@pytest.mark.parametrize(
    "change",
    [
        {"raw_principal_minor": -19999},
        {"raw_interest_minor": None},
        {"raw_fee_minor": -1},
        {"effective_date": "2026-01-14"},
        {"tracking_scope": "account_total"},
        {"raw_amount_minor": -22000.0},
    ],
)
def test_component_proof_refuses_incomplete_changed_or_untyped_facts(change):
    with pytest.raises(ValueError):
        validate_component(replace(_proof(), **change))


def test_component_proof_refuses_unbalanced_or_wrong_expense_or_manual_bypass():
    proof = _proof()
    entry = component_entry(proof, "event", "Printed payment")
    for invalid in (
        replace(entry, origin="manual"),
        replace(entry, postings=entry.postings[:-1]),
        replace(entry, reviewed=False),
    ):
        with pytest.raises(ValueError):
            validate_component_postings(proof, invalid, _accounts())


PREFERENCES = V2Preferences(False, True)


def _profile(path, *, amount=22000, bank_day="01/14/2026", evidence=None, definition=None, raw=None):
    evidence = evidence or parse_loan_history(capital.DEFINITION, capital.lines())
    definition = definition or capital.DEFINITION
    raw = raw or b"%PDF-synthetic"
    bank_definition = (
        Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
    ).read_bytes()
    bank_raw = f"Date,Account,Description,Amount,ReportedBalance\n{bank_day},Checking A,Loan payment,-${amount // 100}.{amount % 100:02d},Unavailable\n".encode()
    bank = build_source_evidence(bank_raw, bank_definition, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(bank_raw, bank_definition, bank, suffix=".csv")
        store.import_source(
            raw, definition, evidence, suffix=".csv" if evidence.payload.kind == "activity_export" else ".pdf"
        )
        store.add_financial_account(FinancialAccount("bank", "Checking", "asset", "synthetic"))
        store.add_financial_account(
            FinancialAccount("loan", "Loan principal", "liability", "synthetic", tracking_scope="principal_component")
        )
        store.bind_source_account(bank.source_sha256, "Checking A", "opaque", "bank")
        if evidence.payload.kind == "statement":
            section = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "loan"
            )
            rows = section.rows
        else:
            rows = evidence.payload.rows
            if rows[0].source_account is None:
                store.assert_file_account(evidence.source_sha256, "loan")
            else:
                for identity in {r.source_account for r in rows}:
                    store.bind_source_account(evidence.source_sha256, identity, "opaque", "loan")
    return bank.payload.rows[0].row_id, tuple(r.row_id for r in rows)


def _post(store, bank, rows, **changes):
    kwargs = {
        "expected_basis_sha256": store.loan_review_snapshot(PREFERENCES).basis_sha256,
        "preferences": PREFERENCES,
        "reference": "Printed payment",
        "reason": "Confirmed owned payment and printed split",
    }
    kwargs.update(changes)
    return store.post_reviewed_loan_payment(bank, rows, **kwargs)


def test_capital_store_payment_exact_raw_consumption_reports_withdraw_and_backup(tmp_path):
    path = tmp_path / "loan.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        off = store.loan_review_snapshot(V2Preferences())
        assert off.components[0].blockers == ("loan_assumed_date_disabled",)
        assert not off.components[0].eligible
        with pytest.raises(ProfileFormatError):
            _post(store, bank, rows, preferences=V2Preferences())
        preview = store.loan_payment_preview(bank, rows, preferences=PREFERENCES)
        assert preview.manifest.principal_minor == 20000
        event = _post(store, bank, rows, expected_basis_sha256=preview.basis_sha256)
        assert store._active_consumed() == {bank: -22000, rows[0]: -22000}

        assert store.connection.execute("SELECT amount_minor FROM JournalDerivedAllocations").fetchall() == [(20000,)]
        assert store.connection.execute("SELECT row_id,amount_minor FROM JournalAllocations").fetchall() == [
            (bank, -22000)
        ]
        assert store._unallocated_activity_counts() == (0, 0)
        expense = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert expense.total_minor == 2000
        exported = store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert exported.loan_events == (event,)
        assert exported.loan_source_links[0].principal_minor == 20000
        assert {p.kind: p.recorded_debit_minor for p in store.account_positions(as_of=date(2026, 1, 14)).accounts} == {
            "asset": -22000,
            "liability": 0,
        }
        receipt = store.withdraw_reviewed_loan(
            event.event_id, expected_event_version=event.version, reason="Withdraw entire payment"
        )
        assert store._active_consumed() == {}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        assert (
            store.withdraw_reviewed_loan(
                event.event_id, expected_event_version=event.version, reason="Withdraw entire payment"
            )
            == receipt
        )
        fresh = _post(store, bank, rows)
        assert fresh.event_id != event.event_id
        assert (
            store.withdraw_reviewed_loan(
                event.event_id, expected_event_version=event.version, reason="Withdraw entire payment"
            )
            == receipt
        )
        assert store.loan_history()[0].status == "active"
    restored = tmp_path / "restore.db"
    V2ProfileStore.snapshot_to(path, restored)
    with V2ProfileStore.open(restored, read_only=True) as store:
        assert store._active_consumed() == {bank: -22000, rows[0]: -22000}


@pytest.mark.parametrize("interest_only", [False, True])
def test_wells_explicit_separate_components_and_interest_only_have_no_fake_principal(tmp_path, interest_only):
    evidence = parse_wells_loan(
        wells.DEFINITION,
        wells.lines({5: "", 6: "01/31/26 Ending Principal Balance $100.00*"} if interest_only else None),
    )
    path = tmp_path / "wells.db"
    bank, rows = _profile(
        path,
        amount=100 if interest_only else 2100,
        evidence=evidence,
        definition=wells.DEFINITION,
        raw=b"%PDF-synthetic-loan",
    )
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        assert event.manifest.principal_minor == (0 if interest_only else 2000)
        assert event.manifest.interest_minor == 100
        assert store.connection.execute("SELECT COUNT(*) FROM DerivedFinancialObservations").fetchone() == (
            (0,) if interest_only else (1,)
        )
        assert store._unallocated_activity_counts() == (0, 0)
        assert store.statement_journal_comparisons()[0].source_activity_change_minor == (0 if interest_only else 2000)
        check = store.statement_reconciliation_checks()[0]
        assert "source_period_start_unavailable" in check.exceptions
        assert check.balance_scope == check.tracking_scope == "principal_component"
        assert store.financial_account_scope_locked("loan")
        for entry in payment_entries(event.manifest, event.event_id, event.reason)[1:]:
            proof = next(p for p in event.manifest.components if entry.key.endswith(p.row_id))
            if not proof.principal_minor:
                with pytest.raises(LedgerError, match="needs source evidence"):
                    validate_entry(entry, store._ledger_accounts(), {}, {})
                assert validate_entry(entry, store._ledger_accounts(), {}, {}, component_proofs=(proof,)) == {}
        store.withdraw_reviewed_loan(
            event.event_id, expected_event_version=event.version, reason="Withdraw all actual dated legs"
        )
        assert store._active_consumed() == {}
        with pytest.raises(ProfileFormatError, match="scope_locked"):
            store.update_financial_account(
                FinancialAccount("loan", "Loan", "liability", "synthetic", tracking_scope="account_total")
            )
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


@pytest.mark.parametrize(
    "definition_name,selected_index",
    [
        ("mohela-account-history-definition.json", 0),
        ("mohela-pilot-definition.json", 0),
        ("mohela-pilot-definition.json", 1),
    ],
)
def test_mohela_identity_modes_zero_interest_and_unknown_balance(tmp_path, definition_name, selected_index):
    case = next(c for c in family_sources() if c.definition_name == definition_name)
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / definition_name).read_bytes()
    evidence = build_source_evidence(case.source, definition, suffix=".csv")
    path = tmp_path / "mohela.db"
    amount = -evidence.payload.rows[selected_index].amount.minor
    bank, rows = _profile(path, amount=amount, evidence=evidence, definition=definition, raw=case.source)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, (rows[selected_index],))
        interest = 2000 if selected_index == 0 else 0
        assert event.manifest.interest_minor == interest
        assert event.manifest.principal_minor == amount - interest
        assert store.connection.execute("SELECT COUNT(*) FROM Accounts WHERE id=?", (INTEREST,)).fetchone() == (
            (1,) if interest else (0,)
        )
        assert store.loan_source_links()[0].proof.raw_fee_minor == 0
        assert store.statement_coverage() == ()
        assert store._unallocated_activity_counts()[0] == len(rows) - 1


def _tamper(store, table, sql, values=()):
    trigger = store.connection.execute(
        "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
    ).fetchone()[0]
    store.connection.execute(f"DROP TRIGGER immutable_{table}_update")
    store.connection.execute(sql, values)
    store.connection.execute(trigger)


@pytest.mark.parametrize(
    "table,sql,values",
    [
        ("LoanEvents", "UPDATE LoanEvents SET request_basis=?", (b"blob",)),
        ("LoanEvents", "UPDATE LoanEvents SET manifest=?", ("[" * 2000 + "0" + "]" * 2000,)),
        ("LoanEvents", "UPDATE LoanEvents SET entry_versions='[]'", ()),
        ("LoanEvents", "UPDATE LoanEvents SET reference='changed'", ()),
        ("LoanSourceUses", "UPDATE LoanSourceUses SET amount_minor=amount_minor+1", ()),
        ("DerivedFinancialObservations", "UPDATE DerivedFinancialObservations SET amount_minor=amount_minor+1", ()),
        ("JournalDerivedAllocations", "UPDATE JournalDerivedAllocations SET amount_minor=amount_minor+1", ()),
    ],
)
def test_loan_corrupt_current_or_retired_proof_index_refuses_common_reads_and_backup(tmp_path, table, sql, values):
    path = tmp_path / "corrupt.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        if table in {"LoanSourceUses", "DerivedFinancialObservations"}:
            store.withdraw_reviewed_loan(
                event.event_id, expected_event_version=event.version, reason="Keep immutable original proof"
            )
        _tamper(store, table, sql, values)
        for read in (
            store.loan_history,
            lambda: store.loan_review_snapshot(PREFERENCES),
            lambda: store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1)),
            lambda: store.account_positions(as_of=date(2026, 1, 31)),
            store.statement_reconciliation_checks,
        ):
            with pytest.raises(ProfileFormatError, match="loan_history_integrity"):
                read()
    with pytest.raises(ProfileFormatError, match="loan_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize(
    "table",
    [
        "Accounts",
        "LoanEvents",
        "JournalEntries",
        "JournalAllocations",
        "LoanSourceUses",
        "DerivedFinancialObservations",
        "JournalDerivedAllocations",
    ],
)
def test_initial_payment_failpoints_roll_back_every_fact_and_category(tmp_path, table):
    path = tmp_path / "fail.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        basis = store.loan_review_snapshot(PREFERENCES).basis_sha256
        before = store.connection.total_changes
        store.connection.execute(
            f"CREATE TEMP TRIGGER fail_loan BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected loan failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected loan failure"):
            _post(store, bank, rows, expected_basis_sha256=basis)
        assert store._active_consumed() == {} and store.loan_history() == ()
        assert store.connection.execute(
            "SELECT COUNT(*) FROM Accounts WHERE id IN (?,?)", (INTEREST, CLEARING)
        ).fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert not store.connection.in_transaction
        assert store.loan_review_snapshot(PREFERENCES).basis_sha256 == basis
        assert store.connection.total_changes >= before


def test_rule_five_saved_hsa_cash_scope_is_retained_exactly_stale_and_restorable(tmp_path, hsa_source):
    path = tmp_path / "old-scope.db"
    evidence = hsa_profile(path, hsa_source)
    with V2ProfileStore.open(path) as store:
        source_review(store, evidence)
        store.post_reviewed_opening("hsa")
        rows = evidence.payload.accounts[0].rows
        for row in (rows[0], rows[2]):
            store.post_reviewed_cash_category(
                row.row_id, "income:first", purpose="income", reason="Observed cash receipt"
            )
        post_missing(
            store,
            rows[1].row_id,
            destination=ExpectedOwnedDestination("investment", "Owned investment cash movement", True),
        )
        live = store.statement_reconciliation_checks()[0]
        assert live.rule == "v2-statement-reconciliation-6" and live.reconciled
        previous = replace(live, rule="v2-statement-reconciliation-5", input_version="a" * 64)
        payload = _reconciliation_payload(previous)
        versions = json.dumps(
            tuple(
                (key, hashlib.sha256(content.encode()).hexdigest())
                for key, content in store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key")
            ),
            separators=(",", ":"),
        )
        store.connection.execute(
            "INSERT INTO ReconciliationDecisions(account_id,source_sha256,cutoff_date,rule,input_version,check_payload,journal_versions,snapshot_sha256,reason) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                "hsa",
                evidence.source_sha256,
                previous.period_end.isoformat(),
                previous.rule,
                previous.input_version,
                payload,
                versions,
                _reconciliation_snapshot_digest(payload, versions),
                "Prior cash-only rule check",
            ),
        )
        saved = store.reconciliation_history()[0]
        assert saved.stale and saved.check == previous
        assert saved.check.tracking_scope == saved.check.balance_scope == "cash_component"
    backup = tmp_path / "restored.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.reconciliation_history()[0] == saved
        assert store.connection.execute(
            "SELECT check_payload,journal_versions FROM ReconciliationDecisions"
        ).fetchone() == (payload, versions)


@pytest.mark.parametrize("interest_only", [False, True])
def test_withdrawn_history_keeps_original_binding_and_interest_only_scope_lock(tmp_path, interest_only):
    path = tmp_path / "binding.db"
    evidence = parse_wells_loan(
        wells.DEFINITION,
        wells.lines({5: "", 6: "01/31/26 Ending Principal Balance $100.00*"} if interest_only else None),
    )
    bank, rows = _profile(
        path,
        amount=100 if interest_only else 2100,
        evidence=evidence,
        definition=wells.DEFINITION,
        raw=b"%PDF-synthetic-loan",
    )
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        section = evidence.payload.accounts[0]
        target = BindingCorrectionTarget(
            evidence.source_sha256, "source", section.source_identity, section.source_identity_form
        )
        store.add_financial_account(
            FinancialAccount("other", "Other loan", "liability", "synthetic", tracking_scope="principal_component")
        )
        preview = store.binding_correction_snapshot(target, destination_account_id="other")
        assert "active_source_consumption" in preview.blockers
        with pytest.raises(ProfileFormatError, match="journal_history"):
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "other"
            )
        store.withdraw_reviewed_loan(
            event.event_id, expected_event_version=event.version, reason="Withdraw before explicit account correction"
        )
        preview = store.binding_correction_snapshot(target, destination_account_id="other")
        assert not preview.blockers
        store.correct_reviewed_binding(
            target,
            destination_account_id="other",
            expected_basis_sha256=preview.basis_sha256,
            reason="Explicit corrected loan identity",
        )
        assert store.loan_history()[0].manifest.components[0].account_id == "loan"
        assert all(b.ledger_account_id == "other" for b in store.account_bindings(evidence.source_sha256))
        assert store.financial_account_scope_locked("loan")
    V2ProfileStore.snapshot_to(path, tmp_path / "old-identity-backup.db")


@pytest.mark.parametrize("table", ["JournalRetirements", "LoanEventActions", "LoanEvents"])
def test_whole_replacement_and_withdrawal_failure_roll_back_all_dates(tmp_path, table):
    path = tmp_path / "replace.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        preview = store.loan_payment_preview(bank, rows, preferences=PREFERENCES, replacing_event_id=event.event_id)
        before = (
            store.loan_history(),
            store._active_consumed(),
            store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1)),
        )
        store.connection.execute(
            f"CREATE TEMP TRIGGER fail_loan BEFORE INSERT ON {table} BEGIN SELECT RAISE(ABORT,'injected replacement failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="injected replacement failure"):
            store.replace_reviewed_loan(
                event.event_id,
                bank,
                rows,
                expected_event_version=event.version,
                expected_basis_sha256=preview.basis_sha256,
                preferences=PREFERENCES,
                reference="Reviewed correction",
                reason="Replace entire loan event",
            )
        assert (
            store.loan_history(),
            store._active_consumed(),
            store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1)),
        ) == before
        assert not store.connection.in_transaction
        store.connection.execute("DROP TRIGGER fail_loan")
        replaced = store.replace_reviewed_loan(
            event.event_id,
            bank,
            rows,
            expected_event_version=event.version,
            expected_basis_sha256=preview.basis_sha256,
            preferences=PREFERENCES,
            reference="Reviewed correction",
            reason="Replace entire loan event",
        )
        assert replaced.event_id != event.event_id
        receipt = store.replace_reviewed_loan(
            event.event_id,
            bank,
            rows,
            expected_event_version=event.version,
            expected_basis_sha256=preview.basis_sha256,
            preferences=V2Preferences(),
            reference="Reviewed correction",
            reason="Replace entire loan event",
        )
        assert receipt == replaced
        store.withdraw_reviewed_loan(
            replaced.event_id,
            expected_event_version=replaced.version,
            reason="Later whole withdrawal despite preference off",
        )
        assert store._active_consumed() == {}
        assert (
            store.replace_reviewed_loan(
                event.event_id,
                bank,
                rows,
                expected_event_version=event.version,
                expected_basis_sha256=preview.basis_sha256,
                preferences=V2Preferences(),
                reference="Reviewed correction",
                reason="Replace entire loan event",
            ).status
            == "cancelled"
        )


def test_stale_snapshot_read_only_nested_and_prior_schema_refusals(tmp_path):
    path = tmp_path / "stale.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        snapshot = store.loan_review_snapshot(PREFERENCES)
        store.add_category_account("expense:extra", "Extra", "expense")
        with pytest.raises(ProfileFormatError, match="loan_changed_since_selection"):
            _post(store, bank, rows, expected_basis_sha256=snapshot.basis_sha256)
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="committed_snapshot"):
            store.loan_review_snapshot(PREFERENCES)
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            _post(store, bank, rows)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA user_version=20")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("changed_components", [False, True])
def test_overlap_same_gross_changed_components_refuse_repeat_and_cancelled_proof_can_support_repeat(
    tmp_path, changed_components
):
    path = tmp_path / "repeat.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        store.withdraw_reviewed_loan(
            event.event_id,
            expected_event_version=event.version,
            reason="Retire all financial effects before repeat review",
        )
        original = capital.lines(
            changes={4: "01/15/2026 Payment Received -$190.00 -$30.00 = -$220.00"} if changed_components else None
        )
        raw = b"%PDF-second-synthetic-loan"
        evidence = parse_loan_history(
            capital.DEFINITION,
            page_lines(raw, ["\n".join(line.raw for line in original.lines)], extraction_library="synthetic-pdf-1"),
        )
        store.import_source(raw, capital.DEFINITION, evidence, suffix=".pdf")
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "loan")
        other = section.rows[0].row_id
        candidate = store.source_overlap_pair(rows[0], other)
        old = next(r for r in (candidate.left, candidate.right) if r.row_id == rows[0])
        assert old.has_journal_history and old.repeat_support_history_validated
        if changed_components:
            with pytest.raises(ProfileFormatError, match="component_conflict"):
                store.record_source_overlap_review(
                    rows[0],
                    other,
                    decision="repeat",
                    retained_row_id=other,
                    expected_basis_sha256=candidate.basis_sha256,
                    reason="Do not discard changed breakdown",
                )
        else:
            store.record_source_overlap_review(
                rows[0],
                other,
                decision="repeat",
                retained_row_id=other,
                expected_basis_sha256=candidate.basis_sha256,
                reason="Same printed components; original event fully retired",
            )
            assert store.source_overlap_pair(rows[0], other).state == "repeat"
    V2ProfileStore.snapshot_to(path, tmp_path / "repeat-backup.db")


def test_capital_zero_principal_posts_only_printed_interest_and_missing_interest_header_stays_pending(tmp_path):
    evidence = parse_loan_history(
        capital.DEFINITION, capital.lines(changes={4: "01/15/2026 Payment Received $0.00 -$20.00 = -$20.00"})
    )
    path = tmp_path / "zero-principal.db"
    bank, rows = _profile(path, amount=2000, evidence=evidence)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        assert event.manifest.principal_minor == 0 and event.manifest.interest_minor == 2000
        assert store.connection.execute("SELECT COUNT(*) FROM DerivedFinancialObservations").fetchone() == (0,)
        assert store._active_consumed() == {bank: -2000, rows[0]: -2000}
        assert all(
            p.account_id != "loan"
            for e in payment_entries(event.manifest, event.event_id, event.reason)
            for p in e.postings
        )
    evidence = parse_loan_history(capital.DEFINITION, capital.lines(interest=False))
    path = tmp_path / "origination.db"
    bank, rows = _profile(path, amount=1000000, evidence=evidence)
    with V2ProfileStore.open(path) as store:
        assert store.loan_review_snapshot(PREFERENCES).components[0].blockers == ("loan_component_unsupported",)
        with pytest.raises(ProfileFormatError):
            _post(store, bank, rows)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


def test_nonzero_printed_fee_and_wrong_bank_total_stay_pending_without_partial_use(tmp_path):
    definition = (
        Path(__file__).parents[2] / "devtools/parser_engine_pilot/mohela-account-history-definition.json"
    ).read_bytes()
    raw = b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">Date,Description,Principal,Interest,Fees,Total,\n10/01/2026,Payment,-$79.00,-$20.00,-$1.00,-$100.00,\n'
    evidence = build_source_evidence(raw, definition, suffix=".csv")
    path = tmp_path / "fee.db"
    bank, rows = _profile(path, amount=10000, evidence=evidence, definition=definition, raw=raw)
    with V2ProfileStore.open(path) as store:
        assert store.loan_review_snapshot(PREFERENCES).components[0].blockers == ("loan_component_unsupported",)
        with pytest.raises(ProfileFormatError):
            _post(store, bank, rows)
        assert store._active_consumed() == {}
    path = tmp_path / "mismatch.db"
    bank, rows = _profile(path, amount=22001)
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="component_mismatch"):
            _post(store, bank, rows)
        assert store._active_consumed() == {}


def test_raw_bank_source_cannot_be_spent_twice_and_loan_legs_refuse_ordinary_repair(tmp_path):
    path = tmp_path / "exclusive.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        basis = store.loan_review_snapshot(PREFERENCES).basis_sha256
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_cash_category(bank, INTEREST, purpose="expense", reason="Cannot spend gross again")
        with pytest.raises(ProfileFormatError, match="source_interpretation_unsupported"):
            store.withdraw_reviewed_interpretation(
                event.entry_keys[-1], expected_basis_sha256=basis, reason="Cannot withdraw a loan leg"
            )
        with pytest.raises(ProfileFormatError):
            _post(store, bank, rows, reason="Different request cannot duplicate an active event")
        assert store.loan_history() == (event,)


def test_action_and_journal_corruption_refuse_public_history_and_backups(tmp_path):
    for target in ("action", "entry", "inverse"):
        path = tmp_path / (target + ".db")
        bank, rows = _profile(path)
        with V2ProfileStore.open(path) as store:
            event = _post(store, bank, rows)
            if target in {"action", "inverse"}:
                store.withdraw_reviewed_loan(
                    event.event_id, expected_event_version=event.version, reason="Immutable withdrawal"
                )
            if target == "action":
                _tamper(store, "LoanEventActions", "UPDATE LoanEventActions SET request_basis=?", (b"blob",))
            else:
                key = event.entry_keys[-1]
                if target == "inverse":
                    key = store.connection.execute(
                        "SELECT reversal_key FROM JournalRetirements WHERE original_key=?", (key,)
                    ).fetchone()[0]
                payload = json.loads(
                    store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
                )
                payload["postings"][0]["amount_minor"] += 1
                payload["postings"][-1]["amount_minor"] -= 1
                _tamper(
                    store,
                    "JournalEntries",
                    "UPDATE JournalEntries SET payload=? WHERE key=?",
                    (json.dumps(payload), key),
                )
            with pytest.raises(ProfileFormatError):
                store.loan_history()
        with pytest.raises(ProfileFormatError):
            V2ProfileStore.snapshot_to(path, tmp_path / (target + "-refused.db"))


def test_loan_snapshot_is_coherent_during_concurrent_wal_writer_and_save_refuses_old_basis(tmp_path, monkeypatch):
    path = tmp_path / "wal.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        old = store.loan_review_snapshot(PREFERENCES)
        original = store._loan_component_rows

        def concurrent(preferences, releasing=()):
            result = original(preferences, releasing)
            with V2ProfileStore.open(path) as other:
                other.add_financial_account(FinancialAccount("new", "New", "asset", "synthetic"))
            return result

        monkeypatch.setattr(store, "_loan_component_rows", concurrent)
        snapshot = store.loan_review_snapshot(PREFERENCES)
        assert snapshot == old
        monkeypatch.setattr(store, "_loan_component_rows", original)
        fresh = store.loan_review_snapshot(PREFERENCES)
        assert fresh.basis_sha256 != old.basis_sha256 and len(fresh.accounts) == len(old.accounts) + 1
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _post(store, bank, rows, expected_basis_sha256=old.basis_sha256)
