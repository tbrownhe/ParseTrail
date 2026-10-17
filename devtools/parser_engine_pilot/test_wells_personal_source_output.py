"""Wells personal table rows retain source balance and stop boundaries."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_anchored_table import ENGINE_VERSION as TABLE_VERSION
from parsetrail.core.v2_anchored_table import AnchoredPage, AnchoredRow, AnchoredTableEvidence
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot.wells_personal_source_output import WellsPersonalError, from_wells_personal

DEFINITION = Path(__file__).with_name("wells-personal-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic-wells-personal"


def evidence(changes: dict[int, tuple[str, str, str, str, str, str]] | None = None):
    raw = [
        ("1/5", "", "Deposit", "$20.00", "", "$120.00"),
        ("", "", "continued", "", "", ""),
        ("1/10", "", "Withdrawal", "", "$30.00", "$90.00"),
        ("", "", "", "", "", ""),
        ("1/15", "", "After stop", "$5.00", "", ""),
    ]
    for index, replacement in (changes or {}).items():
        raw[index] = replacement
    table = AnchoredTableEvidence(
        1,
        hashlib.sha256(SOURCE).hexdigest(),
        hashlib.sha256(DEFINITION).hexdigest(),
        TABLE_VERSION,
        "pdfplumber-synthetic-anchored-table",
        "synthetic Wells statement",
        (AnchoredPage(1, "table", (10.0, 10.0, 100.0, 20.0), (10.0, 20.0, 30.0, 40.0, 60.0, 80.0, 100.0)),),
        tuple(
            AnchoredRow(1, index + 1, (10.0, 20.0 + index, 100.0, 21.0 + index), cells)
            for index, cells in enumerate(raw)
        ),
        False,
    )
    text = page_lines(
        SOURCE,
        [
            "January 31, 2026 Page 1 of 1\n"
            "Statement period activity summary Account number: 1234567890\n"
            "Beginning balance on 1/1 $100.00\n"
            "Ending balance on 1/31 $90.00"
        ],
        extraction_library="pdfplumber-bounded-simple-v1",
    )
    return table, text


def test_wells_personal_continuation_and_printed_chain() -> None:
    output = from_wells_personal(DEFINITION, *evidence())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert (account.opening.minor, account.closing.minor) == (10000, 9000)
    assert [(row.date.iso, row.amount.minor, row.description.text) for row in account.rows] == [
        ("2026-01-05", 2000, "Deposit continued"),
        ("2026-01-10", -3000, "Withdrawal"),
    ]
    assert len(account.rows[0].fragments) == 2
    assert account.rows[0].description.provenance == "derived"
    assert account.rows[1].description.provenance == "observed"
    assert [item.code for item in output.payload.dispositions] == ["table_terminator", "unresolved_after_stop"]
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True


def test_unresolved_prefix_or_wrong_printed_balance_refuses() -> None:
    with pytest.raises(WellsPersonalError, match="printed_running_mismatch"):
        from_wells_personal(DEFINITION, *evidence({0: ("1/5", "", "Deposit", "$20.00", "", "$121.00")}))
    with pytest.raises(WellsPersonalError, match="unresolved_before_stop"):
        from_wells_personal(DEFINITION, *evidence({0: ("date?", "", "Deposit", "$20.00", "", "$120.00")}))
