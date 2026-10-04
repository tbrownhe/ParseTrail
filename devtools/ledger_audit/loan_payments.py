"""Prepare or open the bounded Capital One loan-payment workflow test."""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "client" / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, help="Accepted unposted candidates; creates a new review folder.")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    if args.smoke and (not args.candidates or args.prepare_only):
        parser.error("--smoke requires a new --candidates copy and cannot use --prepare-only")
    from parsetrail.core.ledger_proposal_review import ProposalReview, prepare_review

    if args.candidates:
        prepare_review(args.candidates, args.folder)
    if args.prepare_only:
        with ProposalReview(args.folder):
            print("Disposable loan-payment workspace ready.")
        return 0
    if args.smoke:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from parsetrail.gui.ledger_loan_payments import LoanPaymentDialog, LoanPaymentWindow
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication([])
    if args.smoke and os.name == "nt":
        from PySide6.QtGui import QFont, QFontDatabase

        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        families = QFontDatabase.applicationFontFamilies(QFontDatabase.addApplicationFont(str(font)))
        if families:
            app.setFont(QFont(families[0], 10))
    with ProposalReview(args.folder) as review:
        window = LoanPaymentWindow(review)
        window.show()
        if not args.smoke:
            return app.exec()
        assert window.page.model.records
        window.page.table.selectRow(0)
        payment_id = window.selected()["pair"]["payment_id"]
        before = list(review.store.connection.iterdump())

        def exercise(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, LoanPaymentDialog)
            assert dialog.category.currentIndex() == -1
            if dialog.category.isEnabled():
                dialog.category.setCurrentIndex(0)
            dialog.preview.click()
            assert dialog.apply.isEnabled()
            if not save:
                dialog.close()
                return
            dialog.grab().save(str(args.folder / "loan-preview-smoke.png"))
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == before
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: exercise(False))
        window.edit.click()
        assert list(review.store.connection.iterdump()) == before
        window.page.table.selectRow(0)
        QTimer.singleShot(0, lambda: exercise(True))
        window.edit.click()
        assert window.tabs.currentIndex() == 1 and payment_id in window.service.decisions()
        assert "Confirmed and posted" in window.confirmed.details.toPlainText()
        app.processEvents()
        window.grab().save(str(args.folder / "loan-review-smoke.png"))
        window.close()
    with ProposalReview(args.folder) as review:
        window = LoanPaymentWindow(review)
        assert payment_id in window.service.decisions()
        assert len(window.confirmed.model.records) == 1
        window.close()
    print("Disposable loan-payment preview/cancel/post/reopen smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
