"""Explicit account decisions for a saved accountless 2.0 activity export."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from parsetrail.core.source_evidence import ActivityExportPayload, ObservationEvidence
from parsetrail.core.v2_profile_store import AccountBinding, FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_evidence_preview import _location, _money


class _BindingsModel(QAbstractTableModel):
    HEADERS = ("Source date", "Description", "Amount", "Ledger account", "Decision", "Source location")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: tuple[ObservationEvidence, ...] = ()
        self.bindings: tuple[AccountBinding, ...] = ()
        self.account_names: dict[str, str] = {}

    def replace(
        self,
        rows: tuple[ObservationEvidence, ...],
        bindings: tuple[AccountBinding, ...],
        accounts: tuple[FinancialAccount, ...],
    ) -> None:
        self.beginResetModel()
        self.rows = rows
        self.bindings = bindings
        self.account_names = {account.id: account.name for account in accounts}
        self.endResetModel()

    def rowCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.rows)

    def columnCount(self, _parent: QModelIndex = QModelIndex()) -> int:
        return len(self.HEADERS)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or role not in {Qt.DisplayRole, Qt.ToolTipRole}:
            return None
        row = self.rows[index.row()]
        binding = self.bindings[index.row()]
        values = (
            row.date.iso,
            row.description.text or "Description not printed",
            _money(row.amount.minor),
            self.account_names.get(binding.ledger_account_id, "Unassigned")
            if binding.ledger_account_id
            else "Unassigned",
            {"file": "Whole-file assertion", "row": "Row assignment", None: "Pending"}[binding.basis],
            _location(row.fragments[0].location),
        )
        return values[index.column()]


class V2AccountBindingReview(QDialog):
    """Review account ownership without changing source facts or posting entries."""

    def __init__(self, profile: Path, source_sha256: str, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source_sha256 = source_sha256
        self.setWindowTitle("2.0 account assignment review")
        self.resize(1080, 620)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "The rows below do not identify an account. Assign the whole file only when every row in the "
            "source lacks an account identity and belongs to one ledger account. For a mixed file, select "
            "rows with Ctrl or Shift and assign them below. "
            "No ledger entries are posted."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.lock_notice = QLabel()
        self.lock_notice.setWordWrap(True)
        layout.addWidget(self.lock_notice)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Ledger account:"))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(260)
        controls.addWidget(self.account_combo)
        self.file_button = QPushButton("Assert entire file")
        self.file_button.clicked.connect(self._assert_file)
        controls.addWidget(self.file_button)
        self.clear_file_button = QPushButton("Clear file assertion")
        self.clear_file_button.clicked.connect(self._clear_file)
        controls.addWidget(self.clear_file_button)
        layout.addLayout(controls)

        self.model = _BindingsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        for column in (0, 2, 3, 4, 5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.selectionModel().selectionChanged.connect(self._update_controls)
        layout.addWidget(self.table)

        row_controls = QHBoxLayout()
        self.assign_rows_button = QPushButton("Assign selected rows")
        self.assign_rows_button.clicked.connect(self._assign_selected)
        row_controls.addWidget(self.assign_rows_button)
        self.clear_rows_button = QPushButton("Clear selected rows")
        self.clear_rows_button.clicked.connect(self._clear_selected)
        row_controls.addWidget(self.clear_rows_button)
        row_controls.addStretch()
        layout.addLayout(row_controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload()

    def _reload(self) -> None:
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            evidence = store.load_import(self.source_sha256).evidence
            payload = evidence.payload
            if not isinstance(payload, ActivityExportPayload) or not any(
                row.source_account is None for row in payload.rows
            ):
                raise ProfileFormatError("account_review_requires_accountless_export")
            accounts = store.financial_accounts()
            rows = tuple(row for row in payload.rows if row.source_account is None)
            bindings = tuple(
                binding
                for row, binding in zip(payload.rows, store.account_bindings(self.source_sha256), strict=True)
                if row.source_account is None
            )
            self._file_eligible = len(rows) == len(payload.rows)
            self.posted_row_ids = store.journal_history_row_ids(self.source_sha256)
            self.overlap_row_ids = store.source_overlap_history_row_ids(self.source_sha256)
        selected_account = self.account_combo.currentData()
        self.account_combo.clear()
        for account in accounts:
            self.account_combo.addItem(f"{account.name} ({account.institution_key}, {account.kind})", account.id)
        if selected_account is not None:
            selected_index = self.account_combo.findData(selected_account)
            if selected_index >= 0:
                self.account_combo.setCurrentIndex(selected_index)
        self.model.replace(rows, bindings, accounts)
        file_count = sum(binding.basis == "file" for binding in bindings)
        row_count = sum(binding.basis == "row" for binding in bindings)
        if file_count:
            account_id = bindings[0].ledger_account_id
            account_name = next(account.name for account in accounts if account.id == account_id)
            self.status.setText(f"Whole-file assertion: {account_name} · {file_count} rows")
        elif row_count:
            self.status.setText(f"Row assignments: {row_count} of {len(bindings)} rows")
        else:
            self.status.setText(f"No account assignments · {len(bindings)} rows pending")
        if not accounts:
            self.status.setText(self.status.text() + " · Create a financial account before assigning")
        self._update_controls()

    def _selected_row_ids(self) -> tuple[str, ...]:
        return tuple(self.model.rows[index.row()].row_id for index in self.table.selectionModel().selectedRows())

    def _update_controls(self, *_args) -> None:
        selected = self._selected_row_ids()
        selected_bindings = (self.model.bindings[index.row()] for index in self.table.selectionModel().selectedRows())
        file_mode = any(binding.basis == "file" for binding in self.model.bindings)
        row_mode = any(binding.basis == "row" for binding in self.model.bindings)
        locked_rows = self.posted_row_ids | self.overlap_row_ids
        file_locked = file_mode and bool(locked_rows)
        selected_locked = any(row_id in locked_rows for row_id in selected)
        account_available = self.account_combo.currentData() is not None
        self.file_button.setEnabled(
            account_available and self._file_eligible and bool(self.model.rows) and not row_mode and not file_locked
        )
        self.clear_file_button.setEnabled(file_mode and not file_locked)
        self.assign_rows_button.setEnabled(
            account_available and bool(selected) and not file_mode and not selected_locked
        )
        self.clear_rows_button.setEnabled(
            not file_mode and not selected_locked and any(binding.basis == "row" for binding in selected_bindings)
        )
        self.lock_notice.setText(
            "Saved repeated-row review history locks this account assignment, including after returning a pair to pending."
            if (file_locked and self.overlap_row_ids) or any(row_id in self.overlap_row_ids for row_id in selected)
            else "Posted journal history locks the whole-file account assertion. Review or correct the entry first."
            if file_locked
            else "Selected posted rows have locked account assignments. Review or correct their entries first."
            if selected_locked
            else ""
        )

    def _write(self, action) -> None:
        try:
            with V2ProfileStore.open(self.profile) as store:
                action(store)
            self._reload()
        except (ProfileFormatError, OSError) as exc:
            message = (
                "This account assignment has saved repeated-row review history and cannot be reassigned."
                if str(exc) == "account_binding_has_overlap_review_history"
                else "This account assignment is locked because a row has posted journal history. "
                "Review or correct the entry; its source account cannot be reassigned."
                if str(exc) == "account_binding_has_journal_history"
                else str(exc)
            )
            QMessageBox.warning(self, "Account assignment was not saved", message)
            self._reload()

    def _assert_file(self) -> None:
        account_id = self.account_combo.currentData()
        self._write(lambda store: store.assert_file_account(self.source_sha256, account_id))

    def _clear_file(self) -> None:
        self._write(lambda store: store.clear_file_account_assertion(self.source_sha256))

    def _assign_selected(self) -> None:
        row_ids = self._selected_row_ids()
        account_id = self.account_combo.currentData()
        self._write(lambda store: store.assign_rows_account(self.source_sha256, row_ids, account_id))

    def _clear_selected(self) -> None:
        row_ids = self._selected_row_ids()
        self._write(lambda store: store.clear_row_account_assignments(self.source_sha256, row_ids))


def review_accountless_export(profile: Path, source_sha256: str, *, parent=None) -> V2AccountBindingReview:
    return V2AccountBindingReview(profile, source_sha256, parent)
