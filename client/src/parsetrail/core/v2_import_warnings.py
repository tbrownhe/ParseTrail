"""Read-only import warning policy; classifications never grant posting permission.

Capture, scoped source arithmetic and accounting acceptance remain separate.
The preview retains bounded locations and occurrence counts; complete original
dispositions remain in source evidence, rather than being copied into a preview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence, SourceLocation, StatementAccount, StatementPayload

MAX_WARNING_LOCATIONS = 16
WarningClassification = Literal["informational", "requires_review"]
_MONEY = re.compile(r"\$|(?<!\d)\d[\d,]*\.\d{2}(?!\d)")


@dataclass(frozen=True, slots=True)
class ImportWarning:
    code: str
    classification: WarningClassification
    message: str
    locations: tuple[SourceLocation, ...] = ()
    occurrence_count: int = 1


def _balance_warning(account: StatementAccount) -> tuple[str, str]:
    scope = {
        "account_total": "account total",
        "cash_component": "cash component",
        "principal_component": "principal component",
    }[account.balance_scope]
    endpoints = (account.opening, account.closing)
    if any(value is None or value.minor is None or value.provenance != "observed" for value in endpoints):
        return "source_balance_check_unavailable", f"The {scope} balance check lacks printed opening or closing amounts"
    if account.balance_scope == "principal_component":
        # Gross loan payments include interest; they cannot check principal endpoints.
        if any(
            not row.components or any(component.amount.provenance != "observed" for component in row.components)
            for row in account.rows
        ):
            return "source_balance_check_unavailable", "The principal balance check lacks printed component amounts"
        change = sum(
            component.amount.minor
            for row in account.rows
            for component in row.components
            if component.role == "principal"
        )
    else:
        if any(row.amount.provenance != "observed" for row in account.rows):
            return "source_balance_check_unavailable", f"The {scope} balance check lacks printed activity amounts"
        change = sum(row.amount.minor for row in account.rows)
    if account.opening.minor + change != account.closing.minor:
        return (
            "source_balance_mismatch",
            f"Printed opening plus extracted changes does not equal closing for the {scope}",
        )
    return "source_balance_check_unverified", f"The parser has not independently verified the {scope} balance check"


def _disposition_warning(code: str, raw_values: tuple[str, ...]) -> tuple[WarningClassification, str] | None:
    # Citi's unclassified page text has already refused financial/date-shaped
    # lines. Keep that benign text distinct from an unresolved monetary line.
    if code == "unclassified_page_text" and not any(_MONEY.search(raw) for raw in raw_values):
        return "informational", "Additional page text is retained outside the extracted financial rows"
    if code == "unclassified_monetary_line" or code == "money_unresolved":
        return "requires_review", "A source line containing money has not been classified"
    if code == "summary_window_unclassified":
        return "requires_review", "A line within the account summary has not been classified"
    if code == "summary_window_tail_unclassified":
        return "requires_review", "Content after the account summary has not been classified"
    if code == "dated_unresolved":
        return "requires_review", "A dated source line has not been resolved"
    if code == "unresolved_after_stop":
        return "requires_review", "Content after the activity table ended has not been resolved"
    if "mismatch" in code:
        return "requires_review", "Source evidence contains a mismatch: " + code.replace("_", " ")
    if "unclassified" in code:
        return "requires_review", "Source content has not been classified: " + code.replace("_", " ")
    if any(token in code for token in ("unsupported", "unresolved", "incomplete", "truncated", "failed")):
        return "requires_review", "Source extraction needs checking: " + code.replace("_", " ")
    if "uninterpreted" in code:
        return (
            ("requires_review", "A source amount has not been interpreted")
            if any(_MONEY.search(raw) for raw in raw_values)
            else ("informational", "Additional source detail is retained without interpretation")
        )
    return None


def evidence_import_warnings(evidence: SourceEvidence) -> tuple[ImportWarning, ...]:
    """Project complete evidence into two warning classes without mutating it."""
    collected: dict[tuple[str, WarningClassification, str], tuple[list[SourceLocation], int]] = {}

    def add(code, classification, message, locations=()):
        key = (code, classification, message)
        selected, count = collected.get(key, ([], 0))
        for location in locations:
            if len(selected) == MAX_WARNING_LOCATIONS:
                break
            if location not in selected:
                selected.append(location)
        collected[key] = (selected, count + 1)

    payload = evidence.payload
    statement = isinstance(payload, StatementPayload)
    rows = tuple(row for account in payload.accounts for row in account.rows) if statement else payload.rows
    start, end = (payload.start, payload.end) if statement else (payload.activity_start, payload.activity_end)
    if not rows:
        add("no_activity_captured", "requires_review", "No activity rows were captured")
    if start.iso is None or end.iso is None:
        add(
            "source_period_unknown",
            "informational",
            "The source does not establish the complete period",
            (*start.locations, *end.locations),
        )
    if start.provenance == "assumed" or end.provenance == "assumed":
        add(
            "source_period_assumed",
            "informational",
            "The source period is estimated because dates are not printed",
            (*start.locations, *end.locations),
        )
    for row in rows:
        if row.date.provenance == "assumed":
            posting = row.date_role == "posting_date"
            add(
                "source_posting_date_assumed" if posting else "source_activity_date_assumed",
                "informational",
                "Some posting dates are estimated because complete dates are not printed"
                if posting
                else "Some activity dates are estimated because complete dates are not printed",
                row.date.locations,
            )
        if row.posting_date_guess is not None:
            add(
                "source_posting_date_assumed",
                "informational",
                "Some posting dates are estimated because complete dates are not printed",
                row.posting_date_guess.locations,
            )
        for value in (row.amount, row.running_balance, *(component.amount for component in row.components)):
            if value is not None and value.provenance == "unknown":
                add(
                    "source_amount_unknown",
                    "requires_review",
                    "A source amount is unknown",
                    value.locations or tuple(fragment.location for fragment in row.fragments),
                )
    if statement:
        if not payload.capture_verified:
            add("source_capture_unverified", "informational", "Complete source capture has not been verified")
        if not payload.independent_balance_verified:
            for account in payload.accounts:
                code, message = _balance_warning(account)
                add(
                    code,
                    "requires_review",
                    message,
                    tuple(
                        location
                        for value in (account.opening, account.closing)
                        if value is not None
                        for location in value.locations
                    )
                    or account.identity_locations,
                )
    for disposition in payload.dispositions:
        warning = _disposition_warning(disposition.code, disposition.raw_values)
        if warning is not None:
            classification, message = warning
            add(disposition.code, classification, message, (disposition.location,))
    return tuple(
        ImportWarning(code, classification, message, tuple(locations), count)
        for (code, classification, message), (locations, count) in collected.items()
    )
