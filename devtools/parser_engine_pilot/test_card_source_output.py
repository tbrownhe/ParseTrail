"""Card pilot keeps source locations and uncertainty in the shared envelope."""

from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.card_lines import parse_card_lines
from devtools.parser_engine_pilot.card_source_output import from_card
from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.test_card_lines import pages

DEFINITION = Path(__file__).with_name("chase-card-pilot-definition.json").read_bytes()


def test_card_statement_round_trips_with_printed_and_derived_provenance() -> None:
    lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    output = from_card(parse_card_lines(DEFINITION, lines), lines)
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.kind == "statement"
    assert output.payload.accounts[0].source_identity_form == "last_four"
    assert output.payload.accounts[0].opening.minor == -2500
    assert output.payload.accounts[0].rows[0].date.provenance == "derived"
    assert output.payload.accounts[0].rows[0].fragments[0].raw_values[0].startswith("03/15")
    assert output.payload.dispositions[0].code == "dated_auxiliary_uninterpreted"
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is False


def test_card_adapter_refuses_changed_source_lines() -> None:
    lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    pilot = parse_card_lines(DEFINITION, lines)
    changed = page_lines(
        b"%PDF-synthetic",
        [*pages()[:-1], pages()[-1].replace("PRIOR-DAY", "ALTERED")],
        extraction_library="synthetic-pdf-1",
    )
    with pytest.raises(ValueError, match="card_row_source_mismatch"):
        from_card(pilot, changed)
