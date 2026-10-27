"""Shared authored financial-account form and explicit account-only creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox

from parsetrail.core.v2_account_creation import AccountCreationDraft
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore


class V2FinancialAccountDialog(QDialog):
    """Record an account exactly as the owner describes it."""

    def __init__(
        self,
        parent=None,
        *,
        existing: FinancialAccount | None = None,
        scope_locked: bool = False,
        draft: AccountCreationDraft | None = None,
    ):
        super().__init__(parent)
        self.existing = existing
        self.draft = draft
        self._account_id = existing.id if existing is not None else uuid4().hex
        self.setWindowTitle(
            "Edit financial account"
            if existing is not None
            else "New account from document"
            if draft
            else "Add financial account"
        )
        form = QFormLayout(self)
        if draft is not None:
            self.setMinimumWidth(480)
            self.source_identity = QLineEdit(draft.source_identity or "No account identifier in these rows")
            self.source_identity.setReadOnly(True)
            self.source_identity.setFrame(False)
            source_palette = self.source_identity.palette()
            source_palette.setColor(QPalette.Base, source_palette.color(QPalette.Window))
            self.source_identity.setPalette(source_palette)
            self.source_identity.setAccessibleDescription(
                "Read-only identifier from the document. Text can be selected and copied."
            )
            self.source_identity.setCursorPosition(0)
            self.source_identity.setToolTip(draft.source_identity or "This document does not identify an account.")
            form.addRow("Document account (read-only)", self.source_identity)
            context_note = QLabel(
                "Review these editable suggestions before creating the account. "
                "Creating an account does not change this document’s assignment or add transactions. "
                "Confirm the assignment separately in Review."
                + (
                    " The full account number is unknown; abbreviated or masked text is kept above."
                    if draft.source_identity is not None and draft.full_account_number is None
                    else ""
                )
                + (
                    " Institution and account kind need your input because no exact signed catalog context is available."
                    if not draft.verified_context
                    else ""
                )
            )
            context_note.setWordWrap(True)
            form.addRow(context_note)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        if existing is not None:
            self.name.setText(existing.name)
        elif draft is not None:
            self.name.setText(draft.name)
        form.addRow("Account name", self.name)
        self.kind = QComboBox()
        if draft is not None:
            self.kind.addItem("Choose account kind…", None)
        self.kind.addItem("Asset (cash or investment)", "asset")
        self.kind.addItem("Liability (card or loan)", "liability")
        if existing is not None:
            self.kind.setCurrentIndex(self.kind.findData(existing.kind))
            self.kind.setEnabled(False)
        elif draft is not None:
            self.kind.setCurrentIndex(max(0, self.kind.findData(draft.kind)))
        form.addRow("Account kind", self.kind)
        self.scope = QComboBox()
        self._populate_scopes(
            existing.tracking_scope if existing is not None else draft.tracking_scope if draft else "account_total"
        )
        self.kind.currentIndexChanged.connect(
            lambda: self._populate_scopes(
                self.scope.currentData() or (self.draft.tracking_scope if self.draft else None)
            )
        )
        self.scope.setEnabled(not scope_locked)
        form.addRow("Tracking scope", self.scope)
        scope_note = QLabel(
            "Scope specifies the amount represented by this account. Account totals, loan principal and cash "
            "components are different values. Scope becomes fixed when reviewed history is saved."
            + (" This account's scope is fixed by its history." if scope_locked else "")
        )
        scope_note.setWordWrap(True)
        form.addRow(scope_note)
        self.institution = QLineEdit()
        self.institution.setPlaceholderText("e.g. mohela")
        self.institution.setMaxLength(80)
        if existing is not None:
            self.institution.setText(existing.institution_key)
        elif draft is not None:
            self.institution.setText(draft.institution_key)
        form.addRow("Institution matching code", self.institution)
        institution_help = QLabel(
            "Used locally to match documents to accounts from the same bank or servicer. "
            "Keep the suggested code unless you are correcting the institution."
        )
        institution_help.setWordWrap(True)
        form.addRow(institution_help)
        self.number = QLineEdit()
        self.number.setPlaceholderText("Optional; full number only")
        self.number.setMaxLength(80)
        if existing is not None:
            self.number.setText(existing.full_account_number or "")
        elif draft is not None:
            self.number.setText(draft.full_account_number or "")
        form.addRow("Full account number", self.number)
        self.save_error = QLabel()
        self.save_error.setWordWrap(True)
        form.addRow(self.save_error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        if draft is not None:
            buttons.button(QDialogButtonBox.Ok).setText("Create account")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _populate_scopes(self, selected: str | None) -> None:
        self.scope.clear()
        if self.draft is not None:
            self.scope.addItem("Choose tracking scope…", None)
            if self.kind.currentData() is None:
                return
        self.scope.addItem("Whole account", "account_total")
        if self.kind.currentData() == "asset":
            self.scope.addItem("Cash component only", "cash_component")
        else:
            self.scope.addItem("Loan principal only", "principal_component")
        self.scope.setCurrentIndex(max(0, self.scope.findData(selected)))

    def accept(self) -> None:
        if self.draft is not None:
            if not self.name.text().strip():
                self.save_error.setText("Enter an account name.")
                self.name.setFocus()
                return
            if self.kind.currentData() is None or self.scope.currentData() is None:
                self.save_error.setText("Choose the account kind and the amount this account tracks.")
                (self.kind if self.kind.currentData() is None else self.scope).setFocus()
                return
            if not self.institution.text().strip():
                self.save_error.setText("Enter the institution key for this account.")
                self.institution.setFocus()
                return
        self.save_error.clear()
        super().accept()

    def account(self) -> FinancialAccount:
        return FinancialAccount(
            id=self._account_id,
            name=self.name.text().strip(),
            kind=self.kind.currentData(),
            institution_key=self.institution.text().strip(),
            full_account_number=self.number.text().strip() or None,
            tracking_scope=self.scope.currentData(),
        )


def create_financial_account(profile: Path, *, draft: AccountCreationDraft, parent=None) -> FinancialAccount | None:
    """Create only an authored account; keep failed form values available for retry."""
    dialog = V2FinancialAccountDialog(parent, draft=draft)
    while dialog.exec() == QDialog.Accepted:
        try:
            account = dialog.account()
            with V2ProfileStore.open(profile) as store:
                store.add_financial_account(account)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            dialog.save_error.setText(f"Account was not saved: {exc}. Your entries are retained; correct or retry.")
            QMessageBox.warning(parent, "Account was not saved", str(exc))
        else:
            return account
    return None
