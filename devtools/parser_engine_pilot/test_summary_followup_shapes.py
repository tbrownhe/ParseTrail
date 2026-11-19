"""Invented labelled-column, merged-note and actually empty cash-table shapes."""

import hashlib
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_hsa_cash_lines import HsaCashError, parse_cash_section
from parsetrail.core.v2_hsa_cash_source_output import from_hsa_cash
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_investment_summary_lines import parse_investment_summary
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_single_column_summary import parse_plan_label_summary, parse_single_column_summary

from devtools.parser_engine_pilot.test_investment_summary_lines import DEFINITION as FIDELITY
from devtools.parser_engine_pilot.test_investment_summary_lines import lines as fidelity_lines
from devtools.parser_engine_pilot.test_plan_label_summary import DEFINITION as PLAN
from devtools.parser_engine_pilot.test_plan_label_summary import lines as plan_lines
from devtools.parser_engine_pilot.test_single_column_summary import DEFINITION as VANGUARD
from devtools.parser_engine_pilot.test_summary_context_roles import chart_source_lines

HSA = Path(__file__).with_name("hsa-cash-pilot-definition.json").read_bytes()
MERGED_NOTE = (
    "Contact Information * Reflects appreciation or depreciation of your holdings due to price changes, transactions"
)


def source_lines(source):
    return page_lines(b"synthetic-summary-shapes", ["\n".join(source)], extraction_library="synthetic-pdf-1")


def paired_column_lines():
    source = chart_source_lines()
    source[4] = "Current Period Year to Date"
    source[6] += " $300.00"
    source[7] = "Your contributions $50.00 $200.00 $1,500"
    source[9] += " $75.00"
    source[10] = "Market gain/loss -$5.00 $15.00 $500"
    source[11] += " $0.00"
    source[12] += " $590.00"
    return source


def test_complete_paired_column_retains_each_distinct_value_without_activity():
    output = parse_single_column_summary(VANGUARD, source_lines(paired_column_lines()))
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.engine_version == "single-column-summary-pilot-3"
    ytd = [item for item in output.payload.dispositions if item.code == "year_to_date_column"]
    assert [(item.location.line, item.raw_values) for item in ytd] == [
        (8, ("$200.00",)),
        (10, ("$75.00",)),
        (11, ("$15.00",)),
        (12, ("$0.00",)),
        (7, ("$300.00",)),
        (13, ("$590.00",)),
    ]
    assert not any(item.code == "summary_extra_column" for item in output.payload.dispositions)
    account = output.payload.accounts[0]
    assert [row.amount.minor for row in account.rows] == [5000, 2500, -500, 0]
    assert (account.opening.minor, account.closing.minor) == (10000, 17000)
    assert all(row.row_role == "period_summary" for row in account.rows)
    assert not output.payload.capture_verified and output.payload.independent_balance_verified


@pytest.mark.parametrize(
    "index,replacement",
    [
        (4, "Statement period"),
        (4, "Current Period Unknown Column"),
        (9, "Employer contributions $25.00"),
        (9, "Employer contributions $25.00 $75.00 $9.00"),
        (9, "Employer contributions $25.00 $75.00 01/20/2026"),
        (9, "Employer contributions $25.00 $75.00 $"),
    ],
)
def test_incomplete_unlabelled_or_unknown_column_is_not_upgraded(index, replacement):
    source = paired_column_lines()
    source[index] = replacement
    output = parse_single_column_summary(VANGUARD, source_lines(source))
    assert not any(item.code == "year_to_date_column" for item in output.payload.dispositions)
    assert any(item.code == "summary_extra_column" for item in output.payload.dispositions)


def test_duplicate_column_header_is_ambiguous():
    source = paired_column_lines()
    source[2] = "Current Period Year to Date"
    output = parse_single_column_summary(VANGUARD, source_lines(source))
    assert not any(item.code == "year_to_date_column" for item in output.payload.dispositions)


def test_exact_merged_contact_note_keeps_alternative_valuation_separate():
    output = parse_investment_summary(FIDELITY, fidelity_lines({13: MERGED_NOTE}))
    assert output.engine_version == "investment-summary-lines-pilot-3"
    assert output.payload.accounts[0].closing.minor == 14500
    assert output.payload.dispositions[-1].code == "summary_explanatory_note"
    assert output.payload.dispositions[-1].raw_values == (MERGED_NOTE,)


@pytest.mark.parametrize("tail", [" $7.00", " 01/20/2026", " 7.00", " $"])
def test_merged_note_with_unknown_money_or_date_stays_unresolved(tail):
    output = parse_investment_summary(FIDELITY, fidelity_lines({13: MERGED_NOTE + tail}))
    assert output.payload.dispositions[-1].code == "summary_window_tail_unclassified"


def empty_cash_lines():
    return [
        "Period:11/01/26through11/30/26",
        "AccountNumber:SYNTHETIC-EMPTY",
        "StatementPrintDate:12/01/26",
        "Depositor Account",
        "Date DescriptionofTransaction (Withdrawal) Balance",
        "BeginningBalance $10.00",
        "EndingBalance $10.00",
        "InterestRateScheduleEffective:11/01/26",
        "Interest AverageDaily Interest",
        "BalanceTier",
        "Rate Balance Earned YeartoDate",
        "Period",
        "$0.00-$2,000.00 0.010% $0.00 Total",
        "$2,000.00-$5,000.00 0.010% TotalOverdraftFees $0.00 $0.00",
        "$5,000.00-$10,000.00 0.010%",
        "TotalNon-SufficientFundsFees $0.00 $0.00",
        "Over$10,000 0.010%",
        "TotalReturnDepositItemFees $0.00 $0.00",
        "Total $0.00",
        "FundsarecurrentlyheldatSyntheticBank Total $0.00 $0.00",
    ]


def cash_output(source):
    lines = source_lines(source)
    return from_hsa_cash(parse_cash_section(HSA, lines), lines)


def test_empty_cash_table_proof_is_located_and_never_certifies_full_capture():
    output = cash_output(empty_cash_lines())
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.engine_version == "hsa-cash-lines-pilot-3"
    proof = [item for item in output.payload.dispositions if item.code == "hsa_empty_cash_table"]
    assert len(proof) == 1 and (proof[0].location.page, proof[0].location.line) == (1, 5)
    assert proof[0].raw_values == ("Date DescriptionofTransaction (Withdrawal) Balance",)
    assert not output.payload.accounts[0].rows
    assert output.payload.accounts[0].opening.minor == output.payload.accounts[0].closing.minor == 1000
    assert not output.payload.capture_verified and output.payload.independent_balance_verified
    assert not any(item.code == "hsa_exterior_unclassified" for item in output.payload.dispositions)


@pytest.mark.parametrize(
    "index,replacement",
    [
        (3, "Other Account"),
        (4, "Date Description Balance"),
        (4, "Date DescriptionofTransaction (Withdrawal) Balance $9.00"),
        (5, "Unexplained line\nBeginningBalance $10.00"),
        (6, "\nEndingBalance $10.00"),
    ],
)
def test_equal_endpoints_without_complete_adjacent_empty_table_do_not_qualify(index, replacement):
    source = empty_cash_lines()
    source[index] = replacement
    assert not any(item.code == "hsa_empty_cash_table" for item in cash_output(source).payload.dispositions)


@pytest.mark.parametrize(
    "extra",
    [
        "Unknown fee $9.00",
        "01/20/2026 unknown activity",
        "Total $0.00 $9.00",
        "TotalOverdraftFees $0.00 $0.00 $9.00",
        "InterestRateScheduleEffective:11/01/26 $9.00",
        "StatementPrintDate:12/01/26 01/20/2026",
        "Unknown $",
        "Unknown date 2026-11-20",
        "Unknown date November 20, 2026",
        "Unknown date NOVEMBER 20, 2026",
        "Unknown date Nov 20, 2026",
        "Unknown date 20 November 2026",
        "Unknown date 20Nov2026",
        "Unknown date 2026 Nov 20",
        "Unknown date November 20",
        "Unknown date 20 Nov",
        "Unknown date 11-20-2026",
        "Unknown NOVEMBER 20, 2026 StatementPrintDate:12/01/26",
        "Unknown date 11/20",
        "InterestRateScheduleEffective:99/99/26",
        "StatementPrintDate:99/99/26",
        "TotalOverdraftFees $1.00 $1.00",
    ],
)
def test_empty_table_keeps_exterior_money_date_and_truncated_money_unresolved(extra):
    source = empty_cash_lines() + [extra, extra]
    output = cash_output(source)
    unresolved = [item for item in output.payload.dispositions if item.code == "hsa_exterior_unclassified"]
    assert [item.raw_values for item in unresolved] == [(extra,), (extra,)]
    assert [item.location.line for item in unresolved] == [len(source) - 1, len(source)]


@pytest.mark.parametrize("extra", ["Total $9.00", "FundsarecurrentlyheldatSyntheticBank Total $0.00 $0.00"])
def test_bare_total_outside_the_complete_rate_frame_stays_unresolved(extra):
    output = cash_output(empty_cash_lines() + [extra])
    assert output.payload.dispositions[-1].code == "hsa_exterior_unclassified"


@pytest.mark.parametrize("change", ["missing_header", "duplicate_header", "unknown_money", "unknown_date", "truncated"])
def test_rate_totals_need_the_complete_unique_uninterrupted_frame(change):
    source = empty_cash_lines()
    if change == "missing_header":
        source[9] = "Unknown column labels"
    elif change == "duplicate_header":
        source.append("Interest AverageDaily Interest")
    elif change == "truncated":
        source.pop(14)
    else:
        source.insert(14, "Unknown $9.00" if change == "unknown_money" else "11/20/2026 missing activity")
    output = cash_output(source)
    for item in output.payload.dispositions:
        if item.raw_values[0].startswith(("Total $", "Fundsarecurrentlyheldat")):
            assert item.code == "hsa_exterior_unclassified"


def test_empty_source_cancel_and_bad_closing_refuse():
    with pytest.raises(HsaCashError, match="cancelled"):
        parse_cash_section(HSA, source_lines(empty_cash_lines()), cancelled=lambda: True)
    source = empty_cash_lines()
    source[6] = "EndingBalance $11.00"
    with pytest.raises(HsaCashError, match="printed_closing_mismatch"):
        cash_output(source)


def test_empty_table_can_retain_a_nonzero_year_to_date_fee_without_inventing_activity():
    output = cash_output(empty_cash_lines() + ["TotalOverdraftFees $0.00 $9.00"])
    assert output.payload.dispositions[-1].code == "hsa_cash_rate_fee_information"
    assert output.payload.dispositions[-1].raw_values == ("TotalOverdraftFees $0.00 $9.00",)
    assert not output.payload.accounts[0].rows


def no_activity_warning(output):
    return next(item for item in evidence_import_warnings(output) if item.code == "no_activity_captured")


def test_actual_empty_table_warning_is_informational_and_keeps_capture_limit():
    output = cash_output(empty_cash_lines())
    before = output.model_dump_json()
    assert no_activity_warning(output).classification == "informational"
    assert not any(item.classification == "requires_review" for item in evidence_import_warnings(output))
    assert any(item.code == "source_capture_unverified" for item in evidence_import_warnings(output))
    assert output.model_dump_json() == before


def test_prefixed_spaced_cash_headers_keep_raw_proof_and_empty_warning():
    source = empty_cash_lines()
    source[3] = "_    Depositor    Account"
    source[4] = "_    Date   DescriptionofTransaction    (Withdrawal)    Balance"
    output = cash_output(source)
    proof = next(item for item in output.payload.dispositions if item.code == "hsa_empty_cash_table")
    assert proof.raw_values == (source[4],)
    assert no_activity_warning(output).classification == "informational"


def test_prefixed_cash_header_with_money_suffix_cannot_prove_empty_table():
    source = empty_cash_lines()
    source[4] = "_    Date   DescriptionofTransaction    (Withdrawal)    Balance $9.00"
    output = cash_output(source)
    assert not any(item.code == "hsa_empty_cash_table" for item in output.payload.dispositions)
    assert no_activity_warning(output).classification == "requires_review"
    assert any(item.code == "hsa_exterior_unclassified" for item in output.payload.dispositions)


@pytest.mark.parametrize(
    "change",
    [
        "missing_proof",
        "duplicate_proof",
        "wrong_header",
        "wrong_header_location",
        "old_engine",
        "wrong_parser",
        "unequal_endpoint",
        "unknown_endpoint",
        "missing_endpoint",
        "unlocated_endpoint",
        "wrong_scope",
        "unknown_period",
        "reversed_period",
        "second_account",
    ],
)
def test_empty_warning_guard_does_not_upgrade_unproved_evidence(change):
    output = cash_output(empty_cash_lines())
    payload = output.payload
    account = payload.accounts[0]
    proof = next(item for item in payload.dispositions if item.code == "hsa_empty_cash_table")
    if change == "missing_proof":
        payload = payload.model_copy(
            update={"dispositions": tuple(item for item in payload.dispositions if item != proof)}
        )
    elif change == "duplicate_proof":
        payload = payload.model_copy(update={"dispositions": (*payload.dispositions, proof)})
    elif change in {"wrong_header", "wrong_header_location"}:
        changed = (
            proof.model_copy(update={"raw_values": ("Date Description Balance",)})
            if change == "wrong_header"
            else proof.model_copy(update={"location": proof.location.model_copy(update={"line": 1})})
        )
        payload = payload.model_copy(
            update={"dispositions": tuple(changed if item == proof else item for item in payload.dispositions)}
        )
    elif change == "old_engine":
        output = output.model_copy(update={"engine_version": "hsa-cash-lines-pilot-1"})
    elif change == "wrong_parser":
        output = output.model_copy(update={"parser_id": "synthetic_other_cash"})
    elif change in {"unequal_endpoint", "unknown_endpoint", "missing_endpoint", "unlocated_endpoint"}:
        closing = account.closing
        if change == "unequal_endpoint":
            closing = closing.model_copy(update={"minor": 1100})
        elif change == "unknown_endpoint":
            closing = closing.model_copy(update={"minor": None, "provenance": "unknown"})
        elif change == "unlocated_endpoint":
            closing = closing.model_copy(update={"locations": ()})
        else:
            closing = None
        account = account.model_copy(update={"closing": closing})
    elif change == "wrong_scope":
        account = account.model_copy(update={"balance_scope": "account_total"})
    elif change == "unknown_period":
        payload = payload.model_copy(
            update={"start": payload.start.model_copy(update={"iso": None, "provenance": "unknown"})}
        )
    elif change == "reversed_period":
        payload = payload.model_copy(update={"start": payload.end, "end": payload.start})
    elif change == "second_account":
        payload = payload.model_copy(
            update={"accounts": (account, account.model_copy(update={"source_identity": "SECOND"}))}
        )
    if change != "second_account":
        payload = payload.model_copy(update={"accounts": (account,)})
    output = output.model_copy(update={"payload": payload})
    assert no_activity_warning(output).classification == "requires_review"


@pytest.mark.parametrize("extra", ["Unknown $9.00", "11/20/2026 missing row", "Unknown 2026-11-20"])
def test_empty_table_warning_never_waives_exterior_review(extra):
    output = cash_output(empty_cash_lines() + [extra])
    warnings = evidence_import_warnings(output)
    assert no_activity_warning(output).classification == "informational"
    assert any(
        item.code == "hsa_exterior_unclassified" and item.classification == "requires_review" for item in warnings
    )


def test_nonempty_cash_with_empty_proof_cannot_be_described_as_empty():
    source = empty_cash_lines()
    source.insert(6, "11/20/2026 Known zero adjustment 0.00 10.00")
    output = cash_output(source)
    assert not any(item.code == "hsa_empty_cash_table" for item in output.payload.dispositions)
    assert not any(item.code == "no_activity_captured" for item in evidence_import_warnings(output))


def test_paired_summary_and_exact_merged_note_have_only_informational_warnings():
    for output in (
        parse_single_column_summary(VANGUARD, source_lines(paired_column_lines())),
        parse_investment_summary(FIDELITY, fidelity_lines({13: MERGED_NOTE})),
    ):
        assert not any(item.classification == "requires_review" for item in evidence_import_warnings(output))
        assert any(item.code == "source_capture_unverified" for item in evidence_import_warnings(output))


@pytest.mark.parametrize(
    "variant,digest",
    [
        ("printed", "cdc14c8509b4c1a27f969dc5ee040048cdb683a9cdd1d6aab36557414c3f2f1f"),
        ("headerless", "80be08336bfa52f403b505ad844fec0787826d1dc56347f1f7a171d586cf1c58"),
        ("browser", "cdc14c8509b4c1a27f969dc5ee040048cdb683a9cdd1d6aab36557414c3f2f1f"),
    ],
)
def test_plan_summary_entire_synthetic_envelope_matches_baseline(variant, digest):
    # Captured from baseline 32e365c using these existing public synthetic cases.
    # The shared module's Vanguard policy revision must not rewrite plan IDs or
    # any other retained plan-label evidence field.
    output = parse_plan_label_summary(PLAN, plan_lines(variant=variant))
    assert hashlib.sha256(output.model_dump_json().encode()).hexdigest() == digest
