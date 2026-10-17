"""HSA cash evidence stays scoped and retains unclassified window lines."""

from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_hsa_cash_lines import parse_cash_section
from parsetrail.core.v2_hsa_cash_source_output import from_hsa_cash
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import V2ProfileStore

from devtools.parser_engine_pilot.test_hsa_cash_lines import pages

DEFINITION = Path(__file__).with_name("hsa-cash-pilot-definition.json").read_bytes()


def test_cash_scope_unknown_description_and_unclassified_lines_round_trip(tmp_path: Path) -> None:
    source = b"%PDF-synthetic"
    lines = page_lines(source, pages(), extraction_library="synthetic-pdf-1")
    output = from_hsa_cash(parse_cash_section(DEFINITION, lines), lines)
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    account = output.payload.accounts[0]
    assert account.balance_scope == "cash_component"
    assert account.source_identity_form == "opaque"
    assert (account.opening.minor, account.closing.minor) == (100000, 110010)
    assert len(account.rows) == 3
    assert account.rows[-1].description.provenance == "unknown"
    assert account.rows[-1].description.text is None
    assert [item.code for item in output.payload.dispositions] == [
        "cash_window_rate_table",
        "cash_window_heading",
        "cash_window_heading",
    ]
    assert len(output.payload.dispositions) == 3
    assert output.payload.independent_balance_verified is True
    assert output.payload.capture_verified is False
    profile = tmp_path / "hsa-pilot.db"
    with V2ProfileStore.create(profile) as store:
        assert store.import_source(source, DEFINITION, output, suffix=".pdf")
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(output.source_sha256).evidence == output


def test_hsa_adapter_refuses_changed_source_line() -> None:
    lines = page_lines(b"%PDF-synthetic", pages(), extraction_library="synthetic-pdf-1")
    pilot = parse_cash_section(DEFINITION, lines)
    changed = pages()
    changed[0] = changed[0].replace("EmployeeContribution", "ChangedContribution")
    with pytest.raises(ValueError, match="hsa_row_source_mismatch"):
        from_hsa_cash(
            pilot,
            page_lines(b"%PDF-synthetic", changed, extraction_library="synthetic-pdf-1"),
        )
