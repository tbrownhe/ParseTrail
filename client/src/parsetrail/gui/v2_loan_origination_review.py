"""Explicit source-backed financing acquisition, separate from repayment review."""

from PySide6.QtCore import QDate, Qt
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
)

from parsetrail.gui.v2_account_anchors import _typed_minor
from parsetrail.gui.v2_evidence_preview import _money, preview_saved_source
from parsetrail.gui.v2_form_state import install_form_styles
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_profile_jobs import ProfileJobs
from parsetrail.gui.v2_tangible_assets import V2TangibleAssets


class V2LoanOriginationReview(QDialog):
    def __init__(self, workspace, parent=None, *, source_sha256=None, focus_row_id=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace = workspace
        self._source, self._focus_row = source_sha256, focus_row_id
        self.snapshot = self.preview = None
        self.rows = {}
        self._rendering = False
        self._preferred_destination = None
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._completed)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        self.setWindowTitle("Review loan origination")
        self.resize(960, 650)
        layout = QVBoxLayout(self)
        title = QLabel("Loan origination")
        title.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(title)
        explanation = QLabel(
            "Review where the financing went. The lender's amount financed is separate from the vehicle's acquisition value. Import can remain pending until destination and funding are established."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.source_row = QComboBox()
        self.source_row.setAccessibleName("Loan origination source")
        self.source_row.currentIndexChanged.connect(self._source_selected)
        layout.addWidget(self.source_row)
        self.facts = QLabel()
        self.facts.setWordWrap(True)
        self.facts.setTextFormat(Qt.PlainText)
        layout.addWidget(self.facts)
        self.assumed_dates = QCheckBox("Allow the loan activity date as an assumed accounting date")
        self.assumed_dates.setChecked(workspace.preferences().allow_assumed_posting_dates)
        self.assumed_dates.toggled.connect(self._toggle_dates)
        layout.addWidget(self.assumed_dates)
        form = self.form = QFormLayout()
        destination_row = QHBoxLayout()
        self.destination = QComboBox()
        self.destination.setAccessibleName("Vehicle receiving the financing")
        self.destination.currentIndexChanged.connect(self._draft_changed)
        destination_row.addWidget(self.destination, 1)
        create = QPushButton("Create vehicle asset…")
        create.clicked.connect(self._create_vehicle)
        destination_row.addWidget(create)
        form.addRow("Financing used for", destination_row)
        self.acquisition_value = QLineEdit()
        self.acquisition_value.setPlaceholderText("Enter the acquisition value independently of financing")
        self.acquisition_value.textChanged.connect(self._draft_changed)
        form.addRow("Acquisition value (USD)", self.acquisition_value)
        self.acquisition_date = QDateEdit(QDate.currentDate())
        self.acquisition_date.setDisplayFormat("yyyy-MM-dd")
        self.acquisition_date.setCalendarPopup(True)
        self.acquisition_date.dateChanged.connect(self._draft_changed)
        form.addRow("Acquisition date", self.acquisition_date)
        self.downpayment = QComboBox()
        self.downpayment.setAccessibleName("Actual bank downpayment")
        self.downpayment.currentIndexChanged.connect(self._draft_changed)
        form.addRow("Bank downpayment, if needed", self.downpayment)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        self.reason.textChanged.connect(self._draft_changed)
        form.addRow("Review note", self.reason)
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setPlaceholderText("Enter a fresh reason to withdraw this origination")
        self.correction_reason.textChanged.connect(self._update_saved_actions)
        form.addRow("Reason for withdrawal", self.correction_reason)
        layout.addLayout(form)
        limits = QLabel(
            "A value above the financing requires the exact bank downpayment. Trade-ins, financed extras, fees and other funding shapes need further review; no difference is filled automatically. The acquisition date is your explicit accounting decision, separately retained from the source activity date. Unknown prior openings and incomplete book positions remain qualified."
        )
        limits.setWordWrap(True)
        layout.addWidget(limits)
        self.effects = QLabel()
        self.effects.setWordWrap(True)
        self.effects.setTextFormat(Qt.PlainText)
        layout.addWidget(self.effects, 1)
        self.status = QLabel("Loading origination evidence…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.confirm = QPushButton("Review acquisition posting…")
        self.confirm.clicked.connect(self._confirm)
        actions.addWidget(self.confirm)
        self.original = QPushButton("View source evidence…")
        self.original.clicked.connect(self._open_source)
        actions.addWidget(self.original)
        self.withdraw = QPushButton("Withdraw origination…")
        self.withdraw.clicked.connect(self._withdraw)
        actions.addWidget(self.withdraw)
        actions.addStretch()
        layout.addLayout(actions)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh()

    def refresh(self):
        source = self._source

        def read(store, _cancelled):
            snapshot = store.origination_snapshot(source_sha256=source)
            accounts = tuple(account for account in store.financial_accounts() if account.product_type == "vehicle")
            return snapshot, accounts

        self.jobs.submit("snapshot", read)

    def _completed(self, key, result):
        if key == "snapshot":
            self.snapshot, accounts = result
            self._accounts = {account.id: account for account in accounts}
            self.rows = {row.row_id: row for row in self.snapshot.rows}
            current = self.source_row.currentData() or self._focus_row
            destination = self._preferred_destination or self.destination.currentData()
            self._rendering = True
            self.source_row.clear()
            for row in self.snapshot.rows:
                self.source_row.addItem(
                    f"{row.account_name or 'Unassigned loan'} · {row.activity_date} · financed {_money(row.principal_minor)}",
                    row.row_id,
                )
            self.source_row.setCurrentIndex(max(0, self.source_row.findData(current)))
            self.destination.clear()
            self.destination.addItem("Choose a vehicle or create one…", None)
            for account in accounts:
                self.destination.addItem(account.name, account.id)
            self.destination.setCurrentIndex(max(0, self.destination.findData(destination)))
            self.downpayment.clear()
            self.downpayment.addItem("No bank downpayment selected", None)
            for bank in self.snapshot.bank_movements:
                self.downpayment.addItem(
                    f"{bank.account_name} · {bank.posting_date} · {_money(-bank.amount_minor)}", bank.row_id
                )
            self._rendering = False
            self._source_selected()
        elif key == "preview":
            self.preview = result
            row = self.rows.get(self.source_row.currentData())
            amount = _typed_minor(self.acquisition_value.text())
            self.effects.setText(
                f"Vehicle acquisition {_money(amount)} · financed principal {_money(row.principal_minor)} · bank downpayment {_money(amount - row.principal_minor)}. The preview records only the explicitly supported funding and preserves each source's date. No interest expense is invented. Prior openings remain separately reviewed."
            )
            self.status.setText("Ready to review the acquisition posting. Nothing has been posted yet.")
            self.confirm.setEnabled(not self.jobs.pending)
        else:
            self.preview = None
            self.correction_reason.clear()
            self.status.setText(
                "Origination saved. Its acquisition and funding are retained separately from repayments and valuation estimates."
            )
            self.refresh()

    def _source_selected(self, *_args):
        row = self.rows.get(self.source_row.currentData())
        if row is not None:
            self.facts.setText(
                f"Source: amount financed {_money(row.principal_minor)} · observed activity date {row.activity_date}. This is new financing, not a repayment; absence of interest is retained."
            )
            self._rendering = True
            parsed = QDate.fromString(row.activity_date, Qt.ISODate)
            if parsed.isValid() and not self.acquisition_value.text():
                self.acquisition_date.setDate(parsed)
            self._rendering = False
            event = self._event()
            if event is not None:
                destination = self._accounts.get(event.destination_account_id)
                self._rendering = True
                self.destination.setCurrentIndex(max(0, self.destination.findData(event.destination_account_id)))
                self.acquisition_value.setText(_money(event.acquisition_value_minor))
                self.acquisition_date.setDate(
                    QDate(event.acquisition_date.year, event.acquisition_date.month, event.acquisition_date.day)
                )
                self.reason.setText(event.reason)
                self._rendering = False
                self.effects.setText(
                    f"Saved acquisition: {_money(event.acquisition_value_minor)} to {destination.name if destination else 'the retained vehicle account'} "
                    f"on {event.acquisition_date}. Financed principal {_money(event.principal_minor)}; "
                    f"bank downpayment {_money(event.acquisition_value_minor - event.principal_minor)}. "
                    "These are reviewed movements; prior openings remain separately qualified."
                )
        self._draft_changed()
        self._update_saved_actions()

    def _draft_changed(self, *_args):
        if self._rendering or self.jobs.writing:
            return
        self.jobs.cancel_reads()
        self.preview = None
        self.confirm.setEnabled(False)
        row = self.rows.get(self.source_row.currentData())
        if row is None or self.snapshot is None:
            self.status.setText("No supported origination evidence is available.")
            return
        if self._event() is not None:
            self.status.setText(
                "This origination already has a saved accounting event. Its source remains available for inspection."
            )
            return
        if self.destination.currentData() is None:
            self.status.setText(
                "Destination needed. Choose or create the vehicle; the imported evidence is already retained."
            )
            return
        try:
            value = _typed_minor(self.acquisition_value.text())
            if value <= 0:
                raise ValueError
        except ValueError:
            self.status.setText("Enter the vehicle's acquisition value before preparing the posting.")
            return
        if not self.reason.text().strip():
            self.status.setText("Enter a review note.")
            return
        row_id, destination = row.row_id, self.destination.currentData()
        acquired, bank = self.acquisition_date.date().toPython(), self.downpayment.currentData()
        preferences, basis, reason = (
            self.workspace.preferences(),
            self.snapshot.basis_sha256,
            self.reason.text().strip(),
        )
        self.jobs.submit(
            "preview",
            lambda store, _cancelled: store.preview_loan_origination(
                row_id,
                destination_account_id=destination,
                acquisition_value_minor=value,
                acquisition_date=acquired,
                bank_downpayment_row_id=bank,
                preferences=preferences,
                expected_basis_sha256=basis,
                reason=reason,
            ),
            delay=100,
        )
        self.status.setText("Checking the exact acquisition and funding…")

    def _event(self):
        row = self.rows.get(self.source_row.currentData())
        if row is None or self.snapshot is None:
            return None
        return next(
            (event for event in self.snapshot.events if event.event_id == row.event_id and event.status == "active"),
            None,
        )

    def _update_saved_actions(self, *_args):
        if not hasattr(self, "withdraw"):
            return
        active = self._event() is not None
        self.withdraw.setVisible(active)
        self.withdraw.setEnabled(bool(active and self.correction_reason.text().strip() and not self.jobs.pending))
        self.correction_reason.setEnabled(active and not self.jobs.writing)
        self.correction_reason.setVisible(active)
        self.form.labelForField(self.correction_reason).setVisible(active)
        self.confirm.setVisible(not active)
        for widget in (self.destination, self.acquisition_value, self.acquisition_date, self.downpayment, self.reason):
            widget.setEnabled(not self.jobs.writing and not active)

    def _withdraw(self):
        event = self._event()
        if event is None or not self.withdraw.isEnabled():
            return
        reason = self.correction_reason.text().strip()
        if (
            QMessageBox.question(
                self,
                "Withdraw loan origination",
                "Reverse this origination's exact saved acquisition and funding entries? Evidence, valuation points and history remain.\n\nReason: "
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

    def _create_vehicle(self):
        if self.jobs.writing:
            return
        dialog = V2TangibleAssets(self.workspace, self)
        try:
            dialog.exec()
            self._preferred_destination = dialog.selected_account_id
        finally:
            dialog.deleteLater()
        self.refresh()

    def _confirm(self):
        if self.preview is None or not self.confirm.isEnabled():
            return
        preview = self.preview
        preferences = preview.preferences
        if preferences != self.workspace.preferences():
            self.status.setText("Posting-date preferences changed. Inspect a fresh preview.")
            self._draft_changed()
            return
        if (
            QMessageBox.question(
                self,
                "Confirm loan origination",
                self.effects.text() + "\n\nPost this explicitly reviewed acquisition and financing?",
            )
            != QMessageBox.Yes
        ):
            return
        if preferences != self.workspace.preferences():
            self.status.setText("Preferences changed during confirmation. Inspect a fresh preview.")
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
        for widget in (
            self.source_row,
            self.destination,
            self.acquisition_value,
            self.acquisition_date,
            self.downpayment,
            self.reason,
            self.assumed_dates,
        ):
            widget.setEnabled(not self.jobs.writing)
        self.confirm.setEnabled(bool(not busy and self.preview is not None))
        self._update_saved_actions()

    def _failed(self, key, error):
        self.preview = None
        self.confirm.setEnabled(False)
        messages = {
            "origination_exact_downpayment_evidence_required": "Funding is incomplete. This review supports financing equal to acquisition value, or one exact bank downpayment for the difference. Fees, trade-ins and other funding differences remain pending.",
            "origination_vehicle_destination_required": "Choose a vehicle asset as the destination.",
            "origination_assumed_date_permission_required": "Allow the observed loan activity date as an assumed accounting date before posting. The source date is not a printed posting date.",
        }
        self.status.setText(messages.get(str(error), "This acquisition needs review before posting. " + str(error)))
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
