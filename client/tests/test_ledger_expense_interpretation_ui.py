import pytest
from parsetrail.core.ledger_expense_interpretations import DEFAULT_REASON, ExpenseInterpretations
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.gui.ledger_expense_corrections import ExpenseCorrectionWindow
from parsetrail.gui.ledger_expense_interpretations import ExpenseInterpretationDialog
from PySide6.QtCore import QTimer

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_expense_corrections import workspace as workspace
from .test_ledger_proposal_review import app as app


def choose(dialog, cid=2):
    combo = dialog.table.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(cid))


def test_reject_then_preview_cancel_post_and_reopen(app, workspace):
    with ProposalReview(workspace[0]) as review:
        window = ExpenseCorrectionWindow(review, interpretations=True)
        window.show()
        assert window.tabs.currentIndex() == 2
        window.tabs.setCurrentIndex(1)
        window.ordinary.page.search.setText("bank_purchase")
        window.ordinary.page.table.selectRow(0)
        window.ordinary.reason.setText("Wrong expense category")
        window.ordinary.confirm = lambda *_: True
        window.ordinary.reject.click()
        window.tabs.setCurrentIndex(2)
        page = window.interpretations
        page.filter.setCurrentText("Rejected proposal")
        page.page.table.selectRow(0)
        assert "Wrong expense category" in page.page.details.toPlainText()
        before = list(review.store.connection.iterdump())

        def interact(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, ExpenseInterpretationDialog)
            assert dialog.table.cellWidget(0, 0).currentIndex() == -1
            assert not dialog.apply.isEnabled()
            choose(dialog)
            dialog.preview.click()
            assert not dialog.apply.isEnabled()  # Rejected interpretation needs a new reason.
            dialog.reason.setText("Review corrected expense category")
            dialog.preview.click()
            assert dialog.apply.isEnabled()
            assert "Expense total added to ledger: $15.00" in dialog.preview_text.toPlainText()
            assert "Wrong expense category" in dialog.preview_text.toPlainText()
            if not save:
                dialog.close()
                return
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == before
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: interact(False))
        page.interpret.click()
        assert list(review.store.connection.iterdump()) == before
        page.page.table.selectRow(0)
        QTimer.singleShot(0, lambda: interact(True))
        page.interpret.click()
        assert window.tabs.currentIndex() == 0
        assert window.selected()["cells"][4] == "Household: $15.00"
        assert window.edit.isEnabled()
        window.tabs.setCurrentIndex(2)
        assert not page.page.model.records and not page.interpret.isEnabled()
        window.tabs.setCurrentIndex(1)
        assert review.decisions()["proposal:bank_purchase"]["action"] == "rejected"
        window.close()
    with ProposalReview(workspace[0]) as review:
        window = ExpenseCorrectionWindow(review, interpretations=True)
        assert "source:bank_purchase" not in {r["record"]["observation_id"] for r in window.interpretations.records}
        window.tabs.setCurrentIndex(0)
        assert len(window.page.model.records) == 1
        assert window.page.model.records[0]["cells"][4] == "Household: $15.00"
        window.close()


@pytest.mark.parametrize("oid,expected", [("source:bank_payment", "$10.00"), ("source:card_payment", "-$10.00")])
@pytest.mark.usefixtures("app")
def test_explicit_category_optional_note_split_preview_and_invalidation(workspace, oid, expected):
    with ProposalReview(workspace[0]) as review:
        service = ExpenseInterpretations(review)
        record = next(r for r in service.inventory() if r["observation_id"] == oid)
        before = list(review.store.connection.iterdump())
        dialog = ExpenseInterpretationDialog(service, record)
        dialog.preview.click()
        assert not dialog.apply.isEnabled()  # No default category decision.
        choose(dialog)
        dialog.table.cellWidget(0, 1).setText("9.99")
        dialog.add_split(1, 1)
        dialog.preview.click()
        assert dialog.apply.isEnabled()
        assert f"Expense total added to ledger: {expected}" in dialog.preview_text.toPlainText()
        assert dialog.plan["reason"] == DEFAULT_REASON
        dialog.reason.setText("New optional note")
        assert not dialog.apply.isEnabled() and not dialog.preview_text.toPlainText()
        dialog.preview.click()
        dialog.table.cellWidget(0, 1).setText("9.999")
        dialog.preview.click()
        assert not dialog.apply.isEnabled()
        dialog.reject()
        assert list(review.store.connection.iterdump()) == before


@pytest.mark.usefixtures("app")
def test_stale_transfer_preview_fails_without_extra_post_and_refresh_clears_row(workspace):
    with ProposalReview(workspace[0]) as review, ProposalReview(workspace[0]) as other:
        window = ExpenseCorrectionWindow(review, interpretations=True)
        page = window.interpretations
        page.page.search.setText("bank_payment")
        page.page.table.selectRow(0)
        dialog = ExpenseInterpretationDialog(page.service, page.selected()["record"])
        choose(dialog)
        dialog.preview.click()
        TransferReview(other).decide([("source:bank_payment", "source:card_payment")], "confirmed")
        before = list(review.store.connection.iterdump())
        dialog.confirm = lambda: True
        dialog.apply.click()
        assert "allocated" in dialog.error.text() and not dialog.apply.isEnabled()
        assert list(review.store.connection.iterdump()) == before
        dialog.reject()
        page.reload.click()
        assert not page.selected() and not page.interpret.isEnabled()
        window.close()


@pytest.mark.usefixtures("app")
def test_search_and_state_filter_clear_selection(workspace):
    with ProposalReview(workspace[0]) as review:
        window = ExpenseCorrectionWindow(review, interpretations=True)
        page = window.interpretations
        page.page.table.selectRow(0)
        assert page.interpret.isEnabled()
        page.page.search.setText("NO-MATCH")
        assert not page.selected() and not page.interpret.isEnabled()
        page.page.search.clear()
        page.page.table.selectRow(0)
        page.filter.setCurrentText("Rejected proposal")
        assert not page.selected() and not page.interpret.isEnabled()
        window.close()
