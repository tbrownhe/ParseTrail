"""Older Citi layout date starts and bounded continuation remain located."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_legacy_citi_lines import (
    LegacyCitiDefinition,
    LegacyCitiError,
    parse_legacy_citi,
)
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence

from devtools.parser_engine_pilot.audit_legacy_citi_money import audit as audit_monetary_archive

DEFINITION = Path(__file__).with_name("legacy-citi-pilot-definition.json").read_bytes()


def lines(changes: dict[int, str] | None = None, extra: tuple[str, ...] = (), *, source: bytes = b"%PDF-synthetic"):
    source_lines = [
        "www.citicards.com",
        "Account number ending in: 1234",
        "Billing Period: 01/01/26-01/31/26",
        "Previous balance $100.00",
        "New balance $90.00",
        "Date Date Description Amount",
        "01/05 AUTOPAY AUTO-PMT -$20.00",
        "01/10 01/09 FOREIGN PURCHASE",
        "            LOCATION $10.00",
    ]
    for index, replacement in (changes or {}).items():
        source_lines[index] = replacement
    source_lines.extend(extra)
    return page_lines(
        source,
        ["\n".join(source_lines)],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )


def parse(changes: dict[int, str] | None = None, extra: tuple[str, ...] = ()):
    return parse_legacy_citi(DEFINITION, lines(changes, extra))


def test_bounded_continuation_and_liability_equation() -> None:
    output = parse()
    assert SourceEvidence.model_validate_json(output.model_dump_json()) == output
    assert output.payload.capture_verified is False
    assert output.payload.independent_balance_verified is True
    account = output.payload.accounts[0]
    assert account.source_identity == "1234" and account.source_identity_form == "last_four"
    assert (account.opening.minor, account.closing.minor) == (-10000, -9000)
    assert [(r.date.iso, r.amount.minor, r.description.text) for r in account.rows] == [
        ("2026-01-05", 2000, "AUTOPAY AUTO-PMT"),
        ("2026-01-09", -1000, "FOREIGN PURCHASE LOCATION"),
    ]
    assert account.rows[0].date.provenance == "assumed"
    assert account.rows[0].transaction_date.iso == "2026-01-05"
    assert account.rows[1].date.provenance == "derived"
    assert account.rows[1].transaction_date.iso == "2026-01-10"
    assert len(account.rows[1].fragments) == 2
    assert account.rows[1].date.locations[0].end_line == 9


def test_missing_amount_or_changed_balance_refuses() -> None:
    with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
        parse({8: "            LOCATION"})
    with pytest.raises(LegacyCitiError, match="printed_card_balance_equation"):
        parse({4: "New balance $91.00"})
    with pytest.raises(LegacyCitiError, match="missing_or_ambiguous_account"):
        parse({1: "Account number absent"})


def test_parallel_column_and_repeated_balance_are_located() -> None:
    output = parse(
        {
            2: "Billing Period:01/01/26-01/31/26 01/05-01/31",
            6: "01/05 AUTOPAY AUTO-PMT -$20.00 No Late Fee: $10.00",
        },
        ("Please pay New balance $90.00 promptly",),
    )
    assert [row.amount.minor for row in output.payload.accounts[0].rows] == [2000, -1000]
    assert [item.code for item in output.payload.dispositions] == [
        "parallel_no_late_fee",
        "repeated_closing_balance",
    ]
    with pytest.raises(LegacyCitiError, match="ambiguous_parallel_money"):
        parse({6: "01/05 AUTOPAY AUTO-PMT -$20.00 Unknown $10.00"})


def test_unclassified_money_lines_are_preserved_without_becoming_rows() -> None:
    output = parse(extra=("Total fees charged in 2026 $1.23", "Offer balance $2.34", "A stray $ sign"))
    assert len(output.payload.accounts[0].rows) == 2
    money = [
        item
        for item in output.payload.dispositions
        if item.code.endswith("monetary_line") or item.code == "annual_fee_total"
    ]
    assert [(item.location.page, item.location.line, item.code) for item in money] == [
        (1, 10, "annual_fee_total"),
        (1, 11, "unclassified_monetary_line"),
    ]
    assert output.payload.capture_verified is False


def test_overlapping_literal_labels_stay_unclassified() -> None:
    raw = json.loads(DEFINITION)
    raw["monetary_line_rules"].append({"code": "fee_period_total", "all_of": ["Total fees charged in 2026"]})
    output = parse_legacy_citi(
        json.dumps(raw).encode(),
        lines(extra=("Total fees charged in 2026 $1.23",)),
    )
    assert output.payload.dispositions[-1].code == "unclassified_monetary_line"


def test_zero_activity_requires_printed_equal_balances_and_table_header() -> None:
    output = parse({4: "New balance $100.00", 6: "", 7: "", 8: ""})
    assert output.payload.accounts[0].rows == ()
    assert any(
        w.code == "no_activity_captured" and w.classification == "requires_review"
        for w in evidence_import_warnings(output)
    )
    with pytest.raises(LegacyCitiError, match="printed_card_balance_equation"):
        parse({6: "", 7: "", 8: ""})
    with pytest.raises(LegacyCitiError, match="missing_activity_rows"):
        parse({4: "New balance $100.00", 5: "", 6: "", 7: "", 8: ""})


@pytest.mark.parametrize("raw", ["01/20", "01/20/2026", "01/20/2026 Unresolved activity"])
def test_unmatched_date_start_never_proves_an_empty_table(raw):
    with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
        parse({4: "New balance $100.00", 6: raw, 7: "", 8: ""})


def test_empty_table_with_unexplained_bare_amount_still_needs_review():
    output = parse({4: "New balance $100.00", 6: "Unknown amount 9.00", 7: "", 8: ""})
    assert any(
        w.code == "no_activity_captured" and w.classification == "requires_review"
        for w in evidence_import_warnings(output)
    )


def test_definition_schema_and_unknown_field() -> None:
    assert LegacyCitiDefinition.model_validate_json(DEFINITION).operation == "layout_date_start_continuation_v1"
    schema = json.loads(Path(__file__).with_name("legacy-citi-declaration-schema-v2.json").read_text())
    assert schema == LegacyCitiDefinition.model_json_schema()
    raw = json.loads(DEFINITION)
    raw["python_module"] = "arbitrary"
    with pytest.raises(LegacyCitiError, match="invalid_definition"):
        parse_legacy_citi(json.dumps(raw).encode(), lines())
    nested = json.loads(DEFINITION)
    nested["monetary_line_rules"][0]["regex"] = ".*"
    with pytest.raises(LegacyCitiError, match="invalid_definition"):
        parse_legacy_citi(json.dumps(nested).encode(), lines())


def test_monetary_audit_refuses_an_empty_archive(tmp_path: Path) -> None:
    assert audit_monetary_archive(tmp_path)["failure_reasons"] == {"no_matching_sources": 1}


def test_finite_summary_and_interest_detail_roles_preserve_source() -> None:
    first = lines(
        extra=(
            "Payments -$20.00",
            "Purchases +$10.00",
            "Minimum payment due $5.00",
            "New balance as of 01/31/26: $90.00",
            "Credit limit $500.00",
        )
    )
    second = "\n".join(
        (
            "Interest charged",
            "Interest: $0.00",
            "Explanation",
            "Total interest charged in this billing period $0.00",
            "Standard Purch 12.34% $90.00 (D) $0.00",
            "Standard Adv 24.99% (V) $0.00 (D) $0.00",
        )
    )
    source = page_lines(
        b"synthetic", ["\n".join(line.raw for line in first.lines), second], extraction_library=first.extraction_library
    )
    before = source.lines
    output = parse_legacy_citi(DEFINITION, source)
    assert [d.code for d in output.payload.dispositions] == [
        "citi_account_summary",
        "citi_account_summary",
        "citi_payment_information",
        "citi_payment_information",
        "citi_credit_terms",
        "citi_interest_charge_detail",
        "interest_period_total",
        "citi_apr_information",
        "citi_apr_information",
    ]
    assert source.lines == before
    for disposition in output.payload.dispositions:
        line = next(
            line
            for line in source.lines
            if (line.page, line.line) == (disposition.location.page, disposition.location.line)
        )
        assert disposition.raw_values == (line.raw,)
    assert len(output.payload.accounts[0].rows) == 2
    assert output.payload.capture_verified is False
    assert output.engine_version == "legacy-citi-lines-pilot-4"
    assert not [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]


@pytest.mark.parametrize(
    "raw",
    [
        "Purchases +$10.00 Unknown $9.00",
        "Unknown $9.00",
        "Credit limit $500.00 Unknown $1.00",
        "New balance $90.00 Unknown $1.00",
        "New balance $90.00 Unknown $1",
        "Please pay New balance $90.00 Unknown $1.00",
        "Standard Purch 12.34% $90.00 (D) $0.00 Unknown $1.00",
        "Total interest charged in this billing period $0.00 Unknown $1.00",
        "Total fees charged in 2026 $0.00 Unknown $1.00",
        "Total fees charged in 2026 $0.00 Unknown $1",
        "$0.00",
    ],
)
def test_unknown_or_parallel_money_keeps_review_gate(raw: str) -> None:
    output = parse(extra=(raw,))
    warnings = [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]
    assert [w.code for w in warnings] == ["unclassified_monetary_line"]
    assert output.payload.dispositions[-1].raw_values == (raw,)
    assert len(output.payload.accounts[0].rows) == 2
    assert output.payload.independent_balance_verified and not output.payload.capture_verified


def test_summary_label_does_not_rescue_unresolved_dated_input() -> None:
    with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
        parse(extra=("01/20 Interest charged",))


@pytest.mark.parametrize(
    "raw",
    [
        "Mystery $3",
        "Purchases +$10",
        "Total interest charged in this billing period $0",
        "Total fees charged in 2026 $0.001",
    ],
)
def test_standalone_incomplete_money_remains_reviewable(raw) -> None:
    output = parse(extra=(raw,))
    warning = next(w for w in evidence_import_warnings(output) if w.code == "unclassified_monetary_line")
    assert warning.classification == "requires_review" and warning.occurrence_count == 1
    assert output.payload.dispositions[-1].raw_values == (raw,)
    assert len(output.payload.accounts[0].rows) == 2


def test_truncated_parallel_dollar_amount_refuses() -> None:
    with pytest.raises(LegacyCitiError, match="ambiguous_parallel_money"):
        parse({6: "01/05 AUTOPAY AUTO-PMT -$20.00 Mystery $3"})


def test_whole_dollar_disclosures_preserve_all_lines_without_becoming_activity() -> None:
    raw = (
        "your balance. For example: Credit Limit $5,000",
        "Includes $1,000 cash advance limit",
        "Available credit $4,000",
        "charges using this card balance shown on the paying an estimated Available credit $4,000",
        "and each month you pay... statement in about... total of... Includes $1,000 available for cash advances",
        "Only the minimum payment 12 year(s) $800",
        "$400",
        "$30 3 year(s)",
        "(Savings= $100)",
    )
    output = parse(extra=raw)
    assert [d.code for d in output.payload.dispositions] == [
        "citi_credit_terms",
        "citi_credit_terms",
        "citi_credit_terms",
        "citi_credit_terms",
        "citi_credit_terms",
        "citi_repayment_example",
        "unclassified_monetary_line",
        "citi_repayment_example",
        "citi_repayment_example",
    ]
    assert tuple(d.raw_values[0] for d in output.payload.dispositions) == raw
    assert len(output.payload.accounts[0].rows) == 2
    assert not output.payload.capture_verified
    assert (
        next(w for w in evidence_import_warnings(output) if w.code == "unclassified_monetary_line").occurrence_count
        == 1
    )


@pytest.mark.parametrize(
    "raw",
    [
        "Credit limit $500 Unknown $3",
        "Credit limit $500.0",
        "Includes $500 cash advance limit unknown",
        "Only the minimum payment 0 year(s) $800",
        "Only the minimum payment 100 year(s) $800",
        "Only the minimum payment 12 year(s) $800 Unknown $3",
        "$30 3 year(s)",
        "(Savings=$100)",
        "your balance. For example: Credit Limit $5,000",
        "charges using this card balance shown on the paying an estimated Available credit $4,000",
        "and each month you pay... statement in about... total of... Includes $1,000 available for cash advances",
        "Total interest charged in this billing period $0",
    ],
)
def test_disclosure_whole_dollars_do_not_weaken_unknown_or_context_refusal(raw: str) -> None:
    output = parse(extra=(raw,))
    assert output.payload.dispositions[-1].code == "unclassified_monetary_line"
    assert output.payload.dispositions[-1].raw_values == (raw,)


def test_dated_whole_dollar_disclosure_is_not_rescued_by_disclosure_rules() -> None:
    with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
        parse(extra=("01/20 Credit limit $500",))


def test_kerning_spaces_and_finite_parallel_summary_context_preserve_amounts():
    raw = (
        "Payments - $ 20.00",
        "Credits - $0.00",
        "Available revolving credit $ 400",
        "Includes $100 available for cash advances",
        "Minimum Payment Warning: I f you make only the minimum payment each Purchases +$ 10.00",
        "period, you will pay more in interest and it will take you longer to pay off Cash advances $0.00",
        "your balance. For example: Fees $0.00",
        "For information about credit counseling services, call 800-555-0100. Revolving Credit limit $500",
        "Enrolled in AutoPay. Minimum payment due $5.00",
    )
    output = parse(extra=raw)
    assert not [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]
    assert tuple(d.raw_values[0] for d in output.payload.dispositions) == raw
    assert [row.amount.minor for row in output.payload.accounts[0].rows] == [2000, -1000]


def test_detached_repayment_total_requires_complete_headings_and_savings_equation():
    raw = (
        "If you make no additional charges using this card",
        "and each month you pay... statement in about... total of...",
        "Only the minimum payment 12 year(s) $1,800",
        "Credit limit $500",
        "$1,700",
        "$30 3 year(s) Includes $100 cash advance limit",
        "(Savings = $100)",
    )
    output = parse(extra=raw)
    assert not [w for w in evidence_import_warnings(output) if w.classification == "requires_review"]
    assert [d.code for d in output.payload.dispositions].count("citi_repayment_example") == 4
    for replacement in ("$1,701", "$1,700 unknown", "$1,700 $9.00"):
        changed = list(raw)
        changed[4] = replacement
        assert any(
            w.code == "unclassified_monetary_line" for w in evidence_import_warnings(parse(extra=tuple(changed)))
        )


def test_exact_conditional_late_fee_and_minimum_interest_prose_is_not_activity():
    first = lines()
    clause = "using a $35 late fee (if your minimum payment due was less than $35, we used"
    for raw, expected in (
        (clause, "citi_credit_terms"),
        ("Minimum interest charge. If we charge interest, it will be at least $0.50.", "citi_credit_terms"),
        (clause + " Unknown $9.00", "unclassified_monetary_line"),
        (clause.replace("$35 late fee", "$35.0 late fee"), "unclassified_monetary_line"),
    ):
        source = page_lines(
            b"synthetic",
            ["\n".join(line.raw for line in first.lines), raw],
            extraction_library=first.extraction_library,
        )
        output = parse_legacy_citi(DEFINITION, source)
        assert output.payload.dispositions[-1].code == expected
        assert len(output.payload.accounts[0].rows) == 2


@pytest.mark.parametrize(
    "raw",
    [
        "Unknown adjustment 9.00 is greater than $25. (Note: None of these is final if your purchase rate is based on",
        "01/20/2026 your balance is greater than $25. (Note: None of these is final if your purchase rate is based on",
    ],
)
def test_unknown_decimal_or_date_near_minimum_payment_is_not_legal_prose(raw):
    first = lines()
    source = page_lines(
        b"synthetic",
        ["\n".join(line.raw for line in first.lines), "minimum payment\n" + raw],
        extraction_library=first.extraction_library,
    )
    if raw.startswith("01/20/2026"):
        with pytest.raises(LegacyCitiError, match="unresolved_dated_start"):
            parse_legacy_citi(DEFINITION, source)
    else:
        output = parse_legacy_citi(DEFINITION, source)
        assert output.payload.dispositions[-1].code == "unclassified_monetary_line"


def test_interest_detail_requires_its_section_and_total() -> None:
    first = lines()
    source = page_lines(
        b"synthetic",
        ["\n".join(line.raw for line in first.lines), "Interest: $0.00"],
        extraction_library=first.extraction_library,
    )
    output = parse_legacy_citi(DEFINITION, source)
    assert output.payload.dispositions[-1].code == "unclassified_monetary_line"


def test_interest_detail_before_heading_and_offer_apr_need_exact_context() -> None:
    first = lines()
    detail = ("Interest: $0.00", "Interest charged", "Total interest charged in this billing period $0.00")
    apr = (
        "Standard Purch 12.34% $90.00 (D) $0.00",
        "Example Offer 0.00% $10.00 (D) $0.00",
        "Standard Adv 24.99% (V) $0.00 (D) $0.00",
    )
    for second, expected in ((detail, "citi_interest_charge_detail"), (apr, "citi_apr_information")):
        source = page_lines(
            b"synthetic",
            ["\n".join(line.raw for line in first.lines), "\n".join(second)],
            extraction_library=first.extraction_library,
        )
        output = parse_legacy_citi(DEFINITION, source)
        assert all(d.code == expected or d.code == "interest_period_total" for d in output.payload.dispositions)
    for second in ((detail[0], detail[2]), (apr[1],), (apr[0], apr[1]), (apr[1], apr[2])):
        source = page_lines(
            b"synthetic",
            ["\n".join(line.raw for line in first.lines), "\n".join(second)],
            extraction_library=first.extraction_library,
        )
        output = parse_legacy_citi(DEFINITION, source)
        assert any(d.code == "unclassified_monetary_line" for d in output.payload.dispositions)


def test_real_bounded_legacy_decoder_keeps_roles_unknown_money_and_cancellation() -> None:
    from devtools.parser_engine_pilot.synthetic_family_sources import pdf_document, text_page

    raw = [line.raw for line in lines({5: "Date Description Amount"}).lines]
    raw.extend(("Payments -$20.00", "Mystery $3.00", "Mystery $3.00"))
    source = pdf_document((text_page(*raw),))
    before = source
    output = build_source_evidence(source, DEFINITION, suffix=".pdf")
    assert source == before
    assert output.payload.dispositions[-3].code == "citi_account_summary"
    unknown = [d for d in output.payload.dispositions if d.code == "unclassified_monetary_line"]
    assert len(unknown) == 2 and unknown[0].location != unknown[1].location
    assert all(d.raw_values[0].strip() == "Mystery $3.00" for d in unknown)
    assert (
        next(w for w in evidence_import_warnings(output) if w.code == "unclassified_monetary_line").occurrence_count
        == 2
    )
    assert not output.payload.capture_verified
    with pytest.raises(SourcePipelineError, match="cancelled"):
        build_source_evidence(source, DEFINITION, suffix=".pdf", cancelled=lambda: True)
    with pytest.raises(SourcePipelineError):
        build_source_evidence(source[:90], DEFINITION, suffix=".pdf")


def test_parallel_summary_terms_and_inline_repayment_total_have_finite_roles():
    raw = (
        "includes an overlimit amount of $7.00 and a",
        "past due amount of $8.00.",
        "Late Payment Warning: If we do not receive your minimum payment by the date Purchases +$10.00",
        "listed above, you may have to pay a late fee of up to $25 and your APRs may be Cash advances +$0.00",
        "increased up to the Penalty APR of 28.99%. Fees +$0.00",
        "charges using this card balance shown on the paying an estimated Revolving Credit limit $900",
        "If you make no additional charges using this card",
        "and each month you pay... statement in about... total of...",
        "Only the minimum payment 12 year(s) $900 Available Revolving credit $800",
        "$42 3 year(s) $700 Credit limit $900",
        "(Savings = $200)",
        "For information about credit counseling services, call 800-555-0100. Available credit $800",
    )
    output = parse(extra=raw)
    assert not [d for d in output.payload.dispositions if d.code == "unclassified_monetary_line"]
    assert len(output.payload.accounts[0].rows) == 2
    assert output.payload.capture_verified is False
    for index in (8, 9):
        changed = list(raw)
        changed[index] += " Unknown $9.00"
        assert any(d.code == "unclassified_monetary_line" for d in parse(extra=tuple(changed)).payload.dispositions)
    changed = list(raw)
    changed[9] = changed[9].replace("$700", "$701")
    assert any(d.code == "unclassified_monetary_line" for d in parse(extra=tuple(changed)).payload.dispositions)


def test_savings_sidebar_needs_complete_labels_column_and_arithmetic():
    base = "\n".join(line.raw for line in lines().lines)
    sidebar = (
        " " * 55 + "Citi Simplicity Lifetime Savings",
        " " * 60 + "Interest: $12.00",
        "Fees charged" + " " * 48 + "No Late Fee: $25.00",
        "Your Annual Percentage Rate (APR) is the annual interest rate on your account. CITI SIMPLICITY LIFETIME SAVINGS:",
        " " * 67 + "$37.00",
    )

    def output(second):
        return parse_legacy_citi(
            DEFINITION,
            page_lines(b"synthetic", [base, "\n".join(second)], extraction_library=lines().extraction_library),
        )

    evidence = output(sidebar)
    assert [d.code for d in evidence.payload.dispositions] == ["citi_savings_information"] * 3
    assert evidence.payload.dispositions[-1].location.line == 5
    assert evidence.payload.dispositions[-1].raw_values == (sidebar[-1],)
    for altered in (
        sidebar[:-1] + (" " * 67 + "$38.00",),
        sidebar[:-1] + ("$37.00",),
        sidebar[:-1] + (" " * 67 + "$37.00 Unknown $9",),
        sidebar[1:],
        sidebar + (" " * 67 + "$37.00",),
    ):
        assert any(d.code == "unclassified_monetary_line" for d in output(altered).payload.dispositions)


@pytest.mark.parametrize(
    "interest,fee,total",
    [
        ("$1000.00", "$25.00", "$1,025.00"),
        ("$25.00", "$1000.00", "$1,025.00"),
        ("$1,000.00", "$25.00", "$1025.00"),
        ("$90,000,000,000,000.00", "$25.00", "$90,000,000,000,025.00"),
    ],
)
def test_savings_sidebar_converter_refusal_preserves_unknown_source_lines(interest, fee, total):
    base = "\n".join(line.raw for line in lines().lines)
    sidebar = (
        " " * 55 + "Citi Simplicity Lifetime Savings",
        " " * 60 + f"Interest: {interest}",
        "Fees charged" + " " * 48 + f"No Late Fee: {fee}",
        "Your Annual Percentage Rate (APR) is the annual interest rate on your account. CITI SIMPLICITY LIFETIME SAVINGS:",
        " " * 67 + total,
    )
    output = parse_legacy_citi(
        DEFINITION, page_lines(b"synthetic", [base, "\n".join(sidebar)], extraction_library=lines().extraction_library)
    )
    assert [d.code for d in output.payload.dispositions] == ["unclassified_monetary_line"] * 3
    assert [d.raw_values for d in output.payload.dispositions] == [(sidebar[i],) for i in (1, 2, 4)]
    assert [d.location.line for d in output.payload.dispositions] == [2, 3, 5]
    assert len(output.payload.accounts[0].rows) == 2
    assert any(w.classification == "requires_review" for w in evidence_import_warnings(output))


def test_statutory_purchase_threshold_requires_exact_complete_parallel_prose():
    base = "\n".join(line.raw for line in lines().lines)
    prose = (
        "take the balance at the end of the previous day, add the interest on the previous "
        "your current mailing address, and the purchase price must have been more",
        "day’s balance and new charges, subtract new credits or payments, and make "
        "than $50. (Note: Neither of these is necessary if your purchase was based on",
        "adjustments. The Balance Subject to Interest Rate is the average of the daily "
        "an advertisement we mailed to you, or if we own the company that sold you",
    )
    for second, expected in (
        (prose, "citi_credit_terms"),
        (prose[1:], "unclassified_monetary_line"),
        ((prose[0], prose[1] + " Unknown $9.00", prose[2]), "unclassified_monetary_line"),
    ):
        output = parse_legacy_citi(
            DEFINITION,
            page_lines(b"synthetic", [base, "\n".join(second)], extraction_library=lines().extraction_library),
        )
        assert output.payload.dispositions[-1].code == expected
