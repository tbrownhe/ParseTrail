"""Disposable import-to-review proof without any 1.x database dependency."""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from devtools.v2_fresh_slice.fresh_slice import (
    FreshSliceError,
    accept_expense,
    create_disposable_profile,
    review_items,
)

DEFINITION = Path(__file__).with_name("synthetic-posted-cash-definition.json")
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Unclassified credit,$10.00,Unavailable\n"
)


def create(output: Path, source: bytes = SOURCE, definition: bytes | None = None) -> Path:
    return create_disposable_profile(
        output,
        source,
        definition if definition is not None else DEFINITION.read_bytes(),
        account_id="checking:synthetic",
        account_name="Synthetic checking",
        expense_categories=(("expense:food", "Food"),),
    )


def test_new_profile_imports_without_posting_then_explicit_review_posts_once(tmp_path: Path) -> None:
    profile = create(tmp_path / "fresh-profile")
    assert profile.is_dir()
    assert (profile / "source.csv").read_bytes() == SOURCE
    rows = review_items(profile)
    assert [(row["amount_minor"], row["status"]) for row in rows] == [(-400, "pending"), (1000, "pending")]
    assert [row["source_row"] for row in rows] == [2, 3]
    assert accept_expense(profile, rows[0]["row_id"], "expense:food", reason="Synthetic expense review") == (
        "review:" + rows[0]["row_id"]
    )
    assert [row["status"] for row in review_items(profile)] == ["reviewed", "pending"]
    assert accept_expense(profile, rows[0]["row_id"], "expense:food", reason="Synthetic expense review") == (
        "review:" + rows[0]["row_id"]
    )
    from parsetrail.core.ledger_store import LedgerStore

    with LedgerStore(profile / "ledger.db", read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 1
        assert store.consumed() == {rows[0]["row_id"]: -400}


def test_refuses_ambiguous_date_role_and_multiple_accounts(tmp_path: Path) -> None:
    declaration = json.loads(DEFINITION.read_bytes())
    declaration["date_role"] = "activity_date"
    with pytest.raises(FreshSliceError, match="unsupported_source_contract"):
        create(tmp_path / "wrong-date", definition=json.dumps(declaration).encode())
    changed = SOURCE.replace(b"Checking A,Unclassified", b"Checking B,Unclassified")
    with pytest.raises(FreshSliceError, match="multiple_source_accounts"):
        create(tmp_path / "multiple", source=changed)
    assert not (tmp_path / "wrong-date").exists()
    assert not (tmp_path / "multiple").exists()


def test_rejects_tampered_source_and_nonexpense_decisions(tmp_path: Path) -> None:
    profile = create(tmp_path / "fresh-profile")
    rows = review_items(profile)
    with pytest.raises(FreshSliceError, match="expense_review_requires_negative_row_and_reason"):
        accept_expense(profile, rows[1]["row_id"], "expense:food", reason="Do not infer a refund")
    with pytest.raises(FreshSliceError, match="expense_category_required"):
        accept_expense(profile, rows[0]["row_id"], "missing", reason="Synthetic review")
    with pytest.raises(FreshSliceError, match="profile_target_exists_or_parent_missing"):
        create(profile)
    (profile / "source.csv").write_bytes(SOURCE + b"10/03/2026,Checking A,Tamper,-$1.00,$995.00\n")
    with pytest.raises(FreshSliceError, match="profile_hash_mismatch"):
        review_items(profile)


def test_saved_evidence_reopens_without_reparsing_and_rejects_unknown_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = create(tmp_path / "fresh-profile")

    def forbidden_reparse(*_args, **_kwargs):
        raise AssertionError("reparse must not run on reopen")

    monkeypatch.setattr("devtools.v2_fresh_slice.fresh_slice._evidence", forbidden_reparse)
    rows = review_items(profile)
    assert [row["status"] for row in rows] == ["pending", "pending"]
    assert accept_expense(profile, rows[0]["row_id"], "expense:food", reason="Synthetic review")

    saved = json.loads((profile / "evidence.json").read_bytes())
    saved["output_schema_version"] = 2
    changed = json.dumps(saved).encode()
    (profile / "evidence.json").write_bytes(changed)
    manifest_path = profile / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["evidence_sha256"] = sha256(changed).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FreshSliceError, match="invalid_saved_evidence"):
        review_items(profile)


def test_refuses_legacy_and_newer_profile_targets_before_writes(tmp_path: Path) -> None:
    legacy = tmp_path / "legacy.db"
    legacy.write_bytes(b"old profile marker")
    with pytest.raises(FreshSliceError, match="profile_contents"):
        review_items(legacy)
    assert legacy.read_bytes() == b"old profile marker"

    profile = create(tmp_path / "fresh-profile")
    manifest_path = profile / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["profile_version"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(FreshSliceError, match="unsupported_profile_format"):
        accept_expense(profile, "absent", "expense:food", reason="No write")
    from parsetrail.core.ledger_store import LedgerStore

    with LedgerStore(profile / "ledger.db", read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 0
