"""One read-only entry point builds strict CSV and bounded PDF evidence."""

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore

from devtools.parser_engine_pilot.catalog_admission import admit_pilot_definition
from devtools.parser_engine_pilot.citi_layout import DEFINITION_BYTES
from devtools.parser_engine_pilot.source_pipeline import SourcePipelineError, build_source_evidence
from devtools.parser_engine_pilot.test_bounded_citi import sample_table_pdf

CSV_DEFINITION = Path(__file__).parents[1] / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
CSV = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
HAPPEN_DEFINITION = Path(__file__).with_name("happen-savings-pilot-definition.json").read_bytes()
MOHELA_DEFINITION = Path(__file__).with_name("mohela-pilot-definition.json").read_bytes()
MOHELA_ACCOUNT_HISTORY_DEFINITION = Path(__file__).with_name("mohela-account-history-definition.json").read_bytes()
PDF_DEFINITIONS = tuple(
    path.read_bytes()
    for path in sorted(Path(__file__).parent.glob("*definition.json"))
    if admit_pilot_definition(path.read_bytes()).suffix == ".pdf"
)


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


def test_mohela_account_history_keeps_components_without_inventing_loan_identity(tmp_path: Path) -> None:
    source = (
        b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
        b"Date,Description,Principal,Interest,Fees,Total,\n"
        b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
    )
    output = build_source_evidence(source, MOHELA_ACCOUNT_HISTORY_DEFINITION, suffix=".csv")
    assert output.payload.kind == "activity_export"
    assert output.payload.coverage_verified is False
    assert len(output.payload.rows) == 1
    row = output.payload.rows[0]
    assert row.source_account is None and row.source_account_form is None
    assert row.running_balance is None
    assert row.amount.minor == -10000
    assert [(part.role, part.amount.minor) for part in row.components] == [
        ("principal", -8000),
        ("interest", -2000),
        ("fee", 0),
    ]
    profile = tmp_path / "mohela-history.db"
    with V2ProfileStore.create(profile) as store:
        assert store.import_source(source, MOHELA_ACCOUNT_HISTORY_DEFINITION, output, suffix=".csv")
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(output.source_sha256).evidence == output


@pytest.mark.parametrize("definition", PDF_DEFINITIONS)
def test_valid_pdf_definition_reaches_source_checks(definition: bytes) -> None:
    assert len(PDF_DEFINITIONS) == 21
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), definition, suffix=".pdf")


def test_recent_citi_stays_pinned_until_handler_uses_supplied_declaration() -> None:
    with pytest.raises(SourcePipelineError, match="unsupported_definition_revision"):
        build_source_evidence(sample_table_pdf(), DEFINITION_BYTES + b" ", suffix=".pdf")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(sample_table_pdf(), DEFINITION_BYTES, suffix=".pdf")


def test_changed_valid_pdf_revision_uses_supplied_declaration(monkeypatch) -> None:
    import json

    from devtools.parser_engine_pilot import source_pipeline
    from devtools.parser_engine_pilot.bounded_pdf_text import DecodedPDFText
    from devtools.parser_engine_pilot.test_savings_lines import pages

    raw = json.loads(HAPPEN_DEFINITION)
    raw["revision"] = "2"
    changed = json.dumps(raw).encode("utf-8")
    monkeypatch.setattr(
        source_pipeline,
        "decode_pdf",
        lambda _source, *, cancelled=None: DecodedPDFText(tuple(pages()), ()),
    )
    output = build_source_evidence(b"%PDF-synthetic", changed, suffix=".pdf")
    assert output.definition_revision == "2"
    assert (
        output.definition_sha256
        != build_source_evidence(b"%PDF-synthetic", HAPPEN_DEFINITION, suffix=".pdf").definition_sha256
    )
    assert len(output.payload.accounts[0].rows) == 1


def test_source_or_definition_failure_has_no_output_or_profile_write(tmp_path: Path) -> None:
    with pytest.raises(SourcePipelineError, match="unsupported_source_kind"):
        build_source_evidence(CSV, CSV_DEFINITION.read_bytes(), suffix=".xlsx")
    with pytest.raises(SourcePipelineError, match="definition_size"):
        build_source_evidence(CSV, b"", suffix=".csv")
    with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
        build_source_evidence(CSV + b"garbled", CSV_DEFINITION.read_bytes(), suffix=".csv")
    assert list(tmp_path.iterdir()) == []
