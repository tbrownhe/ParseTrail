"""Shared authored financial-account form and explicit account-only creation."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
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
from parsetrail.core.v2_account_products import ACCOUNT_PRODUCTS, account_product
from parsetrail.core.v2_institutions import BUILTIN_INSTITUTIONS, Institution, institution_label
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_original_document import open_original_document


class InstitutionChoice(QComboBox):
    """Search managed display names; typed text is never an institution identity."""

    def __init__(self, institutions, *, selected=None, established=False, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setAccessibleName("Institution")
        self.addItem("Choose an institution…", "")
        self.addItem("Institution not identified", None)
        for institution in sorted(institutions, key=lambda item: (item.name.casefold(), item.id)):
            self.addItem(institution.name, institution.id)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.setCurrentIndex(max(0, self.findData(selected)) if established or selected else 0)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().editingFinished.connect(self.resolve_matching_name)

    def resolve_matching_name(self):
        text = self.currentText().strip().casefold()
        matches = [index for index in range(1, self.count()) if self.itemText(index).strip().casefold() == text]
        if len(matches) == 1:
            self.setCurrentIndex(matches[0])
            self.setEditText(self.itemText(matches[0]))

    def eventFilter(self, watched, event):
        if watched is self.lineEdit():
            if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
                popup = self.completer().popup()
                if popup is not None and popup.isVisible() and popup.currentIndex().isValid():
                    self.setEditText(str(popup.currentIndex().data()))
                    popup.hide()
                self.resolve_matching_name()
                self.hidePopup()
                if popup is not None:
                    popup.hide()
                event.accept()
                return True
            if event.type() == QEvent.FocusOut:
                self.resolve_matching_name()
        return super().eventFilter(watched, event)

    def valid_selection(self):
        index = self.currentIndex()
        return index > 0 and self.currentText() == self.itemText(index)

    def selected_key(self):
        return self.currentData() if self.valid_selection() else ""


def account_institutions(parent=None, profile=None):
    """Read registry/options only; catalog identities are registered on explicit save."""
    current = parent
    while current is not None:
        workspace = getattr(current, "workspace", None)
        if workspace is not None and hasattr(workspace, "institutions"):
            return workspace.institutions()
        current = current.parent() if hasattr(current, "parent") else None
    if profile is not None:
        with V2ProfileStore.open(profile, read_only=True) as store:
            return store.institutions()
    return BUILTIN_INSTITUTIONS


def _parent_catalog(parent):
    current = parent
    while current is not None:
        workspace = getattr(current, "workspace", None)
        if workspace is not None:
            return workspace.catalog_cache.load_current()
        current = current.parent() if hasattr(current, "parent") else None
    return None


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
        institutions: tuple[Institution, ...] | None = None,
    ):
        super().__init__(parent)
        install_form_styles(self)
        self.existing = existing
        self.draft = draft
        self._staged = staged
        current = parent
        while profile is None and current is not None:
            workspace = getattr(current, "workspace", None)
            if workspace is not None:
                profile = workspace.profile_path
                break
            current = current.parent() if hasattr(current, "parent") else None
        self.profile = profile
        self.identity_lock = None
        if existing is not None and profile is not None:
            with V2ProfileStore.open(profile, read_only=True) as store:
                self.identity_lock = store.account_identity_lock(existing.id)
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
        self.form = form
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
            self.document_values.setMinimumHeight(self.document_values.fontMetrics().lineSpacing() * 2)
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
            form.addRow(self.view_original_button)
            self.original_status = QLabel()
            self.original_status.setWordWrap(True)
            form.addRow(self.original_status)
            self.document_details_button = QPushButton("Document details")
            self.document_details_button.setCheckable(True)
            self.document_details_button.toggled.connect(self.source_context.setVisible)
            form.addRow(self.document_details_button)
            form.addRow(self.source_context)
            self.source_context.hide()
            context_note = QLabel(
                "The account saves with your assignments when you apply the batch. No transactions are posted."
                if staged
                else "Create the account, then confirm its document assignment in Review. No transactions are posted."
                + (
                    " Choose institution and product; the document did not identify them."
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
        form.addRow("Account name *", self.name)
        self.product = QComboBox()
        self.product.setAccessibleName("Account product")
        if existing is None or existing.product_type is None:
            self.product.addItem("Product not recorded" if existing else "Choose an account product…", None)
        for product in ACCOUNT_PRODUCTS:
            if (
                draft is not None
                and draft.verified_context
                and getattr(draft, "product_type", None) not in {None, product.id}
            ):
                continue
            if existing is not None and (
                product.kind != existing.kind or existing.tracking_scope not in product.tracking_scopes
            ):
                continue
            if (
                draft is not None
                and draft.verified_context
                and (
                    draft.kind is not None
                    and product.kind != draft.kind
                    or draft.tracking_scope is not None
                    and draft.tracking_scope not in product.tracking_scopes
                )
            ):
                continue
            self.product.addItem(product.label, product.id)
        product_type = getattr(existing if existing else draft, "product_type", None)
        self._tangible_product_locked = existing is not None and product_type == "vehicle"
        if self._tangible_product_locked:
            self.product.setToolTip("Tangible asset classification is fixed by its value/acquisition history.")
        self.product.setCurrentIndex(max(0, self.product.findData(product_type)))
        self.product.setEnabled(
            self.identity_lock is None
            and not self._tangible_product_locked
            and not (draft is not None and draft.verified_context and product_type is not None)
        )
        form.addRow("Account product" + (" *" if existing is None else ""), self.product)
        self.product_summary = QLabel()
        self.product_summary.setWordWrap(True)
        form.addRow(self.product_summary)
        self.kind = QComboBox()
        if draft is not None:
            self.kind.addItem("Choose an account type…", None)
        self.kind.addItem("Asset — value you own", "asset")
        self.kind.addItem("Liability — money you owe (card or loan)", "liability")
        if existing is not None:
            self.kind.setCurrentIndex(self.kind.findData(existing.kind))
            self.kind.setEnabled(False)
        elif draft is not None:
            self.kind.setCurrentIndex(max(0, self.kind.findData(draft.kind)))
        form.addRow("2. Account type *", self.kind)
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
        self._scope_locked = scope_locked
        form.addRow("3. What this account tracks *", self.scope)
        scope_note = self.scope_note = QLabel(
            "Scope specifies the amount represented by this account. Account totals, loan principal and cash "
            "components are different values. Scope becomes fixed when reviewed history is saved."
            + (" This account's scope is fixed by its history." if scope_locked else "")
        )
        scope_note.setWordWrap(True)
        form.addRow(scope_note)
        self.institutions = institutions if institutions is not None else account_institutions(parent, profile)
        self._known_institution = self.identity_lock is not None or (
            draft is not None and draft.verified_context and bool(draft.institution_key)
        )
        self._fixed_institution_key = (
            self.identity_lock.institution_key
            if self.identity_lock is not None
            else draft.institution_key
            if draft is not None
            else None
        )
        known_institution = self._known_institution
        if known_institution:
            self.institution = QLineEdit(institution_label(self._fixed_institution_key, self.institutions))
            self.institution.setReadOnly(True)
            self.institution.setFrame(False)
            institution_palette = self.institution.palette()
            institution_palette.setColor(QPalette.Base, institution_palette.color(QPalette.Window))
            self.institution.setPalette(institution_palette)
            self.institution.setAccessibleDescription(
                "Read-only institution set during statement import."
                if self.identity_lock is not None
                else "Read-only institution identified by the document's verified parser."
            )
        else:
            self.institution = InstitutionChoice(
                self.institutions,
                selected=existing.institution_key if existing else (draft.institution_key or None) if draft else None,
                established=existing is not None,
            )
        form.addRow(
            "Institution (set during import)"
            if self.identity_lock is not None
            else "Institution (from document)"
            if known_institution
            else "Institution *",
            self.institution,
        )
        institution_help = QLabel(
            "Institution and product are locked after statement-import account creation. The account name remains editable."
            if self.identity_lock is not None
            else "Identified by the document."
            if known_institution
            else "Choose a name from the list, or Institution not identified."
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
        self.account_details_button = QPushButton("More account details")
        self.account_details_button.setCheckable(True)
        self.account_details_button.toggled.connect(self._show_account_details)
        form.addRow(self.account_details_button)
        form.addRow("Full account number (optional)", self.number)
        self.save_error = QLabel()
        self.save_error.setWordWrap(True)
        form.addRow(self.save_error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.save_button = buttons.button(QDialogButtonBox.Ok)
        if draft is not None:
            buttons.button(QDialogButtonBox.Ok).setText("Add to batch" if staged else "Create account")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        for field in (self.name, self.number):
            field.textChanged.connect(self._update_form_cues)
        if isinstance(self.institution, InstitutionChoice):
            self.institution.currentIndexChanged.connect(self._update_form_cues)
            self.institution.editTextChanged.connect(self._update_form_cues)
        self.kind.currentIndexChanged.connect(self._update_form_cues)
        self.scope.currentIndexChanged.connect(self._update_form_cues)
        self.product.currentIndexChanged.connect(self._product_changed)
        self.scope.currentIndexChanged.connect(self._show_account_details)
        self._product_changed()
        self._update_form_cues()

    def _show_account_details(self, *_args):
        show = self.account_details_button.isChecked()
        known = self.product.currentData() is not None or self.existing is not None
        self.form.setRowVisible(self.kind, show and known)
        self.form.setRowVisible(self.scope, known and (show or self.scope.isEnabled()))
        self.form.setRowVisible(self.scope_note, show and known)
        self.form.setRowVisible(self.number, show)
        if self.product.currentData() is not None:
            product = account_product(self.product.currentData())
            scope = self.scope.currentText()
            self.product_summary.setText(
                f"{'Money you own' if product.kind == 'asset' else 'Money you owe'} · Tracks {scope.lower()}."
                + (
                    " Tangible asset classification is fixed by its value/acquisition history."
                    if self._tangible_product_locked
                    else ""
                )
            )
        elif self.existing is not None:
            self.product_summary.setText(f"Saved account · Tracks {self.scope.currentText().lower()}.")
        else:
            self.product_summary.setText("Choose a product to see what this account tracks.")

    def _product_changed(self, *_args):
        product_type = self.product.currentData()
        if product_type is None:
            self.kind.setEnabled(False)
            self.scope.setEnabled(self.existing is not None and not self._scope_locked)
            self.form.labelForField(self.kind).setText(
                "Accounting class (from product)" if self.existing is None else "Accounting class (saved)"
            )
            self._update_form_cues()
            self._show_account_details()
            return
        product = account_product(product_type)
        selected = self.scope.currentData()
        self.kind.setCurrentIndex(self.kind.findData(product.kind))
        self.kind.setEnabled(False)
        self.form.labelForField(self.kind).setText("Accounting class (from product)")
        self._populate_scopes(selected)
        self.scope.setEnabled(not self._scope_locked and len(product.tracking_scopes) > 1)
        self.form.labelForField(self.scope).setText(
            "Amount represented (from product)" if not self.scope.isEnabled() else "Amount represented *"
        )
        self._update_form_cues()
        self._show_account_details()

    def _institution_key(self):
        return self._fixed_institution_key if self._known_institution else self.institution.selected_key()

    def _institution_valid(self):
        return self._known_institution or self.institution.valid_selection()

    def _institution_choice_value(self):
        if self._institution_valid():
            return self._institution_key()
        return "" if self.institution.currentText() == self.institution.itemText(0) else self.institution.currentText()

    def _update_form_cues(self, *_args):
        existing = self.existing
        values = (
            (
                self.product,
                "account product",
                existing is not None or self.product.currentData() is not None,
                getattr(existing, "product_type", None),
                self.product.currentData(),
            ),
            (
                self.name,
                "account name",
                bool(self.name.text().strip()),
                existing.name if existing else None,
                self.name.text().strip(),
            ),
            (
                self.kind,
                "account type",
                self.kind.currentData() in {"asset", "liability"},
                existing.kind if existing else None,
                self.kind.currentData(),
            ),
            (
                self.scope,
                "amount tracked",
                self.scope.currentData() is not None,
                existing.tracking_scope if existing else None,
                self.scope.currentData(),
            ),
            (
                self.institution,
                "institution",
                self._institution_valid(),
                existing.institution_key if existing else None,
                self._institution_choice_value(),
            ),
        )
        missing = []
        changed = existing is None
        for field, label, valid, saved, current in values:
            if field in {self.kind, self.scope} and self.product.currentData() is None and existing is None:
                set_field_state(field, "readonly", "Choose an account product first.")
            elif field is self.kind or field is self.scope and not self.scope.isEnabled():
                set_field_state(field, "readonly", "Derived from the selected product or fixed saved scope.")
            elif field is self.product and not self.product.isEnabled():
                set_field_state(
                    field,
                    "readonly",
                    "Product set during statement import and locked."
                    if self.identity_lock is not None
                    else "Tangible asset classification is fixed by its value/acquisition history."
                    if self._tangible_product_locked
                    else "Product identified from verified source context.",
                )
            elif field is self.institution and self._known_institution:
                set_field_state(field, "readonly", "Institution supplied by this document")
            elif not valid:
                missing.append(label)
                set_field_state(field, "invalid" if current else "required")
            elif existing is not None and saved == current:
                set_field_state(field, "saved")
            else:
                set_field_state(field, "ready")
                changed = True
        number = self.number.text().strip()
        saved_number = (existing.full_account_number or "") if existing else ""
        number_changed = number != saved_number
        changed = changed or number_changed
        set_field_state(
            self.number,
            "ready" if number_changed else "saved" if number and existing else "ready" if number else "optional",
            "Optional; enter a full number only. This does not verify account ownership.",
        )
        if missing:
            text = (
                "Choose a listed institution or Institution not identified; typed names do not create institutions."
                if "institution" in missing
                else "Required: " + ", ".join(missing) + ". * marks a required choice."
            )
            set_status(self.save_error, "required", text)
        elif changed:
            text = (
                "Choices valid · Not saved. Add to batch, then Apply to save accounts and assignments."
                if self._staged
                else "Choices valid · Not saved. Create/save the account; document assignment and activity review are separate."
            )
            set_status(self.save_error, "ready", text)
        else:
            set_status(self.save_error, "saved", "Saved account details. Edit a field to prepare a change.")
        self.save_button.setEnabled(not missing and changed)
        set_field_state(self.save_button, "ready" if not missing and changed else "neutral")

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
            self.scope.addItem("Choose what this account tracks…", None)
            if self.kind.currentData() is None:
                return
        product_type = self.product.currentData()
        scopes = account_product(product_type).tracking_scopes if product_type is not None else None
        if scopes is None or "account_total" in scopes:
            self.scope.addItem("Whole account", "account_total")
        if self.kind.currentData() == "asset" and (scopes is None or "cash_component" in scopes):
            self.scope.addItem("Cash component only", "cash_component")
        elif self.kind.currentData() != "asset" and (scopes is None or "principal_component" in scopes):
            self.scope.addItem("Loan principal only", "principal_component")
        if scopes is not None and len(scopes) == 1:
            selected = scopes[0]
        self.scope.setCurrentIndex(max(0, self.scope.findData(selected)))

    def accept(self) -> None:
        if self.existing is None and self.product.currentData() is None:
            self.save_error.setText("Choose the account product before saving.")
            self.product.setFocus()
            return
        if self.draft is not None:
            if not self.name.text().strip():
                self.save_error.setText("Enter an account name.")
                self.name.setFocus()
                return
            if self.kind.currentData() is None or self.scope.currentData() is None:
                self.save_error.setText("Choose the account type and the amount this account tracks.")
                (self.kind if self.kind.currentData() is None else self.scope).setFocus()
                return
        if not self._institution_valid():
            self.save_error.setText(
                "Choose a listed institution or Institution not identified. Typed names do not create institutions."
            )
            self.institution.setFocus()
            return
        self.save_error.clear()
        super().accept()

    def account(self) -> FinancialAccount:
        return FinancialAccount(
            id=self._account_id,
            name=self.name.text().strip(),
            kind=self.kind.currentData(),
            institution_key=self._institution_key(),
            full_account_number=self.number.text().strip() or None,
            tracking_scope=self.scope.currentData(),
            product_type=self.product.currentData(),
        )


def create_financial_account(profile: Path, *, draft: AccountCreationDraft, parent=None) -> FinancialAccount | None:
    """Create only an authored account; keep failed form values available for retry."""
    try:
        dialog = V2FinancialAccountDialog(parent, draft=draft, profile=profile)
    except (ProfileFormatError, sqlite3.Error, OSError, ValueError) as exc:
        QMessageBox.warning(
            parent,
            "Account choices unavailable",
            f"Institution choices could not be read. Reload the profile and try again.\n\nDetails: {exc}",
        )
        return None
    while dialog.exec() == QDialog.Accepted:
        try:
            account = dialog.account()
            with V2ProfileStore.open(profile) as store:
                catalog = _parent_catalog(parent)
                store.add_financial_account(account, catalog=catalog)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            set_status(
                dialog.save_error,
                "blocked",
                f"Account was not saved: {exc}. Your entries are retained; correct or retry.",
            )
            QMessageBox.warning(parent, "Account was not saved", str(exc))
        else:
            return account
    return None
