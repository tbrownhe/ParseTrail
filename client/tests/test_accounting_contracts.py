import copy
import sqlite3
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core.accounting_contracts import FIELD, RULE, encode, loan_workflow, snapshot
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_corrections import LoanPaymentCorrections
from parsetrail.core.ledger_loan_payments import LoanPayments
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_rebuild import key, replay_sources
from parsetrail.core.orm import Statements
from parsetrail.core.parse import BaseRouter, ParseInput
from parsetrail.core.parser_routing import ParserExecutionError
from parsetrail.core.plugin_loader import load_plugin
from parsetrail.core.statements import StatementImportService
from parsetrail.core.validation import Transaction
from parsetrail.plugins.pdf_capitaloneauto_202402 import Parser as CapitalOne
from parsetrail.plugins.pdf_wfloanper_202306 import Parser as WellsFargo
from sqlalchemy import select

from .test_import_recovery import _empty_database
from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_corrections import correction_rebuild as correction_rebuild
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_rebuild import example as example
from .test_ledger_reviewed_reconciliation import prepare_custom
from .test_parse_outcomes import _statement


@pytest.mark.parametrize("parser", [CapitalOne, WellsFargo])
def test_loader_retains_detached_optional_declaration(parser):
    name, loaded, metadata = load_plugin(
        Path(__file__).parents[1] / "src/parsetrail/plugins" / f"{parser.PLUGIN_NAME}.py"
    )
    assert name == parser.PLUGIN_NAME
    assert metadata[FIELD] == parser.ACCOUNTING_CONTRACT
    metadata[FIELD]["label"] = "Changed catalog label"
    assert loaded.ACCOUNTING_CONTRACT["label"] == parser.ACCOUNTING_CONTRACT["label"]


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"label": ""},
        {"payment_description": "Interest Fee"},
        {"association": "nearby-date"},
        {"date_basis": "verified"},
        {"excluded_descriptions": "LOAN"},
        {"unexpected": "ignored?"},
        {"excluded_descriptions": ["Payment Received"]},
    ],
)
def test_malformed_declarations_are_not_silently_accepted(change):
    contract = {**copy.deepcopy(CapitalOne.ACCOUNTING_CONTRACT), **change}
    with pytest.raises(ValueError):
        snapshot(contract)
    assert loan_workflow(contract) is None


@pytest.mark.parametrize(
    "contract",
    [
        None,
        {"schema_version": 99, "representation": "future"},
        {"schema_version": 1, "representation": "principal-only"},
    ],
)
def test_absent_or_future_contracts_are_retained_without_a_workflow(contract):
    assert snapshot(contract) == contract
    assert loan_workflow(contract) is None


def test_parser_snapshot_survives_class_changes_and_round_trips_import(tmp_path):
    class Example:
        ACCOUNTING_CONTRACT = copy.deepcopy(CapitalOne.ACCOUNTING_CONTRACT)

        def parse(self, _):
            return _statement()

    metadata = {
        "PLUGIN_NAME": "example",
        "VERSION": "1",
        "SUFFIX": ".pdf",
        "COMPANY": "Example",
        "STATEMENT_TYPE": "Loan",
    }
    registry = SimpleNamespace(get_parser=lambda _: Example, metadata={"example": metadata})
    statement = (
        BaseRouter(registry, ParseInput("example.pdf", ".pdf", b"")).extract_statement("example", None).statement
    )
    original = encode(statement.accounting_contract)
    Example.ACCOUNTING_CONTRACT["label"] = "New parser interpretation"
    assert encode(statement.accounting_contract) == original
    statement.accounts[0].add_account_info(1, "Checking")
    Transaction.hash_transactions(1, statement.accounts[0].transactions)
    statement.dpath = tmp_path / "example.pdf"
    statement.add_content_hash("a" * 64)
    Session = _empty_database(tmp_path / "import.db")
    with Session() as session:
        StatementImportService(Session, registry).complete_data_transaction(session, statement)
    with Session() as session:
        assert session.scalar(select(Statements)).AccountingContract == original


def test_bad_parser_declaration_fails_before_import():
    class Example:
        ACCOUNTING_CONTRACT = {"schema_version": 0}

        def parse(self, _):
            return _statement()

    registry = SimpleNamespace(get_parser=lambda _: Example)
    with pytest.raises(ParserExecutionError):
        BaseRouter(registry, ParseInput("example.pdf", ".pdf", b"")).extract_statement("example", None)


def test_replay_captures_declarations_without_changing_category_identity(example):
    legacy, archive, registry, parsed = example
    before = replay_sources(legacy, archive, registry)
    parsed.accounting_contract = copy.deepcopy(CapitalOne.ACCOUNTING_CONTRACT)
    after = replay_sources(legacy, archive, registry)
    assert before["transactions"] == after["transactions"] and before["memberships"] == after["memberships"]
    assert all(s["accounting_contract"] == parsed.accounting_contract for s in after["statements"].values())
    parsed.accounting_contract["label"] = "Changed later"
    assert all(s["accounting_contract"]["label"] == "Capital One Auto" for s in after["statements"].values())


@pytest.fixture
def declared_rebuild(correction_rebuild):
    e = correction_rebuild["evidence"]
    # Neither parser identity nor description strings are hardcoded in dispatch.
    e["files"]["loan"].update(plugin="example_new_loan", version="9.0")
    declaration = copy.deepcopy(CapitalOne.ACCOUNTING_CONTRACT)
    declaration.update(
        label="Example Loan", payment_description="Total remittance", interest_description="Finance cost"
    )
    e["statements"]["s4"]["accounting_contract"] = declaration
    e["transactions"]["loan"]["Description"] = "Total remittance"
    e["transactions"]["loan_interest"]["Description"] = "Finance cost"
    return correction_rebuild


def test_retained_declaration_drives_shared_posting_correction_and_reopen(tmp_path, declared_rebuild, monkeypatch):
    folder = prepare_custom(tmp_path, declared_rebuild)[0]
    declaration = declared_rebuild["evidence"]["statements"]["s4"]["accounting_contract"]
    with ProposalReview(folder) as review:
        c = review.store.connection
        assert c.execute("SELECT accounting_contract FROM SourceStatements WHERE id='s4'").fetchone()[0] == encode(
            declaration
        )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            c.execute("UPDATE SourceStatements SET accounting_contract=NULL WHERE id='s4'")
        service = LoanPayments(review)
        assert service.snapshot()["pairs"][0]["source_contract"]["name"] == "Example Loan"
        plan = service.preview("source:bank_payment", "loan")
        assert plan["rule"] == RULE
        assert plan["source_basis"]["sources"][0]["statement"]["accounting_contract"] == declaration
        monkeypatch.setattr(CapitalOne, "ACCOUNTING_CONTRACT", {"schema_version": 99, "representation": "future"})
        assert service.preview("source:bank_payment", "loan") == plan
        tampered = copy.deepcopy(plan)
        tampered["source_basis"]["sources"][0]["statement"]["accounting_contract"]["label"] = "Different"
        tampered["preview_hash"] = key({k: v for k, v in tampered.items() if k != "preview_hash"})
        with pytest.raises(LedgerError):
            service.apply(tampered)
        service.apply(plan)
        correction = LoanPaymentCorrections(review).preview("loan", "source:bank_other", "Test funding correction")
        LoanPaymentCorrections(review).apply(correction)
        assert review.store.balances(date.max)["account:4"] == 900
    with ProposalReview(folder, read_only=True) as review:
        assert LoanPaymentCorrections(review).histories()["loan"][-1] == correction["replacement"]


@pytest.mark.parametrize("problem", ["absent", "future", "other", "overlap", "version"])
def test_unsupported_or_conflicting_declarations_do_not_fall_back(tmp_path, declared_rebuild, problem):
    e = declared_rebuild["evidence"]
    statement = e["statements"]["s4"]
    if problem in ("absent", "future", "other"):
        # Even a formerly allowlisted parser cannot override an explicit declaration.
        e["files"]["loan"].update(plugin="pdf_capitaloneauto_202402", version="0.2.1")
        statement["accounting_contract"] = {
            "absent": None,
            "future": {"schema_version": 2, "representation": "loan-total-and-interest"},
            "other": {"schema_version": 1, "representation": "principal-only"},
        }[problem]
    else:
        e["files"]["overlap"] = {**e["files"]["loan"]}
        e["statements"]["overlap"] = {**copy.deepcopy(statement), "id": "overlap", "source": "overlap"}
        if problem == "overlap":
            e["statements"]["overlap"]["accounting_contract"]["balance_basis"] = "printed-principal"
        else:
            e["files"]["overlap"]["version"] = "10.0"
        e["memberships"] += [
            {**m, "statement_id": "overlap", "source": "overlap"}
            for m in list(e["memberships"])
            if m["statement_id"] == "s4"
        ]
    with ProposalReview(prepare_custom(tmp_path, declared_rebuild)[0]) as review:
        assert not LoanPayments(review).snapshot()["pairs"]


def test_declaration_column_mismatch_is_detected(tmp_path, declared_rebuild):
    folder = prepare_custom(tmp_path, declared_rebuild)[0]
    with ProposalReview(folder) as review:
        c = review.store.connection
        c.execute("DROP TRIGGER SourceStatements_UPDATE")
        c.execute("UPDATE SourceStatements SET accounting_contract=NULL WHERE id='s4'")
        with pytest.raises(LedgerError, match="conflicts"):
            LoanPayments(review).snapshot()


def test_declared_wells_fargo_synthetic_exclusion(tmp_path, loan_rebuild):
    e = loan_rebuild["evidence"]
    e["statements"]["s4"]["accounting_contract"] = copy.deepcopy(WellsFargo.ACCOUNTING_CONTRACT)
    e["files"]["loan"].update(plugin=WellsFargo.PLUGIN_NAME, version=WellsFargo.VERSION)
    e["transactions"]["loan"].update(Description="PAYMENT")
    e["transactions"]["loan_interest"].update(Description="LOAN ORIGINATION")
    with ProposalReview(prepare_custom(tmp_path, loan_rebuild)[0]) as review:
        assert not LoanPayments(review).snapshot()["components"]
