"""One read-only entry point builds strict CSV and bounded PDF evidence."""

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore

from devtools.parser_engine_pilot.citi_layout import DEFINITION_BYTES
from devtools.parser_engine_pilot.source_pipeline import SourcePipelineError, build_source_evidence
from devtools.parser_engine_pilot.test_bounded_citi import sample_table_pdf

CSV_DEFINITION = Path(__file__).parents[1] / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
CSV = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
CHASE_DEFINITION = Path(__file__).with_name("chase-card-pilot-definition.json").read_bytes()
HAPPEN_DEFINITION = Path(__file__).with_name("happen-savings-pilot-definition.json").read_bytes()
LENDINGCLUB_DEFINITION = Path(__file__).with_name("lendingclub-savings-pilot-definition.json").read_bytes()
LENDINGCLUB_TABLE_DEFINITION = Path(__file__).with_name("lendingclub-table-pilot-definition.json").read_bytes()
WELLS_PERSONAL_TABLE_DEFINITION = Path(__file__).with_name("wells-personal-table-pilot-definition.json").read_bytes()
TRANSAMERICA_DEFINITION = Path(__file__).with_name("transamerica-summary-pilot-definition.json").read_bytes()
WELLS_LOAN_DEFINITION = Path(__file__).with_name("wells-loan-pilot-definition.json").read_bytes()
WELLS_DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json").read_bytes()
FIDELITY_HSA_DEFINITION = Path(__file__).with_name("fidelity-hsa-summary-pilot-definition.json").read_bytes()
YAMAHA_DEFINITION = Path(__file__).with_name("yamaha-card-pilot-definition.json").read_bytes()
CAPITAL_ONE_DEFINITION = Path(__file__).with_name("capital-one-loan-pilot-definition.json").read_bytes()
USBANK_DEFINITION = Path(__file__).with_name("usbank-rei-card-pilot-definition.json").read_bytes()
VANGUARD_DEFINITION = Path(__file__).with_name("vanguard-summary-pilot-definition.json").read_bytes()
FIDELITY_401K_DEFINITION = Path(__file__).with_name("fidelity-401k-summary-pilot-definition.json").read_bytes()
MOHELA_DEFINITION = Path(__file__).with_name("mohela-pilot-definition.json").read_bytes()
HSA_CASH_DEFINITION = Path(__file__).with_name("hsa-cash-pilot-definition.json").read_bytes()
SYNCHRONY_DEFINITION = Path(__file__).with_name("synchrony-table-pilot-definition.json").read_bytes()


def test_csv_build_is_strict_and_keeps_raw_cells() -> None:
    output = build_source_evidence(CSV, CSV_DEFINITION.read_bytes(), suffix=".csv")
    assert output.payload.kind == "activity_export"
    assert output.payload.rows[0].amount.raw == "-$4.00"
    assert output.payload.rows[0].fragments[0].location.kind == "csv_row"
    assert output.payload.coverage_verified is False


def test_detailed_mohela_export_keeps_loan_components_and_unknown_principal(tmp_path: Path) -> None:
    source = (
        b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
        b"Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue,\n"
        b"10/01/2026,123-1 Loan A,Payment,-$80.00,-$20.00,$0.00,-$100.00,$900.00,\n"
        b"10/02/2026,456-2 Loan B,Payment,-$50.00,$0.00,$0.00,-$50.00,Unavailable,\n"
    )
    output = build_source_evidence(source, MOHELA_DEFINITION, suffix=".csv")
    assert output.parser_id == "mohela_detailed_export"
    assert output.payload.kind == "activity_export"
    assert output.payload.coverage_verified is False
    assert output.payload.rows[0].source_account == "123-1"
    assert output.payload.rows[1].source_account == "456-2"
    assert output.payload.rows[1].running_balance.provenance == "unknown"
    assert output.payload.rows[1].running_balance.minor is None
    assert [(part.role, part.amount.minor) for part in output.payload.rows[0].components] == [
        ("principal", -8000),
        ("interest", -2000),
        ("fee", 0),
    ]
    profile = tmp_path / "mohela.db"
    with V2ProfileStore.create(profile) as store:
        assert store.import_source(source, MOHELA_DEFINITION, output, suffix=".csv")
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(output.source_sha256).evidence == output


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
        build_source_evidence(sample_table_pdf(), LENDINGCLUB_TABLE_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), LENDINGCLUB_TABLE_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), WELLS_PERSONAL_TABLE_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), WELLS_PERSONAL_TABLE_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), TRANSAMERICA_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), TRANSAMERICA_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), WELLS_LOAN_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), WELLS_LOAN_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), WELLS_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), WELLS_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), FIDELITY_HSA_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), FIDELITY_HSA_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), HSA_CASH_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), HSA_CASH_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), SYNCHRONY_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), SYNCHRONY_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), YAMAHA_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), YAMAHA_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), CAPITAL_ONE_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), CAPITAL_ONE_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), USBANK_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), USBANK_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), VANGUARD_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), VANGUARD_DEFINITION, suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), FIDELITY_401K_DEFINITION + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), FIDELITY_401K_DEFINITION, suffix=".pdf")


def test_source_or_definition_failure_has_no_output_or_profile_write(tmp_path: Path) -> None:
    with pytest.raises(SourcePipelineError, match="unsupported_source_kind"):
        build_source_evidence(CSV, CSV_DEFINITION.read_bytes(), suffix=".xlsx")
    with pytest.raises(SourcePipelineError, match="definition_size"):
        build_source_evidence(CSV, b"", suffix=".csv")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(CSV + b"garbled", CSV_DEFINITION.read_bytes(), suffix=".csv")
    assert list(tmp_path.iterdir()) == []
