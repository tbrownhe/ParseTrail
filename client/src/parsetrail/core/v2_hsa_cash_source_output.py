"""Map bounded HSA cash-section evidence into scoped V2 source evidence."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime

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
from parsetrail.core.v2_hsa_cash_lines import CashField, HsaCashEvidence
from parsetrail.core.v2_pdf_lines import PDFLineEvidence

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"
)
_FINANCIAL_OR_DATE = re.compile(
    r"\$|(?<!\d)\d[\d,]*\.\d{2}(?!\d)|(?<!\d)\d{1,4}[-/]\d{1,2}(?:[-/]\d{1,4})?(?!\d)"
    rf"|\b{_MONTH}[ .-]*\d{{1,2}}(?:st|nd|rd|th)?(?:[, .-]*\d{{4}})?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?[ .-]*{_MONTH}(?:[, .-]*\d{{4}})?\b"
    rf"|\b\d{{4}}[ .-]*{_MONTH}[ .-]*\d{{1,2}}\b",
    re.IGNORECASE,
)
_USD = r"\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
_RATE = r"[0-9]{1,2}\.[0-9]{1,4}%"
# An empty cash table cannot explain a nonzero current-period fee. The second
# printed fee column is year to date and can legitimately remain nonzero.
_FEES = rf"(?:TotalOverdraftFees|TotalNon-SufficientFundsFees|TotalReturnDepositItemFees) \$0\.00 {_USD}"
_RATE_TIER = rf"(?:{_USD}-{_USD}|Over\$[0-9][0-9,]*) {_RATE}"
_RATE_ROW = re.compile(rf"(?:{_RATE_TIER}(?: {_USD} Total| {_FEES})?|{_FEES})\Z")


def _valid_printed_date(raw: str) -> bool:
    try:
        return datetime.strptime(raw, "%m/%d/%y").strftime("%m/%d/%y") == raw
    except ValueError:
        return False


def _framed_rate_totals(lines: PDFLineEvidence, closing_index: int) -> set[str]:
    """Require the complete located interleaved rate/fee frame for bare totals."""
    headers = [index for index, line in enumerate(lines.lines) if line.normalized == "Interest AverageDaily Interest"]
    if len(headers) != 1 or headers[0] != closing_index + 2:
        return set()
    block = lines.lines[headers[0] - 1 : headers[0] + 12]
    if len(block) != 13 or any(line.page != lines.lines[closing_index].page for line in block):
        return set()
    raw = [line.normalized for line in block]
    if (
        re.fullmatch(r"InterestRateScheduleEffective:\d{2}/\d{2}/\d{2}", raw[0]) is None
        or not _valid_printed_date(raw[0][-8:])
        or raw[1:5] != ["Interest AverageDaily Interest", "BalanceTier", "Rate Balance Earned YeartoDate", "Period"]
    ):
        return set()
    patterns = (
        rf"{_USD}-{_USD} {_RATE} {_USD} Total",
        rf"{_USD}-{_USD} {_RATE} TotalOverdraftFees \$0\.00 {_USD}",
        rf"{_USD}-{_USD} {_RATE}",
        rf"TotalNon-SufficientFundsFees \$0\.00 {_USD}",
        rf"Over\$[0-9][0-9,]* {_RATE}",
        rf"TotalReturnDepositItemFees \$0\.00 {_USD}",
        rf"Total {_USD}",
        rf"Fundsarecurrentlyheldat[A-Za-z]+ Total {_USD} {_USD}",
    )
    if any(re.fullmatch(pattern, value) is None for pattern, value in zip(patterns, raw[5:], strict=True)):
        return set()
    return {block[11].line_id, block[12].line_id}


def _empty_cash_dispositions(evidence: HsaCashEvidence, lines: PDFLineEvidence) -> list[SourceDisposition]:
    """Locate an actually empty table; equal balances alone do not establish it.

    Only the four adjacent, same-page printed table lines establish the empty
    cash-table role. Other money/date-shaped source text is retained separately;
    this finite source-shape check does not establish complete source capture.
    """
    if evidence.rows:
        return []
    result = []
    positions = {line.line_id: index for index, line in enumerate(lines.lines)}
    first = positions[evidence.printed_opening_minor.source_line_id]
    last = positions[evidence.printed_closing_minor.source_line_id]
    closing = lines.lines[last]
    framed_totals = _framed_rate_totals(lines, last)
    proof_lines = set()
    if (
        first >= 2
        and last == first + 1
        and lines.lines[first - 2].page == closing.page
        and lines.lines[first - 2].normalized.lstrip("_ ") == "Depositor Account"
        and lines.lines[first - 1].normalized.lstrip("_ ") == "Date DescriptionofTransaction (Withdrawal) Balance"
        and evidence.printed_opening_minor.normalized == evidence.printed_closing_minor.normalized
    ):
        heading = lines.lines[first - 1]
        result.append(
            SourceDisposition(
                code="hsa_empty_cash_table",
                location=PdfLine(kind="pdf_line", page=heading.page, line=heading.line),
                raw_values=(heading.raw,),
            )
        )
        proof_lines = {line.line_id for line in lines.lines[first - 2 : last + 1]}
    # Fields already retained by the envelope are removed exactly, so an extra
    # monetary/date tail on their lines cannot inherit the field's known role.
    fields = (
        evidence.account_identity,
        evidence.period_start,
        evidence.period_end,
        evidence.printed_opening_minor,
        evidence.printed_closing_minor,
    )
    for line in lines.lines:
        if first < positions[line.line_id] < last or line.line_id in proof_lines:
            continue
        raw = line.normalized.lstrip("_ ")
        for field in fields:
            if field.source_line_id == line.line_id:
                raw = raw.replace(field.raw, "", 1)
        if not _FINANCIAL_OR_DATE.search(raw):
            continue
        code = "hsa_exterior_unclassified"
        if _RATE_ROW.fullmatch(raw) or line.line_id in framed_totals:
            code = "hsa_cash_rate_fee_information"
        elif re.fullmatch(r"InterestRateScheduleEffective:\d{2}/\d{2}/\d{2}", raw) and _valid_printed_date(raw[-8:]):
            code = "hsa_cash_statement_dates"
        elif re.fullmatch(r"[^$]*StatementPrintDate:\d{2}/\d{2}/\d{2}", raw):
            prefix = raw.rsplit("StatementPrintDate:", 1)[0]
            if not _FINANCIAL_OR_DATE.search(prefix) and _valid_printed_date(raw[-8:]):
                code = "hsa_cash_statement_dates"
        result.append(
            SourceDisposition(
                code=code,
                location=PdfLine(kind="pdf_line", page=line.page, line=line.line),
                raw_values=(line.raw,),
            )
        )
    return result


def _location(field: CashField) -> PdfLine:
    return PdfLine(kind="pdf_line", page=field.page, line=field.line)


def from_hsa_cash(evidence: HsaCashEvidence, lines: PDFLineEvidence) -> SourceEvidence:
    """Retain the cash chain and every unclassified line without claiming total HSA value."""
    if (
        evidence.output_schema_version != 1
        or evidence.source_sha256 != lines.source_sha256
        or evidence.line_adapter_version != lines.adapter_version
        or evidence.extraction_library != lines.extraction_library
        or not evidence.cash_chain_verified
    ):
        raise ValueError("unsupported_hsa_cash_evidence")
    source_lines = {(line.page, line.line): line.raw for line in lines.lines}
    if len(source_lines) != len(lines.lines):
        raise ValueError("duplicate_hsa_line_location")
    account = evidence.account_identity
    for field in (
        account,
        evidence.period_start,
        evidence.period_end,
        evidence.printed_opening_minor,
        evidence.printed_closing_minor,
    ):
        if field.raw not in source_lines.get((field.page, field.line), ""):
            raise ValueError("hsa_printed_field_location")
    account_id = str(account.normalized)
    account_form = "full" if account_id.isdigit() and len(account_id) > 4 else "opaque"
    rows = []
    occurrences: Counter[tuple[str, str, str, str]] = Counter()
    for row in evidence.rows:
        location = _location(row.date)
        if any(
            (field.page, field.line) != (location.page, location.line)
            for field in (row.description, row.amount_minor, row.printed_running_minor)
        ):
            raise ValueError("hsa_row_location_mismatch")
        raw_line = source_lines.get((location.page, location.line))
        if (
            raw_line is None
            or any(field.raw not in raw_line for field in (row.date, row.amount_minor, row.printed_running_minor))
            or row.description.raw not in " ".join(raw_line.split())
        ):
            raise ValueError("hsa_row_source_mismatch")
        key = (row.date.raw, row.description.raw, row.amount_minor.raw, row.printed_running_minor.raw)
        occurrence = occurrences[key]
        occurrences[key] += 1
        description = (
            TextValue(
                raw=row.description.raw,
                text=str(row.description.normalized),
                provenance="observed",
                locations=(location,),
            )
            if row.description.normalized is not None
            else TextValue(raw=row.description.raw, text=None, provenance="unknown", locations=(location,))
        )
        rows.append(
            ObservationEvidence(
                row_role="activity",
                row_id=row.row_id,
                occurrence=occurrence,
                source_account=account_id,
                source_account_form=account_form,
                date_role="posting_date",
                date=DateValue(
                    raw=row.date.raw, iso=str(row.date.normalized), provenance="observed", locations=(location,)
                ),
                transaction_date=None,
                description=description,
                amount=MoneyValue(
                    raw=row.amount_minor.raw,
                    minor=int(row.amount_minor.normalized),
                    provenance="observed",
                    locations=(location,),
                ),
                running_balance=MoneyValue(
                    raw=row.printed_running_minor.raw,
                    minor=int(row.printed_running_minor.normalized),
                    provenance="observed",
                    locations=(location,),
                ),
                components=(),
                fragments=(SourceFragment(channel="hsa_cash_line", location=location, raw_values=(raw_line,)),),
            )
        )
    dispositions = []
    for item in evidence.unresolved_section_lines:
        raw = source_lines.get((item.page, item.line))
        if raw != item.raw:
            raise ValueError("hsa_unclassified_line_mismatch")
        dispositions.append(
            SourceDisposition(
                code=item.reason,
                location=PdfLine(kind="pdf_line", page=item.page, line=item.line),
                raw_values=(raw,),
            )
        )
    dispositions.extend(_empty_cash_dispositions(evidence, lines))
    payload = StatementPayload(
        kind="statement",
        start=DateValue(
            raw=evidence.period_start.raw,
            iso=str(evidence.period_start.normalized),
            provenance="observed",
            locations=(_location(evidence.period_start),),
        ),
        end=DateValue(
            raw=evidence.period_end.raw,
            iso=str(evidence.period_end.normalized),
            provenance="observed",
            locations=(_location(evidence.period_end),),
        ),
        accounts=(
            StatementAccount(
                source_identity=account_id,
                source_identity_form=account_form,
                balance_scope="cash_component",
                identity_locations=(_location(account),),
                opening=MoneyValue(
                    raw=evidence.printed_opening_minor.raw,
                    minor=int(evidence.printed_opening_minor.normalized),
                    provenance="observed",
                    locations=(_location(evidence.printed_opening_minor),),
                ),
                closing=MoneyValue(
                    raw=evidence.printed_closing_minor.raw,
                    minor=int(evidence.printed_closing_minor.normalized),
                    provenance="observed",
                    locations=(_location(evidence.printed_closing_minor),),
                ),
                rows=tuple(rows),
            ),
        ),
        dispositions=tuple(dispositions),
        capture_verified=False,
        independent_balance_verified=True,
    )
    return SourceEvidence(
        schema_version=2,
        source_sha256=evidence.source_sha256,
        definition_sha256=evidence.definition_sha256,
        parser_id=evidence.parser_id,
        definition_revision=evidence.definition_revision,
        engine_version=evidence.engine_version,
        extractor_version=evidence.extraction_library + "+" + evidence.line_adapter_version,
        payload=payload,
    )
