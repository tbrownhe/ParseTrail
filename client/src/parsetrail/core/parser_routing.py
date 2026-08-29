"""Typed, format-independent parser routing results and failures."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity

if TYPE_CHECKING:
    from parsetrail.core.validation import Statement


class ParseError(Exception):
    """Base error safe for GUI, batch, and future CLI adapters to present."""

    code = "parse.error"

    def __init__(self, message: str, *, diagnostics: Sequence[Diagnostic] = ()) -> None:
        super().__init__(message)
        self.diagnostics = tuple(diagnostics)


class NoParserMatchError(ParseError):
    code = "routing.no_match"

    def __init__(self, suffix: str) -> None:
        super().__init__(f"No plugin matched this {suffix or 'statement'} input.")
        self.suffix = suffix


class AmbiguousParserMatchError(ParseError):
    code = "routing.ambiguous"

    def __init__(self, candidates: Sequence[str], suffix: str) -> None:
        self.candidates = tuple(candidates)
        self.suffix = suffix
        names = ", ".join(self.candidates)
        super().__init__(f"Multiple plugins matched this {suffix or 'statement'} input: {names}")


class InvalidPluginSearchError(ParseError):
    code = "routing.invalid_expression"

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name
        super().__init__(f"Plugin {plugin_name} has an invalid routing expression.")


class ParserExecutionError(ParseError):
    code = "parser.execution_failed"

    def __init__(self, plugin_name: str, cause_type: str) -> None:
        self.plugin_name = plugin_name
        self.cause_type = cause_type
        diagnostic = Diagnostic(
            code=self.code,
            message=f"Plugin {plugin_name} failed with {cause_type}.",
            severity=DiagnosticSeverity.ERROR,
            plugin_name=plugin_name,
        )
        super().__init__(diagnostic.message, diagnostics=(diagnostic,))


class ParserOutputError(ParseError):
    code = "parser.invalid_output"

    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name
        super().__init__(f"Plugin {plugin_name} returned malformed output.")


class StatementValidationError(ParseError):
    code = "validation.failed"

    def __init__(self, plugin_name: str, diagnostics: Sequence[Diagnostic]) -> None:
        self.plugin_name = plugin_name
        super().__init__(
            f"Plugin {plugin_name} produced a statement that failed validation.",
            diagnostics=diagnostics,
        )


class ParseWarningsRejectedError(ParseError):
    code = "validation.warnings_not_accepted"

    def __init__(self, diagnostics: Sequence[Diagnostic]) -> None:
        super().__init__("Statement validation warnings require explicit acceptance.", diagnostics=diagnostics)


class UnsupportedStatementFormatError(ParseError):
    code = "routing.unsupported_format"

    def __init__(self, suffix: str) -> None:
        self.suffix = suffix
        super().__init__(f"Unsupported statement format: {suffix or '<none>'}")


@dataclass(frozen=True, slots=True)
class ParseResult:
    statement: Statement
    plugin_name: str
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is DiagnosticSeverity.WARNING)

    def require_statement(self, *, accept_warnings: bool = False) -> Statement:
        if self.warnings and not accept_warnings:
            raise ParseWarningsRejectedError(self.warnings)
        return self.statement


def require_unique_candidate(candidates: Sequence[str], *, suffix: str) -> str:
    """Require metadata routing to identify exactly one parser."""
    if not candidates:
        raise NoParserMatchError(suffix)
    if len(candidates) > 1:
        raise AmbiguousParserMatchError(candidates, suffix)
    return candidates[0]


def raise_execution_error(plugin_name: str, error: Exception) -> NoReturn:
    """Convert arbitrary plugin failures without exposing extracted statement data."""
    raise ParserExecutionError(plugin_name, type(error).__name__) from None
