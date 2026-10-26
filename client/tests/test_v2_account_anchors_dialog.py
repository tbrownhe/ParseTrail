"""Manual anchors and tracking reviews exercise real disposable V2 services."""

from __future__ import annotations

import hashlib
from datetime import date

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore

from .test_v2_opening_corrections_dialog import _dialog as source_dialog
from .test_v2_opening_corrections_dialog import _initial, _review
from .test_v2_source_openings import _variant


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    return QApplication.instance() or QApplication([])


def _profile(profile, *, kind="liability", scope="principal_component"):
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(
            FinancialAccount("loan", "Synthetic account", kind, "synthetic", tracking_scope=scope)
        )


def _dialog(profile):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors

    return V2AccountAnchors(profile, "loan")


def _opening_form(dialog, *, amount="1000.00", day="2025-12-31", reason="Reviewed missing opening information"):
    dialog.opening_amount.setText(amount)
    dialog.opening_date.setText(day)
    dialog.opening_reference.setText("Independent loan agreement / prior records")
    dialog.opening_reason.setText(reason)
    dialog.opening_ack.setChecked(True)


def _value_form(dialog, *, amount="0.00", day="2026-10-01"):
    dialog.value_amount.setText(amount)
    dialog.value_date.setText(day)
    dialog.value_reference.setText("Manual information after final statement unavailable")
    dialog.value_reason.setText("Reviewed observation; settlement history remains unknown")
    dialog.value_ack.setChecked(True)


def test_empty_accounts_show_no_action_and_preserve_profile(tmp_path, app):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors

    profile = tmp_path / "empty.db"
    with V2ProfileStore.create(profile):
        pass
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = V2AccountAnchors(profile)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.profile_path.isReadOnly()
        assert dialog.account.count() == 0 and dialog.snapshot is None
        assert not dialog.opening_save.isEnabled() and not dialog.opening_withdraw.isEnabled()
        assert not dialog.value_save.isEnabled() and not dialog.lifecycle_save.isEnabled()
        assert dialog.opening_history.rowCount() == dialog.value_history.rowCount() == 0
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize(
    "kind,scope,amount,expected",
    [
        ("liability", "principal_component", "1000.00", -100000),
        ("asset", "cash_component", "123.45", 12345),
        ("liability", "account_total", "0", 0),
    ],
)
def test_exact_manual_opening_direction_scope_confirmation_and_reopen(
    tmp_path, app, monkeypatch, kind, scope, amount, expected
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "manual.db"
    _profile(profile, kind=kind, scope=scope)
    dialog = _dialog(profile)
    questions = []

    def accept(_parent, _title, message):
        questions.append(message)
        return QMessageBox.Yes

    monkeypatch.setattr(QMessageBox, "question", accept)
    try:
        assert "unknown is not zero" in dialog.opening_state.text()
        assert scope.replace("_", " ") in dialog.scope.text()
        assert not dialog.opening_save.isEnabled()
        _opening_form(dialog, amount=amount)
        dialog.opening_ack.setChecked(False)
        assert not dialog.opening_save.isEnabled()
        dialog.opening_ack.setChecked(True)
        assert dialog.opening_save.isEnabled()
        dialog.opening_save.click()
        assert "opening equity" in questions[0] and "2025-12-31" in questions[0]
        assert scope.replace("_", " ") in questions[0]
        assert dialog.snapshot.opening.amount_minor == expected
        assert dialog.snapshot.opening.origin == "manual"
        assert dialog.opening_history.rowCount() == 1
        assert dialog.opening_amount.text() == ""
        dialog.opening_history.selectRow(0)
        assert "Origin: manual" in dialog.opening_details.toPlainText()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert (
                store.reviewed_category_summary(
                    kind="expense", start=date(2025, 1, 1), end=date(2026, 12, 31)
                ).total_minor
                == 0
            )
            assert (
                store.reviewed_category_summary(
                    kind="income", start=date(2025, 1, 1), end=date(2026, 12, 31)
                ).total_minor
                == 0
            )
            assert store._active_consumed() == {}
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(profile)
    try:
        assert reopened.snapshot.opening.amount_minor == expected
        assert reopened.snapshot.opening.cutoff_date == date(2025, 12, 31)
        assert reopened.snapshot.opening.tracking_scope == scope
        assert "Manual opening" in reopened.opening_state.text()
    finally:
        reopened.close()


def test_cancel_invalid_inputs_stale_form_and_failed_read_clear_actions(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    _profile(profile)
    first, stale = _dialog(profile), _dialog(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    try:
        _opening_form(first)
        first.opening_amount.setText("1.005")
        assert not first.opening_save.isEnabled()
        first.opening_amount.setText("1000.00")
        first.opening_date.setText("2026-02-30")
        assert not first.opening_save.isEnabled()
        first.opening_date.setText("2025-12-31")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        first.opening_save.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        _opening_form(stale, amount="2000.00")
        first.opening_save.click()
        stale.opening_save.click()
        assert warnings and "not recorded" in stale.status.text()
        assert stale.snapshot.opening.amount_minor == -100000
        assert not stale.opening_save.isEnabled()
        assert stale.opening_amount.text() == ""

        def unavailable(*_args, **_kwargs):
            raise ProfileFormatError("synthetic_snapshot_refusal")

        monkeypatch.setattr(V2ProfileStore, "account_anchor_snapshot", unavailable)
        stale.refresh()
        assert stale.snapshot is None
        assert stale.opening_history.rowCount() == 0
        assert stale.value_history.rowCount() == 0
        assert not stale.opening_withdraw.isEnabled()
        assert not stale.value_save.isEnabled()
        assert not stale.lifecycle_save.isEnabled()
        assert "unavailable" in stale.books.text()
        assert "unavailable" in stale.history_boundary_note.text()
        assert stale.history_boundary_note.toolTip() == ""
    finally:
        first.close()
        stale.close()
        app.processEvents()


def test_final_manual_zero_and_tracking_closure_leave_residual_books_and_history(tmp_path, app, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "final.db"
    _profile(profile)
    dialog = _dialog(profile)
    try:
        _opening_form(dialog)
        dialog.opening_save.click()
        original = dialog.snapshot
        with V2ProfileStore.open(profile, read_only=True) as store:
            journal_count = store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0]
        _value_form(dialog, amount="50.00", day="2026-09-01")
        dialog.value_save.click()
        _value_form(dialog)
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.value_save.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.value_save.click()
        assert dialog.snapshot.latest_dated_value.amount_minor == 0
        assert dialog.snapshot.position_debit_minor == original.position_debit_minor
        assert "$1,000.00" in dialog.books.text()
        assert dialog.value_history.rowCount() == 2
        dialog.value_history.sortItems(2, Qt.AscendingOrder)
        assert [dialog.value_history.item(index, 2).text() for index in range(2)] == ["$0.00", "$50.00"]
        zero = dialog.snapshot.latest_dated_value
        dialog.value_target.setCurrentIndex(dialog.value_target.findData(zero.value_id))
        assert dialog.value_amount.text() == "0.00"
        _value_form(dialog, amount="25.00")
        dialog.value_save.click()
        assert dialog.snapshot.latest_dated_value.amount_minor == -2500
        old = next(row for row in dialog.snapshot.dated_values if row.value_id == zero.value_id)
        assert old.superseded_by_value_id == dialog.snapshot.latest_dated_value.value_id
        assert dialog.value_target.findData(zero.value_id) == -1
        dialog.lifecycle_choice.setCurrentIndex(dialog.lifecycle_choice.findData("closed"))
        dialog.lifecycle_date.setText("2026-10-01")
        dialog.lifecycle_reason.setText("Stop tracking; final source statement unavailable")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.lifecycle_save.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.lifecycle_save.click()
        assert dialog.snapshot.lifecycle.state == "closed"
        assert dialog.snapshot.position_debit_minor == original.position_debit_minor
        assert "$1,000.00" in dialog.books.text()
        dialog.lifecycle_choice.setCurrentIndex(dialog.lifecycle_choice.findData("open"))
        dialog.lifecycle_date.setText("2026-10-02")
        dialog.lifecycle_reason.setText("Resume tracking to investigate residual")
        dialog.lifecycle_save.click()
        assert dialog.snapshot.lifecycle.state == "open" and dialog.lifecycle_history.rowCount() == 2
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == journal_count
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(profile)
    try:
        assert reopened.value_history.rowCount() == 3
        assert reopened.lifecycle_history.rowCount() == 2
        assert reopened.snapshot.position_debit_minor == original.position_debit_minor
    finally:
        reopened.close()


def test_dated_zero_does_not_supply_unknown_opening_and_duplicate_names_are_distinct(tmp_path, app):
    profile = tmp_path / "unknown.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(
            FinancialAccount(
                "other", "Synthetic account", "liability", "synthetic", tracking_scope="principal_component"
            )
        )
    dialog = _dialog(profile)
    try:
        assert dialog.account.itemText(0) != dialog.account.itemText(1)
        _value_form(dialog)
        dialog.value_save.click()
        assert dialog.snapshot.opening is None and dialog.snapshot.position_debit_minor is None
        assert dialog.snapshot.latest_dated_value.amount_minor == 0
        assert "unknown" in dialog.books.text()
        assert "unknown is not zero" in dialog.opening_state.text()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("amount", [0, 10000])
def test_source_opening_withdrawal_unknown_history_and_fresh_reestablishment(tmp_path, app, monkeypatch, amount):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "source.db"
    _initial(profile, amount_minor=amount)
    dialog = source_dialog(profile)
    try:
        dialog.correction_reason.setText("Withdraw independently of current source facts")
        assert dialog.withdraw.isEnabled()
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        dialog.withdraw.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.withdraw.click()
        assert dialog.decision.state == "withdrawn" and dialog.decision.amount_minor is None
        assert "unknown, not zero" in dialog.saved_label.text()
        assert dialog.history_model.rowCount() == 2
        assert dialog.history_model.data(dialog.history_model.index(0, 1)) == "Unknown (withdrawn)"
        assert not dialog.withdraw.isEnabled()
        dialog.correction_reason.setText("Fresh source review after explicit withdrawal")
        assert dialog.correct.isEnabled()
        dialog.correct.click()
        assert dialog.decision.state == "active" and dialog.decision.amount_minor == amount
        assert dialog.history_model.rowCount() == 3
    finally:
        dialog.close()
        app.processEvents()


def test_unavailable_source_basis_still_allows_withdrawal_and_stale_retry_refreshes(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "unavailable.db"
    evidence = _initial(profile)
    with V2ProfileStore.open(profile) as store:
        content = b"synthetic source with unknown period"
        unknown = _variant(evidence, content, unknown_start=True)
        store.import_source(content, store.load_import(evidence.source_sha256).definition, unknown, suffix=".pdf")
        section = unknown.payload.accounts[0]
        store.bind_source_account(unknown.source_sha256, section.source_identity, section.source_identity_form, "cash")
    first, stale = source_dialog(profile), source_dialog(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        assert first.candidate.printed_opening_minor is None
        assert first.decision.stale
        for dialog in (first, stale):
            dialog.correction_reason.setText("Withdraw old opening with no eligible current candidate")
            assert dialog.withdraw.isEnabled()
            assert not dialog.correct.isEnabled()
        first.withdraw.click()
        assert first.decision.state == "withdrawn"
        stale.correction_reason.setText("Different stale withdrawal reason")
        stale.withdraw.click()
        assert warnings and "not recorded" in stale.status.text()
        assert stale.decision.state == "withdrawn" and not stale.withdraw.isEnabled()
    finally:
        first.close()
        stale.close()
        app.processEvents()


def test_manual_source_switching_requires_confirmation_and_retains_origin_history(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "switch.db"
    evidence = _initial(profile)
    manual = V2AccountAnchors(profile, "cash")
    try:
        _opening_form(manual, amount="90.00")
        assert "Replace source" in manual.opening_save.text()
        manual.opening_save.click()
        assert manual.snapshot.opening.origin == "manual"
    finally:
        manual.close()
    with V2ProfileStore.open(profile) as store:
        _review(store, evidence, reference="Rechecked printed source before switching origin")
    source = source_dialog(profile)
    try:
        assert "independent manual review" in source.saved_label.text()
        source.correction_reason.setText("Replace independent manual fact with reviewed printed opening")
        assert source.correct.isEnabled()
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
        source.correct.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        source.correct.click()
        assert source.decision.origin == "source"
        assert [row.origin for row in source.history_model.rows] == ["source", "manual", "source"]
    finally:
        source.close()
        app.processEvents()


def test_manual_opening_correction_withdrawal_retry_does_not_hide_fresh_reestablishment(tmp_path, app):
    profile = tmp_path / "manual-history.db"
    _profile(profile)
    first = _dialog(profile)
    stale = None
    try:
        _opening_form(first)
        first.opening_save.click()
        _opening_form(
            first, amount="500.00", day="2025-12-30", reason="Correct independently reviewed opening information"
        )
        first.opening_save.click()
        assert first.snapshot.opening.amount_minor == -50000
        assert len(first.snapshot.opening_history) == 2
        first.opening_reason.setText("Explicit withdrawal before fresh review")
        stale = _dialog(profile)
        stale.opening_reason.setText("Explicit withdrawal before fresh review")
        first.opening_withdraw.click()
        assert first.snapshot.opening.state == "withdrawn"
        assert first.snapshot.position_debit_minor is None
        _opening_form(first, amount="250.00", reason="Fresh independent review after withdrawal")
        first.opening_save.click()
        assert first.snapshot.opening.amount_minor == -25000
        stale.opening_withdraw.click()
        assert stale.snapshot.opening.state == "active"
        assert stale.snapshot.opening.amount_minor == -25000
        assert "Manual opening" in stale.opening_state.text()
        assert "current state" in stale.status.text()
        assert len(stale.snapshot.opening_history) == 4
    finally:
        first.close()
        if stale:
            stale.close()
        app.processEvents()


def test_manual_opening_cannot_bypass_earlier_known_activity(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "earlier.db"
    _initial(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    dialog = V2AccountAnchors(profile, "cash")
    try:
        original = dialog.snapshot.opening
        _opening_form(dialog, amount="200.00", day="2026-06-01")
        dialog.opening_save.click()
        assert warnings and "not recorded" in dialog.status.text()
        assert dialog.snapshot.opening.version == original.version
        assert len(dialog.snapshot.opening_history) == 1
        assert dialog.opening_amount.text() == ""
        assert not dialog.opening_save.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_stale_value_and_tracking_decisions_reload_actual_history(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale-values.db"
    _profile(profile)
    first, stale = _dialog(profile), _dialog(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, text: warnings.append(text))
    try:
        _value_form(first, amount="20.00")
        _value_form(stale, amount="30.00")
        first.value_save.click()
        stale.value_save.click()
        assert warnings and stale.value_history.rowCount() == 1
        assert stale.snapshot.latest_dated_value.amount_minor == -2000
        assert not stale.value_save.isEnabled()
        first.refresh()
        for dialog in (first, stale):
            dialog.lifecycle_choice.setCurrentIndex(dialog.lifecycle_choice.findData("closed"))
            dialog.lifecycle_date.setText("2026-10-01")
            dialog.lifecycle_reason.setText("Stop tracking synthetic account")
        first.lifecycle_save.click()
        stale.lifecycle_reason.setText("Different stale reason")
        stale.lifecycle_save.click()
        assert len(warnings) == 2
        assert stale.snapshot.lifecycle.state == "closed"
        assert stale.lifecycle_history.rowCount() == 1
        assert not stale.lifecycle_save.isEnabled()
    finally:
        first.close()
        stale.close()
        app.processEvents()


def test_source_opening_failed_refresh_clears_withdrawal_context(tmp_path, app, monkeypatch):
    profile = tmp_path / "source-refused.db"
    _initial(profile)
    dialog = source_dialog(profile)
    try:
        dialog.correction_reason.setText("Loaded active opening")
        assert dialog.withdraw.isEnabled()

        def unavailable(*_args, **_kwargs):
            raise ProfileFormatError("synthetic_opening_read_refusal")

        monkeypatch.setattr(V2ProfileStore, "opening_review_snapshot", unavailable)
        dialog.refresh()
        assert dialog.decision is None and dialog.candidate is None
        assert dialog.history_model.rowCount() == 0
        assert "unavailable" in dialog.saved_label.text()
        assert not dialog.withdraw.isEnabled()
        assert not dialog.correct.isEnabled() and not dialog.confirm.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("same_phase_correction", [False, True])
def test_invalid_reopen_date_explains_order_and_preserves_history(tmp_path, app, monkeypatch, same_phase_correction):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "tracking-date.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        frame = store.account_anchor_snapshot("loan")
        closed = store.record_account_lifecycle(
            "loan",
            state="closed",
            effective_date=date(2026, 1, 31),
            reason="Stop tracking synthetic account",
            expected_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )
        if same_phase_correction:
            frame = store.account_anchor_snapshot("loan")
            store.record_account_lifecycle(
                "loan",
                state="open",
                effective_date=date(2026, 2, 1),
                reason="Resume tracking synthetic account",
                expected_version=closed.version,
                expected_basis_sha256=frame.basis_sha256,
            )
    dialog = _dialog(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        original = dialog.snapshot.lifecycle_history
        dialog.lifecycle_choice.setCurrentIndex(dialog.lifecycle_choice.findData("open"))
        dialog.lifecycle_date.setText("2026-01-01")
        dialog.lifecycle_reason.setText("Invalid earlier reopen date")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        assert dialog.lifecycle_save.isEnabled()
        dialog.lifecycle_save.click()
        assert warnings and "The effective date cannot precede the previous tracking phase" in warnings[0]
        assert "correct order" in warnings[0] and "could not be verified" not in warnings[0]
        assert "not recorded" in dialog.status.text()
        assert dialog.snapshot.lifecycle_history == original
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert not dialog.lifecycle_save.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("known_start", [False, True])
def test_empty_statement_history_boundary_is_not_activity_and_explains_cutoff(tmp_path, app, monkeypatch, known_start):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from PySide6.QtWidgets import QMessageBox

    from .test_v2_account_anchors import empty_statement
    from .test_v2_reviewed_openings import _profile as statement_profile

    profile = tmp_path / "boundary.db"
    original = statement_profile(profile)
    with V2ProfileStore.open(profile) as store:
        evidence = empty_statement(store, original, known_start=known_start)
        if known_start:
            _review(store, evidence)
            opening = store.post_reviewed_opening("cash")
            store.withdraw_reviewed_opening(
                "cash", expected_decision_version=opening.version, reason="Withdraw source opening"
            )
    dialog = V2AccountAnchors(profile, "cash")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    try:
        assert dialog.snapshot.earliest_known_activity_date is None
        assert "Earliest known activity: none known" in dialog.opening_state.text()
        boundary_day = "2026-01-01" if known_start else "2026-01-31"
        assert boundary_day in dialog.history_boundary_note.text()
        assert ("strictly before" if known_start else "on or before") in dialog.history_boundary_note.text()
        assert (
            "Known statement start" if known_start else "Known statement end (start unknown)"
        ) in dialog.history_boundary_note.text()
        assert evidence.source_sha256 in dialog.opening_details.toPlainText()
        _opening_form(dialog, amount="100.00", day="2026-01-31" if known_start else "2026-02-01")
        dialog.opening_save.click()
        assert warnings and "known account history" in warnings[0]
        assert dialog.snapshot.opening is None or dialog.snapshot.opening.state == "withdrawn"
        _opening_form(dialog, amount="100.00", day="2025-12-31" if known_start else "2026-01-31")
        dialog.opening_save.click()
        assert dialog.snapshot.opening.state == "active"
        assert not dialog.snapshot.opening.stale
    finally:
        dialog.close()
        app.processEvents()
