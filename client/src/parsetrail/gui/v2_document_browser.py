"""Readable document labels and isolated background inventory reads."""

from __future__ import annotations

import atexit
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QThread

from parsetrail.core.v2_profile_store import DocumentSummary, V2ProfileStore

_INVENTORY_READERS: set[QThread] = set()


def profile_revision(profile: Path) -> tuple:
    """Cheap freshness hint for activation, never a substitute for write guards."""
    result = []
    for path in (profile, profile.with_name(profile.name + "-wal")):
        try:
            info = path.stat()
            result.append((info.st_size, info.st_mtime_ns, info.st_ino))
        except OSError:
            result.append(None)
    return tuple(result)


def _finish_inventory_readers() -> None:
    readers = tuple(_INVENTORY_READERS)
    for reader in readers:
        reader.requestInterruption()
    for reader in readers:
        while reader.isRunning():
            reader.wait(10)
            time.sleep(0.001)
        reader.wait()
        _INVENTORY_READERS.discard(reader)


atexit.register(_finish_inventory_readers)


class DocumentInventoryWorker(QThread):
    """Own the SQLite connection in this thread; return immutable summaries only."""

    def __init__(self, profile: Path, generation: int, parent=None):
        # The window may be destroyed before the read connection has closed.
        # Retention below, rather than QObject parenting, owns that lifetime.
        super().__init__()
        self.profile = profile
        self.generation = generation
        self.result: tuple[DocumentSummary, ...] = ()
        self.accounts = ()
        self.revision = profile_revision(profile)
        self.error: Exception | None = None

    def start(self) -> None:
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrail_inventory_exit_hook"):
            app.setProperty("parsetrail_inventory_exit_hook", True)
            app.aboutToQuit.connect(_finish_inventory_readers)
        _INVENTORY_READERS.add(self)
        self.finished.connect(lambda: _INVENTORY_READERS.discard(self))
        self.finished.connect(self.deleteLater)
        super().start()

    def run(self) -> None:
        try:
            self.revision = profile_revision(self.profile)
            with V2ProfileStore.open(self.profile, read_only=True) as store:
                store.connection.set_progress_handler(lambda: int(self.isInterruptionRequested()), 1000)
                self.result = store.document_summaries()
                self.accounts = store.financial_accounts()
        except Exception as exc:
            self.error = exc


def document_title(summary: DocumentSummary) -> str:
    names = summary.bound_account_names or summary.source_accounts
    account = ", ".join(names[:2])
    if len(names) > 2:
        account += f" +{len(names) - 2} more"
    institutions = {
        "capital_one": "Capital One",
        "citi": "Citi",
        "healthequity": "HealthEquity",
        "lendingclub": "LendingClub",
        "usbank": "U.S. Bank",
        "wellsfargo": "Wells Fargo",
        "occu": "OCCU",
        "mohela": "MOHELA",
        "happen": "Happen",
        "yamaha": "Yamaha",
        "fidelity": "Fidelity",
        "vanguard": "Vanguard",
        "transamerica": "Transamerica",
        "synchrony": "Synchrony",
        "chase": "Chase",
        "synthetic": "Synthetic example",
    }
    if summary.institution_key:
        family = institutions.get(summary.institution_key, summary.institution_key.replace("_", " "))
    else:
        families = (
            ("pdf_citicc_", "Citi card document"),
            ("pdf_capitaloneauto_", "Capital One Auto document"),
            ("pdf_fidelity401k_", "Fidelity retirement document"),
            ("pdf_fidelityhsa_", "Fidelity HSA document"),
            ("pdf_lendingclub", "LendingClub document"),
            ("pdf_occubank_", "OCCU bank document"),
            ("pdf_occucc_", "OCCU card document"),
            ("pdf_transamerica_", "Transamerica document"),
            ("pdf_usbankrei", "U.S. Bank card document"),
            ("pdf_vanguard_", "Vanguard document"),
            ("pdf_wfbankper_", "Wells Fargo bank document"),
            ("pdf_wfloanper_", "Wells Fargo loan document"),
            ("pdf_yamahafin_", "Yamaha financing document"),
            ("synchrony_", "Synchrony card document"),
            ("chase_card_", "Chase card document"),
            ("hsa_cash_", "HSA cash document"),
        )
        family = next((label for prefix, label in families if summary.parser_id.startswith(prefix)), None)
        if family is None:
            family = summary.parser_id.replace("_", " ").replace("-", " ")
            family = family.removesuffix(" definition").removesuffix(" pilot")
    return f"{account} · {family}" if account else family


def document_period(summary: DocumentSummary) -> str:
    kind = "Statement period" if summary.document_kind == "statement" else "Activity dates"
    start, end = summary.start, summary.end
    if start is None and end is None:
        return f"{kind} unknown"

    def endpoint(value, provenance):
        text = value.isoformat() if value else "unknown"
        if value and provenance in {"assumed", "derived"}:
            text += " (estimated)" if provenance == "assumed" else " (derived)"
        return text

    dates = f"{endpoint(start, summary.start_provenance)} – {endpoint(end, summary.end_provenance)}"
    return f"{kind}: {dates}"


def document_status(summary: DocumentSummary) -> str:
    if summary.unassigned_source_accounts:
        return f"{summary.unassigned_source_accounts} document account(s) need confirmation"
    if summary.unassigned_activity_rows:
        return f"{summary.unassigned_activity_rows} activity row(s) need an account"
    if summary.pending_activity_rows:
        return f"{summary.pending_activity_rows} unallocated source row(s) · may include repeats"
    return "No activity pending · source checks are separate"


def document_account_association(summary: DocumentSummary) -> str:
    """Explain confirmed source/file/row decisions independently of allocation."""
    names = ", ".join(summary.bound_account_names)
    assigned = summary.assigned_row_count
    if summary.association_kind == "file":
        return f"Whole document assigned to {names} · {summary.row_count} rows"
    if summary.association_kind == "rows":
        if summary.association_complete:
            return (
                f"All {summary.row_count} rows assigned individually to {names}"
                if len(summary.associated_account_ids) == 1
                else f"All {summary.row_count} rows assigned across {len(summary.associated_account_ids)} accounts: {names}"
            )
        return (
            f"{assigned}/{summary.row_count} rows assigned · {summary.row_count - assigned} still need an account"
            + (f" · {names}" if names else "")
        )
    if summary.association_kind in {"source", "mixed"}:
        return f"Confirmed account associations: {names}" + (
            " · some account assignments still need review" if not summary.association_complete else ""
        )
    return (
        "No activity rows; account not established"
        if not summary.row_count
        else f"No row accounts assigned · {summary.row_count} rows need an account"
    )
