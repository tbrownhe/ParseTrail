"""Dual text channels preserve printed account fields and dated row locations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_dual_text_card_lines import (
    DualTextCardDefinition,
    DualTextCardError,
    parse_dual_text_card,
)
from parsetrail.core.v2_pdf_lines import page_lines

DEFINITION = Path(__file__).with_name("usbank-rei-card-pilot-definition.json").read_bytes()


def channels(changes: dict[int, str] | None = None):
    layout_lines = [
        "Open Date: 01/01/2026 Closing Date: 01/31/2026 Account: 1234 5678 9012 3456",
        "New Balance $90.00",
        "Previous Balance + $100.00",
        "New Balance = $90.00",
        "New Balance $90.00",
    ]
    simple_lines = [
        "01/05 01/04 Coffee $10.00",
        "01/10 Payment $20.00CR",
        "01/01/26 TO 01/31/26",
    ]
    for index, replacement in (changes or {}).items():
        if index < 5:
            layout_lines[index] = replacement
        else:
            simple_lines[index - 5] = replacement
    source = b"%PDF-synthetic"
    layout = page_lines(source, ["\n".join(layout_lines)], extraction_library="pdfplumber-bounded-layout-fixed-v1")
    simple = page_lines(source, ["\n".join(simple_lines)], extraction_library="pdfplumber-bounded-simple-v1")
    return layout, simple


def parse(changes: dict[int, str] | None = None):
    return parse_dual_text_card(DEFINITION, *channels(changes))


def test_two_channels_and_interest_header_disposition() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "1234567890123456" and account.source_identity_form == "full"
    assert (account.opening.minor, account.closing.minor) == (-10000, -9000)
    assert [
        (row.date.iso, row.transaction_date.iso if row.transaction_date else None, row.amount.minor)
        for row in account.rows
    ] == [
        ("2026-01-05", "2026-01-04", -1000),
        ("2026-01-10", None, 2000),
    ]
    assert {item.code for item in output.payload.dispositions} == {
        "interest_period_header",
        "repeated_closing_balance",
        "closing_equation_copy",
    }


def test_unrecognized_dated_line_or_conflicting_balance_refuses_source() -> None:
    with pytest.raises(DualTextCardError, match="unresolved_dated_line"):
        parse({5: "01/05 Coffee with missing amount"})
    with pytest.raises(DualTextCardError, match="conflicting_printed_closing"):
        parse({3: "New Balance = $91.00"})
    with pytest.raises(DualTextCardError, match="printed_card_balance_equation"):
        parse({2: "Previous Balance + $101.00"})


def test_channel_identity_and_definition_are_strict() -> None:
    layout, simple = channels()
    with pytest.raises(DualTextCardError, match="source_channel_mismatch"):
        parse_dual_text_card(DEFINITION, layout, replace(simple, source_sha256="f" * 64))
    assert DualTextCardDefinition.model_validate_json(DEFINITION).operation == "dual_text_card_activity_v1"
    saved = json.loads(Path(__file__).with_name("dual-text-card-declaration-schema-v1.json").read_text())
    assert saved == DualTextCardDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(DualTextCardError, match="invalid_definition"):
        parse_dual_text_card(json.dumps(raw).encode(), layout, simple)
