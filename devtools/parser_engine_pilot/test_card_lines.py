"""Synthetic finite card-line declaration and evidence cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.v2_card_lines import (
    MAX_DATED_LINE_CHARS,
    CardDefinition,
    CardLineError,
    parse_card_lines,
)
from parsetrail.core.v2_pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("chase-card-pilot-definition.json")


def pages() -> list[str]:
    return [
        "\n".join(
            (
                "Opening/Closing Date 03/16/26 - 04/15/26",
                "Account Number: XXXX XXXX XXXX 1234",
                "Previous Balance $25.00",
                "New Balance $30.00",
            )
        ),
        "\n".join(
            (
                "03/15      PRIOR-DAY CHARGE 10.00",
                "04/01      PAYMENT -5.00",
                "04/01    ABC                      ",
                "10,000 X 0.001234 (LOCAL RATE)",
            )
        ),
    ]


def parse(text_pages: list[str] | None = None, *, definition: bytes | None = None, library: str = "synthetic-pdf-1"):
    lines = page_lines(b"%PDF-synthetic", text_pages if text_pages is not None else pages(), extraction_library=library)
    return parse_card_lines(definition if definition is not None else DEFINITION.read_bytes(), lines)


def test_card_line_evidence_separates_printed_derived_and_auxiliary() -> None:
    evidence = parse()
    assert evidence.account_identity.normalized == "1234"
    assert (evidence.period_start.normalized, evidence.period_end.normalized) == ("2026-03-16", "2026-04-15")
    assert (evidence.opening_minor.normalized, evidence.closing_minor.normalized) == (-2500, -3000)
    assert evidence.opening_minor.provenance == evidence.closing_minor.provenance == "printed"
    assert [row.amount.normalized for row in evidence.rows] == [-1000, 500]
    assert evidence.rows[0].source_sign_minor == 1000
    assert evidence.rows[0].transaction_date.normalized == "2026-03-15"
    assert evidence.rows[0].posting_date.normalized == "2026-03-16"
    assert evidence.rows[0].posting_date.provenance == "derived_posting_proxy"
    assert (evidence.rows[0].amount.page, evidence.rows[0].amount.line) == (2, 1)
    assert len(evidence.auxiliary_lines) == 1
    assert evidence.auxiliary_lines[0].disposition == "dated_three_letter_detail_uninterpreted"
    assert evidence.coverage_verified is False and evidence.printed_balance_equation_passed is True
    assert parse(library="synthetic-pdf-2").rows[0].row_id != evidence.rows[0].row_id
    revised = json.loads(DEFINITION.read_bytes())
    revised["revision"] = "2"
    assert parse(definition=json.dumps(revised).encode()).rows[0].row_id != evidence.rows[0].row_id


def test_card_printed_balance_equation_failure_stays_visible() -> None:
    changed = pages()
    changed[0] = changed[0].replace("New Balance $30.00", "New Balance $31.00")
    evidence = parse(changed)
    assert evidence.printed_balance_equation_passed is False
    assert evidence.coverage_verified is False


def test_card_declaration_schema_is_strict_and_synchronized() -> None:
    saved = json.loads(Path(__file__).with_name("card-declaration-schema-v1.json").read_text(encoding="utf-8"))
    assert saved == CardDefinition.model_json_schema()
    assert saved["additionalProperties"] is False
    for change in (
        {"schema_version": 2},
        {"python": "import os"},
        {"capabilities": ["pdf_lines_v1"]},
        {"dated_auxiliary": "ignore_all"},
    ):
        definition = json.loads(DEFINITION.read_bytes())
        definition.update(change)
        with pytest.raises(CardLineError, match="invalid_definition"):
            parse(definition=json.dumps(definition).encode())


def test_duplicate_printed_fields_and_unresolved_dated_lines_fail() -> None:
    duplicated = pages()
    duplicated[0] += "\nNew Balance $30.00"
    with pytest.raises(CardLineError) as exc:
        parse(duplicated)
    assert (exc.value.code, exc.value.page, exc.value.line) == ("duplicate_closing", 1, 5)
    malformed = pages()
    malformed[1] += "\n04/02      UNPARSED DATA"
    with pytest.raises(CardLineError) as exc:
        parse(malformed)
    assert (exc.value.code, exc.value.page, exc.value.line) == ("unresolved_dated_line", 2, 5)
    assert "UNPARSED DATA" not in str(exc.value)
    oversized = pages()
    oversized[1] += "\n04/03      " + "X" * MAX_DATED_LINE_CHARS
    with pytest.raises(CardLineError, match="dated_line_limit"):
        parse(oversized)


def test_card_statement_pass_can_cancel_without_partial_evidence() -> None:
    lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    checks = 0

    def cancel() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(CardLineError) as exc:
        parse_card_lines(DEFINITION.read_bytes(), lines, cancelled=cancel)
    assert (exc.value.code, exc.value.page, exc.value.line) == ("cancelled", 1, 3)
