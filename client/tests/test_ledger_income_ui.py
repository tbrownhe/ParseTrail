import pytest
from parsetrail.core.ledger_income import IncomeInterpretations
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.gui.ledger_income import IncomeCorrectionDialog, IncomeInterpretationDialog, IncomeReviewWindow
from PySide6.QtCore import QTimer

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_income import income_workspace as income_workspace
from .test_ledger_proposal_review import app as app


def choose(dialog, cid):
    combo = dialog.table.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(cid))


def test_income_preview_cancel_post_correct_and_reopen(app, income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        window = IncomeReviewWindow(review)
        window.show()
        page = window.interpretations
        assert len(page.records) == 1 and window.tabs.currentIndex() == 2
        page.page.table.selectRow(0)
        before = list(review.store.connection.iterdump())

        def post(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, IncomeInterpretationDialog)
            assert dialog.categories == {3: "Salary", 4: "Interest"}
            assert dialog.table.cellWidget(0, 0).currentIndex() == -1
            assert not dialog.apply.isEnabled()
            choose(dialog, 3)
            dialog.preview.click()
            assert dialog.apply.isEnabled() and not dialog.reason.text()
            assert "Income added to ledger: $10.00" in dialog.preview_text.toPlainText()
            assert "gross pay" in dialog.preview_text.toPlainText()
            if not save:
                dialog.close()
                return
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == before
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: post(False))
        page.interpret.click()
        assert list(review.store.connection.iterdump()) == before
        page.page.table.selectRow(0)
        QTimer.singleShot(0, lambda: post(True))
        page.interpret.click()
        assert window.tabs.currentIndex() == 0 and window.edit.isEnabled()
        assert window.selected()["cells"][4] == "Salary: $10.00"
        original_key = window.selected()["record"]["entry"]["key"]
        posted = list(review.store.connection.iterdump())

        def correct(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, IncomeCorrectionDialog)
            dialog.table.cellWidget(0, 1).setText("9.99")
            dialog.add_split(4, 1)
            dialog.preview.click()
            assert not dialog.apply.isEnabled()  # Corrections require a reason.
            dialog.reason.setText("Workflow category split")
            dialog.preview.click()
            assert "Total income change: $0.00" in dialog.preview_text.toPlainText()
            assert "Interest: $0.01" in dialog.preview_text.toPlainText()
            if not save:
                dialog.reject()
                return
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == posted
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: correct(False))
        window.edit.click()
        assert list(review.store.connection.iterdump()) == posted
        QTimer.singleShot(0, lambda: correct(True))
        window.edit.click()
        assert window.selected()["record"]["previous_key"] == original_key
        assert "Salary: $9.99" in window.selected()["cells"][4]
        window.filter.setCurrentText("Superseded")
        window.page.table.selectRow(0)
        assert not window.edit.isEnabled()
        window.tabs.setCurrentIndex(2)
        assert not page.records
        window.close()
    with ProposalReview(income_workspace[0]) as review:
        window = IncomeReviewWindow(review)
        assert not window.interpretations.records
        window.tabs.setCurrentIndex(0)
        window.page.table.selectRow(0)
        assert window.selected()["record"]["previous_key"] == original_key
        assert "Interest: $0.01" in window.selected()["cells"][4]
        window.close()


@pytest.mark.usefixtures("app")
def test_income_form_exact_amounts_and_preview_invalidation(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        service = IncomeInterpretations(review)
        dialog = IncomeInterpretationDialog(service, service.inventory()[0])
        choose(dialog, 4)
        dialog.table.cellWidget(0, 1).setText("9.99")
        dialog.preview.click()
        assert not dialog.apply.isEnabled()
        dialog.table.cellWidget(0, 1).setText("10.00")
        dialog.preview.click()
        assert dialog.apply.isEnabled()
        choose(dialog, 3)
        assert not dialog.apply.isEnabled() and not dialog.preview_text.toPlainText()
        dialog.preview.click()
        dialog.reason.setText("Edited note")
        assert not dialog.apply.isEnabled()
        dialog.preview.click()
        dialog.table.cellWidget(0, 1).setText("10.001")
        dialog.preview.click()
        assert not dialog.apply.isEnabled()
        dialog.reject()


@pytest.mark.usefixtures("app")
def test_income_rejected_refund_history_and_reason(income_workspace):
    with ProposalReview(income_workspace[0]) as review:
        review.decide(["proposal:bank_refund"], "rejected", "Review as income")
        window = IncomeReviewWindow(review)
        page = window.interpretations
        page.filter.setCurrentText("Rejected proposal")
        page.page.table.selectRow(0)
        assert "Review as income" in page.page.details.toPlainText()
        dialog = IncomeInterpretationDialog(page.service, page.selected()["record"])
        choose(dialog, 3)
        dialog.preview.click()
        assert not dialog.apply.isEnabled()
        dialog.reason.setText("Confirmed receipt purpose")
        dialog.preview.click()
        assert dialog.apply.isEnabled() and "remains rejected" in dialog.preview_text.toPlainText()
        dialog.confirm = lambda: True
        dialog.apply.click()
        assert review.decisions()["proposal:bank_refund"]["action"] == "rejected"
        page.reload.click()
        assert not page.selected() and not page.interpret.isEnabled()
        window.close()


@pytest.mark.usefixtures("app")
def test_income_stale_transfer_preview_and_filter_clearing(income_workspace):
    with ProposalReview(income_workspace[0]) as review, ProposalReview(income_workspace[0]) as other:
        window = IncomeReviewWindow(review)
        page = window.interpretations
        page.page.table.selectRow(0)
        assert page.interpret.isEnabled()
        page.page.search.setText("NO-MATCH")
        assert not page.interpret.isEnabled()
        page.page.search.clear()
        page.page.table.selectRow(0)
        dialog = IncomeInterpretationDialog(page.service, page.selected()["record"])
        choose(dialog, 4)
        dialog.preview.click()
        TransferReview(other).decide([("source:bank_payment", "source:interest")], "confirmed")
        before = list(review.store.connection.iterdump())
        dialog.confirm = lambda: True
        dialog.apply.click()
        assert "allocated" in dialog.error.text() and not dialog.apply.isEnabled()
        assert list(review.store.connection.iterdump()) == before
        dialog.close()
        page.reload.click()
        assert not page.selected() and not page.interpret.isEnabled()
        window.close()
