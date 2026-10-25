"""Map finite card-line evidence into the shared V2 statement envelope."""

from __future__ import annotations

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
from parsetrail.core.v2_card_lines import CardField, CardStatementEvidence
from parsetrail.core.v2_pdf_lines import PDFLineEvidence


def _location(field: CardField) -> PdfLine:
    return PdfLine(kind="pdf_line", page=field.page, line=field.line)


def from_card(evidence: CardStatementEvidence, lines: PDFLineEvidence) -> SourceEvidence:
    """Retain printed fields and dated auxiliaries without claiming capture."""
    account = evidence.account_identity
    if (
        evidence.output_schema_version != 1
        or evidence.source_sha256 != lines.source_sha256
        or evidence.line_adapter_version != lines.adapter_version
        or evidence.extraction_library != lines.extraction_library
    ):
        raise ValueError("unsupported_card_evidence")
    raw_lines = {(line.page, line.line): line.raw for line in lines.lines}
    if len(raw_lines) != len(lines.lines):
        raise ValueError("duplicate_card_line_location")
    for field in (account, evidence.period_start, evidence.period_end, evidence.opening_minor, evidence.closing_minor):
        if field.raw not in raw_lines.get((field.page, field.line), ""):
            raise ValueError("card_printed_field_location")
    rows = []
    for row in evidence.rows:
        location = _location(row.amount)
        if any(
            (field.page, field.line) != (location.page, location.line)
            for field in (row.transaction_date, row.posting_date, row.description)
        ):
            raise ValueError("card_row_location_mismatch")
        raw_line = raw_lines.get((location.page, location.line))
        if raw_line is None or row.description.raw not in raw_line or row.amount.raw not in raw_line:
            raise ValueError("card_row_source_mismatch")
        rows.append(
            ObservationEvidence(
                row_role="activity",
                row_id=row.row_id,
                occurrence=row.occurrence,
                source_account=str(account.normalized),
                source_account_form="last_four",
                date_role="posting_date",
                date=DateValue(
                    raw=None, iso=str(row.posting_date.normalized), provenance="assumed", locations=(location,)
                ),
                transaction_date=DateValue(
                    raw=None, iso=str(row.transaction_date.normalized), provenance="derived", locations=(location,)
                ),
                description=TextValue(
                    raw=row.description.raw,
                    text=str(row.description.normalized),
                    provenance="observed",
                    locations=(location,),
                ),
                amount=MoneyValue(
                    raw=row.amount.raw, minor=int(row.amount.normalized), provenance="observed", locations=(location,)
                ),
                running_balance=None,
                components=(),
                fragments=(SourceFragment(channel="card_line", location=location, raw_values=(raw_line,)),),
            )
        )
    dispositions = tuple(
        SourceDisposition(
            code="dated_auxiliary_uninterpreted",
            location=PdfLine(kind="pdf_line", page=item.page, line=item.line),
            raw_values=(item.raw,),
        )
        for item in evidence.auxiliary_lines
        if raw_lines.get((item.page, item.line)) == item.raw
    )
    if len(dispositions) != len(evidence.auxiliary_lines):
        raise ValueError("card_auxiliary_source_mismatch")
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
                source_identity=str(account.normalized),
                source_identity_form="last_four",
                balance_scope="account_total",
                identity_locations=(_location(account),),
                opening=MoneyValue(
                    raw=evidence.opening_minor.raw,
                    minor=int(evidence.opening_minor.normalized),
                    provenance="observed",
                    locations=(_location(evidence.opening_minor),),
                ),
                closing=MoneyValue(
                    raw=evidence.closing_minor.raw,
                    minor=int(evidence.closing_minor.normalized),
                    provenance="observed",
                    locations=(_location(evidence.closing_minor),),
                ),
                rows=tuple(rows),
            ),
        ),
        dispositions=dispositions,
        capture_verified=False,
        independent_balance_verified=evidence.printed_balance_equation_passed,
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
