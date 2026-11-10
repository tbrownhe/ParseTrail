"""Managed identity, honest unknowns and exact accounting remain separate."""

from __future__ import annotations

import json
import sqlite3
from datetime import date

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_source_account
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import CatalogError, key_id_for_public_key, verify_catalog
from parsetrail.core.v2_institutions import (
    BUILTIN_INSTITUTIONS,
    Institution,
    catalog_institutions,
    institution_label,
    merge_institutions,
)
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import SCHEMA_VERSION, FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from scripts.v2_catalog_release import signed_catalog_bytes

from .test_v2_profile_store import CSV, CSV_DEFINITION


def signed_institutions(tmp_path, *keys):
    declarations = tmp_path / "declarations"
    declarations.mkdir()
    contexts = {}
    for index, key in enumerate(keys):
        declaration = json.loads(CSV_DEFINITION)
        declaration["parser_id"] = f"synthetic_registry_{index}"
        (declarations / f"{index}-definition.json").write_text(json.dumps(declaration))
        contexts[declaration["parser_id"]] = {"institution_key": key, "kind": "asset"}
    (declarations / "account-contexts.json").write_text(json.dumps(contexts))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(declarations, private, release_sequence=1, source_revision="a" * 40)
    return verify_catalog(snapshot, signature, {key_id_for_public_key(public): public}, admit_pilot_definition)


def test_registry_is_independent_of_format_catalog_and_has_no_unknown_sentinel(tmp_path):
    path = tmp_path / "fresh.db"
    with V2ProfileStore.create(path) as store:
        assert set(store.institutions()) == set(BUILTIN_INSTITUTIONS)
        assert institution_label("capital_one") == "Capital One"
        assert institution_label(None) == "Institution not identified"
        assert store.source_ids() == ()
        assert "unknown" not in {item.id for item in store.institutions()}
        assert store.connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert store.connection.execute("PRAGMA foreign_key_list(Accounts)").fetchone()[2:5] == (
            "Institutions",
            "institution_key",
            "id",
        )
        with pytest.raises(ProfileFormatError, match="institution_not_registered"):
            store.add_financial_account(FinancialAccount("account", "Account", "asset", "typed_bank"))
        assert store.financial_accounts() == ()
        institution = Institution("local_bank", "Deliberately managed local bank")
        store.register_institution(institution)
        store.register_institution(institution)  # Exact registration retry is idempotent.
        store.add_financial_account(FinancialAccount("account", "Account", "asset", institution.id))
        with pytest.raises(ProfileFormatError, match="institution_identity_conflict"):
            store.register_institution(Institution(institution.id, "Conflicting name"))
        with pytest.raises(ProfileFormatError, match="institution_identity_conflict"):
            store.register_institution(Institution("citi", "Counterfeit label"))
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute("UPDATE Institutions SET name='Renamed' WHERE id='local_bank'")
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert institution in store.institutions()
        with pytest.raises(ProfileFormatError, match="profile_read_only"):
            store.register_institution(Institution("other_bank", "Other bank"))
    assert path.read_bytes() == before


def test_unknown_institution_manual_review_survives_backup_and_correction(tmp_path):
    profile, backup = tmp_path / "fresh.db", tmp_path / "backup.db"
    evidence = build_source_evidence(CSV, CSV_DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(CSV, CSV_DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "My checking", "asset", None, "123456789"))
        store.add_category_account("expense:food", "Food", "expense")
        store.add_category_account("expense:dining", "Dining", "expense")
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        row = evidence.payload.rows[0]
        original = store.post_reviewed_cash_category(row.row_id, "expense:food", reason="Reviewed synthetic coffee")
        replacement = store.correct_reviewed_cash_category(original, "expense:dining", reason="Corrected category")
        assert replacement != original
        assert store.financial_accounts()[0].institution_key is None
        summary = store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1))
        assert summary.total_minor == 400
        assert store.load_import(evidence.source_sha256).evidence == evidence
    V2ProfileStore.snapshot_to(profile, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.financial_accounts()[0].institution_key is None
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (3,)
        assert store.connection.execute("SELECT count(*) FROM JournalCorrections").fetchone() == (1,)
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )


@pytest.mark.parametrize("source_institution", [None, "citi"])
@pytest.mark.parametrize("form,identity", [("full", "999991234"), ("last_four", "1234")])
def test_unknown_accounts_never_become_automatic_candidates(source_institution, form, identity):
    match = match_source_account(
        identity,
        form,
        institution_key=source_institution,
        kind="liability",
        candidates=(
            LedgerAccountCandidate("unknown-one", None, "liability", "999991234"),
            LedgerAccountCandidate("unknown-two", None, "liability", "999991234"),
        ),
        preferences=V2Preferences(allow_abbreviated_account_matching=True),
    )
    assert match.ledger_account_id is None and match.suggestions == ()


def test_catalog_extension_is_atomic_persistent_and_does_not_post(tmp_path):
    catalog = signed_institutions(tmp_path, "future_bank", "citi")
    profile, backup = tmp_path / "fresh.db", tmp_path / "backup.db"
    with V2ProfileStore.create(profile) as store:
        before = store.institutions()
        assert Institution("future_bank", "Future Bank") in catalog_institutions(catalog)
        assert store.institutions() == before  # Discovery is pure.
        store.connection.execute("BEGIN IMMEDIATE")
        store.register_catalog_institutions(catalog)
        store.connection.execute("ROLLBACK")
        assert store.institutions() == before
        store.register_catalog_institutions(catalog)
        store.add_financial_account(FinancialAccount("future", "Future checking", "asset", "future_bank"))
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    V2ProfileStore.snapshot_to(profile, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert Institution("future_bank", "Future Bank") in store.institutions()
        assert store.financial_accounts()[0].institution_key == "future_bank"


def test_catalog_conflict_rolls_back_every_new_identity(tmp_path):
    catalog = signed_institutions(tmp_path, "alpha_bank", "zulu_bank")
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        store.register_institution(Institution("zulu_bank", "Existing named institution"))
        before = store.institutions()
        with pytest.raises(ProfileFormatError, match="institution_identity_conflict"):
            store.register_catalog_institutions(catalog)
        assert store.institutions() == before


def test_revision_22_is_refused_without_migration_or_write(tmp_path):
    path = tmp_path / "old-pilot.db"
    with V2ProfileStore.create(path):
        pass
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=22")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("conflicting_name", ["Future Bank", "FUTURE BANK", "Future  Bank", "Future\u00a0Bank"])
def test_distinct_institution_ids_cannot_share_a_normalized_display_name(tmp_path, conflicting_name):
    first = Institution("future_bank", "Future Bank")
    other = Institution("future-bank", conflicting_name)
    assert merge_institutions((first,), (first,)) == (first,)
    with pytest.raises(ValueError, match="institution_name_conflict"):
        merge_institutions((first,), (other,))
    path = tmp_path / "profile.db"
    with V2ProfileStore.create(path) as store:
        store.register_institution(first)
        before = path.read_bytes()
        with pytest.raises(ProfileFormatError, match="institution_name_conflict"):
            store.register_institution(other)
        assert not store.connection.in_transaction
        assert path.read_bytes() == before
        assert other not in store.institutions()
        assert store.financial_accounts() == ()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_managed_name_cannot_impersonate_builtin_and_keeps_caller_transaction(tmp_path):
    with V2ProfileStore.create(tmp_path / "profile.db") as store:
        store.connection.execute("BEGIN IMMEDIATE")
        store.register_institution(Institution("future_bank", "Future Bank"))
        with pytest.raises(ProfileFormatError, match="institution_name_conflict"):
            store.register_institution(Institution("chase_bank", "CHASE"))
        assert store.connection.in_transaction
        assert Institution("future_bank", "Future Bank") in store.institutions()
        store.connection.execute("ROLLBACK")
        assert "future_bank" not in {item.id for item in store.institutions()}


def test_signed_catalog_display_collision_is_refused_before_admission(tmp_path):
    with pytest.raises(CatalogError, match="institution.*conflict"):
        signed_institutions(tmp_path, "future_bank", "future-bank")


def test_catalog_display_collision_with_profile_rolls_back_all_registrations(tmp_path):
    catalog = signed_institutions(tmp_path, "alpha_bank", "future_bank")
    with V2ProfileStore.create(tmp_path / "profile.db") as store:
        store.register_institution(Institution("existing_future", "FUTURE BANK"))
        before = store.institutions()
        with pytest.raises(ProfileFormatError, match="institution_name_conflict"):
            store.register_catalog_institutions(catalog)
        assert store.institutions() == before
        assert not store.connection.in_transaction
        assert store.financial_accounts() == ()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_appended_ambiguous_display_name_is_refused_on_reopen_without_write(tmp_path):
    profile = tmp_path / "profile.db"
    with V2ProfileStore.create(profile) as store:
        store.register_institution(Institution("future_bank", "Future Bank"))
    with sqlite3.connect(profile) as connection:
        connection.execute("INSERT INTO Institutions(id,name) VALUES ('other_future','Future  Bank')")
    before = profile.read_bytes()
    with pytest.raises(ProfileFormatError, match="institution_registry_integrity"):
        V2ProfileStore.open(profile)
    assert profile.read_bytes() == before


def test_catalog_account_creation_is_one_atomic_write(tmp_path):
    catalog = signed_institutions(tmp_path, "future_bank")
    with V2ProfileStore.create(tmp_path / "profile.db") as store:
        original = FinancialAccount("cash", "Original cash", "asset", None)
        store.add_financial_account(original)
        registry = store.institutions()
        duplicate = FinancialAccount("cash", "Conflicting account", "asset", "future_bank")
        with pytest.raises(sqlite3.IntegrityError):
            store.add_financial_account(duplicate, catalog=catalog)
        assert store.institutions() == registry
        assert store.financial_accounts() == (original,)
        assert not store.connection.in_transaction
        account = FinancialAccount("future", "Future account", "asset", "future_bank")
        store.connection.execute("BEGIN IMMEDIATE")
        store.add_financial_account(account, catalog=catalog)
        assert store.connection.in_transaction
        assert account in store.financial_accounts()
        assert Institution("future_bank", "Future Bank") in store.institutions()
        store.connection.execute("ROLLBACK")
        assert store.financial_accounts() == (original,) and store.institutions() == registry
        store.add_financial_account(account, catalog=catalog)
        assert account in store.financial_accounts()
        assert Institution("future_bank", "Future Bank") in store.institutions()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_catalog_account_update_rolls_back_registry_on_existing_guard_failure(tmp_path):
    catalog = signed_institutions(tmp_path, "future_bank")
    with V2ProfileStore.create(tmp_path / "profile.db") as store:
        original = FinancialAccount("cash", "Original cash", "asset", None)
        store.add_financial_account(original)
        registry = store.institutions()
        invalid_update = FinancialAccount("cash", "Wrong kind", "liability", "future_bank")
        with pytest.raises(ProfileFormatError, match="financial_account_kind_immutable"):
            store.update_financial_account(invalid_update, catalog=catalog)
        assert store.institutions() == registry and store.financial_accounts() == (original,)
        assert not store.connection.in_transaction
        updated = FinancialAccount("cash", "Identified cash", "asset", "future_bank")
        store.update_financial_account(updated, catalog=catalog)
        assert store.financial_accounts() == (updated,)
        assert Institution("future_bank", "Future Bank") in store.institutions()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
