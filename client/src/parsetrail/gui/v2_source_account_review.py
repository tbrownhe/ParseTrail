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
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    ProfileFormatError,
    SourceAccountBinding,
    V2ProfileStore,
)
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_binding_correction import V2BindingCorrection, ordinary_binding_lock_notice


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
        self.lock_notice = QLabel()
        self.lock_notice.setWordWrap(True)
        layout.addWidget(self.lock_notice)
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
        self.correction_button = QPushButton("Review account correction…")
        self.correction_button.clicked.connect(self._correct)
        layout.addWidget(self.correction_button)
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
        try:
            self._reload_current()
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            self.bindings, self.matches = (), ()
            self.locked_keys, self.overlap_locked_keys = set(), set()
            self.ordinary_blockers = {}
            self.identities.clear()
            self.account_combo.clear()
            self.assign_button.setEnabled(False)
            self.clear_button.setEnabled(False)
            self.correction_button.setEnabled(False)
            self.abbreviated_matching_button.setVisible(False)
            self.status.setText("Source assignments are unavailable. Reopen this review to retry.")
            self.lock_notice.setText(str(exc))

    def _reload_current(self) -> None:
        prior = self._selected_key()
        with V2ProfileStore.open(self.profile, read_only=True) as store:
            evidence = store.load_import(self.source_sha256).evidence
            self.bindings = store.source_account_bindings(self.source_sha256)
            accounts = store.financial_accounts()
            posted_rows = store.journal_history_row_ids(self.source_sha256)
            overlap_rows = store.source_overlap_history_row_ids(self.source_sha256)
            self.ordinary_blockers = {
                (binding.source_identity, binding.source_identity_form): store.binding_correction_snapshot(
                    BindingCorrectionTarget(
                        self.source_sha256, "source", binding.source_identity, binding.source_identity_form
                    ),
                    destination_account_id=None,
                ).ordinary_blockers
                for binding in self.bindings
            }
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
        self.overlap_locked_keys = {
            (row.source_account, row.source_account_form) for row in rows if row.row_id in overlap_rows
        }
        self.locked_keys = (
            {(row.source_account, row.source_account_form) for row in rows if row.row_id in posted_rows}
            | self.overlap_locked_keys
            | {key for key, blockers in self.ordinary_blockers.items() if blockers}
        )
        names = cash_account_labels(accounts)
        self.account_combo.clear()
        self.account_combo.addItem("Choose a ledger account…", None)
        for account in accounts:
            self.account_combo.addItem(names[account.id], account.id)
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
            locked = (binding.source_identity, binding.source_identity_form) in self.locked_keys
            item = QListWidgetItem(
                f"{binding.source_identity} ({binding.source_identity_form}) · {count} row(s) · {assigned}"
                + (
                    " · Locked by source-row review"
                    if (binding.source_identity, binding.source_identity_form) in self.overlap_locked_keys
                    else " · Locked by posted entries"
                    if "account_binding_has_journal_history"
                    in self.ordinary_blockers.get((binding.source_identity, binding.source_identity_form), ())
                    else " · Ordinary reassignment locked"
                    if locked
                    else ""
                )
            )
            item.setToolTip(item.text())
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
        locked = selected and self._selected_key() in self.locked_keys
        self.assign_button.setEnabled(selected and not locked and self.account_combo.currentData() is not None)
        self.clear_button.setEnabled(selected and not locked and self.bindings[index].ledger_account_id is not None)
        self.correction_button.setEnabled(selected)
        self.lock_notice.setText(ordinary_binding_lock_notice(self.ordinary_blockers.get(self._selected_key(), ())))
        if locked:
            self.lock_notice.setText(
                self.lock_notice.text()
                + " Review account correction shows whether withdrawal and opening prerequisites permit an explicit correction."
            )
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
            message = ordinary_binding_lock_notice((str(exc),)) if str(exc).startswith("account_binding_") else str(exc)
            QMessageBox.warning(self, "Account assignment was not saved", message)
            self._reload()

    def _assign(self) -> None:
        key = self._selected_key()
        account_id = self.account_combo.currentData()
        if key is not None and account_id is not None:
            self._write(lambda store: store.bind_source_account(self.source_sha256, *key, account_id))

    def _clear(self) -> None:
        key = self._selected_key()
        if key is not None:
            self._write(lambda store: store.clear_source_account_binding(self.source_sha256, *key))

    def _correct(self) -> None:
        key = self._selected_key()
        if key is None:
            return
        target = BindingCorrectionTarget(
            self.source_sha256, "source", source_identity=key[0], source_identity_form=key[1]
        )
        V2BindingCorrection(self.profile, target, self).exec()
        self._reload()
