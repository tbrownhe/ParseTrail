"""Explicit same-obligation consolidation; all accounting policy stays headless."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_account_products import account_product
from parsetrail.core.v2_institutions import institution_label
from parsetrail.gui.v2_csv_import_preview import _ExplicitDecisionButton
from parsetrail.gui.v2_details_disclosure import DetailsDisclosure
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_profile_jobs import ProfileJobs


def _label(text=""):
    widget = QLabel(text)
    widget.setTextFormat(Qt.PlainText)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def _account_label(account):
    product = account_product(account.product_type).label if account.product_type else "Product not established"
    suffix = f" · ending {account.full_account_number[-4:]}" if account.full_account_number else ""
    institution = institution_label(account.institution_key) if account.institution_key else "Unknown institution"
    scope = account.tracking_scope.replace("_", " ")
    return f"{account.name} · {institution} · {product} · {scope}{suffix}"


def _compatible(left, right):
    return left.id != right.id and (left.kind, left.institution_key, left.product_type, left.tracking_scope) == (
        right.kind,
        right.institution_key,
        right.product_type,
        right.tracking_scope,
    )


class _SameAccountConfirmation(QCheckBox):
    def hitButton(self, position):
        return self.rect().contains(position)


class V2AccountConsolidation(QDialog):
    """One disposable dialog, with GUI-owned jobs and immutable preflight handoff."""

    consolidated = Signal(str)

    def __init__(self, profile: Path, account_id: str | None = None, parent=None):
        super().__init__(parent)
        self.profile = Path(profile)
        self._preferred = account_id
        self.accounts = ()
        self.snapshot = self.consolidation_result = None
        self._rendering = False
        self._close_pending = False
        self.setWindowTitle("Consolidate account records")
        self.resize(900, 650)
        install_form_styles(self)
        layout = QVBoxLayout(self)
        title = _label("One actual account, recorded twice")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(title)
        layout.addWidget(
            _label(
                "Use this when two ParseTrail records represent the same actual account or debt, "
                "such as different numbers after a replacement card. Payments and balance transfers "
                "connect separate accounts; use Transfers for those."
            )
        )
        form = QFormLayout()
        self.keep = QComboBox()
        self.keep.setAccessibleName("Keep this account")
        self.absorb = QComboBox()
        self.absorb.setAccessibleName("Consolidate this record into the kept account")
        for field in (self.keep, self.absorb):
            field.setMinimumContentsLength(28)
            field.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        form.addRow("Keep this account *", self.keep)
        form.addRow("Combine this record into it *", self.absorb)
        layout.addLayout(form)
        self.keep.currentIndexChanged.connect(self._keep_changed)
        self.absorb.currentIndexChanged.connect(self._pair_changed)
        self.scope = _label("Choose the account to keep and the record to combine into it.")
        layout.addWidget(self.scope)
        self.preview = _label()
        self.preview.setAccessibleName("Consolidation preview")
        layout.addWidget(self.preview)
        self.blockers = _label()
        self.blockers.setAccessibleName("Consolidation prerequisites")
        layout.addWidget(self.blockers)
        layout.addStretch()
        details_content = QWidget()
        details = QVBoxLayout(details_content)
        details.setContentsMargins(0, 0, 0, 0)
        fields = QFormLayout()
        self.reference = QLineEdit("Account records reviewed for consolidation")
        self.reason = QLineEdit("These records represent the same actual account or obligation")
        for field in (self.reference, self.reason):
            field.setMaxLength(500)
            field.textChanged.connect(self._update_actions)
        fields.addRow("Review reference *", self.reference)
        fields.addRow("Reason *", self.reason)
        details.addLayout(fields)
        self.details = DetailsDisclosure(details_content, self, subject="consolidation review reference and reason")
        layout.addWidget(self.details)
        self.same_account = _SameAccountConfirmation("These records represent the same actual account or debt")
        self.same_account.toggled.connect(self._update_actions)
        layout.addWidget(self.same_account)
        self.irreversible = _label(
            "Cannot be undone in this profile. Recovery requires a backup made before consolidation."
        )
        layout.addWidget(self.irreversible)
        self.status = _label("Loading accounts…")
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.action_button = _ExplicitDecisionButton("Consolidate accounts")
        self.action_button.clicked.connect(self._save)
        actions.addWidget(self.action_button)
        self.reload_button = QPushButton("Reload")
        self.reload_button.setAutoDefault(False)
        self.reload_button.clicked.connect(self.reload)
        actions.addWidget(self.reload_button)
        actions.addStretch()
        self.close_button = _ExplicitDecisionButton("Cancel")
        self.close_button.clicked.connect(self.reject)
        actions.addWidget(self.close_button)
        layout.addLayout(actions)
        self.jobs = ProfileJobs(self, self.profile)
        self.jobs.completed.connect(self._loaded)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        self.reload()

    def reload(self):
        if self.jobs.writing:
            return
        self.snapshot = None
        self.same_account.setChecked(False)
        selected = self.keep.currentData() or self._preferred

        def read(store, cancelled):
            if cancelled():
                return None
            accounts = store.active_financial_accounts()
            return accounts, store.canonical_account_id(selected) if selected is not None else None

        self.jobs.submit("accounts", read)

    def _keep_changed(self, *_args):
        if self._rendering:
            return
        prior = self.absorb.currentData()
        self._rendering = True
        self.absorb.clear()
        self.absorb.addItem("Choose the other bookkeeping record…", None)
        kept = next((account for account in self.accounts if account.id == self.keep.currentData()), None)
        if kept is not None:
            for account in self.accounts:
                if _compatible(kept, account):
                    self.absorb.addItem(_account_label(account), account.id)
                    self.absorb.setItemData(self.absorb.count() - 1, _account_label(account), Qt.ToolTipRole)
        self.absorb.setCurrentIndex(max(0, self.absorb.findData(prior)))
        self._rendering = False
        self._pair_changed()

    def _pair_changed(self, *_args):
        if self._rendering or self.jobs.writing:
            return
        self.snapshot = None
        self.same_account.setChecked(False)
        self.preview.clear()
        self.blockers.clear()
        kept, absorbed = self.keep.currentData(), self.absorb.currentData()
        if kept is None or absorbed is None:
            self.jobs.cancel_reads()
            self.scope.setText(
                "No compatible second record. Both records must have the same institution, product and tracking scope."
                if kept is not None and self.absorb.count() == 1
                else "Choose the account to keep and the record to combine into it."
            )
            self.status.setText("No consolidation is ready. No saved state has changed.")
            self._update_actions()
            return
        self.scope.setText("Checking the statements and accounting history for these records…")

        def read(store, cancelled):
            return None if cancelled() else store.account_consolidation_snapshot(kept, absorbed)

        self.jobs.submit(("preview", kept, absorbed), read)

    def _loaded(self, key, result):
        if result is None:
            return
        if key == "accounts":
            self.accounts, selected = result
            self._rendering = True
            self.keep.clear()
            self.keep.addItem("Choose the account to keep…", None)
            for account in self.accounts:
                self.keep.addItem(_account_label(account), account.id)
                self.keep.setItemData(self.keep.count() - 1, _account_label(account), Qt.ToolTipRole)
            self.keep.setCurrentIndex(max(0, self.keep.findData(selected)))
            self._rendering = False
            self._keep_changed()
        elif key[0] == "preview" and key[1:] == (self.keep.currentData(), self.absorb.currentData()):
            self.snapshot = result
            self.scope.setText(
                f"Keep: {result.kept_account.name}\nRetire this duplicate record: {result.absorbed_account.name}"
            )
            numbers = (
                ", ".join(
                    dict.fromkeys(
                        f"ending {identity[-4:]}" if form in {"full", "last_four"} else identity
                        for identity, form in result.retained_source_identities
                    )
                )
                or "No printed numbers established"
            )
            self.preview.setText(
                f"{result.source_count} linked documents · {result.activity_row_count} imported rows · "
                f"{result.journal_entry_count} journal entries retained\n"
                f"Statement numbers retained: {numbers}\n"
                f"{result.absorbed_account.name} leaves ordinary account choices. Original evidence and "
                "journal history stay available. No payment, income or expense is created."
            )
            recovery = ()
            if any("opening" in item.lower() or "dated values" in item.lower() for item in result.blockers):
                recovery = (
                    "Cancel, then open Accounts → Reviewed openings, dated values and closure… to correct or "
                    "withdraw the conflicting decision. Return here and reload before confirming.",
                )
            self.blockers.setText("\n".join((*result.blockers, *recovery, *result.warnings)))
            set_field_state(self.blockers, "blocked" if result.blockers else "readonly")
            self.status.setText(
                "This pair cannot be consolidated yet. Check the prerequisites above; no changes have been saved."
                if result.blockers
                else "Review the direction, then confirm these are the same actual account."
            )
        elif key[0] == "save":
            self.consolidation_result = result
            kept = key[1]
            name = self.snapshot.kept_account.name if self.snapshot is not None else "the kept account"
            self.scope.setText(f"Consolidated into {name}.")
            self.status.setText("Saved. Use the kept account for future work; original history is retained.")
            self.same_account.setChecked(False)
            self.close_button.setText("Close")
            self.consolidated.emit(kept)
            if self._close_pending:
                self.accept()
        self._update_actions()

    def _update_actions(self, *_args):
        if not hasattr(self, "jobs"):
            return
        busy, saved = self.jobs.pending, self.consolidation_result is not None
        self.keep.setEnabled(not busy and not saved)
        self.absorb.setEnabled(not busy and not saved)
        self.same_account.setEnabled(
            not busy and not saved and self.snapshot is not None and not self.snapshot.blockers
        )
        self.reload_button.setEnabled(not busy and not saved)
        self.close_button.setEnabled(not self.jobs.writing)
        for field in (self.reference, self.reason):
            field.setEnabled(not busy and not saved)
            set_field_state(field, "readonly" if saved else "ready" if field.text().strip() else "required")
        set_field_state(self.keep, "readonly" if saved else "ready" if self.keep.currentData() else "required")
        set_field_state(self.absorb, "readonly" if saved else "ready" if self.absorb.currentData() else "required")
        set_field_state(
            self.same_account, "readonly" if saved else "ready" if self.same_account.isChecked() else "required"
        )
        ready = (
            not busy
            and not saved
            and self.snapshot is not None
            and not self.snapshot.blockers
            and self.same_account.isChecked()
            and self.reference.text().strip()
            and self.reason.text().strip()
        )
        self.action_button.setEnabled(bool(ready))
        set_field_state(self.action_button, "ready" if ready else "neutral")
        self.action_button.setText("Consolidated" if saved else "Consolidate accounts")
        if not busy and not saved and self.snapshot is not None and not self.snapshot.blockers:
            if not self.reference.text().strip() or not self.reason.text().strip():
                set_status(self.status, "required", "Show details and complete the review reference and reason.")

    def _busy(self, busy):
        if busy:
            set_status(
                self.status, "loading", "Saving consolidation…" if self.jobs.writing else "Checking account history…"
            )
        self._update_actions()

    def _save(self):
        if not self.action_button.isEnabled() or self.snapshot is None:
            return
        kept, absorbed = self.keep.currentData(), self.absorb.currentData()
        basis, profile = self.snapshot.basis_sha256, self.snapshot.profile_sha256
        reason, reference = self.reason.text().strip(), self.reference.text().strip()

        def write(store, _cancelled):
            return store.consolidate_accounts(
                kept,
                absorbed,
                expected_basis_sha256=basis,
                expected_profile_sha256=profile,
                reason=reason,
                reference=reference,
            )

        self.jobs.submit(("save", kept, absorbed), write, write=True)

    def _failed(self, key, error):
        self.snapshot = None
        self._close_pending = False
        self.same_account.setChecked(False)
        self.status.setText(
            "Consolidation was not saved. Reload and check the current account history before confirming again."
            if key != "accounts" and key[0] == "save"
            else "Account history is unavailable. Reload to retry."
        )
        self.status.setToolTip(str(error))
        self._update_actions()

    def reject(self):
        if not self.jobs.close():
            self._close_pending = True
            self.status.setText("Waiting for the confirmed consolidation to finish…")
            return
        super().reject()

    def closeEvent(self, event):
        if not self.jobs.close():
            self._close_pending = True
            event.ignore()
            self.status.setText("Waiting for the confirmed consolidation to finish…")
            return
        super().closeEvent(event)
