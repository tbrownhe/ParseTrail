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


def empty_cash_pages(*, alternate=True, closed="08/31/26"):
    labels = ["Rate Balance Earned"] if alternate else ["Rate Balance Earned YeartoDate", "Period"]
    first_rows = (
        ["$0.00-$99.99 0.05% $0.00 YeartoDate", "$100.00-$999.99 0.05% Period Total"]
        if alternate
        else ["$0.00-$99.99 0.05% $0.00 Total", "$100.00-$999.99 0.05% TotalOverdraftFees $0.00 $0.00"]
    )
    return [
        "\n".join(
            [
                "HealthSavingsAccount(Closed",
                f"{closed})",
                "Period:08/01/26through08/31/26",
                "AccountNumber:SYNTHETIC-EMPTY",
                "Depositor Account",
                "Date DescriptionofTransaction (Withdrawal) Balance",
                "BeginningBalance $0.00",
                "EndingBalance $0.00",
                "InterestRateScheduleEffective:08/01/26",
                "Interest AverageDaily Interest",
                "BalanceTier",
                *labels,
                *first_rows,
                "$1,000.00-$9,999.99 0.05%",
                "TotalNon-SufficientFundsFees $0.00 $5.00",
                "Over$10,000 0.05%",
                "TotalReturnDepositItemFees $0.00 $0.00",
                "Total $0.00",
                "FundsarecurrentlyheldatSynthetic Total $0.00 $0.00",
            ]
        )
    ]


def empty_cash_output(text):
    source = b"%PDF-synthetic-empty"
    lines = page_lines(source, text, extraction_library="pdfplumber-bounded-simple-v1")
    return from_hsa_cash(parse_cash_section(DEFINITION, lines), lines)


@pytest.mark.parametrize("alternate", [False, True])
@pytest.mark.parametrize("closed", ["08/31/26", "09/30/26"])
def test_complete_empty_rate_frames_and_closure_metadata_keep_financial_facts(alternate, closed):
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    output = empty_cash_output(empty_cash_pages(alternate=alternate, closed=closed))
    assert output.engine_version == "hsa-cash-lines-pilot-3"
    account = output.payload.accounts[0]
    assert account.rows == () and account.opening.minor == account.closing.minor == 0
    assert output.payload.start.iso == "2026-08-01" and output.payload.end.iso == "2026-08-31"
    assert output.payload.independent_balance_verified and not output.payload.capture_verified
    closure = next(d for d in output.payload.dispositions if d.location.line == 1)
    assert closure.code == "hsa_cash_statement_dates"
    assert closure.raw_values == ("HealthSavingsAccount(Closed", f"{closed})")
    assert closure.location.end_line == 2
    assert not [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]


@pytest.mark.parametrize(
    "change",
    [
        "missing_header",
        "missing_fee",
        "bad_rate_date",
        "extra_rate_money",
        "nonzero_fee",
        "extra_fee_money",
        "invalid_closed_date",
        "unframed_closed_date",
        "extra_closed_money",
        "duplicate_closed",
        "foreign_currency",
    ],
)
def test_empty_cash_context_needs_complete_unambiguous_frames(change):
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    text = empty_cash_pages()[0]
    if change == "missing_header":
        text = text.replace("Interest AverageDaily Interest\n", "")
    elif change == "missing_fee":
        text = text.replace("TotalNon-SufficientFundsFees $0.00 $5.00\n", "")
    elif change == "bad_rate_date":
        text = text.replace("InterestRateScheduleEffective:08/01/26", "InterestRateScheduleEffective:02/30/26")
    elif change == "extra_rate_money":
        text = text.replace("0.05% Period Total", "0.05% Period Total Unknown $9.00")
    elif change == "nonzero_fee":
        text = text.replace("TotalNon-SufficientFundsFees $0.00", "TotalNon-SufficientFundsFees $1.00")
    elif change == "extra_fee_money":
        text = text.replace("TotalReturnDepositItemFees $0.00 $0.00", "TotalReturnDepositItemFees $0.00 $0.00 $9.00")
    elif change == "invalid_closed_date":
        text = text.replace("08/31/26)", "02/30/26)")
    elif change == "unframed_closed_date":
        text = text.replace("HealthSavingsAccount(Closed\n", "")
    elif change == "extra_closed_money":
        text = text.replace("08/31/26)", "08/31/26) Unknown $9.00")
    elif change == "duplicate_closed":
        text += "\nHealthSavingsAccount(Closed\n09/30/26)"
    else:
        text += "\nUnknown €3"
    output = empty_cash_output([text])
    assert output.payload.accounts[0].rows == ()
    assert any(w.classification == "requires_review" for w in evidence_import_warnings(output))


def test_empty_cash_old_engine_qualification_remains_and_future_engine_does_not_inherit_it():
    from parsetrail.core.v2_import_warnings import evidence_import_warnings

    output = empty_cash_output(empty_cash_pages())
    for engine, expected in (("hsa-cash-lines-pilot-2", "informational"), ("future-engine", "requires_review")):
        changed = output.model_copy(update={"engine_version": engine})
        warning = next(w for w in evidence_import_warnings(changed) if w.code == "no_activity_captured")
        assert warning.classification == expected
