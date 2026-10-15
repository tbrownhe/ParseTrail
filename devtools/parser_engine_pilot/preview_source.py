"""Open a read-only 2.0 evidence preview without touching a live profile."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_evidence_preview import preview_saved_source
from PySide6.QtWidgets import QApplication

from devtools.parser_engine_pilot.source_pipeline import build_source_evidence

DEMO_SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
DEMO_DEFINITION = Path(__file__).parents[1] / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", type=Path, help="Local source PDF or CSV, read-only")
    parser.add_argument("definition", nargs="?", type=Path, help="Checked-in 2.0 definition JSON")
    parser.add_argument("--demo", action="store_true", help="Open a synthetic example")
    args = parser.parse_args(argv)
    if args.demo:
        if args.source is not None or args.definition is not None:
            parser.error("--demo does not take file paths")
        source, definition, suffix = DEMO_SOURCE, DEMO_DEFINITION.read_bytes(), ".csv"
    else:
        if args.source is None or args.definition is None:
            parser.error("source and definition are required together")
        suffix = args.source.suffix.lower()
        if suffix not in {".csv", ".pdf"}:
            parser.error("source must be a CSV or PDF")
        source, definition = args.source.read_bytes(), args.definition.read_bytes()
    evidence = build_source_evidence(source, definition, suffix=suffix)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="parsetrail-v2-preview-") as temporary:
        profile = Path(temporary) / "preview.db"
        with V2ProfileStore.create(profile) as store:
            store.import_source(source, definition, evidence, suffix=suffix)
        dialog = preview_saved_source(profile, evidence.source_sha256)
        dialog.exec()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
