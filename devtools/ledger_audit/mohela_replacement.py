"""Prepare a disposable MOHELA replacement and inspect its read-only review."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "client/src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--accepted", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--old-export", type=Path)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if bool(args.accepted) != bool(args.csv) or (args.old_export and not args.accepted):
        parser.error("Preparation requires --accepted and --csv together; --old-export is preparation-only.")
    if args.prepare_only and (not args.accepted or args.smoke):
        parser.error("--prepare-only requires preparation inputs and cannot be combined with --smoke.")
    from parsetrail.core.ledger_mohela_replacement import create_replacement

    if args.accepted:
        create_replacement(args.accepted, args.csv, args.folder, old_export=args.old_export)
    if args.prepare_only:
        print("Disposable MOHELA evidence replacement prepared; no financial approvals or live changes.")
        return 0
    if args.smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from parsetrail.core.recovery_bundle import digest
    from parsetrail.gui.ledger_mohela_replacement import preview_data
    from parsetrail.gui.ledger_preview import LedgerPreviewWindow
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    if args.smoke and os.name == "nt":
        from PySide6.QtGui import QFont, QFontDatabase

        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(font)))
        if families:
            app.setFont(QFont(families[0], 10))
    before = digest(args.folder / "fresh.db")
    window = LedgerPreviewWindow(preview_data(args.folder))
    window.show()
    if not args.smoke:
        return app.exec()
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        page = window.tabs.widget(i)
        if page.model.records:
            page.table.selectRow(0)
            assert page.details.toPlainText()
        app.processEvents()
        window.grab().save(str(args.folder / f"review-tab-{i}.png"))
    window.close()
    reopened = LedgerPreviewWindow(preview_data(args.folder))
    assert reopened.tabs.count() == 4
    reopened.close()
    assert digest(args.folder / "fresh.db") == before
    print("MOHELA read-only review/reopen smoke passed; database unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
