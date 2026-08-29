from datetime import datetime
from types import SimpleNamespace

import pytest
from parsetrail.core.parse import BaseRouter, ParseInput
from parsetrail.core.parser_routing import (
    ParserExecutionError,
    ParserOutputError,
    ParseWarningsRejectedError,
    StatementValidationError,
)
from parsetrail.core.validation import Account, Statement, Transaction


def _statement(*, end_balance: float = 10.0, unusual_date_gap: bool = False) -> Statement:
    transaction_date = datetime(2026, 1, 1) if unusual_date_gap else datetime(2026, 3, 15)
    return Statement(
        start_date=datetime(2026, 3, 1),
        end_date=datetime(2026, 3, 31),
        accounts=[
            Account(
                account_num="confidential-account-number",
                start_balance=0.0,
                end_balance=end_balance,
                transactions=[
                    Transaction(
                        transaction_date=transaction_date,
                        posting_date=datetime(2026, 3, 15),
                        amount=10.0,
                        desc="confidential transaction description",
                    )
                ],
            )
        ],
    )


def _router(parser_class: type) -> BaseRouter[object]:
    manager = SimpleNamespace(get_parser=lambda _name: parser_class)
    return BaseRouter(
        manager,
        ParseInput(name="statement.pdf", suffix=".pdf", data=b"unused"),
    )


def test_validation_warning_returns_a_typed_result_and_requires_acceptance() -> None:
    class WarningParser:
        def parse(self, _input: object) -> Statement:
            return _statement(unusual_date_gap=True)

    result = _router(WarningParser).extract_statement("warning_plugin", object())

    assert [warning.code for warning in result.warnings] == ["transaction.dates.unusual_gap"]
    with pytest.raises(ParseWarningsRejectedError):
        result.require_statement()
    assert result.require_statement(accept_warnings=True) is result.statement


def test_hard_validation_failure_is_redacted() -> None:
    class InvalidParser:
        def parse(self, _input: object) -> Statement:
            return _statement(end_balance=11.0)

    with pytest.raises(StatementValidationError) as exc_info:
        _router(InvalidParser).extract_statement("invalid_plugin", object())

    diagnostic_text = " ".join(item.message for item in exc_info.value.diagnostics)
    assert "confidential-account-number" not in diagnostic_text
    assert "confidential transaction description" not in diagnostic_text
    assert "discrepancy 1.00" in diagnostic_text


def test_malformed_parser_output_has_a_typed_error() -> None:
    class MalformedParser:
        def parse(self, _input: object) -> dict:
            return {"not": "a statement"}

    with pytest.raises(ParserOutputError):
        _router(MalformedParser).extract_statement("malformed_plugin", object())


def test_parser_exception_text_is_not_exposed() -> None:
    class FailingParser:
        def parse(self, _input: object) -> Statement:
            raise ValueError("account 1234 secret extracted text")

    with pytest.raises(ParserExecutionError) as exc_info:
        _router(FailingParser).extract_statement("failing_plugin", object())

    assert exc_info.value.cause_type == "ValueError"
    assert "secret" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
