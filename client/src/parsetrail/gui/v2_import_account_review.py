"""Account-first import choices; provisional accounts never own a store write."""

from __future__ import annotations

from dataclasses import replace
from uuid import uuid4
from weakref import ref

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from parsetrail.core.v2_account_products import account_product
from parsetrail.core.v2_cash_movement import cash_account_labels
from parsetrail.core.v2_import_accounts import (
    ImportAccountChoice,
    compatible_import_accounts,
    import_account_creation_draft,
    import_account_profiles,
    matching_import_candidates,
    prepare_import_accounts,
)
from parsetrail.core.v2_institutions import institution_label
from parsetrail.core.v2_profile_store import FinancialAccount
from parsetrail.gui.v2_csv_import_preview import V2CsvImportPreview, _ExplicitDecisionButton, _FormatChoice
from parsetrail.gui.v2_financial_account import InstitutionChoice
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_original_document import open_selected_original

_NEW = "__create_new_account__"
_SCOPES = {
    "account_total": "whole account",
    "principal_component": "loan principal",
    "cash_component": "cash component",
}


class _AccountChoice(QComboBox):
    """Search existing labels without creating identities from typed text."""

    def __init__(self):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMinimumContentsLength(28)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.completer().setCaseSensitivity(Qt.CaseInsensitive)
        self.completer().setFilterMode(Qt.MatchContains)
        self.completer().setCompletionMode(QCompleter.PopupCompletion)
        self.lineEdit().installEventFilter(self)
        self.lineEdit().editingFinished.connect(self._resolve)

    def _resolve(self):
        text = self.currentText().strip().casefold()
        matches = [i for i in range(1, self.count()) if self.itemText(i).strip().casefold() == text]
        if len(matches) == 1:
            self.setCurrentIndex(matches[0])
            self.setEditText(self.itemText(matches[0]))

    def choice(self):
        return (
            self.currentData()
            if self.currentIndex() > 0 and self.currentText() == self.itemText(self.currentIndex())
            else None
        )

    def eventFilter(self, watched, event):
        if (
            watched is self.lineEdit()
            and event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
        ):
            popup = self.completer().popup()
            if popup is not None and popup.isVisible() and popup.currentIndex().isValid():
                self.setEditText(str(popup.currentIndex().data()))
                popup.hide()
            self._resolve()
            self.hidePopup()
            event.accept()
            return True
        return super().eventFilter(watched, event)


class _RecognizedPreview(V2CsvImportPreview):
    """Rendering stays reusable; every decision belongs to the account dialog."""

    def __init__(self, institutions, owner):
        super().__init__(institutions, owner)
        self._decision_owner = ref(owner)

    def reject(self):
        if (owner := self._decision_owner()) is not None:
            owner.reject()

    def _import(self):
        if (owner := self._decision_owner()) is not None:
            owner._import()

    def _skip(self):
        if (owner := self._decision_owner()) is not None:
            owner._skip()

    def _view_original(self):
        if (owner := self._decision_owner()) is not None:
            owner._view_original()


class V2ImportAccountReview(QDialog):
    """One reusable two-step surface for every PDF/CSV and queue request."""

    cancel_remaining = Signal()
    abbreviated_matching_changed = Signal(bool)
    import_preview_mode_changed = Signal(str)

    def __init__(self, institutions=(), parent=None):
        super().__init__(parent)
        self.institutions = institutions
        self.request = None
        self._finished = False
        self._states = {}
        self._drafts = {}
        self._editing_draft_id = None
        self._active_group = None
        self._rendering = False
        self._pending = False
        self._original_open = None
        self.setWindowTitle("Import document and choose accounts")
        self.setWindowModality(Qt.WindowModal)
        self.resize(1050, 700)
        install_form_styles(self)
        layout = QVBoxLayout(self)
        self.file_context = QLabel()
        self.file_context.setTextFormat(Qt.PlainText)
        self.file_context.setWordWrap(True)
        layout.addWidget(self.file_context)
        self.queue_status = QLabel()
        self.queue_status.setTextFormat(Qt.PlainText)
        self.queue_status.setWordWrap(True)
        layout.addWidget(self.queue_status)
        self.recovery_notice = QLabel()
        layout.addWidget(self.recovery_notice)
        self.step_label = QLabel()
        self.step_label.setStyleSheet("font-weight: 600")
        layout.addWidget(self.step_label)
        self.scope = QLabel(
            "Choose the account for every group in this document, then review the recognized activity and assignments. Nothing is saved until Import and assign."
        )
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.accounts_page = QWidget()
        account_layout = QVBoxLayout(self.accounts_page)
        account_layout.setContentsMargins(0, 0, 0, 0)
        self.groups = QTableWidget(0, 3)
        self.groups.setAccessibleName("All account groups found in the document")
        self.groups.setHorizontalHeaderLabels(("From the document", "Activity rows", "Chosen account"))
        self.groups.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.groups.setSelectionMode(QAbstractItemView.SingleSelection)
        self.groups.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.groups.setTabKeyNavigation(False)
        self.groups.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.groups.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.groups.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.groups.setMaximumHeight(185)
        self.groups.currentCellChanged.connect(self._group_changed)
        account_layout.addWidget(self.groups)
        self.editor = QGroupBox("Account for selected group")
        self.editor.setProperty("formRole", "decision")
        form = QFormLayout(self.editor)
        self.group_context = QLabel()
        self.group_context.setWordWrap(True)
        self.group_context.setTextFormat(Qt.PlainText)
        form.addRow(self.group_context)
        self.account_choice = _AccountChoice()
        self.account_choice.setAccessibleName("Existing account or create a new account")
        self.account_choice.currentIndexChanged.connect(self._account_changed)
        self.account_choice.editTextChanged.connect(self._account_changed)
        self.account_choice.activated.connect(self._focus_account_draft)
        form.addRow("Account *", self.account_choice)
        self.new_account = QWidget()
        new_form = QFormLayout(self.new_account)
        new_form.setContentsMargins(0, 0, 0, 0)
        self.name = QLineEdit()
        self.name.setMaxLength(200)
        self.name.setAccessibleName("New account nickname")
        self.name.setPlaceholderText("A name you will recognize")
        self._draft_focus_timer = QTimer(self)
        self._draft_focus_timer.setSingleShot(True)
        self._draft_focus_timer.timeout.connect(self._focus_current_account_draft)
        new_form.addRow("Nickname *", self.name)
        self.institution = InstitutionChoice(institutions)
        new_form.addRow("Institution *", self.institution)
        self.product = _FormatChoice()
        self.product.setAccessibleName("Account product and supported amount")
        new_form.addRow("Account product *", self.product)
        self.detected = QLabel()
        self.detected.setTextFormat(Qt.PlainText)
        self.detected.setWordWrap(True)
        new_form.addRow(self.detected)
        form.addRow(self.new_account)
        self.name.textChanged.connect(self._changed)
        self.institution.currentIndexChanged.connect(self._institution_changed)
        self.institution.editTextChanged.connect(self._institution_changed)
        self.product.currentIndexChanged.connect(self._product_changed)
        account_layout.addWidget(self.editor)
        account_layout.addStretch()
        self.pages.addWidget(self.accounts_page)
        self.preview = _RecognizedPreview(institutions, self)
        self.preview.setWindowFlags(Qt.Widget)
        self.preview.setWindowModality(Qt.NonModal)
        self.preview.layout().setContentsMargins(0, 0, 0, 0)
        self.preview.details.setTabChangesFocus(True)
        for widget in (
            self.preview.file_context,
            self.preview.queue_status,
            self.preview.scope,
            self.preview.status,
            self.preview.import_button,
            self.preview.skip_button,
            self.preview.cancel_button,
            self.preview.original_button,
        ):
            widget.hide()
        self.preview.format_selector.currentIndexChanged.connect(self._preview_changed)
        self.pages.addWidget(self.preview)
        self.pending_page = QWidget()
        self.pending_page.setFocusPolicy(Qt.StrongFocus)
        self.pending_page.setAccessibleName("Import in progress; Tab reaches Cancel remaining imports")
        pending_layout = QVBoxLayout(self.pending_page)
        pending_layout.addStretch()
        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy.setAccessibleName("Import queue is working")
        pending_layout.addWidget(self.busy)
        pending_layout.addStretch()
        self.pages.addWidget(self.pending_page)
        self.preferences = QWidget()
        preference_row = QHBoxLayout(self.preferences)
        preference_row.setContentsMargins(0, 0, 0, 0)
        self.abbreviated_matching = QCheckBox("Automatically match abbreviated account numbers")
        self.abbreviated_matching.setToolTip("Saved for future imports. Your current account choices will not change.")
        self.abbreviated_matching.toggled.connect(self._matching_preference_changed)
        preference_row.addWidget(self.abbreviated_matching)
        preference_row.addStretch()
        preference_row.addWidget(QLabel("Show import preview"))
        self.preview_mode = QComboBox()
        self.preview_mode.addItem("Always", "always")
        self.preview_mode.addItem("Only when attention is needed", "when_needed")
        self.preview_mode.setAccessibleName("Show import preview")
        self.preview_mode.setToolTip(
            "Saved for future imports. New accounts, unknown accounts and warnings still need your review."
        )
        self.preview_mode.currentIndexChanged.connect(self._preview_preference_changed)
        preference_row.addWidget(self.preview_mode)
        layout.addWidget(self.preferences)
        self.preference_notice = QLabel(
            "Import preferences are saved for future files. Current choices stay unchanged."
        )
        self.preference_notice.setWordWrap(True)
        layout.addWidget(self.preference_notice)
        self.assignment_summary = QPlainTextEdit()
        self.assignment_summary.setReadOnly(True)
        self.assignment_summary.setTabChangesFocus(True)
        self.assignment_summary.setMaximumHeight(90)
        self.assignment_summary.setAccessibleName("Accounts and assignments saved by this import")
        layout.addWidget(self.assignment_summary)
        self.status = QLabel()
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.back_button = _ExplicitDecisionButton("&Back to accounts")
        self.back_button.clicked.connect(self._back)
        self.next_button = _ExplicitDecisionButton("&Next: review import")
        self.next_button.clicked.connect(self._next)
        self.import_button = _ExplicitDecisionButton("&Import and assign")
        self.import_button.clicked.connect(self._import)
        self.skip_button = _ExplicitDecisionButton("&Skip this file")
        self.skip_button.clicked.connect(self._skip)
        self.cancel_button = _ExplicitDecisionButton("Cancel remaining imports")
        self.cancel_button.clicked.connect(self.reject)
        self.original_button = _ExplicitDecisionButton("View &original…")
        self.original_button.clicked.connect(self._view_original)
        actions.addWidget(self.original_button)
        actions.addWidget(self.back_button)
        # The two steps share one primary slot. Hidden secondary actions retain
        # their space so another decision never inherits the Import coordinates.
        self.primary_actions = QStackedWidget(self)
        self.primary_actions.addWidget(self.next_button)
        self.primary_actions.addWidget(self.import_button)
        self.primary_actions.setFixedWidth(
            max(self.next_button.sizeHint().width(), self.import_button.sizeHint().width())
        )
        actions.addWidget(self.primary_actions)
        actions.addStretch()
        actions.addWidget(self.skip_button)
        actions.addWidget(self.cancel_button)
        for widget in (self.original_button, self.back_button, self.primary_actions, self.skip_button):
            policy = widget.sizePolicy()
            policy.setRetainSizeWhenHidden(True)
            widget.setSizePolicy(policy)
        layout.addLayout(actions)

    def present(self, request):
        if self._original_open is not None and isValid(self._original_open):
            self._original_open.cancel()
        previous = self.request
        same_file = previous is not None and previous.path == request.path
        same_bytes = same_file and previous.recognition.source_sha256 == request.recognition.source_sha256
        old = self._states if same_bytes else {}
        old_names = (
            {
                key: self._drafts.get(value["new_id"] if value["choice"] == _NEW else value["choice"], value)["name"]
                for key, value in self._states.items()
            }
            if same_file
            else {}
        )
        self._drafts = self._drafts if same_bytes else {}
        self.request, self._finished = request, False
        self._pending = False
        for widget in (
            self.step_label,
            self.scope,
            self.preferences,
            self.preference_notice,
            self.original_button,
            self.primary_actions,
            self.skip_button,
        ):
            widget.show()
        self.status.setToolTip("")
        self.review = request.review
        self.institutions = request.review.institutions
        self._rendering = True
        self.sync_preferences(
            getattr(request.review, "allow_abbreviated_account_matching", False),
            getattr(request.review, "import_preview_mode", "always"),
        )
        self.institution.clear()
        self.institution.addItem("Choose an institution…", "")
        self.institution.addItem("Institution not identified", None)
        for institution in sorted(self.institutions, key=lambda item: item.name.casefold()):
            self.institution.addItem(institution.name, institution.id)
        self._rendering = False
        self._active_group = None
        self._states = {
            group.group_id: old.get(
                group.group_id,
                {
                    "choice": group.suggested_account_id if group.automatic else None,
                    "name": old_names.get(group.group_id, ""),
                    "institution": "",
                    "institution_text": "",
                    "profile": None,
                    "new_id": uuid4().hex,
                    "initial_name": old_names.get(group.group_id, ""),
                },
            )
            for group in request.review.groups
        }
        self.file_context.setText(f"File {request.index} of {request.total}: {request.path.name}")
        self.file_context.setToolTip(str(request.path))
        notice = getattr(request.review, "recovery_notice", "") or ""
        self.recovery_notice.setVisible(bool(notice))
        if notice:
            set_status(self.recovery_notice, "blocked", notice)
        self.update_queue(request.completed)
        self.editor.setEnabled(True)
        self.groups.setRowCount(0)
        self._render_groups()
        self.accounts_page.setEnabled(True)
        self.preview.setEnabled(True)
        self.original_button.setEnabled(True)
        self.preview_mode.setEnabled(True)
        self.abbreviated_matching.setEnabled(True)
        self.back_button.setEnabled(True)
        self.skip_button.setEnabled(True)
        self.cancel_button.setEnabled(True)
        self.pages.setCurrentIndex(0)
        self._set_step(0)
        self._changed()
        self.show()
        self.account_choice.setFocus()
        if (
            not notice
            and len(self.review.recognition.candidates) == 1
            and self.review.groups
            and all(group.automatic and group.suggested_account_id for group in self.review.groups)
            and not self._drafts
            and all(
                self._states[group.group_id]["choice"] == group.suggested_account_id for group in self.review.groups
            )
        ):
            # A content warning can require preview without reopening an already
            # unique account assignment. The final Import remains explicit.
            self._next()

    def _render_groups(self):
        self._active_group = None
        self.groups.blockSignals(True)
        self.groups.setRowCount(len(self.review.groups))
        for row, group in enumerate(self.review.groups):
            for col, value in enumerate(
                (
                    group.source_label or "Account not identified in source",
                    str(group.row_count),
                    "Required: choose an account",
                )
            ):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.groups.setItem(row, col, item)
        self.groups.blockSignals(False)
        if self.review.groups:
            self.groups.setCurrentCell(0, 0)
            self._group_changed(0)

    def _group_changed(self, row, *_args):
        if self.request is None or row < 0:
            return
        self._save_active()
        group = self.review.groups[row]
        self.abbreviated_matching.setVisible(
            getattr(group, "offer_enable_abbreviated_matching", False) or group.source_form == "last_four"
        )
        self._active_group = group.group_id
        state = self._states[group.group_id]
        selected_draft_id = state["new_id"] if state["choice"] == _NEW else state["choice"]
        fields = self._drafts.get(selected_draft_id, state)
        self._editing_draft_id = (
            selected_draft_id if state["choice"] == _NEW or selected_draft_id in self._drafts else None
        )
        self._rendering = True
        self.group_context.setText(
            f"{group.source_label or 'Account not identified in source'} · {group.row_count} activity rows. "
            + (
                f"Supported amount: {_SCOPES[group.source_scope]}. "
                if group.source_scope in _SCOPES
                else "Amount scope depends on the account and supported format. "
            )
            + (
                "Multiple accounts match this identifier; choose the correct account. "
                if group.matching_ambiguous
                else ""
            )
            + "Only compatible accounts and products are listed. Printed names do not establish ownership."
        )
        self.account_choice.clear()
        self.account_choice.addItem("Choose an existing account or create a new one…", None)
        self.account_choice.addItem("Create a new account…", _NEW)
        accounts = compatible_import_accounts(self.review, group.group_id, new_accounts=self._draft_accounts())
        labels = cash_account_labels(accounts, self.institutions)
        for account in accounts:
            product = account_product(account.product_type).label if account.product_type else "Product not recorded"
            prefix = "New in this import: " if account.id in self._drafts else ""
            self.account_choice.addItem(prefix + f"{labels[account.id]} · {product}", account.id)
        if state["choice"] in self._drafts and self.account_choice.findData(state["choice"]) < 0:
            self.account_choice.addItem(
                "New account needs attention: " + (fields["name"] or "nickname required"), state["choice"]
            )
        if state["choice"] is None and group.automatic:
            state["choice"] = group.suggested_account_id
        self.account_choice.setCurrentIndex(max(0, self.account_choice.findData(state["choice"])))
        profiles = import_account_profiles(self.review, group.group_id)
        self.name.setText(fields["name"])
        self.institution.setCurrentIndex(max(0, self.institution.findData(fields["institution"])))
        if fields["institution_text"]:
            self.institution.setEditText(fields["institution_text"])
        known_institutions = {
            draft.institution_key
            for profile in profiles
            if (draft := import_account_creation_draft(self.review, group.group_id, profile)).verified_context
            and draft.institution_key is not None
        }
        self._known_institution = next(iter(known_institutions)) if len(known_institutions) == 1 else None
        if self._known_institution:
            self.institution.setCurrentIndex(self.institution.findData(self._known_institution))
        self.institution.setEnabled(self._known_institution is None)
        self._populate_products(fields["profile"])
        self._rendering = False
        self._product_changed()
        self._account_changed()

    def _account_changed(self, *_args):
        if self._rendering or self._active_group is None:
            return
        choice = self.account_choice.choice()
        draft_id = (
            self._states[self._active_group]["new_id"] if choice == _NEW else choice if choice in self._drafts else None
        )
        self.new_account.setVisible(draft_id is not None)
        if draft_id is not None and draft_id != self._editing_draft_id:
            state = self._drafts.get(
                draft_id,
                {
                    "name": self._states[self._active_group].get("initial_name", ""),
                    "institution": "",
                    "institution_text": "",
                    "profile": None,
                },
            )
            self._rendering = True
            self.name.setText(state["name"])
            if self._known_institution:
                self.institution.setCurrentIndex(self.institution.findData(self._known_institution))
            else:
                self.institution.setCurrentIndex(max(0, self.institution.findData(state["institution"])))
                if state["institution_text"]:
                    self.institution.setEditText(state["institution_text"])
            self._populate_products(state["profile"])
            self._rendering = False
            self._editing_draft_id = draft_id
            self._product_changed()
        self._editing_draft_id = draft_id
        self.account_choice.setToolTip(self.account_choice.currentText())
        if self.account_choice.choice() is not None:
            self.account_choice.lineEdit().setCursorPosition(0)
        if self.account_choice.choice() == _NEW and self.product.currentData() is None:
            known = [i for i in range(1, self.product.count()) if self._identified_product(self.product.itemData(i))]
            if len(known) == 1:
                self.product.setCurrentIndex(known[0])
        self._changed()

    def _focus_account_draft(self, *_args):
        if self.account_choice.choice() == _NEW:
            self._draft_focus_timer.start(0)

    def _focus_current_account_draft(self):
        if self.account_choice.choice() == _NEW and self.name.isVisible():
            self.name.setFocus(Qt.OtherFocusReason)

    def _identified_product(self, profile):
        products = {candidate.identifying_product_type for candidate in self.review.recognition.candidates}
        return products == {profile.product_type} and all(
            candidate.institution_key is not None for candidate in self.review.recognition.candidates
        )

    def _populate_products(self, selected):
        was_rendering, self._rendering = self._rendering, True
        institution = self.institution.selected_key()
        by_shape = {}
        for profile in import_account_profiles(self.review, self._active_group):
            if profile.institution_key is None or profile.institution_key == institution:
                by_shape[profile.product_type, profile.tracking_scope] = profile
        self.product.clear()
        self.product.addItem("Choose the product this account represents…", None)
        for profile in by_shape.values():
            label = account_product(profile.product_type).label
            if profile.tracking_scope != "account_total":
                label += " · " + _SCOPES[profile.tracking_scope]
            self.product.addItem(label, profile)
        index = self.product.findData(selected)
        if index < 0 and selected is not None:
            index = next(
                (
                    i
                    for i in range(1, self.product.count())
                    if (self.product.itemData(i).product_type, self.product.itemData(i).tracking_scope)
                    == (selected.product_type, selected.tracking_scope)
                ),
                0,
            )
        self.product.setCurrentIndex(max(0, index))
        self._rendering = was_rendering

    def _institution_changed(self, *_args):
        if self._rendering or self._active_group is None:
            return
        self._populate_products(self.product.currentData())
        self._product_changed()

    def _product_changed(self, *_args):
        if self._rendering or self._active_group is None:
            return
        profile = self.product.currentData()
        self.detected.clear()
        self.product.setEnabled(True)
        if profile is not None:
            draft = import_account_creation_draft(self.review, self._active_group, profile)
            if draft.verified_context and draft.institution_key is not None:
                self._rendering = True
                self.institution.setCurrentIndex(self.institution.findData(draft.institution_key))
                self._rendering = False
                self.institution.setEnabled(False)
                self.detected.setText(
                    f"Institution identified from this document: {institution_label(draft.institution_key, self.institutions)}. "
                    + (
                        f"Identified product: {account_product(profile.product_type).label}."
                        if self._identified_product(profile)
                        else "Account product is your choice."
                    )
                )
            self.product.setEnabled(not self._identified_product(profile))
            self.detected.setText(
                self.detected.text()
                + (" " if self.detected.text() else "Your account choice: ")
                + f"Tracks {_SCOPES[profile.tracking_scope]}; {'money you own' if profile.kind == 'asset' else 'money you owe'}. No balance or transaction is posted by this choice."
            )
            if draft.verified_context and self._identified_product(profile) and not self.name.text().strip():
                self.name.setText(draft.name)
        self._changed()

    def _save_active(self):
        if self._active_group is None or self._rendering:
            return
        self._states[self._active_group].update(
            choice=self.account_choice.choice(),
            name=self.name.text(),
            institution=self.institution.selected_key(),
            institution_text=self.institution.currentText(),
            profile=self.product.currentData(),
        )
        if self._editing_draft_id is not None:
            state = self._states[self._active_group]
            draft = self._drafts.setdefault(self._editing_draft_id, {})
            draft.update({key: state[key] for key in ("name", "institution", "institution_text", "profile")})
            if draft["profile"] is not None and "full_number" not in draft:
                draft["full_number"] = import_account_creation_draft(
                    self.review, self._active_group, draft["profile"]
                ).full_account_number

    def _draft_accounts(self):
        accounts = []
        for identity, state in self._drafts.items():
            profile = state["profile"]
            if profile is None or not state["name"].strip() or state["institution"] == "":
                continue
            if state["institution"] is not None and not any(
                item.id == state["institution"] for item in self.institutions
            ):
                continue
            accounts.append(
                FinancialAccount(
                    identity,
                    state["name"].strip(),
                    profile.kind,
                    state["institution"],
                    state.get("full_number"),
                    profile.tracking_scope,
                    profile.product_type,
                )
            )
        return tuple(accounts)

    def _choices(self):
        choices = []
        drafts = {account.id: account for account in self._draft_accounts()}
        for group in self.review.groups:
            group_id, state = group.group_id, self._states[group.group_id]
            choice = state["choice"]
            account_id = state["new_id"] if choice == _NEW else choice
            if account_id in self._drafts and account_id not in drafts:
                continue
            if account_id is not None:
                choices.append(ImportAccountChoice(group_id, account_id))
        used = {choice.account_id for choice in choices}
        return tuple(choices), tuple(account for account in drafts.values() if account.id in used)

    def _changed(self, *_args):
        if self._rendering or self._pending or self.request is None:
            return
        self._save_active()
        choices, accounts = self._choices()
        ready_ids = {choice.group_id for choice in choices}
        for row, group in enumerate(self.review.groups):
            state = self._states[group.group_id]
            account = next(
                (
                    item
                    for item in (*self.review.accounts, *accounts)
                    if item.id == (state["new_id"] if state["choice"] == _NEW else state["choice"])
                ),
                None,
            )
            text = (
                ("New in this import: " if account is not None and account.id in self._drafts else "Use: ")
                + account.name
                if account is not None and group.group_id in ready_ids
                else "Required: choose an account"
            )
            self.groups.item(row, 2).setText(text)
        self._matching = matching_import_candidates(self.review, choices=choices, new_accounts=accounts)
        complete = bool(self.review.groups) and len(choices) == len(self.review.groups)
        ready = complete and bool(self._matching)
        self.next_button.setEnabled(ready and not self.request.decided.is_set())
        set_field_state(self.next_button, "ready" if self.next_button.isEnabled() else "neutral")
        set_field_state(self.account_choice, "ready" if self.account_choice.choice() else "required")
        if self._editing_draft_id is not None:
            set_field_state(self.name, "ready" if self.name.text().strip() else "required")
            set_field_state(
                self.institution,
                "readonly"
                if not self.institution.isEnabled()
                else "ready"
                if self.institution.valid_selection()
                else "required",
            )
            set_field_state(
                self.product,
                "readonly"
                if not self.product.isEnabled()
                else "ready"
                if self.product.currentData() is not None
                else "required",
            )
        account_lookup = {account.id: account for account in (*self.review.accounts, *accounts)}
        groups = {group.group_id: group for group in self.review.groups}
        self.assignment_summary.setPlainText(
            f"Import assigns {next((candidate.row_count for candidate in self._matching if candidate.parser_id == self.preview.format_selector.currentData()), sum(group.row_count for group in self.review.groups))} activity rows across {len(choices)} document account groups and creates {len(accounts)} new accounts. No transactions are posted.\n"
            + "\n".join(
                f"{groups[choice.group_id].source_label or 'Account not identified in source'} → "
                + ("NEW " if choice.account_id in {account.id for account in accounts} else "EXISTING ")
                + f"{account_lookup[choice.account_id].name} · {institution_label(account_lookup[choice.account_id].institution_key, self.institutions)} · "
                + (
                    account_product(account_lookup[choice.account_id].product_type).label
                    if account_lookup[choice.account_id].product_type
                    else "Product not recorded"
                )
                + " · "
                + _SCOPES[account_lookup[choice.account_id].tracking_scope]
                for choice in choices
            )
        )
        if self.pages.currentIndex() == 0:
            set_status(
                self.status,
                "ready" if ready else "blocked" if complete else "required",
                "Accounts chosen · Not saved. Next, review the recognized activity and assignments."
                if ready
                else "These account choices have no supported format for this document. Choose compatible accounts/products or skip this file."
                if complete
                else "Required: choose an account for every document group. Create new keeps a draft until the final import confirmation.",
            )

    def _set_step(self, index):
        self.step_label.setText("1 of 2 · Choose accounts" if index == 0 else "2 of 2 · Review import")
        self.scope.setText(
            "Choose an account for each group. You can create a new account here."
            if index == 0
            else "Check the dates, amounts and accounts. Import saves the original and assignments; it adds no spending."
        )
        self.back_button.setVisible(index == 1)
        self.primary_actions.setCurrentIndex(index)
        self.next_button.setVisible(index == 0)
        self.import_button.setVisible(index == 1)
        self.assignment_summary.setVisible(index == 1)

    def _matching_preference_changed(self, enabled):
        if not self._rendering and self.request is not None:
            self.abbreviated_matching_changed.emit(enabled)

    def sync_preferences(self, allow_abbreviated: bool, preview_mode: str, error: str = ""):
        """Acknowledge global persistence without touching any current account draft."""
        self.abbreviated_matching.blockSignals(True)
        self.preview_mode.blockSignals(True)
        try:
            self.abbreviated_matching.setChecked(allow_abbreviated)
            self.preview_mode.setCurrentIndex(max(0, self.preview_mode.findData(preview_mode)))
        finally:
            self.abbreviated_matching.blockSignals(False)
            self.preview_mode.blockSignals(False)
        set_status(
            self.preference_notice,
            "blocked" if error else "neutral",
            f"Preferences were not saved. {error}"
            if error
            else "Import preferences apply to future files. Current choices stay unchanged.",
        )

    def _preview_preference_changed(self, *_args):
        if not self._rendering and self.request is not None:
            self.import_preview_mode_changed.emit(self.preview_mode.currentData())

    def _cancel_original(self):
        if self._original_open is not None and isValid(self._original_open):
            self._original_open.cancel()
        self._original_open = None

    def _view_original(self):
        if self.request is None or self.request.decided.is_set():
            return
        self._cancel_original()
        self._original_open = open_selected_original(self.request.path, self.request.recognition.source_sha256, self)

    def _next(self):
        self._changed()
        if not self.next_button.isEnabled():
            return
        recognition = replace(self.request.recognition, candidates=tuple(self._matching))
        # The embedded preview owns rendering only; final decisions stay here.
        preview_request = _PreviewRequest(self.request, recognition)
        self.preview.present(preview_request)
        for widget in (
            self.preview.file_context,
            self.preview.queue_status,
            self.preview.scope,
            self.preview.status,
            self.preview.import_button,
            self.preview.skip_button,
            self.preview.cancel_button,
            self.preview.original_button,
        ):
            widget.hide()
        self.pages.setCurrentIndex(1)
        self._set_step(1)
        self._preview_changed()
        (self.import_button if self.import_button.isEnabled() else self.back_button).setFocus()

    def _back(self):
        self.pages.setCurrentIndex(0)
        self._set_step(0)
        self._changed()
        self.account_choice.setFocus()

    def _preview_changed(self, *_args):
        if self._pending or self.request is None:
            return
        valid = self.preview.format_selector.currentData() is not None and not self.request.decided.is_set()
        if self.pages.currentIndex() == 1:
            self._changed()
        self.import_button.setEnabled(valid)
        set_field_state(self.import_button, "ready" if valid else "neutral")
        if self.pages.currentIndex() == 1:
            preview_reason = ""
            if self.review.import_preview_mode == "when_needed":
                new_count = len(self._draft_accounts())
                if new_count:
                    preview_reason = f"Preview required: {new_count} new {'account needs' if new_count == 1 else 'accounts need'} confirmation. "
                elif any(group.matching_ambiguous for group in self.review.groups):
                    preview_reason = "Preview required: an account match is ambiguous. "
                elif self.review.recovery_notice:
                    preview_reason = "Preview required: import inputs changed or need attention. "
                elif any(candidate.attention_codes for candidate in self.review.recognition.candidates):
                    preview_reason = "Preview required: source interpretation warnings need checking. "
                else:
                    preview_reason = "Preview required: account choices need confirmation. "
            candidate = next(
                (
                    item
                    for item in self.preview.request.recognition.candidates
                    if item.parser_id == self.preview.format_selector.currentData()
                ),
                None,
            )
            warning_guidance = (
                " Compare the warnings, dates and amounts with View original. "
                "Import retains these warnings and assignments; no transactions are posted."
                if candidate is not None and (candidate.attention_codes or getattr(candidate, "warnings", ()))
                else ""
            )
            set_status(
                self.status,
                "ready" if valid else "blocked",
                preview_reason + "Ready to import · Not saved. No spending is posted." + warning_guidance
                if valid
                else "This file matches more than one supported format for these accounts. Nothing has been imported. Back keeps your drafts; check the institution and product, or Skip this file. You can update supported formats from the workspace before trying again.",
            )

    def _import(self):
        if self.request is None or not self.import_button.isEnabled():
            return
        choices, accounts = self._choices()
        try:
            plan = prepare_import_accounts(
                self.review, choices, self.preview.format_selector.currentData(), new_accounts=accounts
            )
        except ValueError as error:
            self.import_button.setEnabled(False)
            set_field_state(self.import_button, "neutral")
            set_status(
                self.status,
                "blocked",
                "These choices need review. Back to accounts keeps your drafts; check the assignments and recognized activity again before importing.",
            )
            self.status.setToolTip(str(error))
            return
        self.request.finish(plan)
        self._waiting("Importing original, accounts and assignments together… No transactions are posted.")

    def _skip(self):
        if self.request is not None and not self.request.decided.is_set():
            self.request.finish(None)
            self._waiting("File skipped. Provisional accounts were not saved. Waiting for the next file…")

    def _waiting(self, text):
        self._cancel_original()
        self._draft_focus_timer.stop()
        self._pending = True
        self.pages.setCurrentWidget(self.pending_page)
        for widget in (
            self.step_label,
            self.scope,
            self.recovery_notice,
            self.assignment_summary,
            self.preferences,
            self.preference_notice,
            self.original_button,
            self.back_button,
            self.primary_actions,
            self.skip_button,
        ):
            widget.hide()
        self.accounts_page.setEnabled(False)
        self.preview.setEnabled(False)
        self.original_button.setEnabled(False)
        self.preview_mode.setEnabled(False)
        self.abbreviated_matching.setEnabled(False)
        for button in (self.next_button, self.back_button, self.import_button, self.skip_button):
            button.setEnabled(False)
            set_field_state(button, "neutral")
        set_status(self.status, "loading", text)
        self.status.setToolTip("")
        self.pending_page.setFocus()

    def wait_for_next(self, index, total, path):
        self.file_context.setText(f"File {index} of {total}: {path.name} · Reading document…")
        self.file_context.setToolTip(str(path))
        self._waiting("Checking the next document. Completed imports stay saved if you cancel.")

    def update_queue(self, completed):
        self.queue_status.setVisible(self.request is not None and self.request.total > 1)
        counts = {
            status: sum(item.status == status for item in completed)
            for status in ("imported", "already_imported", "skipped", "failed")
        }
        self.queue_status.setText(
            "No files completed yet. Cancel retains completed imports."
            if not completed
            else f"Completed: {counts['imported']} imported · {counts['already_imported']} already saved · {counts['skipped']} skipped · {counts['failed']} failed. Last: {completed[-1].path.name} — {completed[-1].status.replace('_', ' ')}. Cancel retains completed imports."
        )

    def finish_queue(self):
        self._cancel_original()
        self._finished = True
        self.request = None
        self.hide()

    def reject(self):
        if not self._finished:
            self.cancel_remaining.emit()
            if self.request is not None:
                self.request.finish(None)
            self._waiting(
                "Cancelling remaining imports… Provisional accounts are discarded; completed imports remain saved."
            )

    def closeEvent(self, event):
        if self._finished:
            event.accept()
        else:
            self.reject()
            event.ignore()


class _PreviewRequest:
    def __init__(self, request, recognition):
        self.recognition = recognition
        self.path, self.index, self.total, self.completed, self.decided = (
            request.path,
            request.index,
            request.total,
            request.completed,
            request.decided,
        )
