"""Profile-wide relationship resolution, separate from reviewing source activity."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parsetrail.gui.v2_evidence_preview import _money
from parsetrail.gui.v2_form_state import install_form_styles
from parsetrail.gui.v2_profile_jobs import ProfileJobs


def _qualified_date(value, provenance):
    return f"{value} ({provenance})" if provenance != "observed" else value


def _dates(item, *, compact=False):
    dates = item.source_dates or ((item.posting_date, item.date_provenance),)
    if compact and len(dates) > 1:
        provenance = dates[0][1] if len({part[1] for part in dates}) == 1 else "mixed date provenance"
        return _qualified_date(f"{dates[0][0]} – {dates[-1][0]}", provenance)
    return "; ".join(_qualified_date(value, provenance) for value, provenance in dates)


class V2TransferWorkspace(QWidget):
    changed = Signal()
    source_requested = Signal(str, str)
    manual_requested = Signal()

    def __init__(self, workspace, parent=None):
        super().__init__(parent)
        install_form_styles(self)
        self.workspace = workspace
        self.snapshot = None
        self._items = {}
        self._focus_row = ""
        self._rendering = False
        self._draft_identity = None
        self._manual_candidates = False
        self._account_names = {}
        self.jobs = ProfileJobs(self, workspace.profile_path)
        self.jobs.completed.connect(self._completed)
        self.jobs.failed.connect(self._failed)
        self.jobs.busy_changed.connect(self._busy)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Transfers")
        heading.setStyleSheet("font-size: 16px; font-weight: 600")
        layout.addWidget(heading)
        context = QLabel("All profile accounts · Resolve counterparts without reviewing the same money twice.")
        context.setWordWrap(True)
        layout.addWidget(context)
        toolbar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItem("Awaiting counterpart", "unmatched")
        self.filter.addItem("Matched", "matched")
        self.filter.addItem("All posted transfer activity", "all")
        self.filter.setAccessibleName("Transfer relationship status")
        self.filter.currentIndexChanged.connect(self._render)
        toolbar.addWidget(self.filter)
        self.counts = QLabel()
        toolbar.addWidget(self.counts, 1)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.refresh)
        toolbar.addWidget(reload_button)
        manual = QPushButton("Other transfer workflows…")
        manual.clicked.connect(self.manual_requested)
        toolbar.addWidget(manual)
        layout.addLayout(toolbar)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(("Account", "Date", "Amount", "Direction", "State"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for column in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        for column in (0, 4):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._selected)
        layout.addWidget(self.table, 1)
        self.saved_context = QLabel()
        self.saved_context.setTextFormat(Qt.PlainText)
        self.saved_context.setWordWrap(True)
        layout.addWidget(self.saved_context)
        form = self.form = QFormLayout()
        self.counterpart = QComboBox()
        self.counterpart.setAccessibleName("Counterpart to match")
        self.counterpart.setMinimumContentsLength(20)
        self.counterpart.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.counterpart.currentIndexChanged.connect(self._update_actions)
        form.addRow("Counterpart", self.counterpart)
        self.manual_candidates_button = QPushButton("Choose an unreviewed counterpart manually…")
        self.manual_candidates_button.clicked.connect(self._show_manual_candidates)
        form.addRow("", self.manual_candidates_button)
        self.reason = QLineEdit("Initial Review")
        self.reason.setMaxLength(500)
        self.reason.textChanged.connect(self._update_actions)
        form.addRow("Match note", self.reason)
        self.correction_reason = QLineEdit()
        self.correction_reason.setMaxLength(500)
        self.correction_reason.setPlaceholderText("Required only to withdraw a saved match or posting")
        self.correction_reason.textChanged.connect(self._update_actions)
        form.addRow("Reason for withdrawal", self.correction_reason)
        layout.addLayout(form)
        self.status = QLabel("Loading transfer relationships…")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.PlainText)
        layout.addWidget(self.status)
        actions = QHBoxLayout()
        self.match_button = QPushButton("Review match…")
        self.match_button.clicked.connect(self._match)
        actions.addWidget(self.match_button)
        self.source_button = QPushButton("Review source")
        self.source_button.clicked.connect(self._open_source)
        actions.addWidget(self.source_button)
        self.counterpart_source = QPushButton("Counterpart evidence")
        self.counterpart_source.clicked.connect(self._open_counterpart_source)
        actions.addWidget(self.counterpart_source)
        actions.addStretch()
        self.withdraw_button = QPushButton("Withdraw match…")
        self.withdraw_button.clicked.connect(self._withdraw_match)
        actions.addWidget(self.withdraw_button)
        self.withdraw_posting_button = QPushButton("Withdraw unmatched posting…")
        self.withdraw_posting_button.clicked.connect(self._withdraw_posting)
        actions.addWidget(self.withdraw_posting_button)
        self.corrections = QPushButton("Corrections…")
        self.corrections.setCheckable(True)
        self.corrections.toggled.connect(self._update_actions)
        actions.addWidget(self.corrections)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        if self.jobs.writing:
            return
        current = self._current()
        if current is not None and not self._focus_row:
            self._focus_row = current.row_ids[0]
        preferences = self.workspace.preferences()

        def read(store, _cancelled):
            return store.resolution_snapshot(preferences=preferences), {
                account.id: account.name for account in store.financial_accounts()
            }

        self.jobs.submit("snapshot", read)

    def focus_row(self, row_id):
        self._focus_row = row_id
        if self.snapshot is not None:
            target = next(
                (item for item in self.snapshot.items if row_id in item.row_ids and not item.id.startswith("row:")),
                None,
            )
            current_filter = self.filter.currentData()
            if target is not None and current_filter not in {"all", target.status}:
                self.filter.setCurrentIndex(max(0, self.filter.findData(target.status)))
            self._render()
            # Navigation may already have started a fresh snapshot. Rendering
            # the retained state must not consume that read's return target.
            if self.jobs.pending:
                self._focus_row = row_id

    def shutdown(self):
        return self.jobs.close()

    def _completed(self, key, result):
        if key == "snapshot":
            self.snapshot, self._account_names = result
            self._items = {item.id: item for item in self.snapshot.items}
            self._render()
        else:
            self.correction_reason.clear()
            self.reason.setText("Initial Review")
            self.status.setText("Saved. Existing source amounts and dates are retained.")
            self.refresh()
            self.changed.emit()

    def _render(self, *_args):
        if self.snapshot is None:
            return
        previous = self._current()
        previous_id = previous.id if previous is not None else None
        previous_choice = self.counterpart.currentData()
        previous_correction = self.correction_reason.text()
        previous_identity = self._draft_identity
        self._rendering = True
        self.table.blockSignals(True)
        selected_status = self.filter.currentData()
        self._visible = tuple(
            item
            for item in self.snapshot.items
            if not item.id.startswith("row:") and (selected_status == "all" or item.status == selected_status)
        )
        self.table.setRowCount(len(self._visible))
        for index, item in enumerate(self._visible):
            state = {
                "unmatched": "Posted · counterpart unresolved",
                "matched": "Posted · matched",
                "withdrawn": "Withdrawn",
            }.get(item.status, item.status)
            for column, text in enumerate(
                (item.account_name, _dates(item, compact=True), _money(item.gross_minor), item.direction.title(), state)
            ):
                cell = QTableWidgetItem(str(text))
                cell.setToolTip(str(text))
                if column == 1:
                    cell.setToolTip(_dates(item))
                if column == 2:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, column, cell)
        self.table.blockSignals(False)
        unmatched = sum(item.status == "unmatched" and not item.id.startswith("row:") for item in self.snapshot.items)
        self.counts.setText(f"{unmatched} posted sides awaiting resolution")
        target = next((i for i, item in enumerate(self._visible) if self._focus_row in item.row_ids), 0)
        if self._visible:
            self.table.selectRow(target)
        self._focus_row = ""
        self._rendering = False
        self._selected()
        current = self._current()
        if current is not None and current.id == previous_id:
            choice = self.counterpart.findData(previous_choice)
            if choice >= 0:
                self.counterpart.setCurrentIndex(choice)
            if previous_identity == self._draft_identity:
                self.correction_reason.setText(previous_correction)

    def _current(self):
        index = self.table.currentRow()
        visible = getattr(self, "_visible", ())
        return visible[index] if 0 <= index < len(visible) else None

    def _link(self, item):
        if item is None or self.snapshot is None:
            return None
        return next(
            (
                link
                for link in self.snapshot.links
                if getattr(link, "status", "active") == "active" and item.id in (link.outgoing_id, link.incoming_id)
            ),
            None,
        )

    def _selected(self):
        if self._rendering:
            return
        item = self._current()
        self.counterpart.blockSignals(True)
        self.counterpart.clear()
        self.counterpart.addItem("Choose a counterpart when evidence is available", None)
        self._candidates = {}
        if item is not None:
            for candidate in self.snapshot.candidates:
                if item.id not in (candidate.outgoing_id, candidate.incoming_id):
                    continue
                if not candidate.automatic and not self._manual_candidates:
                    continue
                other_id = candidate.incoming_id if item.id == candidate.outgoing_id else candidate.outgoing_id
                other = self._items.get(other_id)
                text = (
                    f"{other.account_name} · {_dates(other, compact=True)} · {_money(other.gross_minor)}"
                    if other is not None
                    else "Unposted source transaction"
                )
                if other_id.startswith("row:"):
                    text += " · unreviewed source, manual selection"
                if not candidate.posting_allowed:
                    text += " · date permission required"
                self._candidates[other_id] = candidate
                self.counterpart.addItem(text, other_id)
            self.saved_context.setText(f"{item.account_name} · saved note: {item.reason}")
            if item.kind == "origination":
                destination = self._account_names.get(item.expected_destination_account_id, "Not established")
                self.saved_context.setText(
                    f"Loan financing · {_money(item.gross_minor)} · Expected destination: {destination}. "
                    "Receipt remains unresolved. Full acquisition cost is unknown. Saved note: " + item.reason
                )
            link = self._link(item)
            if link is not None:
                other = self._items.get(link.incoming_id if item.id == link.outgoing_id else link.outgoing_id)
                if other is not None:
                    self.saved_context.setText(
                        f"Matched: {item.account_name} ({_dates(item)}) ↔ {other.account_name} ({_dates(other)}) "
                        f"· {_money(item.gross_minor)}. Saved match note: {link.reason}"
                    )
        else:
            self.saved_context.clear()
        self.counterpart.blockSignals(False)
        self.correction_reason.clear()
        link = self._link(item)
        self._draft_identity = (item.id, item.version, link.version if link is not None else None) if item else None
        self._update_actions()

    def _show_manual_candidates(self):
        self._manual_candidates = not self._manual_candidates
        self.manual_candidates_button.setText(
            "Hide unreviewed alternatives" if self._manual_candidates else "Choose an unreviewed counterpart manually…"
        )
        self._selected()

    def _update_actions(self, *_args):
        if not hasattr(self, "match_button"):
            return
        item = self._current()
        candidate = getattr(self, "_candidates", {}).get(self.counterpart.currentData())
        usable = item is not None and not self.jobs.pending
        self.source_button.setEnabled(usable)
        self.counterpart_source.setEnabled(bool(usable and self._other_item() is not None))
        self.match_button.setEnabled(
            bool(
                usable
                and item.status == "unmatched"
                and candidate
                and candidate.posting_allowed
                and self.reason.text().strip()
            )
        )
        self.counterpart.setEnabled(bool(usable and item.status == "unmatched"))
        self.manual_candidates_button.setEnabled(bool(usable and item.status == "unmatched"))
        self.withdraw_button.setEnabled(bool(usable and self._link(item) and self.correction_reason.text().strip()))
        self.withdraw_posting_button.setEnabled(
            bool(
                usable
                and item.status == "unmatched"
                and item.kind not in {"loan", "origination"}
                and self.correction_reason.text().strip()
            )
        )
        correcting = self.corrections.isChecked()
        self.correction_reason.setVisible(correcting)
        self.form.labelForField(self.correction_reason).setVisible(correcting)
        self.withdraw_button.setVisible(correcting)
        self.withdraw_posting_button.setVisible(
            correcting and item is not None and item.kind not in {"loan", "origination"}
        )
        if self.jobs.pending:
            self.status.setText("Saving confirmed changes…" if self.jobs.writing else "Loading transfer relationships…")
        elif item is None:
            self.status.setText("No transfers in this view. Review statement payments and mark transfers there first.")
        elif item.status == "unmatched" and self.counterpart.count() == 1:
            self.status.setText(
                "Posted · counterpart unresolved. Import the other statement when available and review its transfer. Amounts remain visible until an explicit match is confirmed."
            )
        elif item.status == "unmatched" and candidate is None:
            self.status.setText(
                "Choose a counterpart to inspect the match. Equal amounts alone do not confirm ownership or a relationship."
            )
        elif candidate is not None and not candidate.posting_allowed:
            self.status.setText("This match needs an accounting-date decision. Review its source before matching.")
        elif candidate is not None and not self.reason.text().strip():
            self.status.setText("Enter a match note before reviewing the confirmation.")
        elif item.status == "matched":
            self.status.setText(
                "Matched. Withdrawing a match removes its relationship; the posted sides remain until explicitly withdrawn."
            )
        else:
            self.status.setText("Review the two sides before confirming their relationship.")

    def _match(self):
        if not self.match_button.isEnabled():
            return
        item = self._current()
        candidate = self._candidates[self.counterpart.currentData()]
        basis, preferences, reason = (
            self.snapshot.basis_sha256,
            self.workspace.preferences(),
            self.reason.text().strip(),
        )
        sides = (self._items[candidate.outgoing_id], self._items[candidate.incoming_id])
        lines = [f"Match {_money(item.gross_minor)} between these two source sides?", ""]
        for side in sides:
            state = "Unreviewed source · not posted" if side.id.startswith("row:") else "Already posted"
            lines.append(
                f"{side.account_name} · {_dates(side)} · {_money(side.gross_minor)} · {side.direction} · {state}"
            )
        unposted = tuple(side for side in sides if side.id.startswith("row:"))
        lines.append("")
        if not unposted:
            lines.append(
                "No new financial entries. Link the two existing posted sides; retain their original dates and amounts."
            )
        else:
            for side in unposted:
                lines.append(
                    f"Post {_money(side.gross_minor)} {side.direction} in {side.account_name} on {_dates(side)}, with the opposite clearing movement."
                )
            lines.append(
                "Keep existing lender principal, interest and other posted account effects unchanged, then link the two sides."
            )
        lines.extend(("", f"Match note: {reason}"))
        text = "\n".join(lines)
        if not candidate.automatic:
            text += "\n\nManual selection: confirm this unreviewed source is the other side of your owned transfer. Amount equality alone does not establish that relationship."
        if QMessageBox.question(self, "Confirm transfer match", text) != QMessageBox.Yes:
            return
        if preferences != self.workspace.preferences():
            self.status.setText("Preferences changed during confirmation. Reload before matching.")
            self.refresh()
            return
        outgoing, incoming = candidate.outgoing_id, candidate.incoming_id
        self.jobs.submit(
            "match",
            lambda store, _cancelled: store.resolve_transfer(
                outgoing, incoming, preferences=preferences, expected_basis_sha256=basis, reason=reason
            ),
            write=True,
        )

    def _open_source(self):
        item = self._current()
        if item is not None:
            self.source_requested.emit(item.source_sha256, item.row_ids[0])

    def _other_item(self):
        item = self._current()
        if item is None:
            return None
        link = self._link(item)
        if link is not None:
            return self._items.get(link.incoming_id if item.id == link.outgoing_id else link.outgoing_id)
        return self._items.get(self.counterpart.currentData())

    def _open_counterpart_source(self):
        other = self._other_item()
        if other is not None:
            self.source_requested.emit(other.source_sha256, other.row_ids[0])

    def _withdraw_match(self):
        item = self._current()
        link = self._link(item)
        if link is None or not self.withdraw_button.isEnabled():
            return
        reason = self.correction_reason.text().strip()
        if (
            QMessageBox.question(
                self,
                "Withdraw transfer match",
                "Remove this saved relationship? Both posted source sides remain.\n\nReason: " + reason,
            )
            != QMessageBox.Yes
        ):
            return
        link_id, version = link.link_id, link.version
        self.jobs.submit(
            "withdraw_match",
            lambda store, _cancelled: store.withdraw_transfer_resolution(
                link_id, expected_version=version, reason=reason
            ),
            write=True,
        )

    def _withdraw_posting(self):
        item = self._current()
        if item is None or not self.withdraw_posting_button.isEnabled():
            return
        reason = self.correction_reason.text().strip()
        if (
            QMessageBox.question(
                self,
                "Withdraw unmatched posting",
                "Reverse this unmatched source side? Its evidence and history remain.\n\nReason: " + reason,
            )
            != QMessageBox.Yes
        ):
            return
        event_id, version, kind = item.id, item.version, item.kind
        if kind in {"loan", "origination"}:
            self.status.setText("Review the source to withdraw its whole loan posting.")
            return
        self.jobs.submit(
            "withdraw_posting",
            lambda store, _cancelled: store.withdraw_unresolved_transfer(
                event_id, expected_version=version, reason=reason
            ),
            write=True,
        )

    def _busy(self, _busy):
        self._update_actions()

    def _failed(self, _key, error):
        self.match_button.setEnabled(False)
        self.withdraw_button.setEnabled(False)
        self.withdraw_posting_button.setEnabled(False)
        self.status.setText(
            "The operation could not be confirmed. Saved work is retained; reload and inspect current relationships. "
            + str(error)
        )
