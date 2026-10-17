"""Located bank observations from declared anchored table cells and printed fields."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime

from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfLine,
    PdfTableRow,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)
from parsetrail.core.v2_anchored_table import (
    AnchoredRow,
    AnchoredTableEvidence,
    TableBankStatementRule,
    load_definition,
)
from parsetrail.core.v2_money_operations import USD_TRAILING_CREDIT_2DP, usd_trailing_credit_2dp_minor_v1
from parsetrail.core.v2_partial_dates import PartialDateError, resolve_month_day
from parsetrail.core.v2_pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence

ENGINE_VERSION = "table-bank-source-pilot-1"
DATE = re.compile(r"\d{2}/\d{2}\Z")
DATE_PREFIX = re.compile(r"\d{2}/\d{2}")
PERIOD_DATE = re.compile(r"\d{2}/\d{2}/\d{4}\Z")
MONEY_HINT = re.compile(r"\$\s*\d")


class TableBankError(ValueError):
    """Redacted refusal of incomplete table-bank source evidence."""


def _table_location(row: AnchoredRow) -> PdfTableRow:
    return PdfTableRow(kind="pdf_table_row", page=row.page, row=row.ordinal, region=row.region)


def _line_location(line: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=line.page, line=line.line)


def _money(raw: str) -> int:
    try:
        return usd_trailing_credit_2dp_minor_v1(raw)
    except ValueError:
        raise TableBankError("invalid_bank_money") from None


def _period_date(raw: str):
    if PERIOD_DATE.fullmatch(raw) is None:
        raise TableBankError("invalid_period_date")
    try:
        result = datetime.strptime(raw, "%m/%d/%Y").date()
    except ValueError:
        raise TableBankError("invalid_period_date") from None
    if result.strftime("%m/%d/%Y") != raw:
        raise TableBankError("invalid_period_date")
    return result


def _field(lines: PDFLineEvidence, label: str, pattern: str, code: str) -> tuple[PageLine, re.Match[str]]:
    expression = re.compile(re.escape(label) + r"\s*" + pattern)
    found = [(line, match) for line in lines.lines if (match := expression.search(line.normalized))]
    if len(found) != 1:
        raise TableBankError(code)
    return found[0]


def _printed_fields(rule: TableBankStatementRule, text: PDFLineEvidence):
    start_line, start_match = _field(text, rule.start_label, r"(?P<date>\d{2}/\d{2}/\d{4})(?:\s|$)", "start_field")
    end_line, end_match = _field(text, rule.end_label, r"(?P<date>\d{2}/\d{2}/\d{4})(?:\s|$)", "end_field")
    account_line, account_match = _field(text, rule.account_label, r"(?P<number>\d{10})(?:\s|$)", "account_field")
    summary_lines = [line for line in text.lines if line.normalized == rule.summary_label]
    if len(summary_lines) != 1:
        raise TableBankError("summary_header")
    header = summary_lines[0]
    following = [
        line for line in text.lines if line.page == header.page and line.line > header.line and line.normalized
    ]
    if not following:
        raise TableBankError("summary_values")
    summary_line = following[0]
    values = summary_line.normalized.split()
    if len(values) != 6 or any(USD_TRAILING_CREDIT_2DP.fullmatch(value) is None for value in values):
        raise TableBankError("summary_values")
    amounts = tuple(_money(value) for value in values)
    if amounts[0] + amounts[1] + amounts[2] - amounts[3] - amounts[4] != amounts[5]:
        raise TableBankError("printed_summary_equation")
    start, end = _period_date(start_match["date"]), _period_date(end_match["date"])
    if not 0 < (end - start).days <= 45:
        raise TableBankError("invalid_period")
    return (
        start,
        end,
        start_line,
        start_match,
        end_line,
        end_match,
        account_line,
        account_match,
        summary_line,
        values,
        amounts,
    )


def from_anchored_bank(definition_bytes: bytes, table: AnchoredTableEvidence, text: PDFLineEvidence) -> SourceEvidence:
    """Admit dated debit/credit rows with printed running and summary checks."""
    definition, definition_hash = load_definition(definition_bytes)
    rule = definition.statement
    if not isinstance(rule, TableBankStatementRule):
        raise TableBankError("missing_bank_statement_rule")
    if (
        table.definition_sha256 != definition_hash
        or table.source_sha256 != text.source_sha256
        or text.adapter_version != ADAPTER_VERSION
        or text.extraction_library != "pdfplumber-bounded-simple-v1"
        or len(table.pages) != text.page_count
    ):
        raise TableBankError("source_channel_mismatch")
    (
        start,
        end,
        start_line,
        start_match,
        end_line,
        end_match,
        account_line,
        account_match,
        summary_line,
        values,
        amounts,
    ) = _printed_fields(rule, text)
    account = account_match["number"]
    opening, closing = amounts[0], amounts[5]
    running = opening
    rows = []
    dispositions = []
    occurrences: Counter[tuple[str, int, str]] = Counter()
    saw_forward = False
    for source in table.rows:
        if len(source.raw_cells) != 5:
            raise TableBankError("table_columns")
        date_raw, description_raw, debit_raw, credit_raw, balance_raw = (cell.strip() for cell in source.raw_cells)
        location = _table_location(source)
        if not any((date_raw, description_raw, debit_raw, credit_raw, balance_raw)):
            dispositions.append(SourceDisposition(code="blank_table_row", location=location))
            continue
        if DATE.fullmatch(date_raw) is None:
            if DATE_PREFIX.search(date_raw):
                raise TableBankError("unresolved_dated_table_row")
            code = (
                "unclassified_monetary_table_row"
                if any(MONEY_HINT.search(c) for c in source.raw_cells)
                else "nonactivity_table_row"
            )
            dispositions.append(SourceDisposition(code=code, location=location, raw_values=source.raw_cells))
            continue
        if description_raw == rule.opening_row_label:
            if saw_forward or debit_raw or credit_raw or _money(balance_raw) != opening:
                raise TableBankError("balance_forward_mismatch")
            saw_forward = True
            dispositions.append(
                SourceDisposition(code="balance_forward", location=location, raw_values=source.raw_cells)
            )
            continue
        if not description_raw or bool(debit_raw) == bool(credit_raw) or not balance_raw:
            raise TableBankError("incomplete_activity_row")
        try:
            date = resolve_month_day(date_raw, start, end)
        except PartialDateError:
            raise TableBankError("invalid_activity_date") from None
        if not start <= date <= end:
            raise TableBankError("activity_outside_period")
        amount_raw = debit_raw or credit_raw
        amount = _money(amount_raw)
        if (debit_raw and amount >= 0) or (credit_raw and amount < 0):
            raise TableBankError("debit_credit_direction")
        running += amount
        printed_running = _money(balance_raw)
        if running != printed_running:
            raise TableBankError("printed_running_mismatch")
        description = " ".join(description_raw.split())
        key = (date.isoformat(), amount, description)
        occurrence = occurrences[key]
        occurrences[key] += 1
        rows.append(
            ObservationEvidence(
                row_id=hashlib.sha256(
                    f"{table.source_sha256}:{definition_hash}:{ENGINE_VERSION}:{source.page}:{source.ordinal}".encode()
                ).hexdigest(),
                occurrence=occurrence,
                row_role="activity",
                source_account=account,
                source_account_form="full",
                date_role="posting_date",
                date=DateValue(
                    raw=None,
                    iso=date.isoformat(),
                    provenance="derived",
                    locations=(location, _line_location(start_line)),
                ),
                transaction_date=None,
                description=TextValue(
                    raw=description_raw, text=description, provenance="observed", locations=(location,)
                ),
                amount=MoneyValue(raw=amount_raw, minor=amount, provenance="observed", locations=(location,)),
                running_balance=MoneyValue(
                    raw=balance_raw, minor=printed_running, provenance="observed", locations=(location,)
                ),
                components=(),
                fragments=(
                    SourceFragment(channel="anchored_table_row", location=location, raw_values=source.raw_cells),
                ),
            )
        )
    if not saw_forward or not rows or running != closing:
        raise TableBankError("printed_balance_chain")
    return SourceEvidence(
        schema_version=2,
        source_sha256=table.source_sha256,
        definition_sha256=definition_hash,
        parser_id=definition.parser_id,
        definition_revision=definition.revision,
        engine_version=ENGINE_VERSION,
        extractor_version=table.extraction_library + "+" + text.adapter_version,
        payload=StatementPayload(
            kind="statement",
            start=DateValue(
                raw=start_match["date"],
                iso=start.isoformat(),
                provenance="observed",
                locations=(_line_location(start_line),),
            ),
            end=DateValue(
                raw=end_match["date"], iso=end.isoformat(), provenance="observed", locations=(_line_location(end_line),)
            ),
            accounts=(
                StatementAccount(
                    source_identity=account,
                    source_identity_form="full",
                    balance_scope="account_total",
                    identity_locations=(_line_location(account_line),),
                    opening=MoneyValue(
                        raw=values[0], minor=opening, provenance="observed", locations=(_line_location(summary_line),)
                    ),
                    closing=MoneyValue(
                        raw=values[5], minor=closing, provenance="observed", locations=(_line_location(summary_line),)
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )
