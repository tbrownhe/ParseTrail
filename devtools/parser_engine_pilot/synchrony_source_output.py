"""Strict Synchrony card evidence from bounded page text and declared table cells."""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict, deque
from datetime import date, datetime

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

from devtools.parser_engine_pilot.anchored_table import (
    AnchoredRow,
    AnchoredTableEvidence,
    TableSingleDateCardRule,
    load_definition,
)
from devtools.parser_engine_pilot.money_operations import usd_symbol_minor_v1
from devtools.parser_engine_pilot.partial_dates import PartialDateError, resolve_month_day
from devtools.parser_engine_pilot.pdf_lines import ADAPTER_VERSION, PageLine, PDFLineEvidence
from devtools.parser_engine_pilot.table_continuations import ContinuationError, RawTableRow, assemble

ENGINE_VERSION = "synchrony-table-source-pilot-1"
DATE = re.compile(r"\d{2}/\d{2}\Z")
DATE_PREFIX = re.compile(r"^\d{2}/\d{2}")
TEXT_DATE = re.compile(r"^(\d{2}/\d{2})\s")
FULL_DATE = re.compile(r"^\d{2}/\d{2}/(?:\d{2}|\d{4})\s")
MONEY = re.compile(r"-?\$(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}\Z")
MONEY_IN_TEXT = re.compile(r"-?\$[0-9][0-9,]*\.[0-9]{2}")


class SynchronySourceError(ValueError):
    """Redacted failure to account for statement header or table candidates."""


def _line(item: PageLine) -> PdfLine:
    return PdfLine(kind="pdf_line", page=item.page, line=item.line)


def _row(item: AnchoredRow) -> PdfTableRow:
    return PdfTableRow(kind="pdf_table_row", page=item.page, row=item.ordinal, region=item.region)


def _nonactivity_code(row: AnchoredRow, header_top: float) -> str:
    cells = tuple(cell.strip() for cell in row.raw_cells)
    if not any(MONEY.search(cell) for cell in cells):
        return "undated_table_row"
    first_two = "".join(cells[:2]).replace(" ", "")
    if row.region[1] < header_top:
        if first_two == "+BonusRewardsEarned" and cells[3] == "" and MONEY.fullmatch(cells[2]):
            return "rewards_summary_row"
        if first_two in {"Regular-", "Total"} and MONEY.fullmatch(cells[3]):
            return "balance_summary_row"
    else:
        if (
            first_two
            in {
                "Payments",
                "OtherCredits",
                "PurchasesandOtherDebits",
                "TotalFeesChargedThisPeriod",
                "TotalInterestChargedThisPeriod",
            }
            and cells[2] == ""
            and MONEY.fullmatch(cells[3])
        ):
            return "activity_section_total"
        if (
            not first_two
            and cells[2] in {"Total Fees Charged", "Total Interest Charged", "Total Interest Paid"}
            and MONEY.fullmatch(cells[3])
        ):
            return "interest_fee_summary_row"
        if first_two == "Purchases" and cells[2].startswith("N/A ") and "%" in cells[2] and MONEY.fullmatch(cells[3]):
            return "apr_disclosure_row"
    raise SynchronySourceError("unclassified_monetary_table_row")


def _header(rule: TableSingleDateCardRule, text: PDFLineEvidence):
    accounts = []
    balances = {}
    for line in text.lines:
        normalized = line.normalized
        if normalized.startswith(rule.account_label):
            match = re.match(rf"^{re.escape(rule.account_label)} (?P<suffix>\d{{4}})(?:\s|$)", normalized)
            if match is None:
                raise SynchronySourceError("invalid_account_suffix")
            accounts.append((line, match["suffix"]))
        for role, label in (("opening", rule.opening_label), ("closing", rule.closing_label)):
            if not normalized.startswith(label):
                continue
            if role in balances:
                raise SynchronySourceError("duplicate_printed_balance")
            match = re.match(
                rf"^{re.escape(label)} (?P<date>\d{{2}}/\d{{2}}/\d{{4}}) (?P<amount>-?\$[0-9,]+\.\d{{2}})(?:\s|$)",
                normalized,
            )
            if match is None:
                raise SynchronySourceError("invalid_printed_balance")
            try:
                parsed_date = datetime.strptime(match["date"], "%m/%d/%Y").date()
                if parsed_date.strftime("%m/%d/%Y") != match["date"]:
                    raise ValueError
                amount = -usd_symbol_minor_v1(match["amount"])
            except ValueError:
                raise SynchronySourceError("invalid_printed_balance") from None
            balances[role] = (line, match["date"], parsed_date, match["amount"], amount)
    if not accounts or len(balances) != 2 or len({suffix for _, suffix in accounts}) != 1:
        raise SynchronySourceError("missing_or_conflicting_statement_header")
    if balances["opening"][2] >= balances["closing"][2]:
        raise SynchronySourceError("invalid_statement_period")
    return accounts, balances


def from_synchrony_table(
    definition_bytes: bytes, table: AnchoredTableEvidence, text: PDFLineEvidence
) -> SourceEvidence:
    """Preserve source dates without inventing posting dates or account mapping."""
    definition, definition_hash = load_definition(definition_bytes)
    rule = definition.statement
    if not isinstance(rule, TableSingleDateCardRule):
        raise SynchronySourceError("missing_statement_rule")
    if (
        table.definition_sha256 != definition_hash
        or table.source_sha256 != text.source_sha256
        or text.adapter_version != ADAPTER_VERSION
        or text.extraction_library != "pdfplumber-bounded-simple-v1"
        or len(table.pages) != text.page_count
    ):
        raise SynchronySourceError("source_channel_mismatch")
    accounts, balances = _header(rule, text)
    account_suffix = accounts[0][1]
    start: date = balances["opening"][2]
    end: date = balances["closing"][2]
    selected = []
    dispositions = []
    header_tops = {page.page: page.header_region[1] for page in table.pages if page.header_region is not None}
    text_copies: dict[tuple[int, str, str], deque[PageLine]] = defaultdict(deque)
    for line in text.lines:
        normalized = line.normalized
        short_date = TEXT_DATE.match(normalized)
        if short_date is not None:
            amounts = MONEY.findall(normalized)
            if len(amounts) != 1:
                raise SynchronySourceError("unresolved_dated_text_line")
            text_copies[(line.page, short_date[1], amounts[0])].append(line)
        elif FULL_DATE.match(normalized):
            if not (
                re.match(r"^\d{2}/\d{2}/\d{4} for online and phone payments\.", normalized)
                or re.match(r"^\d{2}/\d{2}/\d{2} New Balance -?\$[0-9,]+\.\d{2}$", normalized)
            ):
                raise SynchronySourceError("unresolved_dated_text_line")
            dispositions.append(
                SourceDisposition(code="dated_statement_summary_line", location=_line(line), raw_values=(line.raw,))
            )
    pending: list[AnchoredRow] = []
    for row in table.rows:
        date_raw, reference_raw, description_raw, amount_raw = (cell.strip() for cell in row.raw_cells)
        if DATE.fullmatch(date_raw):
            if pending:
                raise SynchronySourceError("new_row_before_amount")
            if not description_raw:
                raise SynchronySourceError("empty_activity_description")
            pending = [row]
        elif DATE_PREFIX.match(date_raw):
            raise SynchronySourceError("unresolved_dated_table_row")
        elif pending:
            if date_raw or reference_raw:
                raise SynchronySourceError("invalid_continuation_row")
            pending.append(row)
        else:
            if any(DATE_PREFIX.match(cell) for cell in row.raw_cells):
                raise SynchronySourceError("unresolved_dated_table_row")
            code = _nonactivity_code(row, header_tops[row.page])
            dispositions.append(SourceDisposition(code=code, location=_row(row), raw_values=row.raw_cells))
            continue
        if len(pending) > rule.continuation.max_group_rows:
            raise SynchronySourceError("continuation_limit")
        if amount_raw:
            if MONEY.fullmatch(amount_raw) is None:
                raise SynchronySourceError("invalid_activity_amount")
            raw_rows = tuple(
                RawTableRow(item.page, item.ordinal, tuple(cell.strip() for cell in item.raw_cells)) for item in pending
            )
            try:
                joined = assemble(rule.continuation, raw_rows)
            except ContinuationError:
                raise SynchronySourceError("invalid_continuation") from None
            if len(joined) != 1 or joined[0].amount_raw != amount_raw:
                raise SynchronySourceError("invalid_continuation")
            selected.append((joined[0].description, amount_raw, tuple(pending)))
            pending = []
    if pending:
        raise SynchronySourceError("missing_terminal_amount")
    if not selected:
        raise SynchronySourceError("missing_activity_rows")
    rows = []
    occurrences: Counter[tuple[str, str, int]] = Counter()
    for description, amount_raw, sources in selected:
        first = sources[0]
        date_raw = first.raw_cells[0].strip()
        copies = text_copies[(first.page, date_raw, amount_raw)]
        if not copies:
            raise SynchronySourceError("missing_dated_text_copy")
        copy = copies.popleft()
        if description not in copy.normalized:
            raise SynchronySourceError("dated_text_description_mismatch")
        try:
            activity_date = resolve_month_day(date_raw, start, end)
            amount = -usd_symbol_minor_v1(amount_raw)
        except (PartialDateError, ValueError):
            raise SynchronySourceError("invalid_activity_value") from None
        key = (activity_date.isoformat(), description, amount)
        occurrence = occurrences[key]
        occurrences[key] += 1
        locations = tuple(_row(item) for item in sources)
        rows.append(
            ObservationEvidence(
                row_role="activity",
                row_id=hashlib.sha256(
                    f"{table.source_sha256}:{definition_hash}:{ENGINE_VERSION}:{table.extraction_library}:"
                    f"{first.page}:{first.ordinal}".encode()
                ).hexdigest(),
                occurrence=occurrence,
                source_account=account_suffix,
                source_account_form="last_four",
                date_role="activity_date",
                date=DateValue(
                    raw=None,
                    iso=activity_date.isoformat(),
                    provenance="derived",
                    locations=(locations[0], _line(balances["opening"][0]), _line(balances["closing"][0])),
                ),
                transaction_date=None,
                description=TextValue(raw=description, text=description, provenance="observed", locations=locations),
                amount=MoneyValue(raw=amount_raw, minor=amount, provenance="observed", locations=(locations[-1],)),
                running_balance=None,
                components=(),
                fragments=tuple(
                    SourceFragment(channel="anchored_table_row", location=_row(item), raw_values=item.raw_cells)
                    for item in sources
                )
                + (SourceFragment(channel="simple_text_line", location=_line(copy), raw_values=(copy.raw,)),),
            )
        )
    if any(copies for copies in text_copies.values()):
        raise SynchronySourceError("unmatched_dated_text_line")
    linked_lines = {(line.page, line.line) for line, _suffix in accounts}
    linked_lines.update((item[0].page, item[0].line) for item in balances.values())
    linked_lines.update(
        (fragment.location.page, fragment.location.line)
        for row in rows
        for fragment in row.fragments
        if fragment.location.kind == "pdf_line"
    )
    linked_lines.update(
        (item.location.page, item.location.line) for item in dispositions if item.location.kind == "pdf_line"
    )
    for line in text.lines:
        if (line.page, line.line) in linked_lines or MONEY_IN_TEXT.search(line.normalized) is None:
            continue
        matches = [item for item in rule.monetary_text_dispositions if line.normalized.startswith(item.prefix)]
        if len(matches) != 1:
            raise SynchronySourceError("unclassified_monetary_text_line")
        dispositions.append(SourceDisposition(code=matches[0].code, location=_line(line), raw_values=(line.raw,)))
    opening = balances["opening"][4]
    closing = balances["closing"][4]
    if opening + sum(row.amount.minor for row in rows) != closing:
        raise SynchronySourceError("printed_card_balance_equation")
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
                raw=balances["opening"][1],
                iso=start.isoformat(),
                provenance="observed",
                locations=(_line(balances["opening"][0]),),
            ),
            end=DateValue(
                raw=balances["closing"][1],
                iso=end.isoformat(),
                provenance="observed",
                locations=(_line(balances["closing"][0]),),
            ),
            accounts=(
                StatementAccount(
                    source_identity=account_suffix,
                    source_identity_form="last_four",
                    balance_scope="account_total",
                    identity_locations=tuple(_line(item) for item, _ in accounts[:16]),
                    opening=MoneyValue(
                        raw=balances["opening"][3],
                        minor=opening,
                        provenance="observed",
                        locations=(_line(balances["opening"][0]),),
                    ),
                    closing=MoneyValue(
                        raw=balances["closing"][3],
                        minor=closing,
                        provenance="observed",
                        locations=(_line(balances["closing"][0]),),
                    ),
                    rows=tuple(rows),
                ),
            ),
            dispositions=tuple(dispositions),
            capture_verified=False,
            independent_balance_verified=True,
        ),
    )
