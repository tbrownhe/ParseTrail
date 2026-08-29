"""Redacted, adapter-neutral diagnostics for parsing and validation."""

from dataclasses import dataclass, replace
from enum import StrEnum


class DiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A safe diagnostic that may be shown or logged by any adapter."""

    code: str
    message: str
    severity: DiagnosticSeverity
    plugin_name: str | None = None

    def for_plugin(self, plugin_name: str) -> "Diagnostic":
        return replace(self, plugin_name=plugin_name)
