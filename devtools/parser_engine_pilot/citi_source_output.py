"""Map bounded recent-Citi evidence into the shared 2.0 statement output."""

from __future__ import annotations

import hashlib
from collections import Counter

from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    ObservationEvidence,
    PdfChars,
    PdfLine,
    PdfTableRow,
    SourceDisposition,
    SourceEvidence,
    SourceFragment,
    StatementAccount,
    StatementPayload,
    TextValue,
)

from devtools.parser_engine_pilot.citi_evidence import CitiEvidence
from devtools.parser_engine_pilot.citi_layout import (
    AMOUNT,
    DEFINITION,
    DEFINITION_SHA256,
    EVIDENCE_ENGINE_VERSION,
    TEXT_TRANSACTION,
)
from devtools.parser_engine_pilot.citi_table import CitiTableRow


class CitiOutputError(ValueError):
    """Redacted refusal when located Citi evidence cannot form one output."""


def _raw_line(evidence: CitiEvidence, page: int, line: int) -> str:
    try:
        return evidence.simple_text_pages[page - 1].splitlines()[line - 1]
    except IndexError:
        raise CitiOutputError("source_line_missing") from None


def _table_location(row: CitiTableRow) -> PdfTableRow | PdfLine:
    if row.channel == "interest_text":
        if row.source_line is None:
            raise CitiOutputError("interest_line_missing")
        return PdfLine(kind="pdf_line", page=row.page, line=row.source_line)
    return PdfTableRow(kind="pdf_table_row", page=row.page, row=row.table_row, region=row.region)


def from_citi(evidence: CitiEvidence) -> SourceEvidence:
    """Keep all supporting copies and nontransaction dispositions without posting."""
    if (
        evidence.definition_sha256 != DEFINITION_SHA256
        or evidence.engine_version != EVIDENCE_ENGINE_VERSION
        or not evidence.dated_start_row_bijection
    ):
        raise CitiOutputError("source_contract")
    if any(item.status == "unresolved" for item in (*evidence.dated_lines, *evidence.money_lines)):
        raise CitiOutputError("unresolved_source_line")
    if evidence.source_sha256 != evidence.table_evidence.source_sha256:
        raise CitiOutputError("source_hash_mismatch")

    raw_tables = {(row.page, row.table_row): row for row in evidence.table_evidence.rows}
    groups = {(group.sources[0].page, group.sources[0].ordinal): group for group in evidence.table_candidates.groups}
    if len(raw_tables) != len(evidence.table_evidence.rows) or len(groups) != len(evidence.table_candidates.groups):
        raise CitiOutputError("duplicate_table_location")

    observations = []
    occurrence: Counter[tuple] = Counter()
    for ordinal, resolved in enumerate(evidence.resolution.rows, 1):
        representative = resolved.representative
        fragments = []
        amount_raw = None
        amount_location = None
        for source in resolved.sources:
            if source.page is None or source.line is None:
                raise CitiOutputError("candidate_location")
            if source.channel == "table":
                group = groups.get((source.page, source.line))
                if group is None:
                    raise CitiOutputError("table_group_missing")
                for item in group.sources:
                    raw = raw_tables.get((item.page, item.ordinal))
                    if raw is None or raw.raw_cells != item.cells:
                        raise CitiOutputError("table_row_changed")
                    location = _table_location(raw)
                    fragments.append(SourceFragment(channel="table", location=location, raw_values=raw.raw_cells))
                    if raw.raw_cells[3] == group.amount_raw:
                        amount_raw = group.amount_raw
                        amount_location = location
            elif source.channel in {"text", "fee"}:
                last = source.end_line or source.line
                lines = tuple(_raw_line(evidence, source.page, line) for line in range(source.line, last + 1))
                location = PdfLine(kind="pdf_line", page=source.page, line=source.line, end_line=source.end_line)
                fragments.append(SourceFragment(channel=source.channel, location=location, raw_values=lines))
                if source is representative:
                    if source.channel == "text":
                        match = TEXT_TRANSACTION.match(lines[0])
                        if match is None:
                            raise CitiOutputError("text_source_changed")
                        amount_raw = match["amount"]
                        amount_location = location
                    else:
                        found = next(
                            ((match, index) for index, line in enumerate(lines) if (match := AMOUNT.search(line))), None
                        )
                        if found is None:
                            raise CitiOutputError("fee_amount_missing")
                        amount_raw = found[0].group()
                        amount_location = PdfLine(kind="pdf_line", page=source.page, line=source.line + found[1])
            else:
                raise CitiOutputError("unknown_candidate_channel")
        if not fragments or amount_raw is None or amount_location is None:
            raise CitiOutputError("amount_source_missing")
        if -to_minor_units(parse_money(amount_raw)) != representative.amount_minor:
            raise CitiOutputError("source_amount_mismatch")
        key = (
            representative.transaction_date,
            representative.posting_date,
            representative.amount_minor,
            representative.description,
        )
        index = occurrence[key]
        occurrence[key] += 1
        row_id = hashlib.sha256(
            f"{evidence.source_sha256}:{evidence.definition_sha256}:{evidence.engine_version}:{ordinal}".encode()
        ).hexdigest()
        locations = tuple(fragment.location for fragment in fragments)
        observations.append(
            ObservationEvidence(
                row_id=row_id,
                occurrence=index,
                source_account=evidence.header.account_suffix,
                date_role="posting_date",
                date=DateValue(
                    raw=None,
                    iso=representative.posting_date.isoformat(),
                    provenance="derived",
                    locations=locations,
                ),
                transaction_date=DateValue(
                    raw=None,
                    iso=representative.transaction_date.isoformat(),
                    provenance="derived",
                    locations=locations,
                ),
                description=TextValue(
                    raw=None,
                    text=representative.description,
                    provenance="derived",
                    locations=locations,
                ),
                amount=MoneyValue(
                    raw=amount_raw,
                    minor=representative.amount_minor,
                    provenance="observed",
                    locations=(amount_location,),
                ),
                running_balance=None,
                components=(),
                fragments=tuple(fragments),
            )
        )

    dispositions = []
    for item in evidence.dated_lines:
        dispositions.append(
            SourceDisposition(
                code=f"dated_{item.status}",
                location=PdfLine(kind="pdf_line", page=item.page, line=item.line, end_line=item.end_line),
                raw_values=tuple(_raw_line(evidence, item.page, line) for line in range(item.line, item.end_line + 1)),
            )
        )
    for item in evidence.money_lines:
        dispositions.append(
            SourceDisposition(
                code=f"money_{item.status}",
                location=PdfLine(kind="pdf_line", page=item.page, line=item.line),
                raw_values=(_raw_line(evidence, item.page, item.line),),
            )
        )
    for group in evidence.table_candidates.groups:
        for detail in group.detail_rows:
            raw = raw_tables.get((detail.page, detail.ordinal))
            if raw is None or raw.raw_cells != detail.cells:
                raise CitiOutputError("supplemental_row_changed")
            dispositions.append(
                SourceDisposition(
                    code="supplemental_table_detail",
                    location=_table_location(raw),
                    raw_values=raw.raw_cells,
                )
            )

    header = evidence.header
    char_start, char_end = header.period_char_span
    raw_period = evidence.table_evidence.first_page_chars[char_start:char_end]
    period_location = PdfChars(kind="pdf_chars", page=1, start=char_start, end=char_end)
    if not raw_period:
        raise CitiOutputError("period_source_missing")
    payload = StatementPayload(
        kind="statement",
        start=DateValue(
            raw=raw_period, iso=header.start_date.isoformat(), provenance="observed", locations=(period_location,)
        ),
        end=DateValue(
            raw=raw_period, iso=header.end_date.isoformat(), provenance="observed", locations=(period_location,)
        ),
        accounts=(
            StatementAccount(
                source_identity=header.account_suffix,
                opening=MoneyValue(
                    raw=header.previous_balance.raw,
                    minor=header.previous_balance.ledger_minor,
                    provenance="observed",
                    locations=(
                        PdfLine(kind="pdf_line", page=header.previous_balance.page, line=header.previous_balance.line),
                    ),
                ),
                closing=MoneyValue(
                    raw=header.new_balance.raw,
                    minor=header.new_balance.ledger_minor,
                    provenance="observed",
                    locations=(PdfLine(kind="pdf_line", page=header.new_balance.page, line=header.new_balance.line),),
                ),
                rows=tuple(observations),
            ),
        ),
        dispositions=tuple(dispositions),
        capture_verified=False,
        independent_balance_verified=evidence.resolution.balance_reconciled,
    )
    return SourceEvidence(
        schema_version=1,
        source_sha256=evidence.source_sha256,
        definition_sha256=evidence.definition_sha256,
        parser_id=DEFINITION.parser_id,
        definition_revision=DEFINITION.revision,
        engine_version=evidence.engine_version,
        extractor_version=evidence.table_evidence.extraction_library + "+simple-text-v1",
        payload=payload,
    )
