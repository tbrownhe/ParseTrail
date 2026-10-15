"""Map bounded HSA cash-section evidence into scoped V2 source evidence."""

from __future__ import annotations

from collections import Counter

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

from devtools.parser_engine_pilot.hsa_cash_lines import CashField, HsaCashEvidence
from devtools.parser_engine_pilot.pdf_lines import PDFLineEvidence


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
