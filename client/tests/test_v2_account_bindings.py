"""Accountless export assignments are explicit, editable user decisions."""

from __future__ import annotations

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "parser_engine_pilot" / "mohela-account-history-definition.json"
).read_bytes()
SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,Description,Principal,Interest,Fees,Total,\n"
    b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
    b"10/02/2026,Payment,-$40.00,-$10.00,$0.00,-$50.00,\n"
)
IDENTIFIED_DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
IDENTIFIED_SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def test_file_assertion_and_mixed_row_review_survive_reopen(tmp_path: Path) -> None:
    path = tmp_path / "profile.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    first, second = (row.row_id for row in evidence.payload.rows)
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))
        store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
        store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
        with pytest.raises(ProfileFormatError, match="row_account_assignment_requires_accountless_export"):
            store.assign_rows_account(evidence.source_sha256, (first, "0" * 64), "loan-a")
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))
        store.assert_file_account(evidence.source_sha256, "loan-a")
        assert not store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        with pytest.raises(ProfileFormatError, match="row_account_assignment_conflicts_with_file_assertion"):
            store.assign_row_account(second, "loan-b")
        assert [
            (binding.row_id, binding.ledger_account_id, binding.basis)
            for binding in store.account_bindings(evidence.source_sha256)
        ] == [
            (first, "loan-a", "file"),
            (second, "loan-a", "file"),
        ]
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.account_bindings(evidence.source_sha256)[1].basis == "file"
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.connection.execute("SELECT count(*) FROM sqlite_master WHERE name='LedgerEntries'").fetchone() == (
            0,
        )
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.assert_file_account(evidence.source_sha256, "loan-b")
    with V2ProfileStore.open(path) as store:
        store.clear_file_account_assertion(evidence.source_sha256)
        store.assign_row_account(first, "loan-a")
        store.assign_row_account(second, "loan-b")
        with pytest.raises(ProfileFormatError, match="file_account_assertion_conflicts_with_row_assignments"):
            store.assert_file_account(evidence.source_sha256, "loan-a")
        assert [
            (binding.ledger_account_id, binding.basis) for binding in store.account_bindings(evidence.source_sha256)
        ] == [
            ("loan-a", "row"),
            ("loan-b", "row"),
        ]
    with V2ProfileStore.open(path) as store:
        store.clear_row_account_assignment(first)
        store.clear_row_account_assignment(second)
        assert all(binding.ledger_account_id is None for binding in store.account_bindings(evidence.source_sha256))


def test_file_assertion_refuses_identified_export_and_missing_account(tmp_path: Path) -> None:
    path = tmp_path / "profile.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        with pytest.raises(ProfileFormatError, match="financial_account_missing"):
            store.assert_file_account(evidence.source_sha256, "unknown")
        store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
        with pytest.raises(ProfileFormatError, match="observation_missing"):
            store.assign_row_account("0" * 64, "loan-a")
        identified = build_source_evidence(IDENTIFIED_SOURCE, IDENTIFIED_DEFINITION, suffix=".csv")
        store.import_source(IDENTIFIED_SOURCE, IDENTIFIED_DEFINITION, identified, suffix=".csv")
        with pytest.raises(ProfileFormatError, match="file_account_assertion_requires_accountless_export"):
            store.assert_file_account(identified.source_sha256, "loan-a")
        with pytest.raises(ProfileFormatError, match="row_account_assignment_requires_accountless_export"):
            store.assign_row_account(identified.payload.rows[0].row_id, "loan-a")
        assert store.account_bindings(identified.source_sha256)[0].ledger_account_id is None
