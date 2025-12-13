import math
from datetime import datetime, timedelta

import pandas as pd
from PyQt5.QtCore import QAbstractTableModel, QDate, Qt
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableView,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker

from parsetrail.core import cluster, query
from parsetrail.core.orm import Transactions
from parsetrail.core.validation import Transaction, ValidationError


class InsertTransactionDialog(QDialog):
    def __init__(self, Session: sessionmaker, account_name="", close_account=False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Insert Transaction")
        self.setGeometry(100, 100, 400, 200)
        self.Session = Session
        self.account_name = account_name
        self.close_account = close_account

        # Main layout
        layout = QVBoxLayout(self)

        # Form layout for inputs
        form_layout = QFormLayout()

        # Dropdown to select account
        self.account_dropdown = QComboBox(self)
        self.account_dropdown.currentIndexChanged.connect(self.update_balance)

        # Labels for latest balance info
        self.latest_balance_value = QLineEdit("$0.00")
        self.latest_balance_value.setReadOnly(True)
        self.latest_balance_value.setStyleSheet("color: gray; background-color: #f0f0f0;")

        self.latest_date_value = QLineEdit("N/A")
        self.latest_date_value.setReadOnly(True)
        self.latest_date_value.setStyleSheet("color: gray; background-color: #f0f0f0;")

        # New transaction date selector
        self.date_selector = QDateEdit(self)
        self.date_selector.setCalendarPopup(True)
        self.date_selector.setDate(QDate.currentDate())
        self.date_selector.setDisplayFormat("yyyy-MM-dd")

        # Amount input
        self.amount_input = QLineEdit(self)
        self.amount_input.setPlaceholderText("Enter transaction amount")

        # Description input
        self.description_input = QLineEdit(self)
        self.description_input.setPlaceholderText("Enter transaction description")

        # Add inputs to the form layout
        form_layout.addRow("Account:", self.account_dropdown)
        form_layout.addRow("Latest Balance:", self.latest_balance_value)
        form_layout.addRow("As of Date:", self.latest_date_value)
        form_layout.addRow("Effective Date:", self.date_selector)
        form_layout.addRow("Amount:", self.amount_input)
        form_layout.addRow("Description:", self.description_input)

        layout.addLayout(form_layout)

        # Submit button
        self.submit_button = QPushButton("Submit")
        self.submit_button.clicked.connect(self.submit)
        layout.addWidget(self.submit_button)

        # Set the layout
        self.setLayout(layout)

        # Update the initial values
        self.load_accounts()
        self.update_balance()

    def load_accounts(self):
        """
        Load account names and IDs from the database and populate the dropdown.
        """
        try:
            with self.Session() as session:
                data = query.accounts_with_ids(session)

            selected_index = -1
            for index, (account_id, account_name) in enumerate(data):
                self.account_dropdown.addItem(f"{account_name} (ID: {account_id})", account_id)
                if self.account_name and account_name == self.account_name:
                    selected_index = index

            # Set the dropdown to the selected index if a match was found
            if selected_index != -1:
                self.account_dropdown.setCurrentIndex(selected_index)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load accounts:\n{str(e)}")

    def update_balance(self):
        QApplication.processEvents()
        account_id = self.account_dropdown.currentData()
        if account_id:
            # Query the database for the most recent balance for this account
            with self.Session() as session:
                result = query.latest_balance(session, account_id)
            if result:
                # Set latest balance fields
                latest_date, latest_balance = result
                self.latest_balance_value.setText(f"{latest_balance:.2f}")
                self.latest_date_value.setText(f"{latest_date}")

                # Handle account closure shortcut
                if self.close_account:
                    close_date = datetime.strptime(latest_date, r"%Y-%m-%d") + timedelta(days=30)
                    self.date_selector.setDate(QDate(close_date.year, close_date.month, close_date.day))
                    self.amount_input.setText(f"{-latest_balance:.2f}")
                    self.description_input.setText("Account Closed Manually")

            else:
                # If no transactions found, assume balance is zero
                self.latest_balance_value.setText("0.00")
                self.latest_date_value.setText("N/A")
        else:
            # Clear balance display if no account is selected
            self.latest_balance_value.setText("0.00")
            self.latest_date_value.setText("N/A")

    def validate_input(self) -> tuple[int, list[Transaction]]:
        # Get inputs
        account_id = self.account_dropdown.currentData()
        q_date = self.date_selector.date()
        date = datetime(q_date.year(), q_date.month(), q_date.day())
        amount = self.amount_input.text()
        balance = self.latest_balance_value.text()
        desc = self.description_input.text()

        # Validate inputs
        if not account_id or not amount or not balance or not desc:
            QMessageBox.warning(self, "Missing Information", "Please fill in all fields.")
            return

        # Ensure the amount is a valid number
        try:
            amount = float(amount)
            balance = round(float(balance) + amount, 2)
        except ValueError:
            QMessageBox.warning(
                self,
                "Invalid Amount",
                "Please enter a valid number for the amount.",
            )
            return

        # Traceability for manual entry
        desc = "Manual Entry: " + desc

        # Create transaction object
        transactions = [
            Transaction(
                transaction_date=date,
                posting_date=date,
                amount=amount,
                desc=desc,
                balance=balance,
            )
        ]

        return account_id, transactions

    def insert_transaction(self):
        account_id, transactions = self.validate_input()

        # Hash transaction
        transactions = Transaction.hash_transactions(account_id, transactions)

        # Validate transactions before insertion
        errors = Transaction.validate_complete(transactions)
        if errors:
            raise ValidationError("\n".join(errors))

            # Convert to list of dict for db insertion
        statement_id = None
        rows = Transaction.to_db_rows(statement_id, account_id, transactions)

        # Insert transaction into the database
        with self.Session() as session:
            query.insert_rows_carefully(
                session,
                Transactions,
                rows,
                skip_duplicates=True,
            )
            session.commit()

    def submit(self):
        """
        Validate inputs and insert the transaction into the database.
        """
        try:
            self.insert_transaction()

            QMessageBox.information(self, "Success", "Transaction has been added successfully.")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to insert transaction:\n{str(e)}")


class TransactionTableModel(QAbstractTableModel):
    def __init__(self, data, parent=None):
        super().__init__(parent)
        self._data = data  # Expecting a pandas DataFrame
        self.headers = list(data.columns)

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return None

        value = self._data.iloc[index.row(), index.column()]

        if role == Qt.DisplayRole:
            return str(value)  # Display as a string
        if role == Qt.TextAlignmentRole:
            return Qt.AlignRight if isinstance(value, (int, float)) else Qt.AlignLeft

        return None

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return self.headers[section]  # Column headers
        elif orientation == Qt.Vertical:
            return str(section + 1)  # Row numbers

    def sort(self, column, order):
        """Sort the table by the given column."""
        col_name = self.headers[column]
        ascending = order == Qt.AscendingOrder
        self.layoutAboutToBeChanged.emit()
        self._data.sort_values(by=col_name, ascending=ascending, inplace=True)
        self.layoutChanged.emit()

    def update_data(self, new_data: pd.DataFrame):
        """Update the model with new data."""
        self.layoutAboutToBeChanged.emit()
        self._data = new_data
        self.headers = list(new_data.columns)
        self.layoutChanged.emit()


class RecurringTransactionsDialog(QDialog):
    def __init__(self, Session: sessionmaker, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recurring Transactions Analysis")

        # Fit primary screen
        screen = QApplication.primaryScreen()
        geometry = screen.availableGeometry()
        self.resize(int(0.6 * geometry.width()), int(0.8 * geometry.height()))

        self.Session = Session
        self.clustered = None
        self.columns = [
            "AccountName",
            "Date",
            "Amount",
            "Category",
            "Cluster",
            "Description",
        ]

        # Main layout
        main_layout = QVBoxLayout(self)

        # Control section layout
        control_widget = QWidget()
        control_layout = QGridLayout()
        control_widget.setLayout(control_layout)

        # Start date and end date selectors
        row = 0
        start_date_label = QLabel("Start Date:")
        start_date_label.setAlignment(Qt.AlignRight)
        control_layout.addWidget(start_date_label, row, 0)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDate(QDate.currentDate().addYears(-1))
        control_layout.addWidget(self.start_date, row, 1)

        end_date_label = QLabel("Start Date:")
        end_date_label.setAlignment(Qt.AlignRight)
        control_layout.addWidget(end_date_label, row, 2)

        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDate(QDate.currentDate())
        control_layout.addWidget(self.end_date, row, 3)
        row += 1

        # Clustering options
        self.include_amount_checkbox = QCheckBox("Include Amount in Clustering Analysis")
        control_layout.addWidget(self.include_amount_checkbox, row, 2, 1, 2)
        row += 1

        # Sliders
        self.eps_slider = self._create_slider("Cluster Separation (Epsilon)", 1, 200, 50, 100)
        self.min_samples_slider = self._create_slider("Min Members per Cluster", 1, 10, 2, 1)
        self.min_frequency_slider = self._create_slider("Min Interval (days)", 1, 30, 3, 1)
        self.max_interval_slider = self._create_slider("Max Interval (days)", 1, 100, 35, 1, show_inf=True)
        self.variance_slider = self._create_slider("Max Amount Variance (%)", 0, 300, 100, 1, show_inf=True)

        sliders = [
            self.eps_slider,
            self.min_samples_slider,
            self.min_frequency_slider,
            self.max_interval_slider,
            self.variance_slider,
        ]
        for row, slider in enumerate(sliders, start=row):
            control_layout.addWidget(slider["label"], row, 0, 1, 2)
            control_layout.addWidget(slider["slider"], row, 2, 1, 2)
        row += 1

        # Analyze button
        analyze_button = QPushButton("Analyze")
        analyze_button.clicked.connect(self.analyze_transactions)
        control_layout.addWidget(analyze_button, row, 2, 1, 2)

        # Add the control section to the main layout
        main_layout.addWidget(control_widget)

        # Table for displaying results
        self.table = QTableView()
        self.model = TransactionTableModel(pd.DataFrame([], columns=self.columns))
        self.table.setModel(self.model)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        main_layout.addWidget(self.table)

        # Save Table and Close buttons
        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Save Table")
        self.save_button.clicked.connect(self.save_to_csv)
        button_layout.addWidget(self.save_button)

        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.accept)
        button_layout.addWidget(self.close_button)

        main_layout.addLayout(button_layout)

        self.setLayout(main_layout)

    def _create_slider(self, label, min_val, max_val, default_val, divide_by, show_inf=False):
        precision = int(math.ceil(math.log10(divide_by)))
        slider_label = QLabel(f"{label}: {default_val / divide_by:.{precision}f}")
        slider_label.setAlignment(Qt.AlignRight)
        slider = QSlider(Qt.Horizontal)
        slider.setMinimum(min_val)
        slider.setMaximum(max_val)
        slider.setValue(default_val)

        def update_label(value):
            if show_inf and value == max_val:
                slider_label.setText(f"{label}: Inf")
            else:
                slider_label.setText(f"{label}: {value / divide_by:.{precision}f}")

        slider.valueChanged.connect(update_label)
        return {"slider": slider, "label": slider_label}

    def inf_slider(self, slider):
        value = 1e6 if slider.value() == slider.maximum() else slider.value()
        return value

    def analyze_transactions(self):
        # Retrieve and process transactions
        start_date = self.start_date.date().toPyDate()
        end_date = self.end_date.date().toPyDate()

        with self.Session() as session:
            data, columns = query.transactions_in_range(session, start_date, end_date)
        transactions = pd.DataFrame(data, columns=columns)

        if transactions.empty:
            self.table.setRowCount(0)
            return

        # Preprocess and cluster
        eps = self.eps_slider["slider"].value() / 100
        min_samples = self.min_samples_slider["slider"].value()
        min_frequency = self.min_frequency_slider["slider"].value()
        max_interval = self.inf_slider(self.max_interval_slider["slider"])
        max_variance = self.inf_slider(self.variance_slider["slider"])
        include_amount = self.include_amount_checkbox.isChecked()

        # Perform the clustering
        self.clustered = cluster.recurring_transactions(
            transactions,
            eps=eps,
            min_samples=min_samples,
            min_frequency=min_frequency,
            max_interval=max_interval,
            include_amount=include_amount,
            max_variance=max_variance,
        )

        # Update table
        self.model.update_data(self.clustered[self.columns].reset_index(drop=True))

    def update_table(self, df: pd.DataFrame):
        self.table.setRowCount(len(df))
        for row_index, row in df.iterrows():
            self.table.setItem(row_index, 0, QTableWidgetItem(row["AccountName"]))
            self.table.setItem(row_index, 1, QTableWidgetItem(row["Date"].strftime("%Y-%m-%d")))
            self.table.setItem(row_index, 2, QTableWidgetItem(f"${row['Amount']:.2f}"))
            self.table.setItem(row_index, 3, QTableWidgetItem(str(row["Cluster"])))
            self.table.setItem(row_index, 4, QTableWidgetItem(row["Description"]))

        # Sort by Cluster
        self.table.sortItems(3, Qt.AscendingOrder)

    def save_to_csv(self):
        """
        Save the clustered transactions to a CSV file.
        """
        if self.clustered is None:
            QMessageBox.warning(self, "No Data", "There are no clustered transactions to save.")
            return

        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Clustered Transactions",
            "",
            "CSV Files (*.csv);;All Files (*)",
            options=options,
        )
        if file_path:
            try:
                # Save the dataframe to CSV
                self.clustered.to_csv(file_path, index=False)
                QMessageBox.information(self, "Success", f"Clustered transactions saved to {file_path}.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save file: {e}")
