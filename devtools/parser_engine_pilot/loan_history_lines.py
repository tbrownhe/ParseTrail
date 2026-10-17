"""Finite loan history section with printed components and unknown opening."""

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
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_pdf_lines import PageLine, PDFLineEvidence
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ENGINE_VERSION = "loan-history-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
DATE = r"\d{2}/\d{2}/\d{4}"


class LoanHistoryError(ValueError):
    """Redacted refusal of unsupported loan history evidence."""


class LoanHistoryDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["printed_loan_history_components_v1"]
    date_format: Literal["MM/DD/YYYY"]
    money_format: Literal["signed_usd_2dp"]
    balance_scope: Literal["principal_component"]
    account_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    history_label: str = Field(min_length=1, max_length=80)
    history_end: str = Field(min_length=1, max_length=120)
    header_without_interest: str = Field(min_length=1, max_length=120)
    header_with_interest: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def finite_labels(self) -> LoanHistoryDefinition:
        labels = (
            self.account_label,
            self.closing_label,
            self.history_label,
            self.history_end,
            self.header_without_interest,
            self.header_with_interest,
        )
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[LoanHistoryDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise LoanHistoryError("definition_size")
    try:
        definition = LoanHistoryDefinition.model_validate_json(data)
    except ValidationError:
        raise LoanHistoryError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    if re.fullmatch(MONEY, raw) is None:
        raise LoanHistoryError("invalid_history_money")
    try:
        return usd_symbol_minor_v1(raw)
    except ValueError:
        raise LoanHistoryError("invalid_history_money") from None


def _date(raw: str):
    try:
        parsed = datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        raise LoanHistoryError("invalid_history_date") from None
    if parsed.strftime("%m/%d/%Y") != raw:
        raise LoanHistoryError("invalid_history_date")
    return parsed


def parse_loan_history(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Keep principal and interest source components without inventing an opening."""
    definition, definition_hash = load_definition(definition_bytes)
    account_pattern = re.compile(rf"\b{re.escape(definition.account_label)}\s*(?P<account>\d{{8,20}})\b")
    balance_pattern = re.compile(rf"\b{re.escape(definition.closing_label)}\s*(?P<amount>{MONEY})\b")
    history_pattern = re.compile(rf"^{re.escape(definition.history_label)}\s+(?P<start>{DATE})\s+-\s+(?P<end>{DATE})$")
    accounts = [(line, match) for line in lines.lines if (match := account_pattern.search(line.normalized))]
    identities = {match["account"] for _, match in accounts}
    if not accounts or len(identities) != 1:
        raise LoanHistoryError("missing_or_ambiguous_account")
    account = next(iter(identities))
    balances = [(line, match) for line in lines.lines if (match := balance_pattern.search(line.normalized))]
    histories = [
        (index, line, match)
        for index, line in enumerate(lines.lines)
        if (match := history_pattern.fullmatch(line.normalized))
    ]
    if len(balances) != 1 or len(histories) != 1:
        raise LoanHistoryError("missing_or_ambiguous_history_fields")
    balance_line, balance_match = balances[0]
    history_index, history_line, history_match = histories[0]
    start, end = _date(history_match["start"]), _date(history_match["end"])
    if not start < end or (end - start).days > 370:
        raise LoanHistoryError("invalid_history_period")
    if history_index + 1 >= len(lines.lines):
        raise LoanHistoryError("missing_history_header")
    header = lines.lines[history_index + 1]
    if header.normalized not in {definition.header_with_interest, definition.header_without_interest}:
        raise LoanHistoryError("unsupported_history_header")
    has_interest = header.normalized == definition.header_with_interest
    ends = [
        index
        for index in range(history_index + 2, len(lines.lines))
        if lines.lines[index].normalized == definition.history_end
    ]
    if not ends:
        raise LoanHistoryError("missing_history_end")
    history_end_index = ends[0]
    if history_end_index - history_index > 10_000:
        raise LoanHistoryError("history_window_limit")
    pattern = re.compile(
        rf"^(?P<date>{DATE})\s+(?P<description>.+?)\s+(?P<principal>{MONEY})\s+"
        + (rf"(?P<interest>{MONEY})\s+" if has_interest else "")
        + rf"=\s+(?P<total>{MONEY})$"
    )
    rows = []
    dispositions = [
        SourceDisposition(code="history_header", location=_location(header), raw_values=(header.raw,)),
        SourceDisposition(
            code="history_end_marker",
            location=_location(lines.lines[history_end_index]),
            raw_values=(lines.lines[history_end_index].raw,),
        ),
    ]
    occurrences: Counter[tuple[str, str, int]] = Counter()
    for line in lines.lines[history_index + 2 : history_end_index]:
        if not line.normalized or line.normalized == header.normalized:
            dispositions.append(
                SourceDisposition(
                    code="history_blank_or_repeated_header", location=_location(line), raw_values=(line.raw,)
                )
            )
            continue
        if len(line.normalized) > 512 or (match := pattern.fullmatch(line.normalized)) is None:
            raise LoanHistoryError("unresolved_history_row")
        activity_date = _date(match["date"])
        if not start <= activity_date <= end:
            raise LoanHistoryError("history_row_outside_period")
        principal = _money(match["principal"])
        interest = _money(match["interest"]) if has_interest else 0
        total = _money(match["total"])
        if principal + interest != total:
            raise LoanHistoryError("printed_component_equation")
        description = match["description"]
        location = _location(line)
        key = (activity_date.isoformat(), description, total)
        occurrence = occurrences[key]
        occurrences[key] += 1
        components = [
            ComponentEvidence(
                role="principal",
                amount=MoneyValue(
                    raw=match["principal"], minor=principal, provenance="observed", locations=(location,)
                ),
            )
        ]
        if has_interest:
            components.append(
                ComponentEvidence(
                    role="interest",
                    amount=MoneyValue(
                        raw=match["interest"], minor=interest, provenance="observed", locations=(location,)
                    ),
                )
            )
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account,
                source_account_form="full",
                date_role="activity_date",
                date=DateValue(
                    raw=match["date"], iso=activity_date.isoformat(), provenance="observed", locations=(location,)
                ),
                transaction_date=None,
                description=TextValue(raw=description, text=description, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=match["total"], minor=total, provenance="observed", locations=(location,)),
                running_balance=None,
                components=tuple(components),
                fragments=(SourceFragment(channel="loan_history_line", location=location, raw_values=(line.raw,)),),
            )
        )
    if not rows:
        raise LoanHistoryError("empty_history")
    closing_raw = balance_match["amount"]
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
            start=DateValue(
                raw=history_match["start"],
                iso=start.isoformat(),
                provenance="observed",
                locations=(_location(history_line),),
            ),
            end=DateValue(
                raw=history_match["end"],
                iso=end.isoformat(),
                provenance="observed",
                locations=(_location(history_line),),
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
                    source_identity_form="full",
                    balance_scope=definition.balance_scope,
                    identity_locations=tuple(_location(line) for line, _ in accounts),
                    opening=None,
                    closing=MoneyValue(
                        raw=closing_raw,
                        minor=_money(closing_raw),
                        provenance="observed",
                        locations=(_location(balance_line),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=False,
        ),
    )
