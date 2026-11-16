"""Warning classes follow actual synthetic decoder evidence and scoped checks."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core.source_evidence import MoneyValue, PdfLine, SourceDisposition, StatementPayload
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_import_warnings import MAX_WARNING_LOCATIONS, evidence_import_warnings
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest
from parsetrail.gui.v2_csv_import_preview import V2CsvImportPreview

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

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


def test_missing_opening_is_an_unavailable_balance_check_never_a_failed_equation(decoded):
    evidence = decoded["capital-one-loan-pilot-definition.json"]
    assert evidence.payload.accounts[0].opening is None
    warnings = requires(evidence)
    assert [warning.code for warning in warnings] == ["source_balance_check_unavailable"]
    assert "printed opening or closing" in warnings[0].message
    assert warnings[0].locations


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
