"""Citi output keeps both source channels and refuses changed printed money."""

from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.channel_occurrences import Candidate
from devtools.parser_engine_pilot.citi_channels import CitiResolution, ResolvedRow
from devtools.parser_engine_pilot.citi_evidence import CitiEvidence
from devtools.parser_engine_pilot.citi_layout import DEFINITION_SHA256, EVIDENCE_ENGINE_VERSION
from devtools.parser_engine_pilot.citi_source_dispositions import DatedLineDisposition
from devtools.parser_engine_pilot.citi_source_output import CitiOutputError, from_citi
from devtools.parser_engine_pilot.citi_statement_header import CitiStatementHeader, PrintedBalance
from devtools.parser_engine_pilot.citi_table import CitiTableEvidence, CitiTablePage, CitiTableRow
from devtools.parser_engine_pilot.citi_table_candidates import CitiTableCandidates
from devtools.parser_engine_pilot.table_continuations import JoinedTableRow, RawTableRow


def sample() -> CitiEvidence:
    raw_period = "Billing Period: 01/01/26-01/31/26"
    cells = ("01/02", "01/02", "SHOP", "$10.00")
    day = date(2026, 1, 2)
    table = Candidate(day, day, -1000, "SHOP", "table", 1, 1)
    text = Candidate(day, day, -1000, "SHOP", "text", 1, 1)
    return CitiEvidence(
        source_sha256="a" * 64,
        definition_sha256=DEFINITION_SHA256,
        engine_version=EVIDENCE_ENGINE_VERSION,
        simple_text_pages=("01/02 01/02 SHOP $10.00",),
        header=CitiStatementHeader(
            date(2026, 1, 1),
            date(2026, 1, 31),
            (0, len(raw_period)),
            "1234",
            ((1, 1),),
            PrintedBalance(1, 1, "$100.00", -10000),
            PrintedBalance(1, 1, "$110.00", -11000),
        ),
        table_evidence=CitiTableEvidence(
            1,
            "a" * 64,
            "test",
            "test-pdfplumber",
            raw_period,
            (CitiTablePage(1, "table", (0.0, 0.0, 10.0, 10.0), (0.0, 2.0, 4.0, 6.0, 10.0), False),),
            (CitiTableRow(1, 1, (0.0, 0.0, 10.0, 10.0), None, cells, "table"),),
            False,
            False,
        ),
        table_candidates=CitiTableCandidates(
            (table,),
            (JoinedTableRow((RawTableRow(1, 1, cells),), "SHOP", "$10.00"),),
        ),
        text_candidates=(text,),
        fee_candidates=(),
        resolution=CitiResolution((ResolvedRow(table, (table, text), "table"),), (), 0, True),
        dated_lines=(DatedLineDisposition(1, 1, 1, "simple_text"),),
        money_lines=(),
        dated_start_row_bijection=True,
    )


def test_statement_output_roundtrip_preserves_source_copies() -> None:
    output = from_citi(sample())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    assert account.opening.minor == -10000 and account.closing.minor == -11000
    row = account.rows[0]
    assert row.amount.raw == "$10.00" and row.amount.minor == -1000
    assert row.date.provenance == "derived"
    assert [fragment.channel for fragment in row.fragments] == ["table", "text"]
    assert row.fragments[0].raw_values == ("01/02", "01/02", "SHOP", "$10.00")
    assert [item.code for item in output.payload.dispositions] == ["dated_simple_text"]


def test_changed_printed_amount_is_refused() -> None:
    source = sample()
    changed = replace(
        source,
        table_evidence=replace(
            source.table_evidence,
            rows=(replace(source.table_evidence.rows[0], raw_cells=("01/02", "01/02", "SHOP", "$11.00")),),
        ),
        table_candidates=replace(
            source.table_candidates,
            groups=(JoinedTableRow((RawTableRow(1, 1, ("01/02", "01/02", "SHOP", "$11.00")),), "SHOP", "$11.00"),),
        ),
    )
    with pytest.raises(CitiOutputError, match="source_amount_mismatch"):
        from_citi(changed)
