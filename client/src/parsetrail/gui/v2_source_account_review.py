"""Explicit ledger-account decisions for identities printed by a source."""

from __future__ import annotations

import sqlite3
from collections import Counter

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
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_verified_source_account
from parsetrail.core.v2_profile_store import ProfileFormatError, SourceAccountBinding, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace


class V2SourceAccountReview(QDialog):
    """Bind each printed source identity through an explicit user assertion."""

    def __init__(self, workspace: V2Workspace, source_sha256: str, parent=None):
        super().__init__(parent)
        self.workspace = workspace
        self.profile = workspace.profile_path
        self.source_sha256 = source_sha256
        self.bindings: tuple[SourceAccountBinding, ...] = ()
        self.setWindowTitle("2.0 source account review")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Choose the ledger account represented by each source identity. "
            "A unique full-number match can use signed parser context. Last-four matching "
            "requires the app preference. You can override either with an explicit assignment. "
            "No ledger entries are posted here."
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
        self.abbreviated_matching_button = QPushButton(
            "Allow abbreviated account numbers to automatically match to ledger"
        )
        self.abbreviated_matching_button.setCheckable(True)
        self.abbreviated_matching_button.clicked.connect(self._toggle_abbreviated_matching)
        layout.addWidget(self.abbreviated_matching_button)
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
        catalog = self.workspace.catalog_cache.load_current()
        preferences = self.workspace.preferences()
        self.abbreviated_matching_button.blockSignals(True)
        self.abbreviated_matching_button.setChecked(preferences.allow_abbreviated_account_matching)
        self.abbreviated_matching_button.blockSignals(False)
        self.abbreviated_matching_button.setText(
            "Stop automatically matching abbreviated account numbers"
            if preferences.allow_abbreviated_account_matching
            else "Allow abbreviated account numbers to automatically match to ledger"
        )
        candidates = tuple(
            LedgerAccountCandidate(account.id, account.institution_key, account.kind, account.full_account_number)
            for account in accounts
        )
        self.matches = tuple(
            match_verified_source_account(
                evidence,
                binding.source_identity,
                binding.source_identity_form,
                catalog=catalog,
                candidates=candidates,
                preferences=preferences,
            )
            for binding in self.bindings
        )
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
        for binding, match in zip(self.bindings, self.matches, strict=True):
            count = counts[(binding.source_identity, binding.source_identity_form)]
            if binding.ledger_account_id is not None:
                assigned = f"Assigned: {names.get(binding.ledger_account_id, 'Unknown account')}"
            elif match.status == "automatic":
                assigned = f"Automatic match: {names.get(match.ledger_account_id, 'Unknown account')}"
            elif match.status == "ambiguous":
                assigned = "Multiple eligible accounts; choose one"
            elif match.offer_enable_abbreviated_matching:
                assigned = f"Possible match: {names.get(match.suggestions[0], 'Unknown account')}"
            else:
                assigned = "Unassigned"
            item = QListWidgetItem(
                f"{binding.source_identity} ({binding.source_identity_form}) · {count} row(s) · {assigned}"
            )
            item.setToolTip(binding.source_identity)
            self.identities.addItem(item)
            if (binding.source_identity, binding.source_identity_form) == prior:
                self.identities.setCurrentItem(item)
        if self.identities.currentRow() < 0 and self.identities.count():
            self.identities.setCurrentRow(0)
        pending = sum(
            binding.ledger_account_id is None and match.status != "automatic"
            for binding, match in zip(self.bindings, self.matches, strict=True)
        )
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
        self.abbreviated_matching_button.setVisible(
            selected
            and self.bindings[index].source_identity_form == "last_four"
            and (self.matches[index].offer_enable_abbreviated_matching or self.matches[index].status == "automatic")
        )

    def _toggle_abbreviated_matching(self, enabled: bool) -> None:
        try:
            self.workspace.set_allow_abbreviated_account_matching(enabled)
            self._reload()
            if self.parent() is not None and hasattr(self.parent(), "abbreviated_matching_action"):
                action = self.parent().abbreviated_matching_action
                action.blockSignals(True)
                action.setChecked(enabled)
                action.blockSignals(False)
        except (OSError, ValueError) as exc:
            self.abbreviated_matching_button.blockSignals(True)
            self.abbreviated_matching_button.setChecked(not enabled)
            self.abbreviated_matching_button.blockSignals(False)
            QMessageBox.warning(self, "Preference was not saved", str(exc))

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
