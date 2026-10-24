"""Explicit ledger-account decisions for identities printed by a source."""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_profile_store import ProfileFormatError, SourceAccountBinding, V2ProfileStore


class V2SourceAccountReview(QDialog):
    """Bind each printed source identity through an explicit user assertion."""

    def __init__(self, profile: Path, source_sha256: str, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.source_sha256 = source_sha256
        self.bindings: tuple[SourceAccountBinding, ...] = ()
        self.setWindowTitle("2.0 source account review")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose the ledger account represented by each source identity. "
            "A printed suffix or label alone does not authorize an automatic match. "
            "Assignments are reversible and do not post ledger entries."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.identities = QListWidget()
        self.identities.currentRowChanged.connect(self._update_controls)
        layout.addWidget(self.identities)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Ledger account:"))
        self.account_combo = QComboBox()
        self.account_combo.currentIndexChanged.connect(self._update_controls)
        controls.addWidget(self.account_combo)
        self.assign_button = QPushButton("Assign selected identity")
        self.assign_button.clicked.connect(self._assign)
        controls.addWidget(self.assign_button)
        self.clear_button = QPushButton("Clear assignment")
        self.clear_button.clicked.connect(self._clear)
        controls.addWidget(self.clear_button)
        layout.addLayout(controls)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._reload()

    def _reload(self) -> None:
        prior = self._selected_key()
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            evidence = store.load_import(self.source_sha256).evidence
            self.bindings = store.source_account_bindings(self.source_sha256)
            accounts = store.financial_accounts()
        payload = evidence.payload
        rows = (
            tuple(row for account in payload.accounts for row in account.rows)
            if isinstance(payload, StatementPayload)
            else payload.rows
        )
        counts = Counter((row.source_account, row.source_account_form) for row in rows)
        names = {account.id: account.name for account in accounts}
        self.account_combo.clear()
        self.account_combo.addItem("Choose a ledger account…", None)
        for account in accounts:
            self.account_combo.addItem(f"{account.name} ({account.institution_key}, {account.kind})", account.id)
        self.identities.clear()
        for binding in self.bindings:
            count = counts[(binding.source_identity, binding.source_identity_form)]
            assigned = names.get(binding.ledger_account_id, "Unassigned")
            item = QListWidgetItem(
                f"{binding.source_identity} ({binding.source_identity_form}) · {count} row(s) · {assigned}"
            )
            item.setToolTip(binding.source_identity)
            self.identities.addItem(item)
            if (binding.source_identity, binding.source_identity_form) == prior:
                self.identities.setCurrentItem(item)
        if self.identities.currentRow() < 0 and self.identities.count():
            self.identities.setCurrentRow(0)
        pending = sum(binding.ledger_account_id is None for binding in self.bindings)
        self.status.setText(f"{pending} of {len(self.bindings)} source identities unassigned")
        self._update_controls()

    def _selected_key(self) -> tuple[str, str] | None:
        index = self.identities.currentRow()
        if 0 <= index < len(self.bindings):
            binding = self.bindings[index]
            return binding.source_identity, binding.source_identity_form
        return None

    def _update_controls(self, *_args) -> None:
        index = self.identities.currentRow()
        selected = 0 <= index < len(self.bindings)
        self.assign_button.setEnabled(selected and self.account_combo.currentData() is not None)
        self.clear_button.setEnabled(selected and self.bindings[index].ledger_account_id is not None)

    def _write(self, action) -> None:
        try:
            with V2ProfileStore.open(self.profile) as store:
                action(store)
            self._reload()
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            QMessageBox.warning(self, "Account assignment was not saved", str(exc))

    def _assign(self) -> None:
        key = self._selected_key()
        account_id = self.account_combo.currentData()
        if key is not None and account_id is not None:
            self._write(lambda store: store.bind_source_account(self.source_sha256, *key, account_id))

    def _clear(self) -> None:
        key = self._selected_key()
        if key is not None:
            self._write(lambda store: store.clear_source_account_binding(self.source_sha256, *key))
