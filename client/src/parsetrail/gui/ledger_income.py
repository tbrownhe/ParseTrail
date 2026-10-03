"""Review explicitly classified cash income and category-only corrections."""

from parsetrail.core.ledger_income import IncomeCorrections, IncomeInterpretations
from parsetrail.gui.ledger_expense_corrections import ExpenseCorrectionDialog, ExpenseCorrectionWindow
from parsetrail.gui.ledger_expense_interpretations import ExpenseInterpretationDialog, ExpenseInterpretationPage
from parsetrail.gui.ledger_preview import money


class IncomeInterpretationDialog(ExpenseInterpretationDialog):
    category_type = "Income"

    def __init__(self, service, record, parent=None):
        super().__init__(service, record, parent)
        self.setWindowTitle("Preview cash income receipt — disposable copy")
        self.confirmation_title = "Post cash income receipt"
        self.notice.setText(
            f"{record['posting_date']} · {record['account_name']} · {money(record['amount_minor'])}\n"
            f"{record['description']}\n"
            "Explicitly classify this deposit as income. Its presence in the list does not establish its purpose.\n"
            "Record only the amount received; gross pay and deductions are not inferred. "
            "Transfers, loan proceeds and expense refunds need their own accounting treatment.\n"
            f"Posting-date provenance: {record['date_provenance']}. Source evidence and prior categories remain history."
        )
        self.apply.setText("Post income receipt…")

    def preview_lines(self):
        names = {a["id"]: a["name"] for a in self.plan["category_accounts"]}
        lines = [
            "Income received by category:",
            *[f"  {names[p['account_id']]}: {money(-p['amount_minor'])}" for p in self.plan["entry"]["postings"][1:]],
            "",
            f"Income added to ledger: {money(self.record['amount_minor'])}",
            f"Cash received: {money(self.record['amount_minor'])}",
            "One journal debits cash and credits income, consuming this receipt once.",
            "Income is displayed positive; income journal credits are stored negative.",
            "This is the deposited amount, not reconstructed gross pay. No payroll deductions are inferred.",
            "Source amount, account, date and description are unchanged.",
            f"Posting-date provenance: {self.plan['date_provenance']}",
            "Income classification does not certify source balances or coverage. Previous reconciliation checks become stale.",
            f"Reason: {self.plan['reason']}",
        ]
        if self.plan["proposal"]:
            lines += [
                "",
                "Original expense/refund proposal remains rejected:",
                self.plan["proposal"]["decision"]["reason"],
            ]
        return lines

    def confirm_message(self):
        return (
            "Post this explicit income receipt in the disposable copy?\n\n"
            f"Income and cash received: {money(self.record['amount_minor'])}\n"
            "Only proceed if income treatment is intended. Gross pay and deductions are not inferred.\n"
            f"Reason: {self.plan['reason']}"
        )


class IncomeCorrectionDialog(ExpenseCorrectionDialog):
    category_type = "Income"

    def __init__(self, service, record, parent=None):
        super().__init__(service, record, parent)
        self.setWindowTitle("Preview income category correction — disposable copy")
        self.confirmation_title = "Apply income category correction"
        entry = record["entry"]
        self.notice.setText(
            f"{entry['posting_date']} · {record['account_name']} · {money(record['amount_minor'])}\n"
            f"{entry['description']}\nOnly income-category distribution changes. Cash received and total income remain unchanged.\n"
            "Enter positive amounts totalling the original receipt; a correction reason is required."
        )

    def preview_lines(self):
        names = {a["id"]: a["name"] for a in self.plan["category_accounts"]}
        return [
            "Current income by category:",
            *[f"  {c['name']}: {money(-c['amount_minor'])}" for c in self.record["categories"]],
            "",
            "Replacement income by category:",
            *[
                f"  {names[p['account_id']]}: {money(-p['amount_minor'])}"
                for p in self.plan["replacement"]["postings"][1:]
            ],
            "",
            f"Cash receipt preserved: {money(self.record['amount_minor'])}",
            "Total income change: $0.00. Only category distribution changes.",
            "The original journal is reversed and a reviewed replacement is posted; both remain in history.",
            "Income is displayed positive; income journal credits are stored negative.",
            "Previous reconciliation checks become stale.",
            f"Reason: {self.plan['reason']}",
        ]

    def confirm_message(self):
        return (
            "Apply this income category correction in the disposable copy?\n\n"
            f"Cash receipt: {money(self.record['amount_minor'])} (unchanged)\nTotal income change: $0.00\n"
            "The original journal will be reversed and replaced.\n"
            f"Reason: {self.plan['reason']}"
        )


class IncomeInterpretationPage(ExpenseInterpretationPage):
    service_type = IncomeInterpretations
    dialog_type = IncomeInterpretationDialog
    action_text = "Classify as income…"
    scope_text = "positive checking/savings receipts"
    notice_text = (
        "These unposted checking/savings receipts are not automatically income. Choose the treatment explicitly.\n"
        "Income records the amount received. Gross pay/deductions are not inferred; transfers, loan proceeds and expense refunds need their own workflows."
    )
    detail_text = "Income treatment is not implied. Record only the amount received; no gross pay or payroll deductions are inferred."


class IncomeReviewWindow(ExpenseCorrectionWindow):
    service_type = IncomeCorrections
    dialog_type = IncomeCorrectionDialog
    window_title = "ParseTrail — Income review workflow test (disposable copy)"
    interpretation_window_title = window_title
    posted_title = "Posted income receipts"
    entry_label = "income"
    category_sign = -1
    guidance = "Classify eligible receipts in Unposted movements, then review or correct their income categories here. Income is displayed positive; journal credits are stored negative."

    def __init__(self, review):
        super().__init__(review, interpretations=True)

    def make_interpretations(self, review):
        return IncomeInterpretationPage(review, self.show_posted, self)
