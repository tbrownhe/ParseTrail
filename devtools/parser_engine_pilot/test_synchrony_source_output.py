"""Single-date card rows preserve source dates and reject partial capture."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_anchored_table import (
    ENGINE_VERSION as TABLE_ENGINE_VERSION,
)
from parsetrail.core.v2_anchored_table import (
    AnchoredPage,
    AnchoredRow,
    AnchoredTableDefinition,
    AnchoredTableError,
    AnchoredTableEvidence,
)
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_synchrony_source_output import SynchronySourceError, from_synchrony_table

DEFINITION = Path(__file__).with_name("synchrony-table-pilot-definition.json").read_bytes()
SOURCE = b"%PDF-synthetic"
RAW_ROWS = (
    AnchoredRow(1, 1, (10.0, 50.0, 90.0, 60.0), ("12/31", "REF", "Prior purchase", "$10.00")),
    AnchoredRow(1, 2, (10.0, 60.0, 90.0, 70.0), ("", "", "Item detail", "")),
    AnchoredRow(1, 3, (10.0, 70.0, 90.0, 80.0), ("", "", "Total Interest Charged", "$0.00")),
)


def channels(rows=RAW_ROWS):
    text = page_lines(
        SOURCE,
        [
            "Account Number ending in 1234\n"
            "Previous Balance as of 01/01/2026 $100.00\n"
            "New Balance as of 01/31/2026 $110.00\n"
            "12/31 REF Prior purchase $10.00\n"
            "02/15/2026 for online and phone payments.\n"
            "01/31/26 New Balance $110.00\n"
        ],
        extraction_library="pdfplumber-bounded-simple-v1",
    )
    table = AnchoredTableEvidence(
        1,
        hashlib.sha256(SOURCE).hexdigest(),
        hashlib.sha256(DEFINITION).hexdigest(),
        TABLE_ENGINE_VERSION,
        "pdfplumber-test-anchored-table",
        "synthetic",
        (AnchoredPage(1, "table", (10.0, 40.0, 90.0, 50.0), (10.0, 25.0, 40.0, 75.0, 90.0)),),
        rows,
        False,
    )
    return table, text


def test_single_date_card_keeps_earlier_date_without_posting_claim(tmp_path: Path) -> None:
    output = from_synchrony_table(DEFINITION, *channels())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert (account.opening.minor, account.closing.minor) == (-10000, -11000)
    assert output.payload.independent_balance_verified is True
    assert output.payload.capture_verified is False
    assert len(account.rows) == 1
    assert account.rows[0].date.iso == "2025-12-31"
    assert account.rows[0].date_role == "activity_date"
    assert account.rows[0].transaction_date is None
    assert account.rows[0].amount.minor == -1000
    assert len(output.payload.dispositions) == 4
    assert any(item.code == "interest_fee_summary_row" for item in output.payload.dispositions)
    assert len(account.rows[0].fragments) == 2
    assert account.rows[0].fragments[-1].channel == "simple_text_line"
    assert len(account.rows[0].fragments) + len(output.payload.dispositions) == len(RAW_ROWS) + 3
    profile = tmp_path / "synchrony.db"
    with V2ProfileStore.create(profile) as store:
        assert store.import_source(SOURCE, DEFINITION, output, suffix=".pdf")
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(output.source_sha256).evidence == output


def test_single_date_card_refuses_unexplained_date_or_balance_change() -> None:
    invalid = replace(RAW_ROWS[1], raw_cells=("01/15 unknown", "", "Item detail", ""))
    with pytest.raises(SynchronySourceError, match="unresolved_dated_table_row"):
        from_synchrony_table(DEFINITION, *channels((RAW_ROWS[0], invalid, RAW_ROWS[2])))
    changed = replace(RAW_ROWS[0], raw_cells=("12/31", "REF", "Prior purchase", "$11.00"))
    table, text = channels((changed, *RAW_ROWS[1:]))
    text = replace(
        text,
        lines=tuple(
            replace(
                line, raw=line.raw.replace("$10.00", "$11.00"), normalized=line.normalized.replace("$10.00", "$11.00")
            )
            if line.normalized.startswith("12/31 REF")
            else line
            for line in text.lines
        ),
    )
    with pytest.raises(SynchronySourceError, match="printed_card_balance_equation"):
        from_synchrony_table(DEFINITION, table, text)


def test_single_date_card_refuses_missing_or_changed_text_copy() -> None:
    table, text = channels()
    missing = replace(text, lines=tuple(line for line in text.lines if not line.normalized.startswith("12/31 REF")))
    with pytest.raises(SynchronySourceError, match="missing_dated_text_copy"):
        from_synchrony_table(DEFINITION, table, missing)
    changed = replace(
        text,
        lines=tuple(
            replace(line, normalized=line.normalized.replace("Prior purchase", "Other description"))
            if line.normalized.startswith("12/31 REF")
            else line
            for line in text.lines
        ),
    )
    with pytest.raises(SynchronySourceError, match="dated_text_description_mismatch"):
        from_synchrony_table(DEFINITION, table, changed)


def test_unknown_monetary_table_line_refuses() -> None:
    changed = replace(RAW_ROWS[2], raw_cells=("", "", "Unfamiliar charge", "$1.00"))
    with pytest.raises(SynchronySourceError, match="unclassified_monetary_table_row"):
        from_synchrony_table(DEFINITION, *channels((*RAW_ROWS[:2], changed)))


def test_monetary_text_dispositions_are_declared_and_unknown_line_refuses() -> None:
    table, text = channels()

    def replace_summary(raw: str):
        return replace(
            text,
            lines=tuple(
                replace(line, raw=raw, normalized=raw) if line.normalized.startswith("01/31/26 New Balance") else line
                for line in text.lines
            ),
        )

    output = from_synchrony_table(DEFINITION, table, replace_summary("Rewards Earned YTD $3.00"))
    assert any(item.code == "rewards_summary" for item in output.payload.dispositions)
    with pytest.raises(SynchronySourceError, match="unclassified_monetary_text_line"):
        from_synchrony_table(DEFINITION, table, replace_summary("Unexpected charge $3.00"))


def test_synchrony_declaration_schema_is_closed() -> None:
    saved = json.loads(Path(__file__).with_name("anchored-table-declaration-schema-v1.json").read_text())
    assert saved == AnchoredTableDefinition.model_json_schema()
    revised = json.loads(DEFINITION)
    revised["python"] = "import os"
    with pytest.raises(AnchoredTableError, match="invalid_definition"):
        from_synchrony_table(json.dumps(revised).encode(), *channels())
    revised = json.loads(DEFINITION)
    revised["statement"]["monetary_text_dispositions"][0]["python"] = "exec"
    with pytest.raises(AnchoredTableError, match="invalid_definition"):
        from_synchrony_table(json.dumps(revised).encode(), *channels())
