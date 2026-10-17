"""Read-only recent Citi statement evidence from bounded PDF workers.

No legacy reader, journal posting or profile write is used on this path.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from parsetrail.core.parser_classification import DocumentFeatures, matching_plugins, normalize_pdf_metadata
from parsetrail.core.v2_bounded_citi import extract_bounded_citi
from parsetrail.core.v2_bounded_pdf_text import decode_pdf
from parsetrail.core.v2_channel_occurrences import Candidate
from parsetrail.core.v2_citi_channels import CitiResolution, resolve
from parsetrail.core.v2_citi_layout import (
    AMOUNT,
    DATE_PREFIX,
    EVIDENCE_ENGINE_VERSION,
    TEXT_TRANSACTION,
    CitiDefinition,
    load_definition,
)
from parsetrail.core.v2_citi_money_lines import MoneyLineDisposition, dispose_unlinked_money_lines
from parsetrail.core.v2_citi_source_dispositions import (
    DatedLineDisposition,
    dispose_dated_lines,
)
from parsetrail.core.v2_citi_statement_header import CitiStatementHeader, parse_header
from parsetrail.core.v2_citi_table import CitiTableEvidence
from parsetrail.core.v2_citi_table_candidates import CitiTableCandidates, candidates_from_table
from parsetrail.core.v2_money_operations import usd_symbol_minor_v1
from parsetrail.core.v2_partial_dates import resolve_month_day


class CitiEvidenceError(ValueError):
    """Redacted refusal of an incomplete recent Citi statement."""


OTHER_LAYOUT_ROUTING_METADATA = {
    "pdf_citicc_202506": {
        "SUFFIX": ".pdf",
        "SEARCH_STRING": "www.citicards.com",
        "ROUTING_RULE": {
            "pdf_metadata": {"Producer": '"crawfordtech"'},
            "header": '("trans. post description amount" || ("trans. post" && "date date description amount")) && !"sale post"',
        },
    },
}


@dataclass(frozen=True, slots=True)
class CitiEvidence:
    source_sha256: str
    definition_sha256: str
    engine_version: str
    simple_text_pages: tuple[str, ...]
    header: CitiStatementHeader
    table_evidence: CitiTableEvidence
    table_candidates: CitiTableCandidates
    text_candidates: tuple[Candidate, ...]
    fee_candidates: tuple[Candidate, ...]
    resolution: CitiResolution
    dated_lines: tuple[DatedLineDisposition, ...]
    money_lines: tuple[MoneyLineDisposition, ...]
    dated_start_row_bijection: bool


def _layout_metadata(definition: CitiDefinition) -> dict[str, dict]:
    metadata = dict(OTHER_LAYOUT_ROUTING_METADATA)
    metadata[definition.parser_id] = definition.routing.plugin_metadata()
    return metadata


def _features(pages: tuple[str, ...], metadata: tuple[tuple[str, str], ...]) -> DocumentFeatures:
    return DocumentFeatures(
        suffix=".pdf",
        body_text="\n".join(" ".join(line.split()) for page in pages for line in page.splitlines()),
        header_text="\n".join(" ".join(line.split()) for page in pages for line in page.splitlines()[:40]),
        pdf_metadata=normalize_pdf_metadata(dict(metadata)),
        page_count=len(pages),
    )


def _text_candidates(pages: tuple[str, ...], start: datetime, end: datetime) -> tuple[Candidate, ...]:
    result = []
    for page_number, page in enumerate(pages, 1):
        for line_number, line in enumerate(page.splitlines(), 1):
            match = TEXT_TRANSACTION.match(line)
            if match is None:
                continue
            transaction_raw = match.group("transaction_date") or match.group("single_date")
            posting_raw = match.group("posting_date") or match.group("single_date")
            result.append(
                Candidate(
                    resolve_month_day(transaction_raw, start, end),
                    resolve_month_day(posting_raw, start, end),
                    -usd_symbol_minor_v1(match.group("amount")),
                    " ".join(match.group("description").split()),
                    "text",
                    page_number,
                    line_number,
                )
            )
    return tuple(result)


def fee_candidates(pages: tuple[str, ...] | list[str], start: datetime, end: datetime) -> tuple[Candidate, ...]:
    """Locate multiline fee rows only within the printed fee section."""
    result = []
    for page_number, page in enumerate(pages, 1):
        in_fees = False
        pending: tuple[str, list[str], int] | None = None
        for line_number, raw in enumerate(page.splitlines(), 1):
            line = " ".join(raw.split())
            if line == "Fees Charged":
                in_fees = True
                continue
            if not in_fees:
                continue
            if "TOTAL FEES FOR THIS PERIOD" in line:
                break
            date_match = DATE_PREFIX.match(line)
            if date_match:
                pending = (date_match.group("date"), [date_match.group("description")], line_number)
            elif pending:
                pending[1].append(line)
            if pending is None:
                continue
            amount_match = AMOUNT.search(line)
            if amount_match is None:
                continue
            transaction_date = resolve_month_day(pending[0], start, end)
            description = " ".join(" ".join(pending[1]).replace(amount_match.group(), "").split())
            result.append(
                Candidate(
                    transaction_date,
                    transaction_date,
                    -usd_symbol_minor_v1(amount_match.group()),
                    description,
                    "fee",
                    page_number,
                    pending[2],
                    line_number,
                )
            )
            pending = None
    return tuple(result)


def _dated_start_bijection(resolution: CitiResolution, dated_lines: tuple[DatedLineDisposition, ...]) -> bool:
    resolved_by_source = {
        (candidate.channel, candidate.page, candidate.line): index
        for index, row in enumerate(resolution.rows)
        for candidate in row.sources
    }
    incomplete_by_location = {
        (candidate.page, candidate.line): candidate for candidate in resolution.incomplete_text_copies
    }
    occurrences: Counter[int] = Counter()
    for item in dated_lines:
        if item.status == "simple_text":
            key = ("text", item.page, item.line)
        elif item.status == "table_copy":
            key = ("table", item.page, item.table_row)
        elif item.status == "fee":
            key = ("fee", item.page, item.line)
        else:
            return False
        row_index = resolved_by_source.get(key)
        if row_index is None and item.status == "simple_text":
            incomplete = incomplete_by_location.get((item.page, item.line))
            if incomplete is not None:
                peers = [
                    index
                    for index, row in enumerate(resolution.rows)
                    if row.disposition == "table"
                    and row.representative.page == incomplete.page
                    and (
                        row.representative.transaction_date,
                        row.representative.posting_date,
                        row.representative.amount_minor,
                    )
                    == (incomplete.transaction_date, incomplete.posting_date, incomplete.amount_minor)
                ]
                if len(peers) == 1:
                    row_index = peers[0]
        if row_index is None:
            return False
        occurrences[row_index] += 1
    return all(occurrences[index] == 1 for index in range(len(resolution.rows)))


def read_recent_citi(
    source: bytes,
    definition_bytes: bytes,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> CitiEvidence:
    """Return source-linked candidates; refuse unresolved dated starts."""
    definition, definition_hash = load_definition(definition_bytes)
    decoded = decode_pdf(source, cancelled=cancelled)
    if matching_plugins(_features(decoded.pages, decoded.metadata), _layout_metadata(definition)) != (
        definition.parser_id,
    ):
        raise CitiEvidenceError("wrong_or_ambiguous_citi_layout")
    table_evidence = extract_bounded_citi(source, cancelled=cancelled)
    if len(table_evidence.pages) != len(decoded.pages):
        raise CitiEvidenceError("page_count_mismatch")
    header = parse_header(table_evidence.first_page_chars, decoded.pages)
    start = datetime.combine(header.start_date, datetime.min.time())
    end = datetime.combine(header.end_date, datetime.min.time())
    table = candidates_from_table(table_evidence, start, end, continuation=definition.table_continuation)
    text = _text_candidates(decoded.pages, start, end)
    fees = fee_candidates(decoded.pages, start, end)
    resolution = resolve(
        list(table.rows),
        list(text),
        list(fees),
        opening_minor=header.previous_balance.ledger_minor,
        closing_minor=header.new_balance.ledger_minor,
        occurrence_rule=definition.channel_occurrences,
    )
    if any(not header.start_date <= row.representative.posting_date <= header.end_date for row in resolution.rows):
        raise CitiEvidenceError("posting_date_outside_statement")
    dated_lines = dispose_dated_lines(list(decoded.pages), list(table.rows), list(fees))
    bijection = _dated_start_bijection(resolution, dated_lines)
    if not bijection:
        raise CitiEvidenceError("unresolved_dated_start")
    money_lines = dispose_unlinked_money_lines(decoded.pages, dated_lines)
    if any(item.status == "unresolved" for item in money_lines):
        raise CitiEvidenceError("unresolved_money_line")
    return CitiEvidence(
        hashlib.sha256(source).hexdigest(),
        definition_hash,
        EVIDENCE_ENGINE_VERSION,
        decoded.pages,
        header,
        table_evidence,
        table,
        text,
        fees,
        resolution,
        dated_lines,
        money_lines,
        bijection,
    )
