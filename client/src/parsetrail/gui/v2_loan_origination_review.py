"""Source-backed principal financing with optional destination and asset allocation."""

from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_account_products import account_product
from parsetrail.gui.v2_details_disclosure import DetailsDisclosure
from parsetrail.gui.v2_evidence_preview import _money, preview_saved_source
from parsetrail.gui.v2_form_state import install_form_styles, set_field_state, set_status
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_tangible_assets import V2TangibleAssets


class V2LoanOriginationReview(QDialog):
    CREATE_ASSET = object()

    def __init__(self, workspace, parent=None, *, source_sha256=None, focus_row_id=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace = workspace
        self._source, self._focus_row = source_sha256, focus_row_id
        self.snapshot = self.preview = None
        self.rows, self._accounts, self._resolution_states = {}, {}, {}
        self._rendering = False
        self._preferred_destination = None
        self._destination_choice = None
        self._create_pending = False
        self._initial_pending_rows = None
        self.initial_posting_succeeded = False
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._completed)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        self.setWindowTitle("Review loan origination")
        self.resize(960, 540)
        layout = QVBoxLayout(self)
        title = QLabel("Review loan origination")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(title)
        explanation = QLabel(
            "Record the exact financed principal now. You can identify its destination now or resolve it later in Transfers."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.source_row = QComboBox()
        self.source_row.setAccessibleName("Loan origination source")
        self.source_row.setMinimumContentsLength(25)
        self.source_row.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source_row.currentIndexChanged.connect(self._source_selected)
        layout.addWidget(self.source_row)
        self.facts = QLabel()
        self.facts.setWordWrap(True)
        self.facts.setTextFormat(Qt.PlainText)
        self.facts.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.facts)
        self.assumed_dates = QCheckBox("Allow the loan activity date as an assumed accounting date")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_dates)
        layout.addWidget(self.assumed_dates)
        form = self.form = QFormLayout()
        self.destination = QComboBox()
        self.destination.setAccessibleName("Financing destination, optional")
        self.destination.setMinimumContentsLength(25)
        self.destination.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.destination.currentIndexChanged.connect(self._destination_changed)
        form.addRow("Destination (optional)", self.destination)
        self.asset_link = QCheckBox("This financing funded this asset")
        self.asset_link.toggled.connect(self._draft_changed)
        form.addRow(self.asset_link)
        self.allocation_date = QDateEdit(QDate.currentDate())
        self.allocation_date.setDisplayFormat("yyyy-MM-dd")
        self.allocation_date.setCalendarPopup(True)
        self.allocation_date.dateChanged.connect(self._draft_changed)
        form.addRow("Financed allocation date", self.allocation_date)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        self.reason.textChanged.connect(self._draft_changed)
        form.addRow("Review note *", self.reason)
        layout.addLayout(form)
        self.limits = QLabel(
            "Full acquisition cost remains unknown. Asset estimates are independent of financing and do not establish a downpayment or spending."
        )
        self.limits.setWordWrap(True)
        self.limits.hide()
        self.effects = QLabel()
        self.effects.setWordWrap(True)
        self.effects.setTextFormat(Qt.PlainText)
        self.effects.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.effects)
        layout.addStretch(1)
        self.status = QLabel("Loading origination evidence…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        correction = QWidget()
        correction_form = QFormLayout(correction)
        correction_form.setContentsMargins(0, 0, 0, 0)
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setPlaceholderText("Enter a fresh reason to withdraw this origination")
        self.correction_reason.textChanged.connect(self._update_saved_actions)
        correction_form.addRow("Reason for withdrawal", self.correction_reason)
        self.withdraw = QPushButton("Withdraw origination…")
        self.withdraw.clicked.connect(self._withdraw)
        correction_form.addRow(self.withdraw)
        self.correction = DetailsDisclosure(correction, self, subject="origination correction")
        self.correction.toggled.connect(self._correction_expanded)
        self._correction_expanded(False)
        layout.addWidget(self.correction)
        actions = QHBoxLayout()
        self.confirm = QPushButton("Review financing posting…")
        self.confirm.clicked.connect(self._confirm)
        actions.addWidget(self.confirm)
        self.original = QPushButton("View source evidence…")
        self.original.clicked.connect(self._open_source)
        actions.addWidget(self.original)
        actions.addStretch()
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        source, preferences = self._source, self.workspace.preferences()

        def read(store, _cancelled):
            accounts = tuple(
                a
                for a in store.financial_accounts()
                if a.kind in {"asset", "liability"}
                and (
                    a.tracking_scope in {"account_total", "cash_component"}
                    or a.kind == "liability"
                    and a.tracking_scope == "principal_component"
                )
            )
            return (
                store.origination_snapshot(source_sha256=source),
                accounts,
                {item.id: item.status for item in store.resolution_snapshot(preferences=preferences).items},
            )

        self.jobs.submit("snapshot", read)

    def _completed(self, key, result):
        if key == "snapshot":
            self.snapshot, accounts, self._resolution_states = result
            self._accounts = {account.id: account for account in accounts}
            self.rows = {row.row_id: row for row in self.snapshot.rows}
            if self._initial_pending_rows is None:
                self._initial_pending_rows = {row.row_id for row in self.snapshot.rows if row.event_id is None}
            current = self.source_row.currentData() or self._focus_row
            destination = self._preferred_destination or self.destination.currentData()
            self._preferred_destination = None
            self._rendering = True
            self.source_row.clear()
            for row in self.snapshot.rows:
                self.source_row.addItem(
                    f"{row.account_name or 'Unassigned loan'} · {row.activity_date}",
                    row.row_id,
                )
            self.source_row.setCurrentIndex(max(0, self.source_row.findData(current)))
            row = self.rows.get(self.source_row.currentData())
            self.destination.clear()
            self.destination.addItem("Destination not established — resolve later in Transfers", None)
            for account in accounts:
                if row is None or account.id != row.account_id:
                    product = (
                        account_product(account.product_type).label if account.product_type else account.kind.title()
                    )
                    scope = " · principal only" if account.tracking_scope == "principal_component" else ""
                    self.destination.addItem(f"{account.name} · {product}{scope}", account.id)
                    self.destination.setItemData(
                        self.destination.count() - 1, f"{account.name} · {product}{scope}", Qt.ToolTipRole
                    )
            self.destination.insertSeparator(self.destination.count())
            self.destination.addItem("Create tangible asset…", self.CREATE_ASSET)
            self.destination.setCurrentIndex(max(0, self.destination.findData(destination)))
            self._rendering = False
            self._source_selected()
        elif key == "preview":
            self.preview = result
            self.effects.setText(self._summary(result))
            self.status.setText("Ready to review the financing posting. Nothing has been posted yet.")
            self.confirm.setEnabled(not self.jobs.pending)
        else:
            if key == "post" and result.row_id in (self._initial_pending_rows or set()):
                self.initial_posting_succeeded = True
            self.preview = None
            self.correction_reason.clear()
            self.correction.button.setChecked(False)
            self.refresh()

    def _summary(self, event):
        destination = self._accounts.get(event.destination_account_id)
        day = getattr(event, "effective_date", None) or self.rows[event.row_id].activity_date
        text = f"Financed principal {_money(event.principal_minor)} on {day} (assumed accounting date). "
        if event.mode == "acquisition":
            return (
                text
                + f"Reviewed acquisition cost {_money(event.acquisition_value_minor)} to {destination.name if destination else 'the retained asset'} on {event.acquisition_date}. The saved funding details remain in history. Valuation estimates stay independent. Unknown opening remains unknown."
            )
        matched = self._resolution_states.get(getattr(event, "event_id", None)) == "matched"
        counterpart = "counterpart matched in Transfers" if matched else "counterpart unresolved in Transfers"
        if destination is None:
            text += f"No destination specified; {counterpart}. "
        elif destination.product_type == "tangible_asset":
            if event.acquisition_date is not None:
                text += f"Financed allocation {_money(event.principal_minor)} to {destination.name} on {event.acquisition_date}. "
            else:
                text += f"Destination: {destination.name}; no asset allocation confirmed. Counterpart unresolved in Transfers. "
        else:
            text += f"Expected destination: {destination.name}. No transaction is posted there by this financing event; {counterpart}. "
        return (
            text
            + "Full acquisition cost remains unknown. Estimates create no downpayment or spending. Unknown opening remains unknown."
        )

    def _source_selected(self, *_args):
        if self._rendering:
            return
        row = self.rows.get(self.source_row.currentData())
        event = self._event()
        self._rendering = True
        if row is not None:
            self.facts.setText(
                f"Source: financed principal {_money(row.principal_minor)} · observed activity date {row.activity_date}. This is new financing; no repayment or interest expense is inferred."
            )
            parsed = QDate.fromString(row.activity_date or "", Qt.ISODate)
            if parsed.isValid():
                self.allocation_date.setDate(parsed)
        self.limits.setText(
            "Full acquisition cost remains unknown. Asset estimates are independent of financing and do not establish a downpayment or spending."
        )
        if event is not None:
            self.destination.setCurrentIndex(max(0, self.destination.findData(event.destination_account_id)))
            self.asset_link.setChecked(event.acquisition_date is not None)
            if event.acquisition_date is not None:
                self.allocation_date.setDate(
                    QDate(event.acquisition_date.year, event.acquisition_date.month, event.acquisition_date.day)
                )
            self.reason.setText(event.reason)
            self.effects.setText("Saved · " + self._summary(event))
            self.limits.setText(
                "Valuation estimates stay independent of the reviewed acquisition cost."
                if event.mode == "acquisition"
                else "Full acquisition cost remains unknown. Asset estimates are independent of financing and do not establish a downpayment or spending."
            )
        self._rendering = False
        self._destination_changed()
        self._update_saved_actions()

    def _destination_changed(self, *_args):
        if self._rendering:
            return
        selected = self.destination.currentData()
        if selected is self.CREATE_ASSET:
            # Finish the combo's native selection before opening a disposable
            # modal. Restore even the valid None choice, never persisting this
            # command or submitting it as a financial destination.
            self.destination.blockSignals(True)
            self.destination.setCurrentIndex(max(0, self.destination.findData(self._destination_choice)))
            self.destination.blockSignals(False)
            self.preview = None
            self.confirm.setEnabled(False)
            self.jobs.cancel_reads()
            if not self._create_pending:
                self._create_pending = True
                QTimer.singleShot(0, self, self._create_asset)
            return
        previous, self._destination_choice = self._destination_choice, selected
        account = self._accounts.get(selected)
        tangible = account is not None and account.product_type == "tangible_asset"
        if not tangible or (previous != selected and self._event() is None):
            self.asset_link.setChecked(False)
        self.form.setRowVisible(self.asset_link, tangible)
        self.form.setRowVisible(self.allocation_date, tangible and self.asset_link.isChecked())
        self._draft_changed()

    def _draft_changed(self, *_args):
        if self._rendering or self.jobs.writing:
            return
        account = self._accounts.get(self.destination.currentData())
        self.form.setRowVisible(
            self.allocation_date,
            account is not None and account.product_type == "tangible_asset" and self.asset_link.isChecked(),
        )
        self.jobs.cancel_reads()
        self.preview = None
        self.confirm.setEnabled(False)
        self._update_cues()
        row = self.rows.get(self.source_row.currentData())
        if row is None or self.snapshot is None:
            self.status.setText("No supported origination evidence is available.")
            self.effects.clear()
            return
        if self._event() is not None:
            self.status.setText("Saved financing. Inspect source evidence or expand correction details to withdraw it.")
            return
        if not self.reason.text().strip():
            self.status.setText("Enter a review note.")
            return
        account = self._accounts.get(self.destination.currentData())
        if account is not None and account.product_type == "tangible_asset" and not self.asset_link.isChecked():
            self.effects.clear()
            self.status.setText(
                f"Confirm this financing funded {account.name}, or leave the destination not established."
            )
            return
        row_id, destination = row.row_id, self.destination.currentData()
        linked = self.asset_link.isChecked()
        allocated = self.allocation_date.date().toPython() if linked else None
        preferences, basis, reason = (
            self.workspace.preferences(),
            self.snapshot.basis_sha256,
            self.reason.text().strip(),
        )
        self.jobs.submit(
            "preview",
            lambda store, _cancelled: store.preview_loan_funding(
                row_id,
                destination_account_id=destination,
                tangible_allocation_date=allocated,
                confirm_tangible_allocation=linked,
                preferences=preferences,
                expected_basis_sha256=basis,
                reason=reason,
            ),
            delay=100,
        )
        self.status.setText("Checking the exact financing…")

    def _event(self):
        row = self.rows.get(self.source_row.currentData())
        return (
            next((e for e in self.snapshot.events if e.event_id == row.event_id and e.status == "active"), None)
            if row is not None and self.snapshot is not None
            else None
        )

    def _update_saved_actions(self, *_args):
        active = self._event() is not None
        has_source = self.source_row.currentData() in self.rows
        self.correction.setVisible(active)
        self.withdraw.setEnabled(bool(active and self.correction_reason.text().strip() and not self.jobs.pending))
        self.correction_reason.setEnabled(active and not self.jobs.writing)
        self.confirm.setVisible(not active)
        for widget in (self.destination, self.asset_link, self.allocation_date, self.reason):
            widget.setEnabled(has_source and not self.jobs.writing and not active)
        self._update_cues()

    def _update_cues(self):
        has_source = self.source_row.currentData() in self.rows
        saved = self._event() is not None
        destination = self._accounts.get(self.destination.currentData())
        tangible = destination is not None and destination.product_type == "tangible_asset"
        readonly = saved or not has_source
        set_field_state(self.source_row, "readonly" if has_source else "loading")
        set_field_state(
            self.destination,
            "saved" if saved else "optional" if self.destination.currentData() is None else "ready",
        )
        set_field_state(self.reason, "saved" if readonly else "ready" if self.reason.text().strip() else "required")
        set_field_state(
            self.assumed_dates, "readonly" if readonly else "ready" if self.assumed_dates.isChecked() else "required"
        )
        set_field_state(
            self.asset_link,
            "readonly"
            if readonly
            else "ready"
            if tangible and self.asset_link.isChecked()
            else "required"
            if tangible
            else "neutral",
        )
        set_field_state(
            self.allocation_date,
            "readonly" if readonly else "ready" if self.allocation_date.date().isValid() else "invalid",
        )
        correcting = saved and self.correction.button.isChecked()
        set_field_state(
            self.correction_reason,
            "ready"
            if correcting and self.correction_reason.text().strip()
            else "required"
            if correcting
            else "optional",
        )
        set_field_state(self.confirm, "ready" if self.confirm.isEnabled() else "neutral")
        set_field_state(self.withdraw, "ready" if self.withdraw.isEnabled() else "neutral")
        state = (
            "loading"
            if self.jobs.pending
            else "saved"
            if saved
            else "neutral"
            if not has_source
            else "required"
            if not self.reason.text().strip()
            or (tangible and not self.asset_link.isChecked())
            or not self.assumed_dates.isChecked()
            else "ready"
            if self.confirm.isEnabled()
            else "blocked"
        )
        set_status(self.status, state, self.status.text())

    def _correction_expanded(self, expanded):
        self.correction.button.setText("Hide correction" if expanded else "Correct saved origination…")
        if hasattr(self, "confirm"):
            self._update_cues()

    def _withdraw(self):
        event = self._event()
        if event is None or not self.withdraw.isEnabled():
            return
        reason = self.correction_reason.text().strip()
        if (
            QMessageBox.question(
                self,
                "Withdraw loan origination",
                "Reverse this origination's exact saved financing and any financed allocation? Evidence, valuation points and history remain.\n\nReason: "
                + reason,
            )
            != QMessageBox.Yes
        ):
            return
        event_id, version = event.event_id, event.version
        self.jobs.submit(
            "withdraw",
            lambda store, _cancelled: store.withdraw_loan_origination(
                event_id, expected_version=version, reason=reason
            ),
            write=True,
        )

    def _create_asset(self):
        self._create_pending = False
        if self.jobs.writing or self._event() is not None or self.source_row.currentData() not in self.rows:
            return
        dialog = V2TangibleAssets(self.workspace, self, value_date=self.allocation_date.date().toPython())
        try:
            dialog.exec()
            self._preferred_destination = dialog.selected_account_id
        finally:
            dialog.deleteLater()
        self.refresh()
        self.destination.setFocus(Qt.OtherFocusReason)

    def _confirm(self):
        if self.preview is None or not self.confirm.isEnabled():
            return
        preview = self.preview
        if preview.preferences != self.workspace.preferences():
            self._draft_changed()
            return
        if (
            QMessageBox.question(
                self, "Confirm financing posting", self.effects.text() + "\n\nPost this reviewed financing?"
            )
            != QMessageBox.Yes
        ):
            return
        if preview.preferences != self.workspace.preferences():
            self._draft_changed()
            return
        self.jobs.submit("post", lambda store, _cancelled: store.post_loan_origination(preview), write=True)

    def _toggle_dates(self, enabled):
        try:
            self.workspace.set_allow_assumed_posting_dates(enabled)
        except (OSError, ValueError):
            self.assumed_dates.blockSignals(True)
            self.assumed_dates.setChecked(not enabled)
            self.assumed_dates.blockSignals(False)
            self.status.setText("The posting-date preference was not saved. Retry before posting.")
            return
        self._draft_changed()

    def _open_source(self):
        row = self.rows.get(self.source_row.currentData())
        if row is not None:
            exec_disposable(preview_saved_source(self.workspace.profile_path, row.source_sha256, parent=self))

    def _busy(self, busy):
        self.source_row.setEnabled(not self.jobs.writing)
        self.assumed_dates.setEnabled(not self.jobs.writing and self.source_row.currentData() in self.rows)
        self.original.setEnabled(not busy and self.source_row.currentData() in self.rows)
        self.confirm.setEnabled(bool(not busy and self.preview is not None))
        self._update_saved_actions()

    def _failed(self, key, error):
        self.preview = None
        self.confirm.setEnabled(False)
        messages = {
            "origination_assumed_date_permission_required": "Allow the observed loan activity date as an assumed accounting date before posting. The source date is not a printed posting date.",
            "origination_tangible_confirmation_required": "Confirm this financing funded the selected asset, or leave the destination not established.",
        }
        self.status.setText(messages.get(str(error), "This financing needs review before posting. " + str(error)))
        if key == "snapshot":
            self.rows = {}

    def reject(self):
        if self.jobs.writing:
            self.status.setText("Finishing the confirmed origination save before closing.")
            return
        self.jobs.close()
        super().reject()

    def closeEvent(self, event):
        if not self.jobs.close():
            event.ignore()
            return
        super().closeEvent(event)
