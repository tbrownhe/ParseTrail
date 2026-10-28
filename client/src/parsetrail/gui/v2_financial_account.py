"""Shared authored financial-account form and explicit account-only creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from parsetrail.core.v2_account_creation import AccountCreationDraft
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_original_document import open_original_document


def _date_context(value):
    if value is None or value.iso is None:
        return "Unknown"
    origin = {"observed": "printed", "derived": "derived", "assumed": "estimated"}[value.provenance]
    return f"{value.iso} ({origin})"


def _money_context(value):
    if value is None or value.minor is None:
        return "Unknown"
    if value.provenance == "observed":
        return f"{value.raw} (printed)"
    magnitude = abs(value.minor)
    return f"{'-' if value.minor < 0 else ''}{magnitude // 100:,}.{magnitude % 100:02d} (derived)"


class V2FinancialAccountDialog(QDialog):
    """Record an account exactly as the owner describes it."""

    def __init__(
        self,
        parent=None,
        *,
        existing: FinancialAccount | None = None,
        scope_locked: bool = False,
        draft: AccountCreationDraft | None = None,
        staged: bool = False,
        profile: Path | None = None,
    ):
        super().__init__(parent)
        self.existing = existing
        self.draft = draft
        self.profile = profile
        self.original_open = None
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
            self.source_context = QGroupBox("From this document")
            context_form = QFormLayout(self.source_context)
            self.document_type = QLabel(
                draft.product_label.text
                if draft.product_label is not None and draft.product_label.text
                else "Account type not identified in saved evidence — view original."
            )
            self.document_type.setWordWrap(True)
            self.document_type.setTextFormat(Qt.PlainText)
            context_form.addRow(self.document_type)
            self.document_period = QLabel(f"{_date_context(draft.period_start)} → {_date_context(draft.period_end)}")
            self.document_period.setWordWrap(True)
            context_form.addRow("Document dates", self.document_period)
            self.document_values = QLabel(
                f"Opening: {_money_context(draft.opening_balance)}\nClosing: {_money_context(draft.closing_balance)}"
            )
            self.document_values.setTextFormat(Qt.PlainText)
            self.document_values.setWordWrap(True)
            self.document_values.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            context_form.addRow("Document values", self.document_values)
            self._source_page = next(
                (location.page for location in draft.source_locations if hasattr(location, "page")), None
            )
            scope_text = {
                "account_total": "whole account",
                "principal_component": "loan principal only",
                "cash_component": "cash component only",
            }.get(draft.tracking_scope, "unknown")
            self.document_scope = QLabel(
                f"Scope: {scope_text}" + (f" · Source page {self._source_page}" if self._source_page else "")
            )
            self.document_scope.setWordWrap(True)
            context_form.addRow(self.document_scope)
            self.view_original_button = QPushButton("View original document…")
            self.view_original_button.setEnabled(profile is not None and draft.source_sha256 is not None)
            self.view_original_button.clicked.connect(self._view_original)
            context_form.addRow(self.view_original_button)
            self.original_status = QLabel()
            self.original_status.setWordWrap(True)
            context_form.addRow(self.original_status)
            form.addRow(self.source_context)
            context_note = QLabel(
                "These account details will be saved together with the selected document assignments when you apply the batch."
                if staged
                else "Review these editable suggestions before creating the account. "
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
        known_institution = draft is not None and draft.verified_context
        if known_institution:
            self.institution.setReadOnly(True)
            self.institution.setFrame(False)
            institution_palette = self.institution.palette()
            institution_palette.setColor(QPalette.Base, institution_palette.color(QPalette.Window))
            self.institution.setPalette(institution_palette)
            self.institution.setAccessibleDescription(
                "Read-only institution identified by the document's verified parser."
            )
        form.addRow(
            "Institution (from document)" if known_institution else "Institution matching code", self.institution
        )
        institution_help = QLabel(
            "Identified automatically from this document's parser."
            if known_institution
            else "Used locally to match documents to accounts from the same bank or servicer. "
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
            buttons.button(QDialogButtonBox.Ok).setText("Add to batch" if staged else "Create account")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _view_original(self):
        if self.profile is None or self.draft is None or self.draft.source_sha256 is None:
            return
        self.view_original_button.setEnabled(False)
        self.original_open = open_original_document(
            self.profile,
            self.draft.source_sha256,
            self,
            initial_page=self._source_page,
            context=f"Document account: {self.draft.source_identity or 'not printed'}. The full original may contain other accounts.",
        )
        self.original_status.setText(self.original_open.status)
        self.original_open.status_changed.connect(self.original_status.setText)
        self.original_open.finished.connect(self._original_finished)

    def _original_finished(self, _success):
        self.view_original_button.setEnabled(True)
        self.view_original_button.setFocus()

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
    dialog = V2FinancialAccountDialog(parent, draft=draft, profile=profile)
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
