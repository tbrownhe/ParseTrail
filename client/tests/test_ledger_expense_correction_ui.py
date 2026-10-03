import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_expense_corrections import ExpenseCorrections
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_transfers import TransferReview
from parsetrail.gui.ledger_expense_corrections import ExpenseCorrectionDialog, ExpenseCorrectionWindow, split_amount
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog

from .test_ledger_candidates import rebuild as rebuild
from .test_ledger_expense_corrections import posted
from .test_ledger_expense_corrections import workspace as workspace
from .test_ledger_proposal_review import app as app


def change_category(dialog, cid=2):
    combo = dialog.table.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(cid))
    dialog.reason.setText("Workflow test category correction")


def test_empty_copy_accept_edit_cancel_apply_and_reopen(app, workspace):
    with ProposalReview(workspace[0]) as review:
        window = ExpenseCorrectionWindow(review)
        window.show()
        assert not window.page.model.records and not window.edit.isEnabled()
        window.tabs.setCurrentIndex(1)
        window.ordinary.page.search.setText("bank_purchase")
        window.ordinary.page.table.selectRow(0)
        window.ordinary.confirm = lambda *_: True
        window.ordinary.accept.click()
        window.tabs.setCurrentIndex(0)
        window.page.table.selectRow(0)
        app.processEvents()
        before = list(review.store.connection.iterdump())
        assert window.edit.isEnabled()

        def interact(save):
            dialog = app.activeModalWidget()
            assert isinstance(dialog, ExpenseCorrectionDialog)
            change_category(dialog)
            dialog.preview.click()
            assert dialog.apply.isEnabled()
            assert "Total expense change: $0.00" in dialog.preview_text.toPlainText()
            if not save:
                dialog.close()  # Window X behavior is cancellation too.
                return
            dialog.confirm = lambda: False
            dialog.apply.click()
            assert list(review.store.connection.iterdump()) == before
            dialog.confirm = lambda: True
            dialog.apply.click()

        QTimer.singleShot(0, lambda: interact(False))
        window.edit.click()
        assert list(review.store.connection.iterdump()) == before
        QTimer.singleShot(0, lambda: interact(True))
        window.edit.click()
        assert len(window.page.model.records) == 1
        assert window.selected()["record"]["previous_key"] == "accepted:proposal:bank_purchase"
        assert window.selected()["cells"][4] == "Household: $15.00"
        window.filter.setCurrentText("Superseded")
        window.page.table.selectRow(0)
        assert not window.edit.isEnabled()
        assert "Replacement:" in window.page.details.toPlainText()
        window.close()
    with ProposalReview(workspace[0]) as review:
        window = ExpenseCorrectionWindow(review)
        assert window.page.proxy.rowCount() == 1
        window.page.table.selectRow(0)
        assert window.selected()["cells"][4] == "Household: $15.00"
        window.page.search.setText("NO-MATCH")
        assert not window.selected() and not window.edit.isEnabled()
        window.close()


@pytest.mark.parametrize("pid", ["proposal:bank_purchase", "proposal:card_refund"])
def test_split_preview_invalidation_exact_totals_and_refund_signs(app, workspace, pid):
    with ProposalReview(workspace[0]) as review:
        posted(review, pid)
        service = ExpenseCorrections(review)
        record = service.entries()[0]
        dialog = ExpenseCorrectionDialog(service, record)
        dialog.show()
        app.processEvents()
        amount = abs(record["amount_minor"])
        dialog.table.cellWidget(0, 1).setText("1.00")
        dialog.add_split(2, amount - 100)
        dialog.reason.setText("Reviewed split")
        dialog.preview.click()
        assert dialog.apply.isEnabled() and "Remaining $0.00" in dialog.total.text()
        if record["amount_minor"] > 0:
            assert "Household: -$4.00" in dialog.preview_text.toPlainText()
        dialog.reason.setText("Changed explanation")
        assert dialog.plan is None and not dialog.apply.isEnabled() and not dialog.preview_text.toPlainText()
        dialog.preview.click()
        dialog.table.cellWidget(1, 1).setText("0.001")
        assert not dialog.apply.isEnabled()
        dialog.preview.click()
        assert "two decimal places" in dialog.error.text()
        dialog.table.cellWidget(1, 1).setText("1.00")
        dialog.preview.click()
        assert "exactly equal" in dialog.error.text()
        dialog.table.cellWidget(1, 1).setText(f"{(amount - 100) // 100}.{(amount - 100) % 100:02d}")
        dialog.preview.click()
        assert dialog.apply.isEnabled()
        # Category edits and row removal also invalidate a previously checked plan.
        dialog.table.cellWidget(1, 0).setCurrentIndex(dialog.table.cellWidget(1, 0).findData(1))
        assert not dialog.apply.isEnabled()
        dialog.preview.click()
        assert "repeated categories" in dialog.error.text()
        dialog.table.cellWidget(1, 2).click()
        assert dialog.table.rowCount() == 1 and dialog.plan is None
        dialog.reject()
        assert review.store.connection.execute("SELECT count(*) FROM LedgerCorrections").fetchone() == (0,)


def test_reason_and_actual_change_required(app, workspace):
    with ProposalReview(workspace[0]) as review:
        posted(review)
        service = ExpenseCorrections(review)
        dialog = ExpenseCorrectionDialog(service, service.entries()[0])
        app.processEvents()
        dialog.preview.click()
        assert not dialog.apply.isEnabled() and "nonempty" in dialog.error.text()
        dialog.reason.setText("A reason alone is not a correction")
        dialog.preview.click()
        assert not dialog.apply.isEnabled() and "unchanged" in dialog.error.text()
        dialog.reject()


def test_intervening_correction_rejects_apply_and_refresh_shows_replacement(app, workspace):
    with ProposalReview(workspace[0]) as review, ProposalReview(workspace[0]) as other:
        original = posted(review)
        window = ExpenseCorrectionWindow(review)
        window.page.table.selectRow(0)
        dialog = ExpenseCorrectionDialog(window.service, window.selected()["record"], window)
        change_category(dialog)
        dialog.preview.click()
        other_service = ExpenseCorrections(other)
        replacement = other_service.apply(other_service.preview(original, [(1, 500), (2, 1000)], "Another window"))
        before = list(review.store.connection.iterdump())
        dialog.confirm = lambda: True
        dialog.apply.click()
        app.processEvents()
        assert dialog.result() != QDialog.DialogCode.Accepted
        assert "already corrected" in dialog.error.text() and not dialog.apply.isEnabled()
        assert list(review.store.connection.iterdump()) == before
        dialog.reject()
        window.reload.click()
        window.page.table.selectRow(0)
        assert window.selected()["record"]["entry"]["key"] == replacement
        window.close()


def test_inventory_excludes_transfer_reversals_and_retains_correction_chain(workspace):
    with ProposalReview(workspace[0]) as review:
        original = posted(review)
        transfers = TransferReview(review)
        pair = transfers.snapshot()["pairs"][0]
        transfers.decide([(pair["outgoing_id"], pair["incoming_id"])], "confirmed")
        service = ExpenseCorrections(review)
        first = service.apply(service.preview(original, [(2, 1500)], "First correction"))
        last = service.apply(service.preview(first, [(1, 500), (2, 1000)], "Second correction"))
        before = list(review.store.connection.iterdump())
        entries = {r["entry"]["key"]: r for r in service.entries()}
        assert set(entries) == {original, first, last}
        assert entries[last]["active"] and entries[last]["previous_key"] == first
        assert not entries[first]["active"] and entries[first]["replacement_key"] == last
        assert list(review.store.connection.iterdump()) == before


@pytest.mark.parametrize("text", ["0", "-1", "1.001", "1e2", "NaN", "$1", "1,000", "92233720368547758.08"])
def test_invalid_split_text_is_never_rounded_or_coerced(text):
    with pytest.raises(LedgerError):
        split_amount(text)


def test_decimal_text_uses_exact_minor_units():
    assert split_amount("0.29") == 29
    assert split_amount(" 12.5 ") == 1250
