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

TAIL_DEFINITION = Path(__file__).with_name("lendingclub-table-pilot-definition.json").read_bytes()
BASE_RULE = json.loads(TAIL_DEFINITION)
BASE_RULE["statement"].pop("monetary_table_tail")
DEFINITION = json.dumps(BASE_RULE).encode()
SOURCE = b"%PDF-synthetic-bank"


def evidence(
    changes: dict[int, tuple[str, str, str, str, str]] | None = None,
    *,
    definition: bytes = DEFINITION,
    tail: bool = False,
):
    raw = [
        ("01/01", "Balance Forward", "", "", "$100.00"),
        ("01/05", "Interest Paid", "", "$10.00", "$110.00"),
        ("01/10", "Withdrawal", "$20.00-", "", "$90.00"),
        ("", "Unclassified", "", "$999.00", ""),
        ("", "", "", "", ""),
    ]
    if tail:
        raw[3:4] = [
            ("ious Sta", "tement Date: 12/31/2025", "Average Statem", "ent Balance: $100.00", ""),
            ("", "$100.00 $0.00", "$10.00", "$20.00", "$0.00 $90.00"),
            ("rest Ear", "ned $10.00", "", "", ""),
            ("", "Savings 1234567890 $90.00", "4.00%", "$10.00 $0.00", ""),
        ]
    for index, replacement in (changes or {}).items():
        raw[index] = replacement
    table = AnchoredTableEvidence(
        1,
        hashlib.sha256(SOURCE).hexdigest(),
        hashlib.sha256(definition).hexdigest(),
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
            "$100.00 $0.00 $10.00 $20.00 $0.00 $90.00\n"
            "Previous Statement Date: 12/31/2025 Average Statement Balance: $100.00\n"
            "Interest Earned $10.00\n"
            "Savings 1234567890 $90.00 4.00% $10.00 $0.00"
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


def test_declared_monetary_tail_requires_matching_table_fragments_and_text() -> None:
    output = from_anchored_bank(TAIL_DEFINITION, *evidence(definition=TAIL_DEFINITION, tail=True))
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert [item.code for item in output.payload.dispositions] == [
        "balance_forward",
        "prior_period_average_balance",
        "summary_values_tail",
        "interest_earned_summary",
        "savings_rate_disclosure",
        "blank_table_row",
        "prior_period_average_balance_text",
        "summary_values_tail_text",
        "interest_earned_summary_text",
        "savings_rate_disclosure_text",
    ]
    assert output.payload.dispositions[-1].location.kind == "pdf_line"
    assert output.payload.dispositions[-1].raw_values[0].startswith("Savings")
    with pytest.raises(TableBankError, match="monetary_table_tail_shape"):
        from_anchored_bank(
            TAIL_DEFINITION,
            *evidence(
                {3: ("Unknown", "tement Date: 12/31/2025", "Average Statem", "ent Balance: $100.00", "")},
                definition=TAIL_DEFINITION,
                tail=True,
            ),
        )
    with pytest.raises(TableBankError, match="monetary_table_tail_count"):
        from_anchored_bank(TAIL_DEFINITION, *evidence(definition=TAIL_DEFINITION))
    with pytest.raises(TableBankError, match="activity_after_monetary_table_tail"):
        from_anchored_bank(
            TAIL_DEFINITION,
            *evidence(
                {7: ("01/20", "Late activity", "$1.00-", "", "$89.00")},
                definition=TAIL_DEFINITION,
                tail=True,
            ),
        )


def test_declaration_rejects_executable_extension() -> None:
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(ValueError, match="invalid_definition"):
        from_anchored_bank(json.dumps(raw).encode(), *evidence())
    raw = json.loads(TAIL_DEFINITION)
    raw["statement"]["monetary_table_tail"][0]["python"] = "exec"
    with pytest.raises(ValueError, match="invalid_definition"):
        from_anchored_bank(json.dumps(raw).encode(), *evidence())
