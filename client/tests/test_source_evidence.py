"""The 2.0 parser output rejects invented source facts and accounting state."""

import json

import pytest
from parsetrail.core.source_evidence import (
    ComponentEvidence,
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfLine,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from pydantic import ValidationError


def line(number: int) -> PdfLine:
    return PdfLine(kind="pdf_line", page=1, line=number)


def money(value: int, number: int) -> MoneyValue:
    return MoneyValue(raw=f"${value / 100:.2f}", minor=value, provenance="observed", locations=(line(number),))


def printed_date(raw: str, iso: str, number: int) -> DateValue:
    return DateValue(raw=raw, iso=iso, provenance="observed", locations=(line(number),))


def statement(*, closing: int, verified: bool) -> SourceEvidence:
    return SourceEvidence(
        schema_version=2,
        source_sha256="a" * 64,
        definition_sha256="b" * 64,
        parser_id="synthetic_statement",
        definition_revision="1",
        engine_version="test-1",
        extractor_version="test-1",
        payload=StatementPayload(
            kind="statement",
            start=printed_date("01/01/26", "2026-01-01", 1),
            end=printed_date("01/31/26", "2026-01-31", 1),
            accounts=(
                StatementAccount(
                    source_identity="card ending 1234",
                    source_identity_form="opaque",
                    balance_scope="account_total",
                    identity_locations=(line(2),),
                    opening=money(100, 2),
                    closing=money(closing, 3),
                    rows=(),
                ),
            ),
            dispositions=(),
            capture_verified=False,
            independent_balance_verified=verified,
        ),
    )


def test_printed_balances_need_exact_independent_equation() -> None:
    assert statement(closing=100, verified=True).payload.independent_balance_verified
    with pytest.raises(ValidationError, match="independent statement balance equation"):
        statement(closing=101, verified=True)
    assert statement(closing=101, verified=False).payload.independent_balance_verified is False


def test_unknown_statement_start_does_not_invent_a_period() -> None:
    raw = statement(closing=100, verified=True).model_dump(mode="json")
    raw["payload"]["start"] = {"raw": None, "iso": None, "provenance": "unknown", "locations": []}
    assert SourceEvidence.model_validate_json(json.dumps(raw)).payload.start.iso is None
    raw["payload"]["end"] = {"raw": None, "iso": None, "provenance": "unknown", "locations": []}
    with pytest.raises(ValidationError, match="statement period"):
        SourceEvidence.model_validate_json(json.dumps(raw))


def test_principal_balance_checks_only_printed_principal_components() -> None:
    rows = tuple(
        ObservationEvidence(
            row_id=character * 64,
            occurrence=0,
            row_role="activity",
            source_account="loan account",
            source_account_form="opaque",
            date_role="activity_date",
            date=printed_date("01/15/2026", "2026-01-15", number),
            description=TextValue(raw=role, text=role, provenance="observed", locations=(line(number),)),
            amount=money(amount, number),
            components=(ComponentEvidence(role=role, amount=money(amount, number)),),
            fragments=(SourceFragment(channel="loan_line", location=line(number), raw_values=(role,)),),
        )
        for character, number, role, amount in (("e", 2, "interest", 100), ("f", 3, "principal", 200))
    )
    account = StatementAccount(
        source_identity="loan account",
        source_identity_form="opaque",
        balance_scope="principal_component",
        identity_locations=(line(1),),
        opening=money(-1000, 1),
        closing=money(-800, 4),
        rows=rows,
    )
    payload = StatementPayload(
        kind="statement",
        start=DateValue(raw=None, iso=None, provenance="unknown", locations=()),
        end=printed_date("01/31/2026", "2026-01-31", 1),
        accounts=(account,),
        dispositions=(),
        capture_verified=False,
        independent_balance_verified=True,
    )
    assert payload.independent_balance_verified
    with pytest.raises(ValidationError, match="independent statement balance equation"):
        StatementPayload.model_validate(
            payload.model_dump() | {"accounts": (account.model_copy(update={"closing": money(-700, 4)}),)}
        )


def test_unknown_value_is_distinct_from_zero_and_derived_value() -> None:
    unknown = MoneyValue(raw="Unavailable", minor=None, provenance="unknown", locations=(line(4),))
    assert unknown.minor is None
    with pytest.raises(ValidationError, match="unknown money cannot have a value"):
        MoneyValue(raw="Unavailable", minor=0, provenance="unknown", locations=(line(4),))
    with pytest.raises(ValidationError, match="derived money needs inputs"):
        MoneyValue(raw="$0.00", minor=0, provenance="derived", locations=(line(4),))
    with pytest.raises(ValidationError):
        MoneyValue(raw="$1.00", minor=True, provenance="observed", locations=(line(4),))


def test_abbreviated_source_identity_requires_exactly_four_digits() -> None:
    with pytest.raises(ValidationError, match="invalid abbreviated account identifier"):
        StatementAccount(
            source_identity="card ending 1234",
            source_identity_form="last_four",
            balance_scope="account_total",
            identity_locations=(line(2),),
            opening=money(100, 2),
            closing=money(100, 3),
            rows=(),
        )


def test_activity_export_may_have_no_printed_account_identity() -> None:
    row = ObservationEvidence(
        row_id="c" * 64,
        occurrence=0,
        row_role="activity",
        source_account=None,
        source_account_form=None,
        date_role="activity_date",
        date=printed_date("01/15/2026", "2026-01-15", 2),
        description=TextValue(raw="Payment", text="Payment", provenance="observed", locations=(line(2),)),
        amount=money(-100, 2),
        components=(),
        fragments=(SourceFragment(channel="table", location=line(2), raw_values=("Payment",)),),
    )
    assert row.source_account is None
    with pytest.raises(ValidationError, match="source account identity pair"):
        ObservationEvidence.model_validate(row.model_dump() | {"source_account_form": "opaque"})


def test_saved_schema_refuses_accounting_fields_and_unknown_versions() -> None:
    saved = statement(closing=100, verified=True)
    assert SourceEvidence.model_validate_json(saved.model_dump_json()).payload.kind == "statement"
    raw = saved.model_dump(mode="json")
    raw["payload"]["accounts"][0].pop("balance_scope")
    with pytest.raises(ValidationError, match="balance_scope"):
        SourceEvidence.model_validate_json(json.dumps(raw))
    raw = saved.model_dump(mode="json")
    raw["category"] = "Food"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SourceEvidence.model_validate_json(json.dumps(raw))
    raw.pop("category")
    raw["schema_version"] = 3
    with pytest.raises(ValidationError):
        SourceEvidence.model_validate_json(json.dumps(raw))


def test_period_summary_cannot_masquerade_as_posted_activity() -> None:
    values = {
        "row_id": "c" * 64,
        "occurrence": 0,
        "row_role": "period_summary",
        "source_account": "123-456789",
        "source_account_form": "full",
        "date_role": "statement_period_end",
        "date": DateValue(raw=None, iso="2026-01-31", provenance="derived", locations=(line(1),)),
        "transaction_date": None,
        "description": TextValue(raw="Additions", text="Additions", provenance="observed", locations=(line(2),)),
        "amount": money(100, 2),
        "running_balance": None,
        "components": (),
        "fragments": (SourceFragment(channel="summary", location=line(2), raw_values=("Additions $1.00 $1.00",)),),
    }
    assert ObservationEvidence(**values).row_role == "period_summary"
    with pytest.raises(ValidationError, match="period-end row date role"):
        ObservationEvidence(**(values | {"date_role": "posting_date"}))
    with pytest.raises(ValidationError, match="period-end row date role"):
        ObservationEvidence(**(values | {"row_role": "activity"}))


def test_statement_allows_observed_activity_date_without_posting_claim() -> None:
    values = {
        "row_id": "d" * 64,
        "occurrence": 0,
        "row_role": "activity",
        "source_account": "loan account",
        "source_account_form": "opaque",
        "date_role": "activity_date",
        "date": printed_date("01/15/2026", "2026-01-15", 2),
        "transaction_date": None,
        "description": TextValue(raw="Payment", text="Payment", provenance="observed", locations=(line(2),)),
        "amount": money(-100, 2),
        "running_balance": None,
        "components": (),
        "fragments": (SourceFragment(channel="history", location=line(2), raw_values=("Payment",)),),
    }
    row = ObservationEvidence(**values)
    account = StatementAccount(
        source_identity="loan account",
        source_identity_form="opaque",
        balance_scope="principal_component",
        identity_locations=(line(1),),
        opening=None,
        closing=money(100, 3),
        rows=(row,),
    )
    assert account.rows[0].date_role == "activity_date"

    outside = row.model_copy(update={"date": printed_date("12/31/2025", "2025-12-31", 2)})
    statement_payload = StatementPayload(
        kind="statement",
        start=printed_date("01/01/2026", "2026-01-01", 1),
        end=printed_date("01/31/2026", "2026-01-31", 1),
        accounts=(account.model_copy(update={"rows": (outside,)}),),
        dispositions=(),
        capture_verified=False,
        independent_balance_verified=False,
    )
    assert statement_payload.accounts[0].rows[0].date.iso == "2025-12-31"
    posted = outside.model_copy(update={"date_role": "posting_date"})
    with pytest.raises(ValidationError, match="statement row date outside period"):
        StatementPayload.model_validate(
            statement_payload.model_dump() | {"accounts": (account.model_copy(update={"rows": (posted,)}),)}
        )
