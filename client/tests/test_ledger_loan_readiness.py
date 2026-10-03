import copy
import importlib.util
import json
from pathlib import Path

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_readiness import build_loan_readiness
from parsetrail.gui.ledger_loan_readiness import load_loan_preview, loan_preview
from parsetrail.gui.ledger_preview import LedgerPreviewWindow

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_proposal_review import app as app


@pytest.fixture
def loan_rebuild(rebuild):
    e = rebuild["evidence"]
    e["files"]["loan"] = {"plugin": "pdf_wfloanper_202306", "filename": "loan.pdf", "status": "parsed"}
    e["statements"]["s4"].update(source="loan", opening_minor=-130, closing_minor=-100)
    e["transactions"]["loan"].update(AmountMinor=40, Description="PAYMENT")
    e["transactions"]["interest_loan"] = {
        **e["transactions"]["loan"],
        "id": "interest_loan",
        "AmountMinor": -10,
        "Description": "INTEREST PAYMENT",
    }
    for link in e["memberships"]:
        if link["statement_id"] == "s4":
            link["source"] = "loan"
    e["memberships"].append({"statement_id": "s4", "transaction_id": "interest_loan", "source": "loan", "row": 2})
    return rebuild


def test_read_only_exact_equation_keeps_interest_separate_and_does_not_certify(loan_rebuild):
    before = copy.deepcopy(loan_rebuild)
    report = build_loan_readiness(loan_rebuild)
    assert loan_rebuild == before and report == build_loan_readiness(loan_rebuild)
    assert report["account_count"] == 1 and report["movement_count"] == 2
    assert report["journal_entries_posted"] == 0 and not report["ready_for_cutover"]
    statement = report["statements"][0]
    assert statement["movement_total_minor"] == 30 and statement["difference_minor"] == 0
    assert statement["equation_agrees"] and not statement["independently_reconciled"]
    assert not statement["ready_for_posting"]
    assert "assumed_statement_period" in statement["blockers"]
    assert report["hint_summary"] == {"interest_component_review": 1, "payment_counterpart_review": 1}
    assert not any(t["posted"] or t["interpretation_reviewed"] for t in report["movements"])


@pytest.mark.parametrize(
    "plugin,limitation",
    [
        ("pdf_capitaloneauto_202402", "derived_opening_balance"),
        ("pdf_yamahafin_202306", "balance_composition_review_required"),
        ("csv_mohela_202411", "derived_balances"),
        ("unknown_loan_parser", "unknown_parser_contract"),
    ],
)
def test_parser_specific_provenance_is_preserved_without_promoting_review(loan_rebuild, plugin, limitation):
    loan_rebuild["evidence"]["files"]["loan"]["plugin"] = plugin
    report = build_loan_readiness(loan_rebuild)
    assert limitation in report["statements"][0]["blockers"]
    assert not report["accounts"][0]["ready_for_posting"]


@pytest.mark.parametrize(
    "description,hint",
    [
        ("LOAN ORIGINATION", "synthetic_estimated_origination"),
        ("CAPITALIZED INTEREST", "capitalized_interest_review"),
        ("DISBURSEMENT", "financing_counterpart_review"),
        ("IN STORE PURCHASE", "purchase_or_asset_funding_review"),
    ],
)
def test_origination_and_financing_cannot_be_assumed_income_or_expense(loan_rebuild, description, hint):
    loan_rebuild["evidence"]["transactions"]["loan"]["Description"] = description
    report = build_loan_readiness(loan_rebuild)
    row = next(t for t in report["movements"] if t["transaction_id"] == "loan")
    assert row["hint"] == hint and not row["posted"]
    if hint == "synthetic_estimated_origination":
        assert row["date_provenance"] == "synthetic_estimated"
        assert report["statements"][0]["synthetic_origination_ids"] == ["loan"]


def test_overlapping_membership_never_double_counts_account_movement(loan_rebuild):
    e = loan_rebuild["evidence"]
    e["statements"]["overlap"] = {**e["statements"]["s4"], "id": "overlap"}
    e["memberships"] += [
        {**link, "statement_id": "overlap"} for link in e["memberships"] if link["statement_id"] == "s4"
    ]
    report = build_loan_readiness(loan_rebuild)
    assert report["statement_count"] == 2 and report["movement_count"] == 2
    assert report["accounts"][0]["movement_total_minor"] == 30
    assert all(len(r["statement_ids"]) == 2 for r in report["movements"])


def test_interest_on_purchases_is_an_interest_hint_not_an_asset_purchase(loan_rebuild):
    loan_rebuild["evidence"]["transactions"]["interest_loan"]["Description"] = "Interest Charge on Purchases"
    report = build_loan_readiness(loan_rebuild)
    row = next(r for r in report["movements"] if r["transaction_id"] == "interest_loan")
    assert row["hint"] == "interest_component_review"


def test_date_balance_and_failed_source_blockers_are_visible(loan_rebuild):
    e = loan_rebuild["evidence"]
    e["files"]["loan"]["status"] = "review_pending"
    e["statements"]["s4"]["closing_minor"] += 1
    e["transactions"]["loan"]["PostingDate"] = "2026-09-01"
    row = build_loan_readiness(loan_rebuild)["statements"][0]
    assert row["difference_minor"] == 1 and not row["equation_agrees"]
    assert row["outside_period_ids"] == ["loan"]
    assert {"source_replay_not_accepted", "source_balance_difference", "movement_outside_source_period"} <= set(
        row["blockers"]
    )


@pytest.mark.parametrize("problem", ["duplicate", "owner", "period"])
def test_malformed_source_membership_or_period_refused(loan_rebuild, problem):
    e = loan_rebuild["evidence"]
    if problem == "duplicate":
        e["memberships"].append(dict(e["memberships"][-1]))
    elif problem == "owner":
        e["memberships"][-1]["source"] = "bank"
    else:
        e["statements"]["s4"]["start"] = "2026-09-01"
    with pytest.raises(LedgerError):
        build_loan_readiness(loan_rebuild)


def test_missing_membership_and_no_source_account_are_explicit(loan_rebuild):
    e = loan_rebuild["evidence"]
    e["memberships"] = [link for link in e["memberships"] if link["statement_id"] != "s4"]
    del e["statements"]["s4"]
    report = build_loan_readiness(loan_rebuild)
    assert {"missing_source_membership", "no_source_statement"} <= set(report["accounts"][0]["blockers"])
    assert all(t["hint"] == "missing_source_membership" for t in report["movements"])


@pytest.mark.parametrize("field", ["AmountMinor", "opening_minor"])
def test_inexact_money_is_refused(loan_rebuild, field):
    e = loan_rebuild["evidence"]
    row = e["transactions"]["loan"] if field == "AmountMinor" else e["statements"]["s4"]
    row[field] = 1.5
    with pytest.raises(LedgerError, match="exact integer"):
        build_loan_readiness(loan_rebuild)


def test_nonusd_account_remains_blocked_and_amounts_are_not_labeled_dollars(loan_rebuild):
    loan_rebuild["legacy_metadata"]["Accounts"][-1]["CurrencyCode"] = "EUR"
    for t in loan_rebuild["evidence"]["transactions"].values():
        if t["AccountID"] == 4:
            t["CurrencyCode"] = "EUR"
    result = build_loan_readiness(loan_rebuild)
    assert "currency_contract_pending" in result["accounts"][0]["blockers"]
    assert loan_preview(result)["tabs"][1][2][0]["cells"][3] == "EUR: -130 minor units"


def tool():
    path = Path(__file__).parents[2] / "devtools/ledger_audit/loans.py"
    spec = importlib.util.spec_from_file_location("loan_audit_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_report


def test_artifact_verification_no_overwrite_replay_and_source_bytes_preserved(tmp_path, loan_rebuild):
    source = accepted_folder(tmp_path, loan_rebuild)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    result = tool()(source, tmp_path / "first")
    assert result == tool()(source, tmp_path / "second")
    assert before == {p.name: p.read_bytes() for p in source.iterdir()}
    assert load_loan_preview(tmp_path / "first")["tabs"]
    with pytest.raises(FileExistsError):
        tool()(source, tmp_path / "first")
    (tmp_path / "first/readiness.json").write_text("{}")
    with pytest.raises(LedgerError, match="changed"):
        load_loan_preview(tmp_path / "first")
    (source / "fresh.db-wal").touch()
    with pytest.raises(LedgerError, match="inactive"):
        tool()(source, tmp_path / "third")


@pytest.mark.usefixtures("app")
def test_preview_selection_filter_clears_details_and_has_no_posting_controls(loan_rebuild):
    report = build_loan_readiness(loan_rebuild)
    original = json.dumps(report, sort_keys=True)
    window = LedgerPreviewWindow(loan_preview(report))
    assert window.tabs.count() == 3
    for index in range(window.tabs.count()):
        page = window.tabs.widget(index)
        page.table.selectRow(0)
        assert page.details.toPlainText()
        page.search.setText("NO-MATCH")
        assert not page.proxy.rowCount() and not page.details.toPlainText()
        page.search.clear()
    window.close()
    assert json.dumps(report, sort_keys=True) == original
