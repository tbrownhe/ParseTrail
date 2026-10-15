"""One read-only entry point builds strict CSV and bounded PDF evidence."""

from pathlib import Path

import pytest

from devtools.parser_engine_pilot.citi_layout import DEFINITION_BYTES
from devtools.parser_engine_pilot.source_pipeline import SourcePipelineError, build_source_evidence
from devtools.parser_engine_pilot.test_bounded_citi import sample_table_pdf

CSV_DEFINITION = Path(__file__).parents[1] / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
CSV = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
CHASE_DEFINITION = Path(__file__).with_name("chase-card-pilot-definition.json").read_bytes()
HAPPEN_DEFINITION = Path(__file__).with_name("happen-savings-pilot-definition.json").read_bytes()
LENDINGCLUB_DEFINITION = Path(__file__).with_name("lendingclub-savings-pilot-definition.json").read_bytes()
WELLS_DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json").read_bytes()
FIDELITY_HSA_DEFINITION = Path(__file__).with_name("fidelity-hsa-summary-pilot-definition.json").read_bytes()
YAMAHA_DEFINITION = Path(__file__).with_name("yamaha-card-pilot-definition.json").read_bytes()
CAPITAL_ONE_DEFINITION = Path(__file__).with_name("capital-one-loan-pilot-definition.json").read_bytes()


def test_csv_build_is_strict_and_keeps_raw_cells() -> None:
    output = build_source_evidence(CSV, CSV_DEFINITION.read_bytes(), suffix=".csv")
    assert output.payload.kind == "activity_export"
    assert output.payload.rows[0].amount.raw == "-$4.00"
    assert output.payload.rows[0].fragments[0].location.kind == "csv_row"
    assert output.payload.coverage_verified is False


def test_pdf_requires_exact_pilot_definition_and_recent_layout() -> None:
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), DEFINITION_BYTES + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), DEFINITION_BYTES, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), CHASE_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), CHASE_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), HAPPEN_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), HAPPEN_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), LENDINGCLUB_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), LENDINGCLUB_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), WELLS_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), WELLS_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), FIDELITY_HSA_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), FIDELITY_HSA_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), YAMAHA_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), YAMAHA_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), CAPITAL_ONE_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), CAPITAL_ONE_DEFINITION, suffix=".pdf")


def test_source_or_definition_failure_has_no_output_or_profile_write(tmp_path: Path) -> None:
    with pytest.raises(SourcePipelineError, match="unsupported_source_kind"):
        build_source_evidence(CSV, CSV_DEFINITION.read_bytes(), suffix=".xlsx")
    with pytest.raises(SourcePipelineError, match="definition_size"):
        build_source_evidence(CSV, b"", suffix=".csv")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(CSV + b"garbled", CSV_DEFINITION.read_bytes(), suffix=".csv")
    assert list(tmp_path.iterdir()) == []
