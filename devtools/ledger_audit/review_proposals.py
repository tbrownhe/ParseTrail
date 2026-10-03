"""Prepare or reopen a disposable ledger workflow review workspace."""

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
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--transfers", action="store_true", help="Review transfers/card payments alongside ordinary proposals."
    )
    modes.add_argument("--openings", action="store_true", help="Review source provenance and opening positions.")
    modes.add_argument("--reconciliation", action="store_true", help="Review statement checks and source provenance.")
    parser.add_argument(
        "--readiness", type=Path, help="Verified opening-readiness folder, required for a new opening workspace."
    )
    parser.add_argument(
        "--smoke", action="store_true", help="Offscreen accept/reject/reopen test; requires a new --candidates copy."
    )
    args = parser.parse_args()
    if args.readiness and not (args.openings or args.reconciliation):
        parser.error("--readiness requires --openings or --reconciliation")
    if (args.openings or args.reconciliation) and args.candidates and not args.readiness:
        parser.error("A new opening/reconciliation workspace requires --readiness")
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
            if args.openings or args.reconciliation:
                from parsetrail.core.ledger_opening_review import OpeningReview

                OpeningReview(review, args.readiness)
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
        if args.reconciliation:
            from parsetrail.core.ledger_opening_review import OpeningReview
            from parsetrail.gui.ledger_reconciliation_review import ReconciliationReviewWindow

            OpeningReview(review, args.readiness)
            window = ReconciliationReviewWindow(review, args.folder)
        elif args.openings:
            from parsetrail.core.ledger_opening_review import OpeningReview
            from parsetrail.gui.ledger_opening_review import OpeningReviewWindow

            window = OpeningReviewWindow(OpeningReview(review, args.readiness))
        elif args.transfers:
            from parsetrail.gui.ledger_transfer_review import TransferReviewWindow

            window = TransferReviewWindow(review)
        else:
            window = ProposalReviewWindow(review)
        window.show()
        if args.smoke and args.reconciliation:
            from parsetrail.gui.ledger_reconciliation_review import SourceReviewDialog
            from PySide6.QtCore import QTimer

            app.processEvents()
            index = next(
                i
                for i, r in enumerate(window.page.model.records)
                if r["row"]["status"] == "checked"
                and r["row"]["statement_id"] not in window.openings.anchors[r["row"]["account_id"]]["statement_ids"]
            )
            window.page.table.selectRow(index)
            sid = window.selected()["row"]["statement_id"]
            old = window.view.report["input_version"]

            def exercise_source(save):
                dialog = app.activeModalWidget()
                assert isinstance(dialog, SourceReviewDialog)
                dialog.opening.setCurrentIndex(dialog.opening.findData("reported"))
                dialog.closing.setCurrentIndex(dialog.closing.findData("reported"))
                dialog.timing.setChecked(True)
                dialog.reference.setText("Automated workflow test; not financial verification")
                if save:
                    dialog.grab().save(str(args.folder / "source-review-smoke.png"))
                    dialog.save.click()
                else:
                    dialog.reject()

            QTimer.singleShot(0, lambda: exercise_source(False))
            window.edit.click()
            assert window.openings.provenance(sid)["sequence"] is None
            assert window.current
            QTimer.singleShot(0, lambda: exercise_source(True))
            window.edit.click()
            assert not window.current and window.view.report["input_version"] == old
            assert window.evidence.model.records
            app.processEvents()
            window.grab().save(str(args.folder / "review-smoke.png"))
            window.close()
        elif args.smoke and args.openings:
            app.processEvents()
            for zero in (False, True):
                index = next(
                    i
                    for i, r in enumerate(window.page.model.records)
                    if (window.openings.anchors[r["account_id"]]["proposed_amount_minor"] == 0) == zero
                )
                window.page.table.selectRow(index)
                aid = window.selected()["account_id"]
                window.opening.setCurrentIndex(window.opening.findData("reported"))
                window.timing.setChecked(True)
                window.reference.setText("Automated workflow test; not actual source verification")
                window.note.setText("Disposable UI exercise only")
                window.confirm = lambda *_: False
                window.save.click()
                assert window.openings.provenance(window.current_source)["sequence"] is None
                window.confirm = lambda *_: True
                window.save.click()
                assert window.post.isEnabled()
                window.confirm = lambda *_: False
                window.post.click()
                assert aid not in window.openings.decisions()
                window.confirm = lambda *_: True
                window.post.click()
                assert window.openings.status(aid)["state"] == ("confirmed_zero" if zero else "posted")
            app.processEvents()
            window.grab().save(str(args.folder / "review-smoke.png"))
            window.close()
        elif args.smoke and args.transfers:
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
        if args.reconciliation:
            from parsetrail.gui.ledger_reconciliation_review import ReconciliationReviewWindow

            window = ReconciliationReviewWindow(reopened, args.folder)
            assert not window.current
            assert window.openings.provenance(sid)["reference"].startswith("Automated workflow test")
            window.check.click()
            assert window.current and window.view.report["input_version"] != old
            window.page.search.setText("NO-MATCH-SYNTHETIC-FILTER-123456")
            assert not window.edit.isEnabled() and not window.evidence.model.records
            window.close()
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        elif args.openings:
            from parsetrail.core.ledger_opening_review import OpeningReview

            assert len(OpeningReview(reopened).decisions()) == 2
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (1,)
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerAllocations").fetchone() == (0,)
        elif args.transfers:
            from parsetrail.core.ledger_transfers import TransferReview

            assert len(TransferReview(reopened).decisions()) == 2
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (2,)
        else:
            assert len(reopened.decisions()) == 2
            assert reopened.store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (1,)
    print("Disposable ledger workflow and reopen smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
