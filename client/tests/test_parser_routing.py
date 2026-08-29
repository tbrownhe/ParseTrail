import pytest
from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity
from parsetrail.core.parser_routing import (
    AmbiguousParserMatchError,
    NoParserMatchError,
    ParseResult,
    ParseWarningsRejectedError,
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
