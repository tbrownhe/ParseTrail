"""Open the read-only review window for one verified disposable shadow run."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument(
        "--fresh", action="store_true", help="Review a fresh archive rebuild instead of a shadow conversion."
    )
    args = parser.parse_args()
    if args.smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from parsetrail.gui.ledger_preview import LedgerPreviewWindow, load_preview
    from PySide6.QtWidgets import QApplication

    if args.fresh:
        from parsetrail.gui.ledger_rebuild_preview import load_rebuild_preview

        data = load_rebuild_preview(args.folder)
    else:
        data = load_preview(args.folder)
    app = QApplication([])
    window = LedgerPreviewWindow(data)
    window.show()
    if args.smoke:
        app.processEvents()
        for index in range(window.tabs.count()):
            window.tabs.setCurrentIndex(index)
            page = window.tabs.widget(index)
            if page.proxy.rowCount():
                page.table.selectRow(0)
                app.processEvents()
                assert page.details.toPlainText()
            page.search.setText("NO-MATCH-SYNTHETIC-FILTER-123456")
            assert page.proxy.rowCount() == 0
            assert not page.details.toPlainText()
            page.search.clear()
        window.close()
        app.processEvents()
        print("Read-only ledger review smoke passed.")
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
