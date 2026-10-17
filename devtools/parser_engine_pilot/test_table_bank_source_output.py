"""Five-column bank tables retain observed running balances and all raw rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_anchored_table import (
    ENGINE_VERSION as TABLE_VERSION,
)
from parsetrail.core.v2_anchored_table import (
    AnchoredPage,
    AnchoredRow,
    AnchoredTableEvidence,
)
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_table_bank_source_output import TableBankError, from_anchored_bank

DEFINITION = Path(__file__).with_name("lendingclub-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic-bank"


def evidence(changes: dict[int, tuple[str, str, str, str, str]] | None = None):
    raw = [
        ("01/01", "Balance Forward", "", "", "$100.00"),
        ("01/05", "Interest Paid", "", "$10.00", "$110.00"),
        ("01/10", "Withdrawal", "$20.00-", "", "$90.00"),
        ("", "Unclassified", "", "$999.00", ""),
        ("", "", "", "", ""),
    ]
    for index, replacement in (changes or {}).items():
        raw[index] = replacement
    table = AnchoredTableEvidence(
        1,
        hashlib.sha256(SOURCE).hexdigest(),
        hashlib.sha256(DEFINITION).hexdigest(),
        TABLE_VERSION,
        "pdfplumber-synthetic-anchored-table",
        "synthetic bank statement",
        (AnchoredPage(1, "table", (10.0, 10.0, 100.0, 20.0), (10.0, 20.0, 40.0, 60.0, 80.0, 100.0)),),
        tuple(
            AnchoredRow(1, index + 1, (10.0, 20.0 + index, 100.0, 21.0 + index), cells)
            for index, cells in enumerate(raw)
        ),
        False,
    )
    text = page_lines(
        SOURCE,
        [
            "Statement Begin Date: 01/01/2026\n"
            "Statement End Date: 01/31/2026\n"
            "Account Number: 1234567890\n"
            "Balance + Deposits + Paid - Withdrawals - Charge = Balance\n"
            "$100.00 $0.00 $10.00 $20.00 $0.00 $90.00"
        ],
        extraction_library="pdfplumber-bounded-simple-v1",
    )
    return table, text


def test_table_bank_printed_chain_and_raw_dispositions() -> None:
    output = from_anchored_bank(DEFINITION, *evidence())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert account.source_identity_form == "full"
    assert (account.opening.minor, account.closing.minor) == (10000, 9000)
    assert [(row.date.iso, row.amount.minor, row.running_balance.minor) for row in account.rows] == [
        ("2026-01-05", 1000, 11000),
        ("2026-01-10", -2000, 9000),
    ]
    assert [item.code for item in output.payload.dispositions] == [
        "balance_forward",
        "unclassified_monetary_table_row",
        "blank_table_row",
    ]
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True


def test_wrong_running_balance_or_missing_activity_refuses() -> None:
    with pytest.raises(TableBankError, match="printed_running_mismatch"):
        from_anchored_bank(DEFINITION, *evidence({1: ("01/05", "Interest Paid", "", "$10.00", "$111.00")}))
    with pytest.raises(TableBankError, match="unresolved_dated_table_row"):
        from_anchored_bank(DEFINITION, *evidence({1: ("01/05/26", "Interest Paid", "", "$10.00", "$110.00")}))


def test_declaration_rejects_executable_extension() -> None:
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(ValueError, match="invalid_definition"):
        from_anchored_bank(json.dumps(raw).encode(), *evidence())
