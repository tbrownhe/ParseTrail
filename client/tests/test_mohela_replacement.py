import copy
import csv
import io
import json
import sqlite3
from contextlib import closing

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_candidates import build_candidates
from parsetrail.core.ledger_mohela_replacement import build_replacement, create_replacement, replacement_report
from parsetrail.core.ledger_rebuild import write_rebuild
from parsetrail.core.ledger_store import encoded
from parsetrail.core.mohela_export import COLUMNS, loan_summary, read_export
from parsetrail.core.recovery_bundle import digest
from parsetrail.gui.ledger_mohela_replacement import preview_data
from parsetrail.gui.ledger_preview import LedgerPreviewWindow
from parsetrail.gui.ledger_rebuild_preview import load_rebuild_preview
from parsetrail.plugins.csv_mohela_202411 import Parser

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_proposal_review import app as app


def csv_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(COLUMNS)
    writer.writerows(rows)
    return buffer.getvalue().encode()


@pytest.fixture
def rows():
    return [
        [
            "08/01/2026",
            "1-01 Direct Loan - Subsidized",
            "DISBURSEMENT",
            "$5.00",
            "$0.00",
            "$0.00",
            "$5.00",
            "Unavailable",
        ],
        [
            "08/01/2026",
            "1-02 Direct Loan - Unsubsidized",
            "DISBURSEMENT",
            "$5.00",
            "$0.00",
            "$0.00",
            "$5.00",
            "Unavailable",
        ],
        ["08/20/2026", "1-01 Direct Loan - Subsidized", "PAYMENT", "-$0.80", "-$0.20", "$0.00", "-$1.00", "$4.20"],
        ["08/20/2026", "1-02 Direct Loan - Unsubsidized", "PAYMENT", "-$1.60", "-$0.40", "$0.00", "-$2.00", "$4.40"],
        [
            "08/21/2026",
            "1-02 Direct Loan - Unsubsidized",
            "CAPITALIZED INTEREST",
            "$0.00",
            "$0.00",
            "$0.00",
            "$0.00",
            "$4.40",
        ],
    ]


@pytest.fixture
def replacement_input(rebuild, rows):
    e = rebuild["evidence"]
    e["files"]["mohela"] = {
        "plugin": "csv_mohela_202411",
        "version": "0.2.0",
        "status": "parsed",
        "statement_ids": [7],
        "filename": "old.csv",
    }
    del e["transactions"]["loan"]
    e["memberships"] = [m for m in e["memberships"] if m["statement_id"] != "s4"]
    e["statements"]["s4"].update(source="mohela", opening_minor=0, closing_minor=-760)
    rebuild["annotations"]["decisions"] = [
        d for d in rebuild["annotations"]["decisions"] if d["transaction_id"] != "loan"
    ]
    legacy_rows = []
    for n, (desc, amount, when) in enumerate(
        [("DISBURSEMENT", -1000, "2026-08-01"), ("PAYMENT", 300, "2026-08-20"), ("INTEREST", -60, "2026-08-20")], 11
    ):
        tid = f"old:{n}"
        row = {
            "id": tid,
            "AccountID": 4,
            "PostingDate": when,
            "TransactionDate": when,
            "AmountMinor": amount,
            "CurrencyCode": "USD",
            "Description": desc,
        }
        e["transactions"][tid] = row
        e["memberships"].append({"statement_id": "s4", "source": "mohela", "transaction_id": tid, "row": n})
        old = {**row, "TransactionID": n, "CategoryID": 1, "Verified": True}
        legacy_rows.append(old)
        rebuild["annotations"]["decisions"].append(
            {
                "legacy_id": n,
                "transaction_id": tid,
                "status": "restored",
                "account_id": 4,
                "amount_minor": amount,
                "currency": "USD",
                "category_id": 1,
                "legacy": old,
                "candidates": [tid],
                "sources": ["mohela"],
            }
        )
    rebuild["annotations"]["totals"] = [
        {
            "account_id": 4,
            "category_id": 1,
            "currency": "USD",
            "original_count": 3,
            "original_minor": -760,
            "restored_count": 3,
            "restored_minor": -760,
            "pending_count": 0,
            "pending_minor": 0,
            "retained_count": 0,
            "retained_minor": 0,
        }
    ]
    legacy = {
        "Transactions": legacy_rows,
        "StatementTransactions": [{"TransactionID": r["TransactionID"], "StatementID": 7} for r in legacy_rows],
    }
    return rebuild, read_export(csv_bytes(rows)), legacy


def test_exact_components_unknown_balances_zero_rows_and_duplicate_occurrences(rows):
    rows.append(copy.deepcopy(rows[-1]))
    export = read_export(csv_bytes(rows))
    assert len(export["rows"]) == len({r["id"] for r in export["rows"]}) == 6
    assert export["rows"][0]["reported_principal_minor"] is None
    assert export["rows"][-1]["total_minor"] == 0
    summaries = loan_summary(export)
    assert summaries[0]["unexplained_minor"] == 0 and not summaries[0]["reconciled"]
    assert summaries[1]["unexplained_minor"] == 100
    assert not export["coverage_verified"] and export["reported_as_of"] is None


@pytest.mark.parametrize(
    "column,value",
    [(0, "08/99/2026"), (1, "Missing identifier"), (2, ""), (3, "$5.001"), (4, "$NaN"), (6, "$6.00"), (7, "")],
)
def test_bad_rows_fail_with_row_number_and_no_private_values(rows, column, value):
    rows[0][column] = value
    with pytest.raises(LedgerError, match="row 2"):
        read_export(csv_bytes(rows))


def test_header_and_old_format_refusal(rows):
    with pytest.raises(LedgerError, match="Empty"):
        read_export(b"\n")
    with pytest.raises(LedgerError, match="detailed"):
        read_export(b"Date,Total\n08/01/2026,$1.00\n")
    with pytest.raises(ValueError, match="replacement review"):
        Parser().parse([list(COLUMNS), *rows])


def test_download_header_trailing_column_and_all_unknown_balances(rows):
    for row in rows:
        row[-1] = "Unavailable"
    data = csv_bytes(rows).decode().splitlines()
    downloaded = "\r\n".join(line + "," for line in data)
    export = read_export(("\ufeff<!DOCTYPE html>" + downloaded).encode())
    assert len(export["rows"]) == len(rows)
    assert all(r["reported_principal_minor"] is None for r in export["rows"])
    for loan in loan_summary(export):
        assert loan["reported_principal_minor"] is None
        assert loan["balance_date"] is None and loan["unexplained_minor"] is None


def test_conflicting_same_day_balances_are_not_arbitrarily_selected(rows):
    other = copy.deepcopy(rows[-1])
    other[-1] = "$4.50"
    rows.append(other)
    summary = loan_summary(read_export(csv_bytes(rows)))[1]
    assert summary["balance_conflict"] and summary["reported_principal_minor"] is None


def test_replacement_retains_categories_without_duplicate_activity_and_preserves_banks(replacement_input, tmp_path):
    original, export, legacy = replacement_input
    before = copy.deepcopy(original)
    result = build_replacement(original, export, legacy)
    assert original == before
    assert not any(r["AccountID"] == 4 for r in result["evidence"]["transactions"].values())
    assert result["superseded_source_evidence"]["mohela"]["transactions"].keys() == {"old:11", "old:12", "old:13"}
    assert len(result["export_category_bindings"]) == 3
    for binding in result["export_category_bindings"]:
        assert sum(a["amount_minor"] for a in binding["allocations"]) == binding["legacy"]["AmountMinor"]
        assert binding["category_verified"] and not binding["accounting_approved"]
    total = result["annotations"]["totals"][0]
    for suffix in ("count", "minor"):
        assert total[f"original_{suffix}"] == total[f"retained_{suffix}"]
    a, b = build_candidates(original), build_candidates(result)
    for field in ("accounts", "observations", "statements", "proposals"):
        assert a[field] == b[field]
    path = tmp_path / "fresh.db"
    write_rebuild(path, result)
    with closing(sqlite3.connect(path)) as c:
        assert c.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
        assert c.execute("SELECT COUNT(*) FROM ActivityExportRows").fetchone()[0] == 5
        assert (
            c.execute("SELECT COUNT(*) FROM CategoryDecisions WHERE status='retained_export_annotation'").fetchone()[0]
            == 3
        )
        assert c.execute("SELECT COUNT(*) FROM LedgerEntries").fetchone()[0] == 0
        for table in ("ActivityExports", "ActivityExportRows", "ExportCategoryBindings", "SupersededSourceEvidence"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                c.execute(f"DELETE FROM {table}")
    with pytest.raises(LedgerError, match="once"):
        build_replacement(result, export, legacy)


@pytest.mark.parametrize("problem", ["missing", "changed", "duplicate_old", "shared", "category", "currency"])
def test_uncertain_replacement_refuses_without_mutation(replacement_input, problem):
    original, export, legacy = replacement_input
    e = original["evidence"]
    if problem == "missing":
        export["rows"] = export["rows"][1:]
    elif problem == "changed":
        e["transactions"]["old:11"]["AmountMinor"] -= 1
    elif problem == "duplicate_old":
        e["transactions"]["dup"] = {**e["transactions"]["old:11"], "id": "dup"}
        e["memberships"].append({"statement_id": "s4", "source": "mohela", "transaction_id": "dup", "row": 9})
    elif problem == "shared":
        e["memberships"].append({"statement_id": "s1", "source": "bank", "transaction_id": "old:11", "row": 99})
    elif problem == "category":
        legacy["Transactions"][0]["Description"] = "Conflicting source details"
    else:
        e["transactions"]["old:11"]["CurrencyCode"] = "EUR"
    before = copy.deepcopy(original)
    with pytest.raises(LedgerError):
        build_replacement(original, export, legacy)
    assert original == before


@pytest.mark.usefixtures("app")
def test_review_is_read_only_and_explains_preserved_categories(replacement_input, tmp_path):
    original, export, legacy = replacement_input
    plan = build_replacement(original, export, legacy)
    write_rebuild(tmp_path / "fresh.db", plan)
    (tmp_path / "plan.json").write_text(encoded(plan), encoding="utf-8")
    (tmp_path / "legacy.db").write_bytes(b"unused retained source")
    report = {
        **replacement_report(plan),
        "plan_sha256": digest(tmp_path / "plan.json"),
        "database_sha256": digest(tmp_path / "fresh.db"),
        "source_sha256": digest(tmp_path / "legacy.db"),
    }
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    before = digest(tmp_path / "fresh.db")
    with pytest.raises(LedgerError, match="MOHELA replacement review"):
        load_rebuild_preview(tmp_path)
    window = LedgerPreviewWindow(preview_data(tmp_path))
    assert window.tabs.count() == 4
    for n in (0, 1, 3):
        page = window.tabs.widget(n)
        page.table.selectRow(0)
        assert page.details.toPlainText()
    assert "does not approve" in window.tabs.widget(1).details.toPlainText()
    window.close()
    assert digest(tmp_path / "fresh.db") == before


def test_prepare_rejects_changed_inputs_before_creating_output(tmp_path):
    accepted = tmp_path / "accepted"
    accepted.mkdir()
    for name in ("plan.json", "fresh.db", "legacy.db"):
        (accepted / name).write_bytes(b"changed")
    (accepted / "report.json").write_text(
        json.dumps({"plan_sha256": "wrong", "database_sha256": "wrong", "source_sha256": "wrong"}), encoding="utf-8"
    )
    target = tmp_path / "target"
    with pytest.raises(LedgerError, match="unchanged"):
        create_replacement(accepted, tmp_path / "unread.csv", target)
    assert not target.exists()
