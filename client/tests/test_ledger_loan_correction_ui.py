import pytest
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.gui.ledger_loan_corrections import LoanCorrectionDialog
from parsetrail.gui.ledger_loan_payments import LoanPaymentWindow
from PySide6.QtCore import QTimer

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_loan_corrections import correction_rebuild as correction_rebuild
from .test_ledger_loan_corrections import correction_workspace as correction_workspace
from .test_ledger_loan_corrections import post_original
from .test_ledger_loan_payments import loan_rebuild as loan_rebuild
from .test_ledger_proposal_review import app as app


def select_replacement(dialog):
    row = next(i for i, r in enumerate(dialog.page.model.records) if not r["candidate"]["blockers"])
    dialog.page.table.selectRow(row)


def test_cancel_correct_history_and_reopen(app, correction_workspace):
    with ProposalReview(correction_workspace[0]) as review:
        post_original(review)
        window = LoanPaymentWindow(review)
        window.show()
        window.tabs.setCurrentIndex(1)
        window.confirmed.table.selectRow(0)
        assert window.correct.isEnabled()
        before = list(review.store.connection.iterdump())

        def exercise(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, LoanCorrectionDialog)
            select_replacement(dialog)
            assert not dialog.preview.isEnabled() and not dialog.apply.isEnabled()
            dialog.reason.setText("Wrong bank selected in workflow test")
            dialog.preview.click()
            assert dialog.apply.isEnabled()
            text = dialog.preview_text.toPlainText()
            assert "Net expense change: $0.00" in text and "unallocated" in text
            assert "Previous bank: Checking" in text and "Replacement bank: Savings" in text
            if not save:
                dialog.close()
                return
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == before
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: exercise(False))
        window.correct.click()
        assert list(review.store.connection.iterdump()) == before
        QTimer.singleShot(0, lambda: exercise(True))
        window.correct.click()
        assert window.selected_confirmed()["cells"][0] == "Savings"
        assert window.selected_confirmed()["cells"][-1] == "Corrected and posted"
        assert window.history.model.records[0]["cells"][0] == "Checking"
        window.tabs.setCurrentIndex(4)
        window.history.table.selectRow(0)
        assert not window.correct.isEnabled()
        assert "Superseded bank match" in window.history.details.toPlainText()
        window.close()
    with ProposalReview(correction_workspace[0], read_only=True) as review:
        window = LoanPaymentWindow(review)
        assert window.confirmed.model.records[0]["cells"][0] == "Savings"
        assert window.history.model.records[0]["cells"][0] == "Checking"
        window.close()


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize("change", ["note", "selection", "filter", "days"])
def test_changed_inputs_invalidate_correction_preview(correction_workspace, change):
    with ProposalReview(correction_workspace[0]) as review:
        post_original(review)
        window = LoanPaymentWindow(review)
        dialog = LoanCorrectionDialog(window.corrections, "loan")
        select_replacement(dialog)
        dialog.reason.setText("Correct the match")
        dialog.preview.click()
        assert dialog.apply.isEnabled()
        if change == "note":
            dialog.reason.setText("Changed reason")
        elif change == "selection":
            row = next(i for i, r in enumerate(dialog.page.model.records) if r["candidate"]["blockers"])
            dialog.page.table.selectRow(row)
        elif change == "filter":
            dialog.page.search.setText("no-match-synthetic-filter")
        else:
            dialog.days.setValue(0)
        assert not dialog.apply.isEnabled() and dialog.plan is None
        dialog.close()
        window.close()


@pytest.mark.usefixtures("app")
def test_stale_correction_cannot_post_after_competing_allocation(correction_workspace):
    with ProposalReview(correction_workspace[0]) as review:
        post_original(review)
        window = LoanPaymentWindow(review)
        dialog = LoanCorrectionDialog(window.corrections, "loan")
        select_replacement(dialog)
        dialog.reason.setText("Correct the match")
        dialog.preview.click()
        TransferReview(review).decide([("source:bank_other", "source:card_payment")], "confirmed")
        dialog.confirm = lambda: True
        dialog.apply.click()
        assert not dialog.apply.isEnabled() and "allocated" in dialog.preview_text.toPlainText()
        assert not window.corrections.decisions()
        dialog.refresh()
        assert all(r["candidate"]["blockers"] for r in dialog.page.model.records)
        dialog.close()
        window.close()
