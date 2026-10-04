import pytest
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.gui.ledger_loan_payments import LoanPaymentDialog, LoanPaymentWindow
from PySide6.QtCore import QTimer

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_loan_payments import loan_workspace as loan_workspace
from .test_ledger_proposal_review import app as app


def test_preview_cancel_post_visible_status_and_reopen(app, loan_workspace):
    with ProposalReview(loan_workspace) as review:
        window = LoanPaymentWindow(review)
        window.show()
        window.page.table.selectRow(0)
        before = list(review.store.connection.iterdump())

        def exercise(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, LoanPaymentDialog)
            assert dialog.category.currentIndex() == -1
            assert not dialog.apply.isEnabled()
            dialog.category.setCurrentIndex(dialog.category.findData(2))
            dialog.preview.click()
            assert dialog.apply.isEnabled()
            assert "Interest expense: $1.00" in dialog.preview_text.toPlainText()
            assert "principal reduction: $9.00" in dialog.preview_text.toPlainText()
            dialog.reason.setText("")
            if not save:
                dialog.close()
                return
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
        assert window.tabs.currentIndex() == 1
        assert len(window.confirmed.model.records) == 1 and not window.page.model.records
        assert "Confirmed and posted" in window.confirmed.details.toPlainText()
        assert "Loan interest" in window.confirmed.details.toPlainText()
        window.days.setValue(0)
        assert len(window.confirmed.model.records) == 1
        window.close()
    with ProposalReview(loan_workspace) as review:
        window = LoanPaymentWindow(review)
        window.tabs.setCurrentIndex(1)
        window.confirmed.table.selectRow(0)
        assert "Confirmed and posted" in window.confirmed.details.toPlainText()
        assert not window.edit.isEnabled()
        window.close()


@pytest.mark.usefixtures("app")
def test_filters_and_tabs_clear_selection_and_disable_post(loan_workspace):
    with ProposalReview(loan_workspace) as review:
        window = LoanPaymentWindow(review)
        window.page.table.selectRow(0)
        assert window.edit.isEnabled()
        window.page.search.setText("no-such-record")
        assert not window.edit.isEnabled() and not window.page.details.toPlainText()
        window.page.search.clear()
        window.page.table.selectRow(0)
        window.tabs.setCurrentIndex(3)
        assert not window.edit.isEnabled()
        window.tabs.setCurrentIndex(0)
        assert not window.edit.isEnabled()
        window.close()


@pytest.mark.parametrize("edit", ["category", "reason"])
@pytest.mark.usefixtures("app")
def test_edits_invalidate_preview(loan_workspace, edit):
    with ProposalReview(loan_workspace) as review:
        window = LoanPaymentWindow(review)
        dialog = LoanPaymentDialog(window.service, window.service.snapshot()["pairs"][0], 7)
        dialog.category.setCurrentIndex(dialog.category.findData(2))
        dialog.preview.click()
        assert dialog.apply.isEnabled()
        if edit == "category":
            dialog.category.setCurrentIndex(dialog.category.findData(1))
        else:
            dialog.reason.setText("Changed note")
        assert dialog.plan is None and not dialog.apply.isEnabled()
        dialog.close()
        window.close()


@pytest.mark.usefixtures("app")
def test_competing_post_refuses_stale_dialog_and_shows_blocker(loan_workspace):
    with ProposalReview(loan_workspace) as review:
        window = LoanPaymentWindow(review)
        dialog = LoanPaymentDialog(window.service, window.service.snapshot()["pairs"][0], 7)
        dialog.category.setCurrentIndex(dialog.category.findData(2))
        dialog.preview.click()
        TransferReview(review).decide([("source:bank_payment", "source:card_payment")], "confirmed")
        dialog.confirm = lambda: True
        dialog.apply.click()
        assert not dialog.apply.isEnabled() and "allocated" in dialog.preview_text.toPlainText()
        assert not window.service.decisions()
        window.status.setCurrentText("Blocked")
        window.page.table.selectRow(0)
        assert not window.edit.isEnabled() and "allocated" in window.page.details.toPlainText()
        dialog.close()
        window.close()
