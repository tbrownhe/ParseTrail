"""Finite OCCU card evidence from bounded default-layout PDF text."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from parsetrail.core.source_evidence import (
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

from devtools.parser_engine_pilot.money_operations import usd_or_decimal_2dp_minor_v1
from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_month_day
from devtools.parser_engine_pilot.pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence

ENGINE_VERSION = "occu-card-lines-pilot-1"
MAX_DEFINITION_BYTES = 64 * 1024
MONEY = r"-?\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
DOLLAR_MONEY = r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
DATED = re.compile(r"^\d{2}/\d{2}\s")
ROW = re.compile(
    rf"^(?P<posting>\d{{2}}/\d{{2}})\s+(?:(?P<transaction>\d{{2}}/\d{{2}})\s+)?"
    rf"(?P<description>.+?)\s+(?P<amount>{MONEY})$"
)


class OccuCardError(ValueError):
    """Redacted refusal of unsupported or conflicting card source evidence."""


class OccuCardDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1]
    parser_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    revision: str = Field(pattern=r"^[1-9][0-9]{0,8}$")
    suffix: Literal[".pdf"]
    kind: Literal["statement"]
    operation: Literal["card_header_charge_v1"]
    text_channel: Literal["pdf_default_layout_v1"]
    date_format: Literal["MM/DD+MM/DD/YY"]
    money_format: Literal["signed_usd_2dp"]
    amount_direction: Literal["invert_for_liability"]
    account_label: str = Field(min_length=1, max_length=80)
    closing_date_label: str = Field(min_length=1, max_length=80)
    cycle_days_label: str = Field(min_length=1, max_length=80)
    opening_label: str = Field(min_length=1, max_length=80)
    closing_label: str = Field(min_length=1, max_length=80)
    interest_label: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def finite_labels(self) -> OccuCardDefinition:
        labels = (
            self.account_label,
            self.closing_date_label,
            self.cycle_days_label,
            self.opening_label,
            self.closing_label,
            self.interest_label,
        )
        if len(set(labels)) != len(labels) or any(
            label != label.strip() or "\n" in label or "\r" in label for label in labels
        ):
            raise ValueError("invalid labels")
        return self


def load_definition(data: bytes) -> tuple[OccuCardDefinition, str]:
    if type(data) is not bytes or not 0 < len(data) <= MAX_DEFINITION_BYTES:
        raise OccuCardError("definition_size")
    try:
        definition = OccuCardDefinition.model_validate_json(data)
    except ValidationError:
        raise OccuCardError("invalid_definition") from None
    return definition, hashlib.sha256(data).hexdigest()


def _location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _one(matches: list[tuple[PageLine, re.Match[str]]], code: str) -> tuple[PageLine, re.Match[str]]:
    if len(matches) != 1:
        raise OccuCardError(code)
    return matches[0]


def _money(raw: str) -> int:
    try:
        return usd_or_decimal_2dp_minor_v1(raw)
    except ValueError:
        raise OccuCardError("invalid_card_money") from None


def parse_occu_card(definition_bytes: bytes, lines: PDFLineEvidence) -> SourceEvidence:
    """Record dated rows and the separately printed header interest charge."""
    definition, definition_hash = load_definition(definition_bytes)
    if lines.adapter_version != ADAPTER_VERSION or lines.extraction_library != "pdfplumber-bounded-layout-default-v1":
        raise OccuCardError("source_channel_mismatch")
    account_pattern = re.compile(rf"^{re.escape(definition.account_label)} (?P<mask>X{{12}}(?P<suffix>\d{{4}}))$")
    closing_date_pattern = re.compile(
        rf"^{re.escape(definition.closing_date_label)}\s+(?P<date>\d{{2}}/\d{{2}}/\d{{2}})(?:\s|$)"
    )
    days_pattern = re.compile(rf"^{re.escape(definition.cycle_days_label)}\s+(?P<days>\d{{1,2}})(?:\s|$)")
    opening_pattern = re.compile(rf"^{re.escape(definition.opening_label)}\s+(?P<amount>{DOLLAR_MONEY})(?:\s|$)")
    closing_pattern = re.compile(rf"^{re.escape(definition.closing_label)}\s+(?P<amount>{MONEY})(?:\s|$)")
    interest_pattern = re.compile(rf"^{re.escape(definition.interest_label)}\s+\+\s+(?P<amount>{MONEY})(?:\s|$)")
    account_line, account_match = _one(
        [(line, match) for line in lines.lines if (match := account_pattern.match(line.normalized))],
        "missing_or_ambiguous_account",
    )
    date_line, date_match = _one(
        [(line, match) for line in lines.lines if (match := closing_date_pattern.match(line.normalized))],
        "missing_or_ambiguous_closing_date",
    )
    days_line, days_match = _one(
        [(line, match) for line in lines.lines if (match := days_pattern.match(line.normalized))],
        "missing_or_ambiguous_cycle_days",
    )
    opening_line, opening_match = _one(
        [(line, match) for line in lines.lines if (match := opening_pattern.match(line.normalized))],
        "missing_or_ambiguous_opening",
    )
    rewards_headings = [index for index, line in enumerate(lines.lines) if line.normalized == "RewardsPointsSummary"]
    if len(rewards_headings) != 1:
        raise OccuCardError("missing_or_ambiguous_rewards_section")
    rewards_index = rewards_headings[0]
    rewards_previous = [
        line
        for line in lines.lines[rewards_index + 1 : rewards_index + 4]
        if re.fullmatch(r"PreviousBalance [0-9,]+\.[0-9]{2}", line.normalized)
    ]
    if len(rewards_previous) != 1:
        raise OccuCardError("missing_or_ambiguous_rewards_balance")
    interest_line, interest_match = _one(
        [(line, match) for line in lines.lines if (match := interest_pattern.match(line.normalized))],
        "missing_or_ambiguous_interest",
    )
    closings = [(line, match) for line in lines.lines if (match := closing_pattern.match(line.normalized))]
    if not closings or len(closings) > 2:
        raise OccuCardError("missing_or_ambiguous_closing")
    closing_line, closing_match = closings[0]
    closing_source = _money(closing_match["amount"])
    if any(_money(match["amount"]) != closing_source for _, match in closings):
        raise OccuCardError("conflicting_printed_closing")
    try:
        month, day, year = map(int, date_match["date"].split("/"))
        end = datetime(2000 + year, month, day).date()
        days = int(days_match["days"])
    except ValueError:
        raise OccuCardError("invalid_period") from None
    if not 2 <= days <= 40:
        raise OccuCardError("invalid_period")
    start = end - timedelta(days=days - 1)
    suffix = account_match["suffix"]
    opening, closing = -_money(opening_match["amount"]), -closing_source
    rows = []
    occurrences: Counter[tuple[str, str | None, int, str]] = Counter()
    for line in lines.lines:
        if DATED.match(line.normalized) is None:
            continue
        if len(line.normalized) > 512 or (match := ROW.fullmatch(line.normalized)) is None:
            raise OccuCardError("unresolved_dated_line")
        try:
            posting = resolve_month_day(match["posting"], start, end)
            transaction = resolve_month_day(match["transaction"], start, end) if match["transaction"] else None
        except PartialDateError:
            raise OccuCardError("invalid_activity_date") from None
        if not start <= posting <= end:
            raise OccuCardError("posting_outside_period")
        amount = -_money(match["amount"])
        description = match["description"]
        location = _location(line)
        key = (posting.isoformat(), transaction.isoformat() if transaction else None, amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{line.line_id}".encode()).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=suffix,
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(
                    raw=None, iso=posting.isoformat(), provenance="derived", locations=(location, _location(date_line))
                ),
                transaction_date=(
                    DateValue(
                        raw=None,
                        iso=transaction.isoformat(),
                        provenance="derived",
                        locations=(location, _location(date_line)),
                    )
                    if transaction
                    else None
                ),
                description=TextValue(raw=description, text=description, provenance="observed", locations=(location,)),
                amount=MoneyValue(raw=match["amount"], minor=amount, provenance="observed", locations=(location,)),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="card_layout_line", location=location, raw_values=(line.raw,)),),
            )
        )
    interest_location = _location(interest_line)
    interest_amount = -_money(interest_match["amount"])
    rows.append(
        ObservationEvidence(
            row_id=hashlib.sha256(f"{definition_hash}:{ENGINE_VERSION}:{interest_line.line_id}".encode()).hexdigest(),
            occurrence=0,
            row_role="header_charge",
            source_account=suffix,
            source_account_form="last_four",
            date_role="statement_period_end",
            date=DateValue(
                raw=None, iso=end.isoformat(), provenance="derived", locations=(interest_location, _location(date_line))
            ),
            transaction_date=None,
            description=TextValue(
                raw=None, text="Interest Charged", provenance="derived", locations=(interest_location,)
            ),
            amount=MoneyValue(
                raw=interest_match["amount"],
                minor=interest_amount,
                provenance="observed",
                locations=(interest_location,),
            ),
            running_balance=None,
            components=(),
            fragments=(
                SourceFragment(channel="card_header_line", location=interest_location, raw_values=(interest_line.raw,)),
            ),
        )
    )
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise OccuCardError("printed_card_balance_equation")
    interest_headings = [line for line in lines.lines if line.normalized == definition.interest_label]
    if len(interest_headings) != 1:
        raise OccuCardError("missing_or_ambiguous_interest_section")
    dispositions = (
        (
            SourceDisposition(
                code="rewards_points_previous_balance",
                location=_location(rewards_previous[0]),
                raw_values=(rewards_previous[0].raw,),
            ),
        )
        + tuple(
            SourceDisposition(code="repeated_closing_balance", location=_location(line), raw_values=(line.raw,))
            for line, _ in closings[1:]
        )
        + (
            SourceDisposition(
                code="interest_section_heading",
                location=_location(interest_headings[0]),
                raw_values=(interest_headings[0].raw,),
            ),
        )
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=lines.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version="pdfplumber-bounded-layout-default-v1+" + lines.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(
                raw=None,
                iso=start.isoformat(),
                provenance="derived",
                locations=(_location(date_line), _location(days_line)),
            ),
            end=DateValue(
                raw=date_match["date"], iso=end.isoformat(), provenance="observed", locations=(_location(date_line),)
            ),
            accounts=(
                StatementAccount(
                    source_identity=suffix,
                    source_identity_form="last_four",
                    balance_scope="account_total",
                    identity_locations=(_location(account_line),),
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
