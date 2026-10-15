"""Printed Wells personal-loan allocations without synthetic periods or payments."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime
from typing import Literal

from parsetrail.core.source_evidence import (
    ComponentEvidence,
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfLine,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1
from devtools.parser_engine_pilot.pdf_lines import PageLine, PDFLineEvidence

ENGINE_VERSION = "wells-loan-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.\d{2}"
DATE = r"\d{2}/\d{2}/\d{2}"
DATE_START = re.compile(rf"^{DATE}\s")


class WellsLoanError(ValueError):
    """Redacted refusal of incomplete Wells loan source evidence."""


class WellsLoanDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["printed_principal_allocations_v1"]
    date_format: Literal["MM/DD/YY"]
    money_format: Literal["usd_symbol_2dp"]
    balance_scope: Literal["principal_component"]
    account_label: str = Field(min_length=1, max_length=80)
    statement_date_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    interest_label: str = Field(min_length=1, max_length=80)
    principal_label: str = Field(min_length=1, max_length=80)
    max_activity_rows: int = Field(ge=1, le=100)

    @model_validator(mode="after")
    def valid_labels(self) -> WellsLoanDefinition:
        labels = (
            self.account_label,
            self.statement_date_label,
            self.opening_label,
            self.closing_label,
            self.interest_label,
            self.principal_label,
        )
        if len(set(labels)) != len(labels) or any(label != label.strip() or "\n" in label for label in labels):
            raise ValueError("invalid loan labels")
        return self


def load_definition(data: bytes) -> tuple[WellsLoanDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise WellsLoanError("definition_size")
    try:
        definition = WellsLoanDefinition.model_validate_json(data)
    except ValidationError:
        raise WellsLoanError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    if re.fullmatch(MONEY, raw) is None:
        raise WellsLoanError("invalid_loan_money")
    try:
        return usd_symbol_minor_v1(raw)
    except ValueError:
        raise WellsLoanError("invalid_loan_money") from None


def _date(raw: str):
    try:
        parsed = datetime.strptime(raw, "%m/%d/%y").date()
    except ValueError:
        raise WellsLoanError("invalid_loan_date") from None
    if parsed.strftime("%m/%d/%y") != raw:
        raise WellsLoanError("invalid_loan_date")
    return parsed


def _one(matches, code: str):
    if len(matches) != 1:
        raise WellsLoanError(code)
    return matches[0]


def parse_wells_loan(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Preserve printed interest/principal lines and verify only principal balance."""
    definition, definition_hash = load_definition(definition_bytes)
    account_pattern = re.compile(rf"\b{re.escape(definition.account_label)}\s+(?P<account>\d{{8,20}})\b")
    date_pattern = re.compile(rf"\b{re.escape(definition.statement_date_label)}\s+(?P<date>{DATE})(?=\s|$)")
    opening_pattern = re.compile(rf"\b{re.escape(definition.opening_label)}\s+(?P<amount>{MONEY})(?=\s|$)")
    closing_pattern = re.compile(
        rf"^(?P<date>{DATE})\s+{re.escape(definition.closing_label)}\s+(?P<amount>{MONEY})\*(?=\s|$)"
    )
    row_pattern = re.compile(
        rf"^(?P<date>{DATE})\s+(?P<label>{re.escape(definition.interest_label)}|"
        rf"{re.escape(definition.principal_label)})\s+(?P<amount>{MONEY})$"
    )
    accounts = [(line, match) for line in lines.lines if (match := account_pattern.search(line.normalized))]
    if not accounts or len({match["account"] for _, match in accounts}) != 1:
        raise WellsLoanError("missing_or_ambiguous_account")
    account_line, account_match = accounts[0]
    statement_line, statement_match = _one(
        [(line, match) for line in lines.lines if (match := date_pattern.search(line.normalized))],
        "missing_or_ambiguous_statement_date",
    )
    opening_line, opening_match = _one(
        [(line, match) for line in lines.lines if (match := opening_pattern.search(line.normalized))],
        "missing_or_ambiguous_opening",
    )
    closings = [
        (index, line, match)
        for index, line in enumerate(lines.lines)
        if (match := closing_pattern.match(line.normalized))
    ]
    closing_index, closing_line, closing_match = _one(closings, "missing_or_ambiguous_closing")
    end = _date(statement_match["date"])
    if _date(closing_match["date"]) != end:
        raise WellsLoanError("closing_date_mismatch")
    opening, closing = -_money(opening_match["amount"]), -_money(closing_match["amount"])
    rows = []
    occurrences: Counter[tuple[str, str, int]] = Counter()
    for line in lines.lines[:closing_index]:
        if not DATE_START.match(line.normalized):
            continue
        match = row_pattern.fullmatch(line.normalized)
        if match is None:
            raise WellsLoanError("unresolved_dated_loan_row")
        if len(rows) >= definition.max_activity_rows:
            raise WellsLoanError("activity_row_limit")
        date = _date(match["date"])
        if date > end:
            raise WellsLoanError("activity_after_statement_date")
        amount = _money(match["amount"])
        label = match["label"]
        role = "principal" if label == definition.principal_label else "interest"
        location = _location(line)
        key = (date.isoformat(), label, amount)
        occurrence = occurrences[key]
        occurrences[key] += 1
        money = MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,))
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account_match["account"],
                source_account_form="full",
                date_role="activity_date",
                date=DateValue(raw=match["date"], iso=date.isoformat(), provenance="observed", locations=(location,)),
                transaction_date=None,
                description=TextValue(raw=label, text=label, provenance="observed", locations=(location,)),
                amount=money,
                running_balance=None,
                components=(ComponentEvidence(role=role, amount=money),),
                fragments=(SourceFragment(channel="loan_allocation_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if opening + sum(row.amount.minor for row in rows if row.components[0].role == "principal") != closing:
        raise WellsLoanError("printed_principal_equation")
    dispositions = tuple(
        SourceDisposition(code="repeated_account_identity", location=_location(line), raw_values=(line.raw,))
        for line, _ in accounts[1:]
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=lines.extraction_library + "+" + lines.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(raw=None, iso=None, provenance="unknown", locations=()),
            end=DateValue(
                raw=statement_match["date"],
                iso=end.isoformat(),
                provenance="observed",
                locations=(_location(statement_line), _location(closing_line)),
            ),
            accounts=(
                StatementAccount(
                    source_identity=account_match["account"],
                    source_identity_form="full",
                    balance_scope="principal_component",
                    identity_locations=tuple(_location(line) for line, _ in accounts[:16]),
                    opening=MoneyValue(
                        raw=opening_match["amount"],
                        minor=opening,
                        provenance="observed",
                        locations=(_location(opening_line),),
                    ),
                    closing=MoneyValue(
                        raw=closing_match["amount"],
                        minor=closing,
                        provenance="observed",
                        locations=(_location(closing_line),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=dispositions,
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )
