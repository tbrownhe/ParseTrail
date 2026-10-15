"""The 2.0 parser output rejects invented source facts and accounting state."""

import json

import pytest
from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    PdfLine,
    SourceEvidence,
    StatementAccount,
    StatementPayload,
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
            identity_locations=(line(2),),
            opening=money(100, 2),
            closing=money(100, 3),
            rows=(),
        )


def test_saved_schema_refuses_accounting_fields_and_unknown_versions() -> None:
    saved = statement(closing=100, verified=True)
    assert SourceEvidence.model_validate_json(saved.model_dump_json()).payload.kind == "statement"
    raw = saved.model_dump(mode="json")
    raw["category"] = "Food"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        SourceEvidence.model_validate_json(json.dumps(raw))
    raw.pop("category")
    raw["schema_version"] = 3
    with pytest.raises(ValidationError):
        SourceEvidence.model_validate_json(json.dumps(raw))
