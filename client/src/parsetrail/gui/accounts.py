from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from sqlalchemy.orm import Session, sessionmaker

from parsetrail.core import query
from parsetrail.core.orm import AccountNumbers, Accounts
from parsetrail.core.utils import open_file_in_os


class AppreciationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Appreciation Rate Calculator")

        # Main layout
        layout = QVBoxLayout(self)

        # Descriptive text
        desc_text = (
            "Use this to estimate the Annual Appreciation Rate of a Tangible Asset.\n"
            "The result can be used for Tangible Assets entered manually into\n"
            "the Edit Accounts Dialog."
        )
        desc_label = QLabel(desc_text)
        layout.addWidget(desc_label)

        # Form layout for user inputs
        form_layout = QFormLayout()

        # Start date selector
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addYears(-1))  # Default: 1 year ago
        form_layout.addRow("Start Date:", self.start_date)

        # End date selector
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())  # Default: today
        form_layout.addRow("End Date:", self.end_date)

        # Starting value input
        self.start_value_edit = QLineEdit()
        self.start_value_edit.setPlaceholderText("Enter the starting value")
        form_layout.addRow("Starting Value:", self.start_value_edit)

        # Ending value input
        self.end_value_edit = QLineEdit()
        self.end_value_edit.setPlaceholderText("Enter the ending value")
        form_layout.addRow("Ending Value:", self.end_value_edit)

        # Output display
        self.result_edit = QLineEdit()
        self.result_edit.setReadOnly(True)
        self.result_edit.setPlaceholderText("Annual Appreciation Rate (%)")
        form_layout.addRow("Appreciation Rate (%)", self.result_edit)

        layout.addLayout(form_layout)

        # Button layout
        button_layout = QHBoxLayout()

        # Submit button
        self.submit_button = QPushButton("Calculate")
        self.submit_button.clicked.connect(self.calculate_appreciation_rate)
        button_layout.addWidget(self.submit_button)

        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.close)
        button_layout.addWidget(self.close_button)

        layout.addLayout(button_layout)
        self.setFixedSize(layout.sizeHint())

    def calculate_appreciation_rate(self):
        try:
            # Extract input values
            start_date = self.start_date.date().toPyDate()
            end_date = self.end_date.date().toPyDate()
            start_value = float(self.start_value_edit.text())
            end_value = float(self.end_value_edit.text())

            # Validate inputs
            if start_date >= end_date:
                raise ValueError("Start Date must be earlier than End Date.")
            if start_value <= 0 or end_value <= 0:
                raise ValueError("Values must be positive.")

            # Calculate appreciation rate
            days = (end_date - start_date).days
            annual_rate = ((end_value / start_value) ** (365 / days) - 1) * 100  # Convert to percentage

            # Display result
            self.result_edit.setText(f"{annual_rate:.2f}")
        except ValueError as e:
            QMessageBox.warning(self, "Input Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred: {e}")


class BalanceCheckDialog(QDialog):
    def __init__(self, account_name: str, balance: float, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Account Balance Alert")
        self.setMinimumWidth(400)

        # Main layout
        layout = QVBoxLayout()

        # Informational message
        neg = "-" if balance < 0 else ""
        balance = abs(round(balance, 2))
        message = (
            f"The account '{account_name}' has a non-zero balance of {neg}${balance} "
            "and no recent transactions.\n\n"
            "Would you like to bring the account to zero by inserting a transaction manually?"
        )
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)

        # Buttons
        button_layout = QHBoxLayout()
        self.yes_button = QPushButton("Yes")
        self.no_button = QPushButton("No")
        button_layout.addWidget(self.yes_button)
        button_layout.addWidget(self.no_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connect buttons to dialog result
        self.yes_button.clicked.connect(self.accept)
        self.no_button.clicked.connect(self.reject)


def update_accounts_table(
    dialog: QDialog,
    session: Session,
    accounts_table: QTableWidget,
):
    accounts_table.setSortingEnabled(True)
    accounts_table.setSelectionBehavior(QAbstractItemView.SelectRows)
    accounts_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    data, columns = query.accounts_details(session)
    accounts_table.setRowCount(len(data))
    accounts_table.setColumnCount(len(columns))
    accounts_table.setHorizontalHeaderLabels(columns)
    accounts_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

    appreciation_idx = len(columns) - 1
    for row_idx, row_data in enumerate(data):
        for col_idx, value in enumerate(row_data):
            if col_idx == appreciation_idx:
                value = f"{value:.4f}" if value != 0 else "0"
            item = QTableWidgetItem(str(value))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            accounts_table.setItem(row_idx, col_idx, item)

    # Set minimum width based on table contents
    accounts_table.resizeColumnsToContents()
    pad = 200 if len(data) == 0 else 60
    total_width = sum(accounts_table.columnWidth(i) for i in range(accounts_table.columnCount()))
    total_width += accounts_table.verticalHeader().width()
    total_width += accounts_table.frameWidth() * 2

    dialog.setMinimumWidth(total_width + pad)
    dialog.adjustSize()


class EditAccountsDialog(QDialog):
    def __init__(self, Session: sessionmaker, company="", description=""):
        super().__init__()
        self.setWindowTitle("Edit Accounts")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        screen_height = QApplication.primaryScreen().availableGeometry().height()
        self.setMinimumHeight(int(screen_height * 0.6))
        self.setMaximumHeight(int(screen_height))
        self.setContentsMargins(10, 10, 10, 10)

        self.Session = Session
        self.selected_account = None

        # Main layout
        layout = QVBoxLayout(self)

        # Descriptive text
        desc1_text = "List of existing accounts:"
        desc1_label = QLabel(desc1_text)
        layout.addWidget(desc1_label)

        # Display Accounts table
        self.accounts_table = QTableWidget(self)
        layout.addWidget(self.accounts_table)
        with self.Session() as session:
            update_accounts_table(self, session, self.accounts_table)
        self.accounts_table.cellClicked.connect(self.populate_fields)

        # Descriptive text
        desc2_text = "To add or edit an account, please fill out the following information:"
        desc2_label = QLabel(desc2_text)
        layout.addWidget(desc2_label)

        # Form layout for user inputs
        form_layout = QFormLayout()

        self.account_name_edit = QLineEdit(self)
        self.account_name_edit.setPlaceholderText("Enter a UNIQUE name for this account")
        self.company_edit = QLineEdit(self)
        self.company_edit.setPlaceholderText("Enter the company name for this account")
        if company:
            self.company_edit.setText(company)
        self.description_edit = QLineEdit(self)
        self.description_edit.setPlaceholderText("Enter a description for this account")
        if description:
            self.description_edit.setText(description)
        self.account_type_combo = QComboBox(self)

        with self.Session() as session:
            account_types = query.account_types(session)
        self.account_type_combo.addItems([""] + account_types)

        self.appreciation_edit = QLineEdit(self)
        self.appreciation_edit.setPlaceholderText("Enter annual appreciation rate (%) for TangibleAssets only")
        self.appreciation_edit.setEnabled(False)

        self.account_type_combo.currentTextChanged.connect(self.toggle_appreciation_field)

        form_layout.addRow("Account Name:", self.account_name_edit)
        form_layout.addRow("Company:", self.company_edit)
        form_layout.addRow("Description:", self.description_edit)
        form_layout.addRow("Account Type:", self.account_type_combo)
        form_layout.addRow("Appreciation Rate (%):", self.appreciation_edit)

        layout.addLayout(form_layout)

        # Action buttons
        button_layout = QHBoxLayout()
        self.cancel_button = QPushButton("OK")
        self.cancel_button.clicked.connect(self.accept)
        button_layout.addWidget(self.cancel_button)

        self.add_button = QPushButton("Add Account")
        self.add_button.setStyleSheet("background-color: lightgreen; color: black;")
        self.add_button.clicked.connect(self.add_account)
        button_layout.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit Account")
        # self.edit_button.setStyleSheet("background-color: lightblue; color: black;")
        self.edit_button.clicked.connect(self.edit_account)
        self.edit_button.setEnabled(False)  # Disabled by default
        button_layout.addWidget(self.edit_button)

        self.delete_button = QPushButton("Delete Account")
        self.delete_button.setStyleSheet("background-color: lightcoral; color: black;")
        self.delete_button.clicked.connect(self.delete_account)
        self.delete_button.setEnabled(False)  # Disabled by default
        button_layout.addWidget(self.delete_button)

        layout.addLayout(button_layout)

        self.setLayout(layout)

    def toggle_appreciation_field(self, account_type: str):
        """
        Enable or disable the Appreciation Rate field based on account type.
        """
        if account_type == "TangibleAsset":
            self.appreciation_edit.setEnabled(True)
        else:
            self.appreciation_edit.clear()
            self.appreciation_edit.setEnabled(False)

    def populate_fields(self, row: int, column: int):
        """
        Populate fields with the data from the selected account in the table.
        """
        self.selected_account = self.accounts_table.item(row, 0).text()
        self.account_name_edit.setText(self.selected_account)
        self.company_edit.setText(self.accounts_table.item(row, 1).text())
        self.description_edit.setText(self.accounts_table.item(row, 2).text())
        self.account_type_combo.setCurrentText(self.accounts_table.item(row, 3).text())
        if self.appreciation_edit.isEnabled():
            self.appreciation_edit.setText(self.accounts_table.item(row, 4).text())
        self.edit_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def add_account(self):
        """
        Add a new account.
        """
        if not self.validate_fields():
            return

        account_type = self.account_type_combo.currentText()
        with self.Session() as session:
            account_type_id = query.account_type_id(session, account_type)

        appreciation_rate = self.get_appreciation_rate()

        row = {
            "AccountTypeID": account_type_id,
            "Company": self.company_edit.text(),
            "Description": self.description_edit.text(),
            "AccountName": self.account_name_edit.text(),
            "AppreciationRate": appreciation_rate or 0.0,
        }

        try:
            with self.Session() as session:
                query.insert_rows_batched(session, Accounts, [row])
            QMessageBox.information(self, "Success", "Account added successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to add account:\n{str(e)}")
        self.refresh_table()

    def edit_account(self):
        """
        Edit the selected account.
        """
        confirm = QMessageBox.question(
            self,
            "Edit Account",
            f"Are you sure you want to edit the account '{self.selected_account}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        if not self.validate_fields():
            return

        account_type = self.account_type_combo.currentText()
        appreciation_rate = self.get_appreciation_rate()

        try:
            with self.Session() as session:
                account_type_id = query.account_type_id(session, account_type)
                query.update_account_details(
                    session,
                    account_name=self.selected_account,
                    account_type_id=account_type_id,
                    company=self.company_edit.text(),
                    desc=self.description_edit.text(),
                    appreciation=appreciation_rate or 0.0,
                )
            QMessageBox.information(self, "Success", "Account updated successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to update account:\n{str(e)}")
        self.refresh_table()

    def delete_account(self):
        """
        Delete the selected account.
        """
        confirm = QMessageBox.question(
            self,
            "Delete Account",
            f"Are you sure you want to delete the account '{self.selected_account}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            with self.Session() as session:
                session.query(Accounts).filter_by(AccountName=self.selected_account).delete()
                session.commit()
            QMessageBox.information(self, "Success", "Account deleted successfully.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete account:\n{str(e)}")
        self.refresh_table()

    def validate_fields(self) -> bool:
        """
        Validate required fields.
        """
        if not all(
            [
                self.account_name_edit.text(),
                self.company_edit.text(),
                self.description_edit.text(),
                self.account_type_combo.currentText(),
            ]
        ):
            QMessageBox.warning(self, "Missing Information", "Please fill in all required fields.")
            return False
        return True

    def get_appreciation_rate(self) -> float:
        """
        Get the appreciation rate value.
        """
        if self.appreciation_edit.isEnabled():
            try:
                return float(self.appreciation_edit.text())
            except ValueError:
                QMessageBox.warning(
                    self,
                    "Invalid Input",
                    "Please enter a valid number for appreciation rate.",
                )
                return None
        return 0.0

    def refresh_table(self):
        """
        Refresh the accounts table.
        """
        with self.Session() as session:
            update_accounts_table(self, session, self.accounts_table)
        self.clear_fields()

    def clear_fields(self):
        """
        Clear the input fields.
        """
        self.account_name_edit.clear()
        self.company_edit.clear()
        self.description_edit.clear()
        self.account_type_combo.setCurrentIndex(0)
        self.appreciation_edit.clear()
        self.edit_button.setEnabled(False)
        self.delete_button.setEnabled(False)


class AssignAccountNumber(QDialog):
    def __init__(
        self,
        Session: sessionmaker,
        fpath: Path,
        metadata: dict[str, str],
        account_num: str,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("New Account Number Found")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        screen_height = QApplication.primaryScreen().availableGeometry().height()
        self.setMinimumHeight(int(screen_height * 0.6))
        self.setMaximumHeight(int(screen_height))
        self.setContentsMargins(10, 10, 10, 10)

        self.Session = Session
        self.fpath = fpath
        self.account_num = account_num
        self.account_name = None

        # Set up layout
        layout = QVBoxLayout()

        # Display plugin metadata for the new account number
        self.company = metadata.get("COMPANY", "Unknown Company")
        self.statement_type = metadata.get("STATEMENT_TYPE", "statement type")

        # Display info to user
        desc1 = f"A {self.company} {self.statement_type} was found with\nnew Account Number: {account_num}"
        desc1_label = QLabel(desc1)
        layout.addWidget(desc1_label)

        # View statement button
        view_statement_button = QPushButton("View Statement")
        view_statement_button.clicked.connect(self.open_statement)
        layout.addWidget(view_statement_button)

        # Display info to user
        desc2 = (
            f"Select an Account to associate with '{account_num}' from the list.\n"
            "If the account has not been created yet, click 'Create New Account'."
        )
        desc2_label = QLabel(desc2)
        layout.addWidget(desc2_label)

        # Display Accounts table
        self.accounts_table = QTableWidget(self)
        self.accounts_table.cellClicked.connect(self.handle_cell_click)
        layout.addWidget(self.accounts_table)

        with self.Session() as session:
            update_accounts_table(self, session, self.accounts_table)

        # Add New Account button
        new_account_button = QPushButton("Create New Account")
        new_account_button.clicked.connect(self.new_account)

        # Add submit button
        submit_button = QPushButton("Submit")
        submit_button.clicked.connect(self.submit)

        button_layout = QHBoxLayout()
        button_layout.addWidget(new_account_button)
        button_layout.addWidget(submit_button)
        layout.addLayout(button_layout)

        # Set the layout in the QDialog
        self.setLayout(layout)

    def open_statement(self):
        open_file_in_os(self.fpath)

    def handle_cell_click(self, row, column):
        # Capture the AccountID of the clicked row
        account_id_item = self.accounts_table.item(row, 0)  # Assuming AccountID is in the first column
        if account_id_item:
            self.account_name = account_id_item.text()

    def new_account(self):
        dialog = EditAccountsDialog(self.Session, self.company, self.statement_type)
        dialog.exec_()

        with self.Session() as session:
            update_accounts_table(self, session, self.accounts_table)

        # Auto-select the newly created account (assuming it's added to the last row)
        self.accounts_table.selectRow(self.accounts_table.rowCount() - 1)
        self.account_name = self.accounts_table.item(self.accounts_table.rowCount() - 1, 0).text()

    def submit(self):
        """
        Gather all input values into the results dictionary and close the dialog.
        """
        # Close dialog and accept the current account ID selection
        if self.account_name is None:
            QMessageBox.warning(
                self,
                "No Account Selected",
                "Please select an account or create a new one.",
            )
        else:
            # Create the AccountNumber -> AccountID association in the db
            with self.Session() as session:
                self.account_id = query.account_id_of_account_name(session, self.account_name)
                row = {
                    "AccountID": self.account_id,
                    "AccountNumber": self.account_num,
                }
                query.insert_rows_batched(session, AccountNumbers, [row])

            self.accept()

    def get_account_id(self):
        """
        Returns the results dictionary with user inputs after the dialog is accepted.
        """
        return self.account_id
