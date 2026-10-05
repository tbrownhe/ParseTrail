"""Synthetic cash-section, continuation and independent printed-check cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devtools.parser_engine_pilot.hsa_cash_lines import (
    MAX_DATED_LINE_CHARS,
    HsaCashDefinition,
    HsaCashError,
    parse_cash_section,
)
from devtools.parser_engine_pilot.pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("hsa-cash-pilot-definition.json")


def pages() -> list[str]:
    return [
        "\n".join(
            (
                "Synthetic header_ Period:08/01/26through08/31/26",
                "Synthetic header_ AccountNumber:SYNTHETIC-001",
                "BeginningBalance $1,000.00",
                "08/10/2026 EmployeeContribution 200.00 1,200.00",
                "InterestRateScheduleEffective:08/01/26",
                "1of2",
            )
        ),
        "\n".join(
            (
                "AccountStatement(Continued)",
                "08/20/2026 Investment:SYNTHETIC (100.00) 1,100.00",
                "_ 08/31/2026 0.10 1,100.10",
                "_ EndingBalance $1,100.10",
                "InvestmentPortfolio",
                "08/31/2026 unrelated portfolio row 999.00 999.00",
            )
        ),
    ]


def parse(text_pages: list[str] | None = None, *, definition: bytes | None = None, library: str = "synthetic-pdf-1"):
    lines = page_lines(b"%PDF-synthetic", text_pages if text_pages is not None else pages(), extraction_library=library)
    return parse_cash_section(definition if definition is not None else DEFINITION.read_bytes(), lines)


def test_cross_page_cash_chain_retains_unknown_description_and_unresolved_lines() -> None:
    evidence = parse()
    assert evidence.account_identity.normalized == "SYNTHETIC-001"
    assert (evidence.period_start.normalized, evidence.period_end.normalized) == ("2026-08-01", "2026-08-31")
    assert (evidence.printed_opening_minor.normalized, evidence.printed_closing_minor.normalized) == (100000, 110010)
    assert [row.amount_minor.normalized for row in evidence.rows] == [20000, -10000, 10]
    assert [row.printed_running_minor.normalized for row in evidence.rows] == [120000, 110000, 110010]
    assert [(row.date.page, row.date.line) for row in evidence.rows] == [(1, 4), (2, 2), (2, 3)]
    assert evidence.rows[-1].description.normalized is None
    assert evidence.rows[-1].description.provenance == "unknown_description"
    assert evidence.cash_chain_verified is True
    assert evidence.coverage_verified is False and evidence.account_balance_reconciled is False
    assert len(evidence.unresolved_section_lines) == 3
    assert parse(library="synthetic-pdf-2").rows[0].row_id != evidence.rows[0].row_id


def test_truncated_or_inconsistent_cash_activity_fails_printed_checks() -> None:
    truncated = pages()
    truncated[1] = truncated[1].replace("_ 08/31/2026 0.10 1,100.10\n", "")
    with pytest.raises(HsaCashError, match="printed_closing_mismatch"):
        parse(truncated)
    inconsistent = pages()
    inconsistent[0] = inconsistent[0].replace("200.00 1,200.00", "200.00 1,201.00")
    with pytest.raises(HsaCashError, match="printed_running_mismatch"):
        parse(inconsistent)
    duplicate = pages()
    duplicate[1] += "\nEndingBalance $1,100.10"
    with pytest.raises(HsaCashError, match="duplicate_closing"):
        parse(duplicate)


def test_hsa_declaration_and_dated_line_work_are_bounded() -> None:
    saved = json.loads(Path(__file__).with_name("hsa-cash-declaration-schema-v1.json").read_text(encoding="utf-8"))
    assert saved == HsaCashDefinition.model_json_schema()
    assert saved["additionalProperties"] is False
    for change in ({"schema_version": 2}, {"python": "import os"}, {"capabilities": ["pdf_lines_v1"]}):
        definition = json.loads(DEFINITION.read_bytes())
        definition.update(change)
        with pytest.raises(HsaCashError, match="invalid_definition"):
            parse(definition=json.dumps(definition).encode())
    oversized = pages()
    oversized[1] = oversized[1].replace(
        "_ EndingBalance", "08/30/2026 " + "X" * MAX_DATED_LINE_CHARS + "\n_ EndingBalance"
    )
    with pytest.raises(HsaCashError, match="dated_line_limit"):
        parse(oversized)


def test_hsa_cash_pass_can_cancel() -> None:
    lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    calls = 0

    def cancel() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 4

    with pytest.raises(HsaCashError) as exc:
        parse_cash_section(DEFINITION.read_bytes(), lines, cancelled=cancel)
    assert (exc.value.code, exc.value.page, exc.value.line) == ("cancelled", 1, 4)
