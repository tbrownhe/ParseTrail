"""Prepare or reopen a disposable ordinary-journal review workspace."""

import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--folder", type=Path, required=True, help="New review directory, or a prepared directory to resume."
    )
    parser.add_argument("--candidates", type=Path, help="Checksum-verified proposal directory; creates --folder once.")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--transfers", action="store_true", help="Review transfers/card payments alongside ordinary proposals."
    )
    parser.add_argument(
        "--smoke", action="store_true", help="Offscreen accept/reject/reopen test; requires a new --candidates copy."
    )
    args = parser.parse_args()
    if args.smoke:
        if not args.candidates or args.prepare_only:
            parser.error("--smoke requires --candidates and cannot use --prepare-only")
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review

    if args.candidates:
        prepare_review(args.candidates, args.folder)
    if args.prepare_only:
        with ProposalReview(args.folder) as review:
            if args.transfers:
                from parsetrail.core.ledger_transfers import TransferReview

                snapshot = TransferReview(review).snapshot()
                (args.folder / "transfer-preview.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
            print("Disposable proposal review is ready.")
        return 0
    from parsetrail.gui.ledger_proposal_review import ProposalReviewWindow
    from PySide6.QtWidgets import QApplication

    with ProposalReview(args.folder) as review:
        app = QApplication([])
        if args.smoke and os.name == "nt":
            from PySide6.QtGui import QFont, QFontDatabase

            font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
            font_id = QFontDatabase.addApplicationFont(str(font))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                app.setFont(QFont(families[0], 10))
        if args.transfers:
            from parsetrail.gui.ledger_transfer_review import TransferReviewWindow

            window = TransferReviewWindow(review)
        else:
            window = ProposalReviewWindow(review)
        window.show()
        if args.smoke and args.transfers:
            app.processEvents()
            rows = window.page.model.records
            index = next(
                i
                for i, r in enumerate(rows)
                if r["pair"]["date_gap_days"] and r["pair"]["status"] == "unique_candidate"
            )
            window.page.table.selectRow(index)
            first = window.selected()["pair"]["id"]
            window.confirm = lambda *_: False
            window.confirm_button.click()
            assert not window.transfers.decisions()
            window.confirm = lambda *_: True
            window.confirm_button.click()
            window.page.table.selectRow(0)
            second = window.selected()["pair"]["id"]
            window.note.setText("Automated disposable pairing-dismissal test")
            window.dismiss_button.click()
            assert window.transfers.decisions()[first]["action"] == "confirmed"
            assert window.transfers.decisions()[second]["action"] == "dismissed"
            window.filter.setCurrentText("Confirmed")
            window.page.table.selectRow(0)
            assert "transfer clearing" in window.page.details.toPlainText()
            window.tabs.setCurrentIndex(1)
            window.movements.search.setText("NO-MATCH-SYNTHETIC-FILTER-123456")
            assert window.movements.proxy.rowCount() == 0
            window.tabs.setCurrentIndex(0)
            window.page.table.selectRow(0)
            app.processEvents()
            window.grab().save(str(args.folder / "review-smoke.png"))
            window.close()
        elif args.smoke:
            app.processEvents()
            assert window.page.proxy.rowCount() >= 2
            window.page.table.selectRow(0)
            first = window.selected()[0]["key"]
            window.reason.setText("Automated disposable acceptance test")
            window.confirm = lambda *_: False
            window.accept.click()
            assert not review.decisions()
            window.confirm = lambda *_: True
            window.accept.click()
            window.page.table.selectRow(0)
            second = window.selected()[0]["key"]
            window.reason.setText("Automated disposable rejection test")
            window.reject.click()
            assert review.decisions()[first]["action"] == "accepted"
            assert review.decisions()[second]["action"] == "rejected"
            window.status_filter.setCurrentText("Posted")
            window.page.table.selectRow(0)
            assert "Automated disposable acceptance test" in window.page.details.toPlainText()
            window.page.search.setText("NO-MATCH-SYNTHETIC-FILTER-123456")
            assert window.page.proxy.rowCount() == 0 and not window.selected()
            window.page.search.clear()
            window.page.table.selectRow(0)
            app.processEvents()
            window.grab().save(str(args.folder / "review-smoke.png"))
            window.close()
        else:
            return app.exec()
    with ProposalReview(args.folder) as reopened:
        if args.transfers:
            from parsetrail.core.ledger_transfers import TransferReview

            assert len(TransferReview(reopened).decisions()) == 2
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (2,)
        else:
            assert len(reopened.decisions()) == 2
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (1,)
    print("Disposable proposal review accept/reject/reopen smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
