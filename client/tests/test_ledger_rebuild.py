import copy
import json
import sqlite3
from contextlib import closing
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity
from parsetrail.core.ledger_rebuild import match_categories, replay_sources, retain_reviewed_asset_values, write_rebuild
from parsetrail.core.ledger_store import encoded
from parsetrail.core.parser_routing import NoParserMatchError, ParseResult
from parsetrail.core.recovery_bundle import digest
from parsetrail.core.validation import Account, Statement, Transaction


@pytest.fixture
def example(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    (archive / "SUCCESS").mkdir(parents=True)
    for filename, content in [("a.pdf", b"statement one"), ("b.pdf", b"overlap")]:
        (archive / "SUCCESS" / filename).write_bytes(content)
    row = {
        "TransactionID": 1,
        "AccountID": 1,
        "TransactionDate": "2026-08-20",
        "PostingDate": "2026-08-20",
        "AmountMinor": -1234,
        "BalanceMinor": 8766,
        "CurrencyCode": "USD",
        "Description": "GROCER",
        "Verified": True,
        "CategoryID": 2,
    }
    legacy = {
        "Accounts": [{"AccountID": 1, "AccountName": "Checking", "AccountTypeID": 1, "CurrencyCode": "USD"}],
        "AccountTypes": [{"AccountTypeID": 1, "AssetType": "Asset"}],
        "AccountNumbers": [{"AccountID": 1, "AccountNumber": "123"}],
        "Categories": [
            {"CategoryID": 1, "Name": "Food", "Type": "Expense", "ParentID": None},
            {"CategoryID": 2, "Name": "Groceries", "Type": "Expense", "ParentID": 1},
        ],
        "Transactions": [row],
        "Statements": [
            {
                "StatementID": n,
                "AccountID": 1,
                "Filename": name,
                "ContentHashAlgorithm": "sha256",
                "ContentHash": digest(archive / "SUCCESS" / name),
            }
            for n, name in [(1, "a.pdf"), (2, "b.pdf")]
        ],
        "StatementTransactions": [{"StatementID": n, "TransactionID": 1, "StatementRow": 1} for n in (1, 2)],
    }
    parsed = Statement(
        date(2026, 8, 1),
        date(2026, 8, 31),
        [
            Account(
                "123",
                Decimal("100"),
                Decimal("87.66"),
                [Transaction(date(2026, 8, 20), date(2026, 8, 20), Decimal("-12.34"), "GROCER", Decimal("87.66"))],
            )
        ],
    )
    monkeypatch.setattr(
        "parsetrail.core.ledger_rebuild.parse_any", lambda *_: ParseResult(copy.deepcopy(parsed), "fake")
    )
    return legacy, archive, SimpleNamespace(metadata={"fake": {"VERSION": "1"}}), parsed


def test_fresh_overlap_is_once_and_category_verification_is_separate(example, tmp_path):
    legacy, archive, registry, _ = example
    evidence = replay_sources(legacy, archive, registry)
    assert len(evidence["files"]) == 2
    assert len(evidence["transactions"]) == 1
    assert len(evidence["memberships"]) == 2
    annotations = match_categories(legacy, evidence)
    assert annotations["counts"] == {"restored": 1}
    plan = {"legacy_metadata": legacy, "evidence": evidence, "annotations": annotations}
    path = tmp_path / "fresh.db"
    write_rebuild(path, plan)
    before = digest(path)
    with pytest.raises(FileExistsError):
        write_rebuild(path, plan)
    assert digest(path) == before
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("SELECT category_id,verified FROM CategoryAnnotations").fetchall() == [(2, 1)]
        assert c.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        assert (
            json.loads(c.execute("SELECT payload FROM CategoryDefinitions WHERE id=2").fetchone()[0])["ParentID"] == 1
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE CategoryAnnotations SET category_id=1")
        c.rollback()
    assert evidence == replay_sources(legacy, archive, registry)
    assert annotations == match_categories(legacy, evidence)


@pytest.mark.parametrize(
    "field,value",
    [("Description", "CHANGED"), ("AmountMinor", -1200), ("AccountID", 2), ("TransactionDate", "2026-08-19")],
)
def test_changed_transaction_never_silently_restores(example, field, value):
    legacy, archive, registry, _ = example
    evidence = replay_sources(legacy, archive, registry)
    next(iter(evidence["transactions"].values()))[field] = value
    assert match_categories(legacy, evidence)["counts"] == {"no_exact_match": 1}


def test_parser_insert_and_corrected_balance_do_not_break_exact_category_match(example):
    legacy, archive, registry, parsed = example
    parsed.accounts[0].transactions.insert(
        0, Transaction(date(2026, 8, 19), date(2026, 8, 19), Decimal("1"), "NEW", Decimal("101"))
    )
    parsed.accounts[0].transactions[1].balance = Decimal("88.66")
    evidence = replay_sources(legacy, archive, registry)
    assert match_categories(legacy, evidence)["counts"] == {"restored": 1}


def test_indistinguishable_rows_are_preserved_but_annotations_pending(example):
    legacy, archive, registry, parsed = example
    parsed.accounts[0].transactions.append(copy.deepcopy(parsed.accounts[0].transactions[0]))
    evidence = replay_sources(legacy, archive, registry)
    assert len(evidence["transactions"]) == 2
    assert match_categories(legacy, evidence)["counts"] == {"ambiguous_match": 1}


def test_conflicting_or_unverified_old_rows_prevent_many_to_one_match(example):
    legacy, archive, registry, _ = example
    other = {**legacy["Transactions"][0], "TransactionID": 2, "Verified": False, "CategoryID": 1}
    legacy["Transactions"].append(other)
    legacy["StatementTransactions"].append({"StatementID": 1, "TransactionID": 2, "StatementRow": 2})
    assert match_categories(legacy, replay_sources(legacy, archive, registry))["counts"] == {"ambiguous_match": 1}


def test_same_details_without_same_source_are_not_enough(example):
    legacy, archive, registry, _ = example
    evidence = replay_sources(legacy, archive, registry)
    evidence["legacy_sources"] = {"1": "different", "2": "different"}
    assert match_categories(legacy, evidence)["counts"] == {"no_exact_match": 1}


def test_absent_legacy_transaction_date_is_not_a_conflicting_date(example):
    legacy, archive, registry, _ = example
    legacy["Transactions"][0]["TransactionDate"] = None
    assert match_categories(legacy, replay_sources(legacy, archive, registry))["counts"] == {"restored": 1}


def test_manual_missing_and_refund_totals_are_fully_accounted(example):
    legacy, archive, registry, _ = example
    legacy["Transactions"].append({**legacy["Transactions"][0], "TransactionID": 2, "AmountMinor": 250})
    result = match_categories(legacy, replay_sources(legacy, archive, registry))
    assert result["counts"] == {"manual_only": 1, "restored": 1}
    total = result["totals"][0]
    assert (total["original_minor"], total["restored_minor"], total["pending_minor"]) == (-984, -1234, 250)


def test_missing_files_routing_errors_and_warnings_remain_pending(example, monkeypatch):
    legacy, archive, registry, _ = example
    # Both referenced sources missing; no synthetic replacements.
    missing = archive / "unavailable"
    missing.mkdir()
    evidence = replay_sources(legacy, missing, registry)
    assert match_categories(legacy, evidence)["counts"] == {"no_available_source": 1}

    def fail(*_):
        raise NoParserMatchError(".pdf")

    monkeypatch.setattr("parsetrail.core.ledger_rebuild.parse_any", fail)
    evidence = replay_sources(legacy, archive, registry)
    assert all(r["status"] == "parse_failed" for r in evidence["files"].values())
    assert match_categories(legacy, evidence)["counts"] == {"source_replay_pending": 1}


def test_warning_requires_acceptance_before_restoring_category(example, monkeypatch):
    legacy, archive, registry, parsed = example
    warning = Diagnostic("synthetic.warning", "Review required", DiagnosticSeverity.WARNING)
    monkeypatch.setattr(
        "parsetrail.core.ledger_rebuild.parse_any", lambda *_: ParseResult(copy.deepcopy(parsed), "fake", (warning,))
    )
    evidence = replay_sources(legacy, archive, registry)
    assert len(evidence["transactions"]) == 1
    assert match_categories(legacy, evidence)["counts"] == {"source_review_pending": 1}


def test_missing_account_in_multi_account_statement_is_visible(example):
    legacy, archive, registry, _ = example
    legacy["Statements"].append({**legacy["Statements"][0], "StatementID": 3, "AccountID": 2})
    evidence = replay_sources(legacy, archive, registry)
    assert any(r["status"] == "statement_coverage_pending" for r in evidence["files"].values())
    assert match_categories(legacy, evidence)["counts"] == {"source_review_pending": 1}


def test_archive_hash_mismatch_stops_before_accepting_evidence(example):
    legacy, archive, registry, _ = example
    (archive / "SUCCESS/a.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Archive bytes differ"):
        replay_sources(legacy, archive, registry)


def test_unknown_account_mapping_does_not_guess(example):
    legacy, archive, registry, parsed = example
    parsed.accounts[0].account_num = "unknown"
    evidence = replay_sources(legacy, archive, registry)
    assert not evidence["transactions"]
    assert all(r["status"] == "account_mapping_pending" for r in evidence["files"].values())


def test_review_checks_artifact_hashes_and_reports_restored_and_pending(example, tmp_path):
    from parsetrail.gui.ledger_rebuild_preview import load_rebuild_preview

    legacy, archive, registry, _ = example
    legacy["Transactions"].append({**legacy["Transactions"][0], "TransactionID": 2})
    evidence = replay_sources(legacy, archive, registry)
    annotations = match_categories(legacy, evidence)
    plan = {"legacy_metadata": legacy, "evidence": evidence, "annotations": annotations}
    (tmp_path / "plan.json").write_text(encoded(plan))
    (tmp_path / "legacy.db").write_bytes(b"retained bytes")
    write_rebuild(tmp_path / "fresh.db", plan)
    report = {
        "plan_sha256": digest(tmp_path / "plan.json"),
        "database_sha256": digest(tmp_path / "fresh.db"),
        "source_sha256": digest(tmp_path / "legacy.db"),
        "transactions": 1,
        "statements": 2,
    }
    (tmp_path / "report.json").write_text(encoded(report))
    preview = load_rebuild_preview(tmp_path)
    assert "1 verified expense categories restored" in preview["summary"]
    assert "1 pending" in preview["summary"]
    assert len(preview["tabs"][1][2]) == len(preview["tabs"][2][2]) == 1
    (tmp_path / "plan.json").write_text("changed")
    with pytest.raises(ValueError, match="changed after verification"):
        load_rebuild_preview(tmp_path)


def test_saved_plan_round_trip_preserves_checksum_and_database(example, tmp_path):
    legacy, archive, registry, _ = example
    legacy["Statements"].extend({**legacy["Statements"][0], "StatementID": n} for n in (11, 3))
    evidence = replay_sources(legacy, archive, registry)
    annotations = match_categories(legacy, evidence)
    plan = {"legacy_metadata": legacy, "evidence": evidence, "annotations": annotations}
    decoded = json.loads(encoded(plan))
    assert encoded(decoded) == encoded(plan)
    assert match_categories(legacy, decoded["evidence"]) == annotations
    write_rebuild(tmp_path / "first.db", plan)
    write_rebuild(tmp_path / "second.db", decoded)
    assert digest(tmp_path / "first.db") == digest(tmp_path / "second.db")


def repeated_purchase(example):
    legacy, archive, registry, parsed = example
    legacy["Transactions"].append(
        {**legacy["Transactions"][0], "TransactionID": 2, "BalanceMinor": 7532, "CategoryID": 1}
    )
    for sid in (1, 2):
        legacy["StatementTransactions"].append({"StatementID": sid, "TransactionID": 2, "StatementRow": 2})
    parsed.accounts[0].transactions.append(copy.deepcopy(parsed.accounts[0].transactions[0]))
    parsed.accounts[0].transactions[1].balance = Decimal("75.32")
    return legacy, replay_sources(legacy, archive, registry)


def test_unchanged_complete_balance_group_preserves_distinct_verified_decisions(example):
    legacy, evidence = repeated_purchase(example)
    result = match_categories(legacy, evidence)
    assert result["counts"] == {"restored": 2}
    assert {d["category_id"] for d in result["decisions"]} == {1, 2}
    for d in result["decisions"]:
        assert d["match_method"] == "exact_source_details_and_unchanged_balance_group"
        assert evidence["transactions"][d["transaction_id"]]["BalanceMinor"] == d["legacy"]["BalanceMinor"]


@pytest.mark.parametrize("change", ["changed_balance", "added_row", "duplicate_balance", "removed_membership"])
def test_changed_or_incomplete_balance_group_cannot_break_a_tie(example, change):
    legacy, evidence = repeated_purchase(example)
    ids = list(evidence["transactions"])
    if change == "changed_balance":
        evidence["transactions"][ids[1]]["BalanceMinor"] += 1
    elif change == "duplicate_balance":
        evidence["transactions"][ids[1]]["BalanceMinor"] = evidence["transactions"][ids[0]]["BalanceMinor"]
    elif change == "added_row":
        evidence["transactions"]["extra"] = {**evidence["transactions"][ids[1]], "id": "extra", "BalanceMinor": 6298}
        evidence["memberships"].append({**evidence["memberships"][0], "transaction_id": "extra", "row": 2})
    else:
        legacy["StatementTransactions"] = [
            r for r in legacy["StatementTransactions"] if not (r["StatementID"] == 1 and r["TransactionID"] == 2)
        ]
    result = match_categories(legacy, evidence)
    assert all(d["status"] == "ambiguous_match" for d in result["decisions"])


def asset_plan(example):
    legacy, archive, registry, _ = example
    legacy["AccountTypes"].append({"AccountTypeID": 2, "AssetType": "TangibleAsset"})
    legacy["Accounts"].append({"AccountID": 2, "AccountTypeID": 2, "AccountName": "Vehicle", "CurrencyCode": "USD"})
    legacy["Transactions"].append(
        {
            **legacy["Transactions"][0],
            "TransactionID": 2,
            "AccountID": 2,
            "AmountMinor": 100000,
            "BalanceMinor": 100000,
            "Description": "Manual asset",
        }
    )
    evidence = replay_sources(legacy, archive, registry)
    plan = {
        "source_sha256": "1" * 64,
        "legacy_metadata": legacy,
        "evidence": evidence,
        "annotations": match_categories(legacy, evidence),
    }
    review = {"source_sha256": "1" * 64, "valuations": [{"legacy_id": 2, "reason": "Owner confirmed asset value"}]}
    return plan, review


def test_reviewed_manual_value_retains_category_without_cash_or_expense_posting(example, tmp_path):
    plan, review = asset_plan(example)
    retain_reviewed_asset_values(plan, review)
    assert plan["annotations"]["counts"] == {"restored": 1, "retained_asset_value": 1}
    for t in plan["annotations"]["totals"]:
        for suffix in ("count", "minor"):
            assert t[f"original_{suffix}"] == sum(
                t[f"{prefix}_{suffix}"] for prefix in ("restored", "pending", "retained")
            )
    write_rebuild(tmp_path / "asset.db", plan)
    with closing(sqlite3.connect(tmp_path / "asset.db")) as c:
        assert c.execute("SELECT category_id,category_verified FROM AssetValuations").fetchall() == [(2, 1)]
        assert c.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM CategoryAnnotations").fetchone() == (1,)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("DELETE FROM AssetValuations")
        c.rollback()
    with pytest.raises(ValueError, match="already applied"):
        retain_reviewed_asset_values(plan, review)


@pytest.mark.parametrize("problem", ["different_snapshot", "duplicate", "empty_reason", "bank_account", "linked"])
def test_manual_review_rejects_wrong_or_uncertain_evidence_atomically(example, problem):
    plan, review = asset_plan(example)
    if problem == "different_snapshot":
        review["source_sha256"] = "2" * 64
    elif problem == "duplicate":
        review["valuations"].append(copy.deepcopy(review["valuations"][0]))
    elif problem == "empty_reason":
        review["valuations"][0]["reason"] = " "
    elif problem == "bank_account":
        plan["legacy_metadata"]["Accounts"][1]["AccountTypeID"] = 1
    else:
        review["valuations"][0]["legacy_id"] = 1
    before = copy.deepcopy(plan)
    with pytest.raises(ValueError):
        retain_reviewed_asset_values(plan, review)
    assert plan == before
