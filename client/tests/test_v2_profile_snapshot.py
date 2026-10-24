"""2.0 profile snapshots preserve authored state and never overwrite a destination."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def test_snapshot_and_restore_as_new_profile_preserve_independent_state(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    backup = tmp_path / "backup.dbb"
    restored = tmp_path / "restored.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.create(profile) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.set_category_budget_rate("expense:food", date(2026, 10, 1), 10_000)
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.post_reviewed_cash_category(evidence.payload.rows[0].row_id, "expense:food", reason="Reviewed coffee")
    source_hash = hashlib.sha256(profile.read_bytes()).hexdigest()
    assert V2ProfileStore.snapshot_to(profile, backup) == backup.resolve()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == source_hash
    backup_hash = hashlib.sha256(backup.read_bytes()).hexdigest()
    assert V2ProfileStore.snapshot_to(backup, restored) == restored.resolve()
    with V2ProfileStore.open(restored) as store:
        assert store.load_import(evidence.source_sha256).source == SOURCE
        assert store.category_budget_targets(date(2026, 10, 1))[0].amount_minor == 10_000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 400
        )
        store.rename_category_account("expense:food", "Dining")
    with V2ProfileStore.open(profile, read_only=True) as original:
        assert original.category_accounts()[0].name == "Food"
    with V2ProfileStore.open(backup, read_only=True) as saved:
        assert saved.category_accounts()[0].name == "Food"
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == source_hash
    assert hashlib.sha256(backup.read_bytes()).hexdigest() == backup_hash


def test_snapshot_refuses_existing_or_invalid_paths_without_changes(tmp_path: Path) -> None:
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile):
        pass
    existing = tmp_path / "existing.db"
    existing.write_bytes(b"keep")
    with pytest.raises(ProfileFormatError, match="profile_destination_exists"):
        V2ProfileStore.snapshot_to(profile, existing)
    assert existing.read_bytes() == b"keep"
    with pytest.raises(ProfileFormatError, match="profile_destination_parent_missing"):
        V2ProfileStore.snapshot_to(profile, tmp_path / "missing" / "backup.db")
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute("CREATE TABLE Sentinel(value TEXT)")
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.snapshot_to(legacy, tmp_path / "refused.db")
    assert not (tmp_path / "refused.db").exists()


def test_snapshot_publish_failure_leaves_no_copy(tmp_path: Path, monkeypatch) -> None:
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile):
        pass
    destination = tmp_path / "backup.db"

    def fail_link(_source, _destination):
        raise OSError("publication failed")

    monkeypatch.setattr(os, "link", fail_link)
    with pytest.raises(OSError, match="publication failed"):
        V2ProfileStore.snapshot_to(profile, destination)
    assert not destination.exists()
    assert not tuple(tmp_path.glob("*.partial"))
