"""Read-only import warning policy; classifications never grant posting permission.

Capture, scoped source arithmetic and accounting acceptance remain separate.
The preview retains bounded locations and occurrence counts; complete original
dispositions remain in source evidence, rather than being copied into a preview.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence, SourceLocation, StatementAccount, StatementPayload
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_wells_loan_lines import _FINANCIAL_OR_DATE as _WELLS_REGISTER_FINANCIAL_OR_DATE

MAX_WARNING_LOCATIONS = 16
WarningClassification = Literal["informational", "requires_review"]
_MONEY = re.compile(r"\$|(?<!\d)\d[\d,]*\.\d{2}(?!\d)")
_PERCENTAGE = re.compile(r"(?<![\d.,$])\d{1,3}\.\d{2}%(?!\d)")


@dataclass(frozen=True, slots=True)
class ImportWarning:
    code: str
    classification: WarningClassification
    message: str
    locations: tuple[SourceLocation, ...] = ()
    occurrence_count: int = 1


def _printed_empty_hsa_cash_table(evidence: SourceEvidence) -> bool:
    """Recognize one audited empty cash table, without certifying page capture."""
    payload = evidence.payload
    if (
        evidence.parser_id != "hsa_cash_line_pilot"
        or evidence.engine_version not in {"hsa-cash-lines-pilot-2", "hsa-cash-lines-pilot-3"}
        or not isinstance(payload, StatementPayload)
        or len(payload.accounts) != 1
        or any(
            value.provenance != "observed" or value.iso is None or not value.locations
            for value in (payload.start, payload.end)
        )
        or payload.start.iso > payload.end.iso
    ):
        return False
    account = payload.accounts[0]
    if account.balance_scope != "cash_component" or account.rows:
        return False
    endpoints = (account.opening, account.closing)
    if any(
        value is None
        or value.provenance != "observed"
        or value.minor is None
        or value.raw is None
        or len(value.locations) != 1
        for value in endpoints
    ):
        return False
    opening, closing = endpoints
    if opening.minor != closing.minor:
        return False
    proof = [item for item in payload.dispositions if item.code == "hsa_empty_cash_table"]
    if (
        len(proof) != 1
        or len(proof[0].raw_values) != 1
        or " ".join(proof[0].raw_values[0].split()).lstrip("_ ") != "Date DescriptionofTransaction (Withdrawal) Balance"
    ):
        return False
    header, first, last = proof[0].location, opening.locations[0], closing.locations[0]
    return (
        header.kind == first.kind == last.kind == "pdf_line"
        and header.page == first.page == last.page
        and first.line == header.line + 1
        and last.line == first.line + 1
    )


def _printed_empty_wells_loan_register(evidence: SourceEvidence) -> bool:
    """A located explicit empty register, not an inference from equal balances."""
    payload = evidence.payload
    if (
        evidence.parser_id != "pdf_wfloanper_202306"
        or evidence.engine_version != "wells-loan-lines-pilot-2"
        or not isinstance(payload, StatementPayload)
        or not payload.independent_balance_verified
        or len(payload.accounts) != 1
        or payload.start.iso is not None
        or payload.start.provenance != "unknown"
        or payload.end.iso is None
        or payload.end.provenance != "observed"
    ):
        return False
    account = payload.accounts[0]
    endpoints = (account.opening, account.closing)
    if (
        account.balance_scope != "principal_component"
        or account.rows
        or any(
            value is None
            or value.provenance != "observed"
            or value.raw is None
            or value.minor is None
            or len(value.locations) != 1
            for value in endpoints
        )
    ):
        return False
    opening, closing = endpoints
    if opening.minor != closing.minor or opening.minor > 0:
        return False
    proofs = [item for item in payload.dispositions if item.code == "wells_loan_empty_register"]
    if len(proofs) != 1:
        return False
    proof = proofs[0]
    location, first, last = proof.location, opening.locations[0], closing.locations[0]
    if (
        location.kind != "pdf_line"
        or first.kind != "pdf_line"
        or last.kind != "pdf_line"
        or location.page != first.page
        or first.page != last.page
        or location.end_line != last.line
        or location.line >= first.line
        or not 1 <= last.line - first.line <= 3
        or len(proof.raw_values) != last.line - location.line + 1
        or not 4 <= len(proof.raw_values) <= 11
        or last not in payload.end.locations
    ):
        return False
    raw = [" ".join(value.split()) for value in proof.raw_values]
    opening_index = first.line - location.line
    if (
        raw[0] != "Effective Transaction Principal"
        or raw.count("Date Description Amount Balance") != 1
        or raw.index("Date Description Amount Balance") >= opening_index
        or raw[opening_index] != f"Prior Principal Balance {opening.raw}"
        or raw[-2] != "No transactions within this billing cycle."
    ):
        return False
    match = re.fullmatch(r"(?P<date>\d{2}/\d{2}/\d{2}) Ending Principal Balance (?P<amount>\$[\d,.]+)\*", raw[-1])
    if match is None or match["amount"] != closing.raw:
        return False
    try:
        if (
            datetime.strptime(match["date"], "%m/%d/%y").date().isoformat() != payload.end.iso
            or usd_symbol_minor_v1(opening.raw) != -opening.minor
            or usd_symbol_minor_v1(closing.raw) != -closing.minor
        ):
            return False
    except ValueError:
        return False
    return all(
        not _WELLS_REGISTER_FINANCIAL_OR_DATE.search(value)
        for index, value in enumerate(raw)
        if index not in {opening_index, len(raw) - 1}
    )


def _capital_auto_origination_without_opening(evidence: SourceEvidence, account: StatementAccount) -> bool:
    """Qualify an evidenced financed amount without inventing an opening."""
    payload = evidence.payload
    if (
        evidence.parser_id != "pdf_capitaloneauto_202402"
        or evidence.engine_version != "loan-history-lines-pilot-2"
        or not isinstance(payload, StatementPayload)
        or len(payload.accounts) != 1
        or account.balance_scope != "principal_component"
        or account.opening is not None
        or account.closing is None
        or len(account.rows) != 1
        or any(
            value.provenance != "observed" or value.iso is None or not value.locations
            for value in (payload.start, payload.end)
        )
        or payload.start.iso > payload.end.iso
    ):
        return False
    row = account.rows[0]
    if (
        row.row_role != "activity"
        or row.date_role != "activity_date"
        or row.date.provenance != "observed"
        or row.date.raw is None
        or row.date.iso is None
        or not payload.start.iso <= row.date.iso <= payload.end.iso
        or row.description.provenance != "observed"
        or row.description.raw is None
        or (row.description.text or "").casefold() != "amount financed"
        or row.occurrence != 0
        or row.running_balance is not None
        or row.source_account != account.source_identity
        or row.source_account_form != account.source_identity_form
        or len(row.components) != 1
        or row.components[0].role != "principal"
    ):
        return False
    values = (account.closing, row.amount, row.components[0].amount)
    return (
        all(
            value.provenance == "observed" and value.raw is not None and value.minor is not None and value.locations
            for value in values
        )
        and 0 < account.closing.minor == row.amount.minor == row.components[0].amount.minor
        and row.date.locations
        == row.description.locations
        == row.amount.locations
        == row.components[0].amount.locations
        and len(row.fragments) == 1
        and row.fragments[0].channel == "loan_history_line"
        and row.amount.locations == (row.fragments[0].location,)
    )


def _capital_auto_payment_without_opening(evidence: SourceEvidence, account: StatementAccount) -> bool:
    """Qualify one finite printed payment, without asserting a balance equation."""
    if (
        evidence.parser_id != "pdf_capitaloneauto_202402"
        or evidence.engine_version != "loan-history-lines-pilot-2"
        or not isinstance(evidence.payload, StatementPayload)
        or len(evidence.payload.accounts) != 1
        or account.balance_scope != "principal_component"
        or account.opening is not None
        or account.closing is None
        or len(account.rows) != 1
    ):
        return False
    row = account.rows[0]
    if (
        row.row_role != "activity"
        or row.date_role != "activity_date"
        or row.date.provenance != "observed"
        or row.description.provenance != "observed"
        or (row.description.text or "").casefold() != "payment received"
        or row.occurrence != 0
        or row.source_account != account.source_identity
        or row.source_account_form != account.source_identity_form
        or row.running_balance is not None
        or len(row.components) != 2
        or {part.role for part in row.components} != {"principal", "interest"}
    ):
        return False
    values = (account.closing, row.amount, *(part.amount for part in row.components))
    if any(
        value.provenance != "observed" or value.minor is None or value.raw is None or not value.locations
        for value in values
    ):
        return False
    return (
        row.amount.minor < 0
        and all(part.amount.minor <= 0 for part in row.components)
        and sum(part.amount.minor for part in row.components) == row.amount.minor
        and row.date.locations == row.description.locations == row.amount.locations
        and all(part.amount.locations == row.amount.locations for part in row.components)
        and len(row.fragments) == 1
        and row.fragments[0].channel == "loan_history_line"
        and row.amount.locations == (row.fragments[0].location,)
    )


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
    loan_roles = {
        "loan_payment_information": "Printed payment information and fee summaries are retained separately from activity",
        "loan_account_summary": "Printed payoff quotes are retained separately from principal balances and activity",
        "loan_statement_dates": "Printed statement, due and payoff dates are retained separately from the activity period",
        "loan_coupon_information": "The blank payment coupon is retained separately from activity",
    }
    if code in loan_roles:
        return "informational", loan_roles[code]
    citi_roles = {
        "citi_account_summary": "Printed account summary amounts are retained separately from activity",
        "citi_payment_information": "Printed payment information is retained separately from activity",
        "citi_credit_terms": "Printed credit terms are retained separately from activity",
        "citi_repayment_example": "Printed repayment examples are retained separately from activity",
        "citi_apr_information": "Printed interest calculation details are retained separately from activity",
        "citi_interest_charge_detail": "Printed interest charge detail is retained separately from activity",
        "citi_savings_information": "Printed card benefit savings are retained separately from account activity",
    }
    if code in citi_roles:
        return "informational", citi_roles[code]
    wells_roles = {
        "wells_non_activity_blank": "Blank cells after the activity table are retained separately",
        "wells_statement_summary": "Printed table totals and ending balance are retained separately from activity",
        "wells_balance_disclosure": "Printed balance explanations are retained separately from activity",
        "wells_service_fee_information": "Printed service fee information is retained separately from activity",
        "wells_transaction_fee_information": "Printed transaction fee calculations are retained separately from activity",
        "wells_account_product": "The printed business account product is retained as source context",
        "wells_statement_context": "Printed statement context is retained separately from activity",
    }
    if code in wells_roles:
        return "informational", wells_roles[code]
    if code == "wells_loan_empty_register":
        return "informational", "The printed principal register explicitly reports no transactions"
    if code in {
        "summary_chart_axis",
        "summary_chart_context",
        "summary_explanatory_note",
        "summary_contact_heading",
        "summary_accrued_interest",
        "summary_inclusive_value",
        "summary_year_to_date_context",
    }:
        return "informational", "Printed summary context is retained separately from period changes and closing value"
    if code in {"hsa_empty_cash_table", "hsa_cash_rate_fee_information", "hsa_cash_statement_dates"}:
        return "informational", "Printed HSA cash-table context is retained separately from activity"
    if code == "hsa_exterior_unclassified":
        return "requires_review", "Content outside the empty HSA cash table needs review"
    # Citi's unclassified page text has already refused financial/date-shaped
    # lines. Keep that benign text distinct from an unresolved monetary line.
    if code == "unclassified_page_text" and not any(_MONEY.search(_PERCENTAGE.sub("", raw)) for raw in raw_values):
        return "informational", "Additional page text is retained outside the extracted financial rows"
    if code == "unclassified_monetary_line" or code == "money_unresolved":
        return "requires_review", "A source line containing money has not been classified"
    if code == "summary_window_unclassified":
        return "requires_review", "A line within the account summary has not been classified"
    if code == "summary_window_tail_unclassified":
        return "requires_review", "Content after the account summary has not been classified"
    if code == "summary_extra_column":
        return "requires_review", "An additional account summary column has not been classified"
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
        if _printed_empty_hsa_cash_table(evidence):
            add(
                "no_activity_captured",
                "informational",
                "The printed cash table has no transactions and its balances agree",
            )
        elif _printed_empty_wells_loan_register(evidence):
            add(
                "no_activity_captured",
                "informational",
                "The printed principal register reports no transactions and its balances agree",
            )
        else:
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
                classification: WarningClassification = "requires_review"
                if code == "source_balance_check_unavailable" and _capital_auto_payment_without_opening(
                    evidence, account
                ):
                    classification = "informational"
                    message = (
                        "Opening principal is not printed; the closing principal and payment components are printed, "
                        "but the principal balance remains unverified"
                    )
                elif code == "source_balance_check_unavailable" and _capital_auto_origination_without_opening(
                    evidence, account
                ):
                    classification = "informational"
                    message = (
                        "Opening principal is not printed for this origination; the financed amount and closing principal agree, "
                        "but opening arithmetic remains unverified. Origination posting still requires separate review"
                    )
                add(
                    code,
                    classification,
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
