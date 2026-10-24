"""Spreadsheet presentation for a reviewed 2.0 journal snapshot."""

from __future__ import annotations

import os
import tempfile
from itertools import chain
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font

from parsetrail.core.v2_profile_store import ReviewedJournalExport


class ReportExportError(ValueError):
    """The reviewed report cannot be published at the chosen path."""


def _sheet(workbook: Workbook, name: str, headers: tuple[str, ...], rows: list[tuple]) -> None:
    if len(rows) > 1_048_575:
        raise ReportExportError("report_sheet_row_limit")
    sheet = workbook.create_sheet(name)
    for row_number, values in enumerate(chain((headers,), rows), start=1):
        for column_number, value in enumerate(values, start=1):
            if isinstance(value, str) and len(value) > 32_767:
                raise ReportExportError("report_cell_too_long")
            cell = sheet.cell(row_number, column_number, value)
            if isinstance(value, str):
                cell.data_type = "s"  # Source descriptions and authored names must not become Excel formulas.
            if row_number == 1:
                cell.font = Font(bold=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column in sheet.columns:
        letter = column[0].column_letter
        width = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[letter].width = min(max(width + 2, 12), 64)


def write_reviewed_journal_workbook(report: ReviewedJournalExport, destination_path: Path) -> Path:
    """Write active reviewed entry rows, exact posting lines, provenance and scope."""
    destination = destination_path.expanduser()
    if destination.suffix.lower() != ".xlsx":
        raise ReportExportError("report_destination_requires_xlsx")
    if destination.is_symlink():
        raise ReportExportError("report_destination_exists")
    destination = destination.resolve()
    if destination.exists():
        raise ReportExportError("report_destination_exists")
    if not destination.parent.is_dir():
        raise ReportExportError("report_destination_parent_missing")
    accounts = {account.id: account for account in report.accounts}
    source_rows = dict(report.source_rows)
    entries = []
    postings = []
    allocations = []
    for entry in report.entries:
        expense_minor = sum(
            posting.amount_minor for posting in entry.postings if accounts[posting.account_id].kind == "expense"
        )
        income_minor = -sum(
            posting.amount_minor for posting in entry.postings if accounts[posting.account_id].kind == "income"
        )
        entries.append(
            (
                entry.key,
                entry.event_id,
                entry.posting_date.isoformat(),
                entry.description,
                entry.origin,
                entry.reason,
                expense_minor / 100,
                str(expense_minor),
                income_minor / 100,
                str(income_minor),
            )
        )
        for line_number, posting in enumerate(entry.postings, start=1):
            account = accounts[posting.account_id]
            postings.append(
                (
                    entry.key,
                    entry.posting_date.isoformat(),
                    line_number,
                    account.id,
                    account.name,
                    account.kind,
                    posting.amount_minor / 100,
                    str(posting.amount_minor),
                )
            )
            for allocation in posting.allocations:
                allocations.append(
                    (
                        entry.key,
                        line_number,
                        allocation.observation_id,
                        source_rows[allocation.observation_id],
                        allocation.amount_minor / 100,
                        str(allocation.amount_minor),
                    )
                )
    workbook = Workbook()
    workbook.remove(workbook.active)
    _sheet(
        workbook,
        "Scope",
        ("Field", "Value"),
        [
            ("Report", "ParseTrail 2.0 active reviewed journal"),
            ("From inclusive", report.start.isoformat()),
            ("To exclusive", report.end.isoformat()),
            ("Active reviewed entries", len(report.entries)),
            ("Posting lines", len(postings)),
            ("Unreviewed journal entries excluded in period", report.excluded_unreviewed_entries),
            ("Opening entries excluded in period", report.excluded_opening_entries),
            (
                "Activity source rows without full allocation, whole profile",
                report.activity_rows_without_full_allocation,
            ),
            ("Sources with incomplete activity, whole profile", report.sources_with_incomplete_activity),
            ("Corrections to original entries posted in period", len(report.corrections)),
            ("Correction presentation", "Superseded entries and reversals are omitted from active rows."),
            ("Precision", "USD columns are for display; minor-unit text columns preserve exact values."),
            ("Coverage", "Source rows can overlap; these rows do not prove complete transaction coverage."),
            ("Balances", "This export does not establish reconciled balances or certified cash flow."),
            ("Openings", "Opening positions are not transaction rows and are excluded from this workbook."),
        ],
    )
    _sheet(
        workbook,
        "Reviewed Entries",
        (
            "Entry key",
            "Event ID",
            "Posting date",
            "Description",
            "Origin",
            "Review reason",
            "Net expense USD",
            "Net expense minor units",
            "Net income USD",
            "Net income minor units",
        ),
        entries,
    )
    _sheet(
        workbook,
        "Posting Lines",
        (
            "Entry key",
            "Posting date",
            "Line",
            "Account ID",
            "Account name",
            "Account kind",
            "Signed USD",
            "Signed minor units",
        ),
        postings,
    )
    _sheet(
        workbook,
        "Source Allocations",
        ("Entry key", "Posting line", "Source row ID", "Source SHA-256", "Signed USD", "Signed minor units"),
        allocations,
    )
    _sheet(
        workbook,
        "Corrections",
        ("Original key", "Reversal key", "Replacement key", "Reason", "Created at"),
        [
            (
                correction.original_key,
                correction.reversal_key,
                correction.replacement_key,
                correction.reason,
                correction.created_at,
            )
            for correction in report.corrections
        ],
    )
    descriptor, partial_name = tempfile.mkstemp(
        prefix=f".{destination.name}.partial.", suffix=".xlsx", dir=destination.parent
    )
    os.close(descriptor)
    partial = Path(partial_name)
    try:
        workbook.save(partial)
        verified = load_workbook(partial, read_only=True, data_only=False)
        try:
            if verified.sheetnames != [
                "Scope",
                "Reviewed Entries",
                "Posting Lines",
                "Source Allocations",
                "Corrections",
            ]:
                raise ReportExportError("report_workbook_integrity")
        finally:
            verified.close()
        try:
            os.link(partial, destination)
        except FileExistsError:
            raise ReportExportError("report_destination_exists") from None
        return destination
    finally:
        partial.unlink(missing_ok=True)
