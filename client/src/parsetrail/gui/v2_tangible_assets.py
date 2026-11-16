"""Named tangible assets and independent, optional nonposting value estimates."""

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
    QGroupBox,
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


class _ValueItem(QTableWidgetItem):
    def __init__(self, text, value):
        super().__init__(text)
        self.setData(Qt.UserRole, value)
        self.setToolTip(text)

    def __lt__(self, other):
        left, right = self.data(Qt.UserRole), other.data(Qt.UserRole)
        return (left is not None, left or 0) < (right is not None, right or 0)


class V2TangibleAssets(QDialog):
    """One-shot dialog, disposed by its caller; financial mutations stay in services."""

    def __init__(self, workspace, parent=None, *, value_date=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace = workspace
        self.selected_account_id = None
        self._accounts = {}
        self._failure_notice = None
        self._success_notice = None
        self._saving_estimate = False
        self._rendering = False
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._completed)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        self.setWindowTitle("Tangible assets")
        self.resize(880, 620)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            "Name an asset such as a vehicle, precious metals, home or equipment. An optional value estimate stays separate from financing, book balances and spending."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(("Asset nickname", "Value date", "Entered value", "Estimated value today"))
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setMinimumHeight(100)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._table_selected)
        layout.addWidget(self.table, 1)
        form = QFormLayout()
        self.account = QComboBox()
        self.account.setAccessibleName("Tangible asset")
        self.account.setMinimumContentsLength(25)
        self.account.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.account.currentIndexChanged.connect(self._selected)
        form.addRow("Asset", self.account)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.name.setPlaceholderText("For example, Family vehicle or Gold coins")
        form.addRow("New asset nickname", self.name)
        layout.addLayout(form)
        self.valuation = QGroupBox("Add a dated value estimate (optional)")
        self.valuation.setCheckable(True)
        self.valuation.setChecked(False)
        valuation_form = QFormLayout(self.valuation)
        initial_date = value_date or date.today()
        self.value_date = QDateEdit(QDate(initial_date.year, initial_date.month, initial_date.day))
        self.value_date.setDisplayFormat("yyyy-MM-dd")
        self.value_date.setCalendarPopup(True)
        valuation_form.addRow("Value as of", self.value_date)
        self.amount = QLineEdit()
        self.amount.setPlaceholderText("Enter an independent value, zero or more")
        valuation_form.addRow("Your value (USD)", self.amount)
        self.rate = QLineEdit()
        self.rate.setPlaceholderText("Optional: -10 decline, +5 growth, 0 flat")
        valuation_form.addRow("Annual change (%)", self.rate)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        valuation_form.addRow("Valuation note", self.reason)
        hint = QLabel(
            "Blank annual change leaves future value unknown. Enter 0 for flat value; negative declines, positive grows. Range: -100% to +1000%."
        )
        hint.setWordWrap(True)
        valuation_form.addRow(hint)
        layout.addWidget(self.valuation)
        self.valuation.toggled.connect(self._input_changed)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        self.save = QPushButton("Create asset")
        self.save.clicked.connect(self._save)
        layout.addWidget(self.save)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        for field in (self.name, self.amount, self.rate, self.reason):
            field.textChanged.connect(self._input_changed)
        self.refresh()

    def refresh(self):
        today = date.today()

        def read(store, _cancelled):
            accounts = tuple(a for a in store.financial_accounts() if a.product_type == "tangible_asset")
            return accounts, store.tangible_asset_values(as_of=today)

        self.jobs.submit("snapshot", read)

    def _completed(self, key, result):
        if key == "snapshot":
            self._rendering = True
            accounts, values = result
            current = self.selected_account_id or self.account.currentData()
            self._accounts = {account.id: account for account in accounts}
            self.account.blockSignals(True)
            self.account.clear()
            self.account.addItem("Create a new tangible asset…", None)
            for account in accounts:
                self.account.addItem(account.name, account.id)
            self.account.setCurrentIndex(max(0, self.account.findData(current)))
            self.account.blockSignals(False)
            by_account = {value.account_id: value for value in values}
            self.table.setSortingEnabled(False)
            self.table.setRowCount(len(accounts))
            for index, account in enumerate(accounts):
                value = by_account.get(account.id)
                items = [QTableWidgetItem(account.name)]
                if value is None:
                    items += [QTableWidgetItem("Unknown"), _ValueItem("Unknown", None), _ValueItem("Unknown", None)]
                else:
                    items += [
                        QTableWidgetItem(str(value.value_date)),
                        _ValueItem(_money(value.amount_minor), value.amount_minor),
                        _ValueItem(
                            _money(value.estimated_minor) if value.estimated_minor is not None else "Unknown",
                            value.estimated_minor,
                        ),
                    ]
                for column, item in enumerate(items):
                    item.setData(Qt.UserRole + 1, account.id)
                    item.setToolTip(item.text())
                    if column == 3 and value is not None and value.estimated_minor is None:
                        item.setToolTip(
                            "No estimate before the entered value date."
                            if value.as_of < value.value_date
                            else "No annual change entered; later value is unknown."
                            if value.annual_rate_basis_points is None
                            else "The estimate is outside the supported date or amount range."
                        )
                    if column in (2, 3):
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.table.setItem(index, column, item)
            self.table.setSortingEnabled(True)
            self._selected()
            self._rendering = False
        else:
            self._failure_notice = None
            self.selected_account_id = result
            self.reason.setText("Initial Review")
            self.valuation.setChecked(False)
            self._success_notice = (
                "Estimate saved. No journal entry or budget expense was created."
                if self._saving_estimate
                else "Asset saved. Value unknown; add an estimate whenever you have one."
            )
            self.status.setText(self._success_notice)
            self.refresh()

    def _table_selected(self):
        selected = self.table.selectedItems()
        if selected:
            self.account.setCurrentIndex(self.account.findData(selected[0].data(Qt.UserRole + 1)))

    def _selected(self, *_args):
        if not self._rendering:
            self._success_notice = None
        creating = self.account.currentData() is None
        self.name.setEnabled(creating and not self.jobs.writing)
        self._update()

    def _inputs(self):
        creating = self.account.currentData() is None
        if creating and not self.name.text().strip():
            raise ValueError("Enter a nickname for the asset.")
        if not self.valuation.isChecked():
            if not creating:
                raise ValueError("Select the optional value estimate to add a new value.")
            return None, None
        amount = _typed_minor(self.amount.text())
        if amount < 0:
            raise ValueError("Enter an asset value of zero or more.")
        rate = None
        if self.rate.text().strip():
            try:
                percentage = Decimal(self.rate.text().strip())
                if (
                    not percentage.is_finite()
                    or not -100 <= percentage <= 1000
                    or percentage * 100 != (percentage * 100).to_integral_value()
                ):
                    raise ValueError
                rate = int(percentage * 100)
            except (InvalidOperation, ValueError):
                raise ValueError("Enter an annual change from -100 to +1000 with at most two decimal places.") from None
        if not self.reason.text().strip():
            raise ValueError("Enter a valuation note.")
        return amount, rate

    def _input_changed(self, *_args):
        self._failure_notice = None
        self._success_notice = None
        self._update()

    def _update(self, *_args):
        creating = self.account.currentData() is None
        self.save.setText(
            "Create asset and save estimate"
            if creating and self.valuation.isChecked()
            else "Create asset"
            if creating
            else "Save new dated estimate"
        )
        try:
            self._inputs()
            ready = not self.jobs.pending
        except ValueError as error:
            ready = False
            if not self.jobs.pending:
                self.status.setText(str(error))
        else:
            if not self.jobs.pending:
                self.status.setText(
                    "Ready to save the independent estimate. No journal entry or budget expense will be created."
                    if self.valuation.isChecked()
                    else "Ready to create the named asset. Its value remains unknown."
                )
        if self._failure_notice is not None:
            self.status.setText(self._failure_notice)
        elif self._success_notice is not None:
            self.status.setText(self._success_notice)
        self.save.setEnabled(ready)

    def _save(self):
        try:
            amount, rate = self._inputs()
        except ValueError as error:
            self.status.setText(str(error))
            return
        account_id = self.account.currentData()
        self._success_notice = None
        self._saving_estimate = amount is not None
        value_date, reason = self.value_date.date().toPython(), self.reason.text().strip()
        if account_id is None:
            account = FinancialAccount(
                "tangible:" + uuid4().hex, self.name.text().strip(), "asset", None, product_type="tangible_asset"
            )

            def write(store, _cancelled):
                if amount is None:
                    store.add_financial_account(account)
                else:
                    store.create_tangible_asset(
                        account,
                        value_date=value_date,
                        amount_minor=amount,
                        annual_rate_basis_points=rate,
                        reason=reason,
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
        for field in (self.account, self.name, self.valuation):
            field.setEnabled(not self.jobs.writing)
        self.name.setEnabled(self.account.currentData() is None and not self.jobs.writing)
        if busy:
            self.save.setEnabled(False)
        else:
            self._update()

    def _failed(self, _key, error):
        self._failure_notice = "The asset was not saved. Inspect the entered details and retry. " + str(error)
        self._update()

    def reject(self):
        if self.jobs.writing:
            self.status.setText("Finishing the confirmed save before closing.")
            return
        self.jobs.close()
        super().reject()

    def closeEvent(self, event):
        if not self.jobs.close():
            event.ignore()
            return
        super().closeEvent(event)
