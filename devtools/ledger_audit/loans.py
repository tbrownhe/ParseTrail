"""Create and optionally review a private read-only loan-readiness report."""

import argparse
import json
import os
from pathlib import Path

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_loan_readiness import RULE, build_loan_readiness
from parsetrail.core.ledger_store import encoded
from parsetrail.core.recovery_bundle import digest


def create_report(rebuild_folder, output):
    report = json.loads((rebuild_folder / "report.json").read_text(encoding="utf-8"))
    checksums = {
        rebuild_folder / "plan.json": report["plan_sha256"],
        rebuild_folder / "fresh.db": report["database_sha256"],
        rebuild_folder / "legacy.db": report["source_sha256"],
    }
    if any(
        Path(str(p) + suffix).exists()
        for p in checksums
        if p.suffix == ".db"
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise LedgerError("Loan readiness requires inactive verified inputs.")
    if any(digest(p) != expected for p, expected in checksums.items()):
        raise LedgerError("Loan readiness input changed after verification.")
    plan = json.loads((rebuild_folder / "plan.json").read_text(encoding="utf-8"))
    result = build_loan_readiness(plan)
    output.mkdir(parents=True, exist_ok=False)
    (output / "readiness.json").write_text(encoded(result), encoding="utf-8")
    if any(digest(p) != expected for p, expected in checksums.items()):
        raise LedgerError("Loan readiness inputs changed while reading.")
    manifest = {
        "rule": RULE,
        "readiness_sha256": digest(output / "readiness.json"),
        "rebuild_hash": result["rebuild_hash"],
        "source_unchanged": True,
        "journal_entries_posted": 0,
        "ready_for_cutover": False,
    }
    (output / "report.json").write_text(encoded(manifest), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", type=Path, help="Verified fresh rebuild; creates a new report folder.")
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--review", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke and not args.review:
        parser.error("--smoke requires --review")
    if not args.rebuild and not args.review:
        parser.error("Use --rebuild to create a report or --review to reopen one")
    if args.rebuild:
        create_report(args.rebuild, args.folder)
    if not args.review:
        print("Read-only loan readiness report created; no evidence or postings changed.")
        return 0
    if args.smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from parsetrail.gui.ledger_loan_readiness import load_loan_preview
    from parsetrail.gui.ledger_preview import LedgerPreviewWindow
    from PySide6.QtWidgets import QApplication

    data = load_loan_preview(args.folder)
    app = QApplication([])
    if args.smoke and os.name == "nt":
        from PySide6.QtGui import QFont, QFontDatabase

        font = QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts/segoeui.ttf"))
        families = QFontDatabase.applicationFontFamilies(font)
        if families:
            app.setFont(QFont(families[0], 10))
    window = LedgerPreviewWindow(data)
    window.show()
    if args.smoke:
        for i in range(window.tabs.count()):
            window.tabs.setCurrentIndex(i)
            page = window.tabs.widget(i)
            if page.proxy.rowCount():
                page.table.selectRow(0)
                app.processEvents()
                assert page.details.toPlainText()
                window.grab().save(str(args.folder / f"loan-tab-{i}-smoke.png"))
            page.search.setText("NO-MATCH-SYNTHETIC-FILTER-123456")
            assert page.proxy.rowCount() == 0 and not page.details.toPlainText()
            page.search.clear()
        window.close()
        print("Read-only loan readiness selection/filter/close smoke passed.")
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
