import pytest
from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity
from parsetrail.core.parser_routing import (
    AmbiguousParserMatchError,
    InvalidPluginSearchError,
    NoParserMatchError,
    ParseResult,
    ParserExecutionError,
    ParserOutputError,
    ParseWarningsRejectedError,
    StatementValidationError,
    UnsupportedStatementFormatError,
    present_parse_error,
    require_unique_candidate,
)


def test_returns_the_only_matching_candidate() -> None:
    assert require_unique_candidate(["csv_a"], suffix=".csv") == "csv_a"


def test_rejects_multiple_matching_candidates() -> None:
    with pytest.raises(AmbiguousParserMatchError) as exc_info:
        require_unique_candidate(["pdf_a", "pdf_b"], suffix=".pdf")

    assert exc_info.value.candidates == ("pdf_a", "pdf_b")
    assert exc_info.value.code == "routing.ambiguous"


def test_rejects_empty_candidate_list() -> None:
    with pytest.raises(NoParserMatchError) as exc_info:
        require_unique_candidate([], suffix=".xlsx")

    assert exc_info.value.suffix == ".xlsx"
    assert exc_info.value.code == "routing.no_match"


def test_parse_result_requires_explicit_warning_acceptance() -> None:
    warning = Diagnostic(
        code="transaction.dates.unusual_gap",
        message="Transaction and posting dates at account 1, transaction row 1 are more than 60 days apart.",
        severity=DiagnosticSeverity.WARNING,
        plugin_name="example",
    )
    statement = object()
    result = ParseResult(statement=statement, plugin_name="example", diagnostics=(warning,))  # type: ignore[arg-type]

    with pytest.raises(ParseWarningsRejectedError):
        result.require_statement()
    assert result.require_statement(accept_warnings=True) is statement


@pytest.mark.parametrize(
    ("error", "expected_title", "expected_guidance"),
    [
        (UnsupportedStatementFormatError(".docx"), "Unsupported Statement File", "PDF, CSV, or XLSX"),
        (NoParserMatchError(".pdf"), "No Compatible Plugin", "Send for Plugin Development"),
        (
            AmbiguousParserMatchError(["bank_pdf", "bank_legacy_pdf"], ".pdf"),
            "Ambiguous Plugin Match",
            "Troubleshoot Parsing",
        ),
        (InvalidPluginSearchError("catalog"), "Invalid Plugin Classification", "reinstall"),
        (ParserExecutionError("bank_pdf", "ValueError"), "Statement Format Changed", "plugin updates"),
        (ParserOutputError("bank_pdf"), "Incompatible Plugin Output", "client and plugin updates"),
    ],
)
def test_parse_error_presentations_are_specific_and_actionable(error, expected_title, expected_guidance) -> None:
    presentation = present_parse_error(error)

    assert presentation.title == expected_title
    assert expected_guidance in presentation.message


def test_validation_failure_presentation_excludes_diagnostic_statement_values() -> None:
    diagnostic = Diagnostic(
        code="fixture.private",
        message="Confidential account 1234 has a secret transaction description.",
        severity=DiagnosticSeverity.ERROR,
        plugin_name="bank_pdf",
    )

    presentation = present_parse_error(StatementValidationError("bank_pdf", [diagnostic]))

    assert presentation.title == "Statement Safety Check Failed"
    assert "bank_pdf" in presentation.message
    assert "1234" not in presentation.message
    assert "secret" not in presentation.message
