"""Warning classes follow actual synthetic decoder evidence and scoped checks."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core.source_evidence import MoneyValue, PdfLine, SourceDisposition, StatementPayload
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_import_warnings import MAX_WARNING_LOCATIONS, evidence_import_warnings
from parsetrail.core.v2_loan_history_lines import LoanHistoryError, parse_loan_history
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest
from parsetrail.gui.v2_csv_import_preview import V2CsvImportPreview

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page
from devtools.parser_engine_pilot.test_loan_history_lines import DEFINITION as LOAN_DEFINITION
from devtools.parser_engine_pilot.test_loan_history_lines import lines as loan_lines

from .test_v2_catalog_import import DEFINITION, SOURCE, _verified_catalog

PILOT = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"


@pytest.fixture(scope="module")
def decoded():
    names = {
        "chase-card-pilot-definition.json",
        "happen-savings-pilot-definition.json",
        "wells-loan-pilot-definition.json",
        "capital-one-loan-pilot-definition.json",
        "recent-citi-pilot-definition.json",
    }
    return {
        case.definition_name: build_source_evidence(
            case.source, (PILOT / case.definition_name).read_bytes(), suffix=".pdf"
        )
        for case in family_sources()
        if case.definition_name in names
    }


def with_account(evidence, account):
    return evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(
                update={"accounts": (account,), "independent_balance_verified": False}
            )
        }
    )


def requires(evidence):
    return tuple(
        warning for warning in evidence_import_warnings(evidence) if warning.classification == "requires_review"
    )


def test_real_decoder_date_omissions_and_capture_limitations_are_informational(decoded):
    evidence = decoded["chase-card-pilot-definition.json"]
    warnings = evidence_import_warnings(evidence)
    assert not requires(evidence)
    dates = next(warning for warning in warnings if warning.code == "source_posting_date_assumed")
    assert dates.classification == "informational" and dates.occurrence_count == 2
    assert dates.locations[0].kind == "pdf_line"
    assert any(warning.code == "source_capture_unverified" for warning in warnings)
    assert evidence.payload.accounts[0].rows[0].date.provenance == "assumed"


def test_capital_single_printed_payment_keeps_unknown_opening_and_informational_balance_limit(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    before = evidence.model_dump_json()
    account = evidence.payload.accounts[0]
    row = account.rows[0]
    assert account.opening is None and account.closing.minor == 950000
    assert account.closing.raw == "$9,500.00" and account.closing.provenance == "observed"
    assert row.amount.minor == -22000 and row.amount.raw == "-$220.00"
    assert [(part.role, part.amount.minor, part.amount.raw) for part in row.components] == [
        ("principal", -20000, "-$200.00"),
        ("interest", -2000, "-$20.00"),
    ]
    assert not requires(evidence)
    warnings = evidence_import_warnings(evidence)
    balance = next(warning for warning in warnings if warning.code == "source_balance_check_unavailable")
    assert balance.classification == "informational"
    assert "Opening principal is not printed" in balance.message and "balance remains unverified" in balance.message
    assert balance.locations == account.closing.locations
    assert any(warning.code == "source_capture_unverified" for warning in warnings)
    assert evidence.payload.independent_balance_verified is False
    assert evidence.payload.capture_verified is False
    assert evidence.model_dump_json() == before


@pytest.mark.parametrize("closing", [None, "unknown", "derived"])
def test_capital_missing_or_unprinted_closing_still_requires_review(decoded, closing):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    if closing == "unknown":
        closing = MoneyValue(raw=None, minor=None, provenance="unknown", locations=account.closing.locations)
    elif closing == "derived":
        closing = MoneyValue(raw=None, minor=950000, provenance="derived", locations=account.closing.locations)
    changed = with_account(evidence, account.model_copy(update={"closing": closing}))
    warning = requires(changed)[0]
    assert warning.code == "source_balance_check_unavailable"
    assert "printed opening or closing" in warning.message
    assert changed.payload.accounts[0].opening is None


@pytest.mark.parametrize(
    "defect",
    [
        "unknown_component",
        "derived_component",
        "derived_gross",
        "component_equation",
        "missing_component",
        "positive_components",
        "unsupported_description",
        "unobserved_description",
        "unobserved_date",
        "summary_row",
        "component_location",
        "missing_fragment",
        "repeated_occurrence",
    ],
)
def test_capital_incomplete_or_unsupported_payment_shape_still_requires_review(decoded, defect):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    row = account.rows[0]
    principal, interest = row.components
    updates = {}
    if defect in {"unknown_component", "derived_component", "component_equation", "component_location"}:
        amount_updates = {
            "unknown_component": {"minor": None, "raw": None, "provenance": "unknown"},
            "derived_component": {"raw": None, "provenance": "derived"},
            "component_equation": {"minor": principal.amount.minor - 1},
            "component_location": {"locations": account.closing.locations},
        }[defect]
        updates["components"] = (
            principal.model_copy(update={"amount": principal.amount.model_copy(update=amount_updates)}),
            interest,
        )
    elif defect == "missing_component":
        updates["components"] = (principal,)
    elif defect == "derived_gross":
        updates["amount"] = row.amount.model_copy(update={"raw": None, "provenance": "derived"})
    elif defect == "positive_components":
        updates = {
            "amount": row.amount.model_copy(update={"minor": 22000}),
            "components": tuple(
                part.model_copy(update={"amount": part.amount.model_copy(update={"minor": -part.amount.minor})})
                for part in row.components
            ),
        }
    elif defect == "unsupported_description":
        updates["description"] = row.description.model_copy(update={"text": "Other activity"})
    elif defect == "unobserved_description":
        updates["description"] = row.description.model_copy(update={"raw": None, "provenance": "derived"})
    elif defect == "unobserved_date":
        updates["date"] = row.date.model_copy(update={"raw": None, "provenance": "assumed"})
    elif defect == "summary_row":
        updates = {"row_role": "period_summary", "date_role": "statement_period_end"}
    elif defect == "missing_fragment":
        updates["fragments"] = ()
    elif defect == "repeated_occurrence":
        updates["occurrence"] = 1
    changed = with_account(evidence, account.model_copy(update={"rows": (row.model_copy(update=updates),)}))
    assert any(warning.code == "source_balance_check_unavailable" for warning in requires(changed))
    assert changed.payload.independent_balance_verified is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("parser_id", "other_loan"),
        ("engine_version", "loan-history-lines-pilot-1"),
        ("engine_version", "future-engine"),
    ],
)
def test_capital_exception_is_limited_to_the_current_finite_parser(decoded, field, value):
    evidence = decoded["capital-one-loan-pilot-definition.json"].model_copy(update={field: value})
    assert [warning.code for warning in requires(evidence)] == ["source_balance_check_unavailable"]


@pytest.mark.parametrize("repeated_payment", [True, False])
def test_decoded_capital_multiple_payments_and_amount_financed_still_require_review(repeated_payment):
    source = loan_lines(changes={5: loan_lines().lines[4].raw}) if repeated_payment else loan_lines(interest=False)
    evidence = parse_loan_history(LOAN_DEFINITION, source)
    assert [warning.code for warning in requires(evidence)] == ["source_balance_check_unavailable"]
    rows = evidence.payload.accounts[0].rows
    if repeated_payment:
        assert [row.occurrence for row in rows] == [0, 1]
        assert len({row.row_id for row in rows}) == 2
        assert sum(row.amount.minor for row in rows) == -44000
    else:
        assert rows[0].description.text == "Amount Financed" and rows[0].amount.minor == 1000000


@pytest.mark.parametrize(
    "changes,error",
    [
        ({1: "Current Payment Due: $300.00"}, "missing_or_ambiguous_history_fields"),
        ({4: "01/15/2026 Payment Received -$200.00 -$20.00 = -$221.00"}, "printed_component_equation"),
        ({4: "01/15/2026 Payment Received -$200.00 -$20.00 ="}, "unresolved_history_row"),
        ({6: "Unclassified $2.00"}, "missing_history_end"),
    ],
)
def test_capital_warning_exception_does_not_admit_refused_source(changes, error):
    with pytest.raises(LoanHistoryError, match=f"^{error}$"):
        parse_loan_history(LOAN_DEFINITION, loan_lines(changes=changes))


@pytest.mark.parametrize(
    "changes,code",
    [
        ({7: "01/16/2026 Payment Received -$100.00 -$10.00 = -$110.00"}, "unclassified_monetary_line"),
        ({7: "Unclassified $2.00"}, "unclassified_monetary_line"),
        ({0: "Account Number: 1234567890123 Unclassified $2.00"}, "unclassified_monetary_line"),
        (
            {1: "Current Payment Due: $300.00 Principal Balance: $9,500.00 Unclassified $2.00"},
            "unclassified_monetary_line",
        ),
        ({7: "Other activity 01/16/2026"}, "dated_unresolved"),
    ],
)
def test_audited_capital_exterior_source_defects_still_require_review(changes, code):
    source = pdf_document(
        (text_page("Capital One Auto Finance", *(line.raw for line in loan_lines(changes=changes).lines)),)
    )
    evidence = build_source_evidence(source, LOAN_DEFINITION, suffix=".pdf")
    assert evidence.engine_version == "loan-history-lines-pilot-2"
    assert len(evidence.payload.accounts[0].rows) == 1
    assert [warning.code for warning in requires(evidence)] == [code]
    assert any(
        warning.code == "source_balance_check_unavailable" and warning.classification == "informational"
        for warning in evidence_import_warnings(evidence)
    )
    assert evidence.payload.capture_verified is False and evidence.payload.independent_balance_verified is False


@pytest.mark.parametrize(
    "source_field,code",
    [
        ("Past Due: $0.00", "loan_payment_information"),
        ("Late Fees: $5.00", "loan_payment_information"),
        ("Total Due: $305.00", "loan_payment_information"),
        ("Payoff Amount: $9,600.00", "loan_account_summary"),
        ("Statement Date: 01/31/2026", "loan_statement_dates"),
        ("Payoff Good Through: 02/15/2026", "loan_statement_dates"),
        ("Amount Enclosed: $", "loan_coupon_information"),
    ],
)
def test_capital_known_exterior_nonactivity_roles_are_informational(source_field, code):
    evidence = parse_loan_history(LOAN_DEFINITION, loan_lines(changes={7: source_field}))
    before = evidence.model_dump_json()
    warnings = evidence_import_warnings(evidence)
    assert not requires(evidence)
    assert any(warning.code == code and warning.classification == "informational" for warning in warnings)
    assert evidence.payload.accounts[0].opening is None
    assert evidence.payload.independent_balance_verified is False
    assert evidence.model_dump_json() == before


def test_capital_ambiguous_accounts_and_nonabsent_opening_still_require_review(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    other = account.model_copy(update={"source_identity": "9876543210987", "rows": ()})
    multiple = evidence.model_copy(
        update={"payload": evidence.payload.model_copy(update={"accounts": (account, other)})}
    )
    assert [warning.code for warning in requires(multiple)] == ["source_balance_check_unavailable"]
    unknown = MoneyValue(raw=None, minor=None, provenance="unknown", locations=())
    assert [
        warning.code for warning in requires(with_account(evidence, account.model_copy(update={"opening": unknown})))
    ] == ["source_balance_check_unavailable"]


def test_capital_exception_preserves_unknown_money_and_source_defects(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    row = account.rows[0]
    unknown = MoneyValue(raw=None, minor=None, provenance="unknown", locations=())
    dispositions = tuple(
        SourceDisposition(code=code, location=row.fragments[0].location, raw_values=("Unknown $1.00",))
        for code in ("unclassified_monetary_line", "source_total_mismatch")
    )
    with_defects = evidence.model_copy(
        update={"payload": evidence.payload.model_copy(update={"dispositions": dispositions})}
    )
    assert {warning.code for warning in requires(with_defects)} == {
        "unclassified_monetary_line",
        "source_total_mismatch",
    }
    with_unknown = with_account(
        evidence, account.model_copy(update={"rows": (row.model_copy(update={"running_balance": unknown}),)})
    )
    assert {warning.code for warning in requires(with_unknown)} == {
        "source_amount_unknown",
        "source_balance_check_unavailable",
    }


def test_capital_printed_opening_never_uses_the_missing_opening_exception(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    opening = account.closing.model_copy(update={"minor": 970001, "raw": "$9,700.01"})
    changed = with_account(evidence, account.model_copy(update={"opening": opening}))
    assert [warning.code for warning in requires(changed)] == ["source_balance_mismatch"]
    opening = opening.model_copy(update={"minor": 970000, "raw": "$9,700.00"})
    changed = with_account(evidence, account.model_copy(update={"opening": opening}))
    assert [warning.code for warning in requires(changed)] == ["source_balance_check_unverified"]


def test_principal_check_uses_components_without_adding_interest_to_principal(decoded):
    evidence = decoded["wells-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    assert sum(row.amount.minor for row in account.rows) == 2100
    assert account.closing.minor - account.opening.minor == 2000
    assert not requires(evidence)
    assert any(
        warning.code == "source_period_unknown" and warning.classification == "informational"
        for warning in evidence_import_warnings(evidence)
    )
    unverified = with_account(evidence, account)
    assert [warning.code for warning in requires(unverified)] == ["source_balance_check_unverified"]
    no_components = account.model_copy(
        update={"rows": tuple(row.model_copy(update={"components": ()}) for row in account.rows)}
    )
    assert requires(with_account(evidence, no_components))[0].code == "source_balance_check_unavailable"


def test_estimated_period_and_posting_guess_are_informational_and_preserve_evidence(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    row = account.rows[0]
    guess = row.date.model_copy(update={"raw": None, "provenance": "assumed"})
    changed = evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(
                update={
                    "start": evidence.payload.start.model_copy(update={"raw": None, "provenance": "assumed"}),
                    "accounts": (
                        account.model_copy(update={"rows": (row.model_copy(update={"posting_date_guess": guess}),)}),
                    ),
                }
            )
        }
    )
    before = changed.model_dump_json()
    warnings = evidence_import_warnings(changed)
    assert {warning.code for warning in warnings if warning.classification == "informational"} >= {
        "source_period_assumed",
        "source_posting_date_assumed",
    }
    assert changed.model_dump_json() == before
    assert changed.payload.accounts[0].rows[0].date_role == "activity_date"


@pytest.mark.parametrize("name", ["happen-savings-pilot-definition.json", "wells-loan-pilot-definition.json"])
def test_actual_supported_scope_mismatch_is_distinct_from_missing_verification(decoded, name):
    evidence = decoded[name]
    account = evidence.payload.accounts[0]
    wrong_closing = account.closing.model_copy(update={"minor": account.closing.minor + 1})
    warning = requires(with_account(evidence, account.model_copy(update={"closing": wrong_closing})))[0]
    assert warning.code == "source_balance_mismatch"
    assert "does not equal closing" in warning.message


def test_unknown_money_requires_review_without_fabricating_a_balance_failure(decoded):
    evidence = decoded["happen-savings-pilot-definition.json"]
    account = evidence.payload.accounts[0]
    unknown = MoneyValue(raw=None, minor=None, provenance="unknown", locations=())
    row = account.rows[0].model_copy(update={"running_balance": unknown})
    changed = evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(update={"accounts": (account.model_copy(update={"rows": (row,)}),)})
        }
    )
    warnings = requires(changed)
    assert [warning.code for warning in warnings] == ["source_amount_unknown"]
    assert warnings[0].locations == tuple(fragment.location for fragment in row.fragments)


def test_benign_citi_page_text_does_not_imply_unclassified_amounts(decoded):
    evidence = decoded["recent-citi-pilot-definition.json"]
    page_text = [warning for warning in evidence_import_warnings(evidence) if warning.code == "unclassified_page_text"]
    assert page_text and all(warning.classification == "informational" for warning in page_text)
    assert not requires(evidence)


def test_repeated_unclassified_amounts_keep_codes_counts_and_bounded_source_locations(decoded):
    evidence = decoded["happen-savings-pilot-definition.json"]
    dispositions = tuple(
        SourceDisposition(
            code="unclassified_monetary_line",
            location=PdfLine(kind="pdf_line", page=1, line=index),
            raw_values=("Unknown fee $1.00",),
        )
        for index in range(1, 25)
    )
    changed = evidence.model_copy(
        update={"payload": evidence.payload.model_copy(update={"dispositions": dispositions})}
    )
    warning = requires(changed)[0]
    assert warning.code == "unclassified_monetary_line" and "containing money" in warning.message
    assert warning.occurrence_count == 24 and len(warning.locations) == MAX_WARNING_LOCATIONS
    assert len(changed.payload.dispositions) == 24


@pytest.mark.parametrize(
    "code",
    [
        "citi_account_summary",
        "citi_payment_information",
        "citi_credit_terms",
        "citi_repayment_example",
        "citi_apr_information",
        "citi_interest_charge_detail",
    ],
)
def test_recognized_citi_detail_is_informational_without_removing_capture_limit(decoded, code):
    evidence = decoded["recent-citi-pilot-definition.json"]
    location = PdfLine(kind="pdf_line", page=2, line=4)
    changed = evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(
                update={
                    "dispositions": (SourceDisposition(code=code, location=location, raw_values=("Synthetic $3.00",)),),
                    "capture_verified": False,
                }
            )
        }
    )
    before = changed.model_dump_json()
    warnings = evidence_import_warnings(changed)
    warning = next(w for w in warnings if w.code == code)
    assert warning.classification == "informational" and warning.locations == (location,)
    assert any(w.code == "source_capture_unverified" for w in warnings)
    assert not requires(changed)
    assert changed.model_dump_json() == before


def test_csv_export_does_not_invent_a_statement_balance_or_capture_check():
    evidence = build_source_evidence(SOURCE, DEFINITION.read_bytes(), suffix=".csv")
    assert not isinstance(evidence.payload, StatementPayload)
    assert evidence_import_warnings(evidence) == ()


def test_preview_names_both_classes_and_exposes_warning_code_and_location(qtbot, decoded, tmp_path):
    recognition = recognize_catalog_source(SOURCE, catalog=_verified_catalog(), suffix=".csv")
    candidate = recognition.candidates[0]
    evidence = decoded["chase-card-pilot-definition.json"]
    location = PdfLine(kind="pdf_line", page=2, line=33)
    changed = evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(
                update={
                    "dispositions": (
                        SourceDisposition(
                            code="unclassified_monetary_line", location=location, raw_values=("Unknown $2.00",)
                        ),
                    )
                }
            )
        }
    )
    candidate = replace(
        candidate, warnings=evidence_import_warnings(changed), attention_codes=("unclassified_monetary_line",)
    )
    preview = V2CsvImportPreview()
    qtbot.addWidget(preview)
    preview.present(
        ImportAccountReviewRequest(
            tmp_path / "synthetic.csv",
            SimpleNamespace(recognition=replace(recognition, candidates=(candidate,))),
            1,
            1,
        )
    )
    assert "Requires review: A source line containing money" in preview.attention_notice.text()
    assert "Informational: Some posting dates are estimated" in preview.attention_notice.text()
    assert "Some source content needs review" not in preview.attention_notice.text()
    assert "[unclassified_monetary_line]" in preview.details.toPlainText()
    assert "Page 2, line 33" in preview.details.toPlainText()
    preview.request.finish()
