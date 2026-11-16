"""Authored vehicle values are separate from source amounts and cash spending."""

from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from parsetrail.core.v2_profile_store import FinancialAccount
from parsetrail.gui.v2_account_anchors import _typed_minor
from parsetrail.gui.v2_evidence_preview import _money
from parsetrail.gui.v2_form_state import install_form_styles
from parsetrail.gui.v2_profile_jobs import ProfileJobs


class V2TangibleAssets(QDialog):
    """Reusable-in-dialog controls; each displayed dialog is disposed by its caller."""

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace = workspace
        self.selected_account_id = None
        self._accounts = {}
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._completed)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        self.setWindowTitle("Vehicle assets and estimated values")
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Record your vehicle separately from its loan. Values entered here are nonposting valuations; they do not create spending or establish the acquisition's funding."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Vehicle", "Value date", "Entered value", "Estimated value today"))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.account = QComboBox()
        self.account.currentIndexChanged.connect(self._selected)
        form.addRow("Vehicle", self.account)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.name.setPlaceholderText("For example, Primary vehicle")
        form.addRow("New vehicle name", self.name)
        self.value_date = QDateEdit(QDate.currentDate())
        self.value_date.setDisplayFormat("yyyy-MM-dd")
        self.value_date.setCalendarPopup(True)
        form.addRow("Value as of", self.value_date)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Enter independently of the loan amount")
        form.addRow("Your value (USD)", self.amount)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("Optional, for example 10.00")
        form.addRow("Estimated annual decline (%)", self.rate)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        form.addRow("Valuation note", self.reason)
        layout.addLayout(form)
        qualification = QLabel(
            "Estimated values are projections from your entered value, date and rate. They remain separate from book balances, statement evidence and monthly budget spending."
        )
        qualification.setWordWrap(True)
        layout.addWidget(qualification)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.save = QPushButton("Save vehicle value")
        self.save.clicked.connect(self._save)
        layout.addWidget(self.save)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for field in (self.name, self.amount, self.rate, self.reason):
            field.textChanged.connect(self._update)
        self.refresh()

    def refresh(self):
        today = date.today()

        def read(store, _cancelled):
            accounts = tuple(account for account in store.financial_accounts() if account.product_type == "vehicle")
            return accounts, store.tangible_asset_values(as_of=today)

        self.jobs.submit("snapshot", read)

    def _completed(self, key, result):
        if key == "snapshot":
            accounts, values = result
            current = self.selected_account_id or self.account.currentData()
            self._accounts = {account.id: account for account in accounts}
            self.account.blockSignals(True)
            self.account.clear()
            self.account.addItem("Create a new vehicle asset…", None)
            for account in accounts:
                self.account.addItem(account.name, account.id)
            self.account.setCurrentIndex(max(0, self.account.findData(current)))
            self.account.blockSignals(False)
            self.table.setRowCount(len(values))
            for index, value in enumerate(values):
                for column, text in enumerate(
                    (value.account_name, value.value_date, _money(value.amount_minor), _money(value.estimated_minor))
                ):
                    self.table.setItem(index, column, QTableWidgetItem(str(text)))
            self._selected()
        else:
            self.selected_account_id = result
            self.reason.setText("Initial Review")
            self.status.setText("Vehicle value saved. No journal or budget expense was created.")
            self.refresh()

    def _selected(self, *_args):
        creating = self.account.currentData() is None
        self.name.setEnabled(creating)
        self.save.setText("Create vehicle and save value" if creating else "Save new dated value")
        self._update()

    def _inputs(self):
        amount = _typed_minor(self.amount.text())
        if amount < 0:
            raise ValueError("Enter a vehicle value of zero or more.")
        rate = None
        if self.rate.text().strip():
            try:
                percentage = Decimal(self.rate.text().strip())
                if (
                    not percentage.is_finite()
                    or not 0 <= percentage <= 100
                    or percentage * 100 != (percentage * 100).to_integral_value()
                ):
                    raise ValueError
                rate = int(percentage * 100)
            except (InvalidOperation, ValueError):
                raise ValueError("Enter an annual percentage from 0 to 100 with at most two decimal places.") from None
        if self.account.currentData() is None and not self.name.text().strip():
            raise ValueError("Enter the new vehicle's name.")
        if not self.reason.text().strip():
            raise ValueError("Enter a valuation note.")
        return amount, rate

    def _update(self, *_args):
        try:
            self._inputs()
            ready = not self.jobs.pending
        except ValueError:
            ready = False
        self.save.setEnabled(ready)

    def _save(self):
        try:
            amount, rate = self._inputs()
        except ValueError as error:
            self.status.setText(str(error))
            return
        account_id = self.account.currentData()
        value_date, reason = self.value_date.date().toPython(), self.reason.text().strip()
        if account_id is None:
            account_id = "vehicle:" + uuid4().hex
            account = FinancialAccount(account_id, self.name.text().strip(), "asset", None, product_type="vehicle")

            def write(store, _cancelled):
                store.create_tangible_asset(
                    account, value_date=value_date, amount_minor=amount, annual_rate_basis_points=rate, reason=reason
                )
                return account.id
        else:

            def write(store, _cancelled):
                store.set_tangible_asset_value(
                    account_id, value_date=value_date, amount_minor=amount, annual_rate_basis_points=rate, reason=reason
                )
                return account_id

        self.jobs.submit("save", write, write=True)

    def _busy(self, busy):
        if busy:
            self.save.setEnabled(False)
        else:
            self._update()

    def _failed(self, _key, error):
        self.status.setText("The vehicle value was not saved. Inspect the entered value/date and retry. " + str(error))
        self._update()

    def reject(self):
        if self.jobs.writing:
            self.status.setText("Finishing the confirmed value save before closing.")
            return
        self.jobs.close()
        super().reject()

    def closeEvent(self, event):
        if not self.jobs.close():
            event.ignore()
            return
        super().closeEvent(event)
