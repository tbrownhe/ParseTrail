"""Integrated grouped assignment keeps drafts local until explicit atomic Apply."""

from __future__ import annotations

import hashlib
import time
from threading import Event

import pytest
import shiboken6
from parsetrail.core.v2_batch_account_assignment import AccountAssignmentCancelled
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card
from parsetrail.gui import v2_batch_account_assignment as gui
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog
from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha

from .test_v2_batch_account_assignment import _variant
from .test_v2_inline_account_creation import _workspace


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(V2FinancialAccountDialog, "exec", lambda _self: QDialog.Rejected)
    monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
    yield app
    gui._finish_jobs()
    app.processEvents()


@pytest.fixture
def archive(tmp_path):
    original = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    workspace = _workspace(tmp_path, yamaha.DEFINITION, original)
    with V2ProfileStore.open(workspace.profile_path) as store:
        additional = tuple(_variant(store, original, str(index), empty=index == 1) for index in range(2))
    return workspace, original, additional


def _wait(app, predicate, message="batch worker did not finish"):
    deadline = time.monotonic() + 20
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate(), message


def _ready(app, dialog):
    _wait(app, lambda: not dialog.pending)
    assert dialog.plan is not None, dialog.status.text()


def _hash(workspace):
    return hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest()


def _seed(workspace, original):
    section = original.payload.accounts[0]
    account = FinancialAccount("known", "Owner Yamaha account", "liability", "yamaha")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(account)
        store.bind_source_account(
            original.source_sha256, section.source_identity, section.source_identity_form, account.id
        )
    return account


def test_async_prior_identity_proposal_review_then_explicit_apply(app, archive):
    workspace, original, additional = archive
    account = _seed(workspace, original)
    before = _hash(workspace)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        assert dialog.plan is None and dialog.pending
        dialog.show()
        _ready(app, dialog)
        group = dialog.plan.groups[0]
        assert group.suggested_account_id == account.id
        assert dialog.account_combo.currentData() == account.id
        assert dialog.documents.count() == 2
        assert "previously confirmed" in dialog.match_reason.text().lower()
        assert "2 account sections" in dialog.counts.text()
        assert _hash(workspace) == before
        dialog.review_button.click()
        assert dialog.pages.currentIndex() == 1
        assert dialog.summary_model.rowCount() == 1
        assert dialog.summary_model.data(dialog.summary_model.index(0, 2)) == account.name
        assert dialog.summary_model.data(dialog.summary_model.index(0, 3)) == "Use existing"
        assert _hash(workspace) == before
        dialog.apply_button.click()
        _wait(app, lambda: not dialog.pending)
        assert dialog.assignment_result.assigned_sections == 2
        assert dialog.assignment_result.created_accounts == 0 and dialog.changed
        assert "Saved 2" in dialog.status.text()
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert all(
                store.source_account_bindings(item.source_sha256)[0].ledger_account_id == account.id
                for item in additional
            )
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_new_account_modal_stages_without_writes_and_cancel_discards_everything(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    before = _hash(workspace)
    captured = []

    def accept(form):
        captured.append(form)
        assert form.source_identity.isReadOnly()
        assert form.source_identity.text() == "123456XXXXXX7890"
        assert form.institution.isReadOnly() and form.institution.text() == "yamaha"
        assert form.number.text() == ""
        assert _hash(workspace) == before
        form.name.setText("New staged Yamaha account")
        form.accept()
        return form.result()

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _wait(app, lambda: bool(dialog.new_accounts) and not dialog.pending)
        assert len(captured) == 1
        assert len(dialog.new_accounts) == len(dialog.choices) == 1
        assert "new, not saved" in dialog.account_combo.currentText()
        assert _hash(workspace) == before
        dialog.review_button.click()
        assert dialog.summary_model.data(dialog.summary_model.index(0, 3)) == "Create and assign"
        assert _hash(workspace) == before
        dialog.cancel_button.click()
        _wait(app, lambda: dialog._closed and not dialog.pending)
        assert _hash(workspace) == before
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.financial_accounts() == ()
            assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (0,)
    finally:
        dialog.close()


def test_staged_new_account_saves_with_all_selected_sections_on_apply(app, archive, monkeypatch):
    workspace, _original, _additional = archive

    def accept(form):
        form.name.setText("One new account for these documents")
        form.accept()
        return form.result()

    monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _wait(app, lambda: bool(dialog.new_accounts) and not dialog.pending)
        account = next(iter(dialog.new_accounts.values()))
        dialog.review_button.click()
        dialog.apply_button.click()
        _wait(app, lambda: not dialog.pending)
        assert (dialog.assignment_result.assigned_sections, dialog.assignment_result.created_accounts) == (3, 1)
        assert not dialog.has_unsaved_changes and not dialog.new_accounts
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.financial_accounts() == (account,)
            assert store.connection.execute(
                "SELECT count(*) FROM SourceAccountBindings WHERE ledger_account_id=?", (account.id,)
            ).fetchone() == (3,)
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_stale_refusal_then_reload_keeps_compatible_choice(app, archive):
    workspace, original, _additional = archive
    _seed(workspace, original)
    account = FinancialAccount("alternate", "Explicit alternative", "liability", "yamaha")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(account)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        group_id = dialog.plan.groups[0].group_id
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData(account.id))
        assert dialog.choices[group_id] == account.id
        dialog.review_button.click()
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.add_financial_account(FinancialAccount("unrelated", "Different account", "asset", "other"))
        before = _hash(workspace)
        dialog.apply_button.click()
        _wait(app, lambda: not dialog.pending)
        assert "changed" in dialog.status.text() and "Nothing was saved" in dialog.status.text()
        assert dialog.assignment_result is None and not dialog.changed
        assert _hash(workspace) == before
        dialog.refresh_button.click()
        _ready(app, dialog)
        assert dialog.choices[group_id] == account.id
        assert dialog.account_combo.currentData() == account.id
        assert dialog.pages.currentIndex() == 0
        assert _hash(workspace) == before
        dialog.review_button.click()
        dialog.apply_button.click()
        _wait(app, lambda: not dialog.pending)
        assert dialog.assignment_result.assigned_sections == 2
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_original_button_uses_the_selected_document_without_changing_scope(app, archive, monkeypatch):
    workspace, original, _additional = archive
    _seed(workspace, original)
    captured = []

    class Operation(QObject):
        status_changed = Signal(str)
        status = "Preparing original"

    operation = Operation()

    def opener(profile, source_id, parent):
        captured.append((profile, source_id, parent))
        return operation

    monkeypatch.setattr(gui, "open_original_document", opener)
    before = _hash(workspace)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        selected_choices = dict(dialog.choices)
        dialog.documents.setCurrentRow(1)
        expected_source = dialog._current().targets[1].source_sha256
        assert dialog.source_digest.text() == expected_source
        dialog.open_original_button.click()
        assert captured == [(workspace.profile_path, expected_source, dialog)]
        operation.status_changed.emit("Original opened")
        assert dialog.original_status.text() == "Original opened"
        assert dialog.choices == selected_choices and _hash(workspace) == before
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_cancel_active_planning_drains_worker_before_close_without_writes(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    started = Event()

    def slow_plan(_store, *, cancelled, **_kwargs):
        started.set()
        while not cancelled():
            time.sleep(0.005)
        raise AccountAssignmentCancelled("batch_assignment_cancelled")

    monkeypatch.setattr(gui, "plan_account_assignments", slow_plan)
    before = _hash(workspace)
    parent = QDialog()
    dialog = gui.V2BatchAccountAssignment(workspace, parent)
    try:
        parent.show()
        dialog.show()
        _wait(app, started.is_set)
        assert dialog.pending and dialog._job.isRunning()
        dialog.cancel_button.click()
        assert not dialog._closed
        _wait(app, lambda: dialog._closed and not dialog.pending)
        assert not gui._JOBS
        assert not dialog.changed and dialog.assignment_result is None
        assert _hash(workspace) == before
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)
        parent.close()


def test_cancel_mid_apply_rolls_back_inserted_assignment_before_closing(app, archive, monkeypatch):
    workspace, original, _additional = archive
    _seed(workspace, original)
    inserted = Event()
    apply = gui.apply_account_assignments

    def pause_after_first_insert(store, plan, choices, **kwargs):
        cancelled = kwargs["cancelled"]

        def pause():
            if store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone()[0] == 2:
                inserted.set()
                while not cancelled():
                    time.sleep(0.005)
            return cancelled()

        kwargs["cancelled"] = pause
        return apply(store, plan, choices, **kwargs)

    monkeypatch.setattr(gui, "apply_account_assignments", pause_after_first_insert)
    before = _hash(workspace)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        dialog.review_button.click()
        dialog.apply_button.click()
        _wait(app, inserted.is_set)
        assert dialog.pending
        dialog.cancel_button.click()
        _wait(app, lambda: dialog._closed and not dialog.pending)
        assert not dialog.changed and dialog.assignment_result is None
        assert not gui._JOBS
        assert _hash(workspace) == before
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (1,)
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_parent_destruction_cancels_apply_and_rolls_back_staged_account(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    inserted, release = Event(), Event()
    original_add = V2ProfileStore.add_financial_account

    def pause_after_account_insert(store, account):
        original_add(store, account)
        inserted.set()
        assert release.wait(10), "test did not release the staged insert"

    monkeypatch.setattr(V2ProfileStore, "add_financial_account", pause_after_account_insert)
    monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: pytest.fail("Forced parent destruction must not ask"))
    before = _hash(workspace)
    parent = QDialog()
    dialog = gui.V2BatchAccountAssignment(workspace, parent)
    try:
        parent.show()
        dialog.show()
        _ready(app, dialog)
        account = FinancialAccount("staged", "Unsaved staged account", "liability", "yamaha")
        dialog.new_accounts[account.id] = account
        dialog.choices[dialog.plan.groups[0].group_id] = account.id
        dialog._update_counts()
        dialog.review_button.click()
        dialog.apply_button.click()
        _wait(app, inserted.is_set)
        job = dialog._job
        assert job is not None and job.isRunning()
        shiboken6.delete(parent)
        assert not shiboken6.isValid(dialog)
        assert job.cancel_event.is_set()
        release.set()
        _wait(app, lambda: not gui._JOBS)
        assert job.result is None
        assert _hash(workspace) == before
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.financial_accounts() == ()
            assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (0,)
            assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    finally:
        release.set()
        if shiboken6.isValid(parent):
            shiboken6.delete(parent)
        _wait(app, lambda: not gui._JOBS)


@pytest.mark.parametrize("close_action", ["cancel", "escape", "window_close"])
def test_keep_working_default_preserves_explicit_skip_on_every_user_close_path(app, archive, monkeypatch, close_action):
    workspace, original, _additional = archive
    _seed(workspace, original)
    before = _hash(workspace)
    messages = []
    discard = False

    def confirm(message):
        messages.append(message.windowTitle())
        assert message.defaultButton().text() == "Keep working"
        assert message.escapeButton().text() == "Keep working"
        return gui.QMessageBox.Discard if discard else gui.QMessageBox.Cancel

    monkeypatch.setattr(gui.QMessageBox, "exec", confirm)
    dialog = gui.V2BatchAccountAssignment(workspace)

    def user_close():
        if close_action == "cancel":
            dialog.cancel_button.click()
        elif close_action == "escape":
            QTest.keyClick(dialog, Qt.Key_Escape)
        else:
            event = QCloseEvent()
            QApplication.sendEvent(dialog, event)
            assert event.isAccepted() == discard

    try:
        dialog.show()
        _ready(app, dialog)
        assert not dialog.has_unsaved_changes
        dialog.account_combo.setCurrentIndex(0)
        assert dialog.has_unsaved_changes and not dialog.choices
        choices, drafts = dict(dialog.choices), dict(dialog.new_accounts)
        user_close()
        assert len(messages) == 1 and not dialog._closed and dialog.isVisible()
        assert dialog.choices == choices and dialog.new_accounts == drafts
        assert dialog.has_unsaved_changes and _hash(workspace) == before
        discard = True
        user_close()
        assert len(messages) == 2 and dialog._closed
        assert not dialog.has_unsaved_changes and _hash(workspace) == before
    finally:
        discard = True
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_reverting_to_proposal_clears_dirty_and_skipping_survives_reload(app, archive, monkeypatch):
    workspace, original, _additional = archive
    known = _seed(workspace, original)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("alternative", "Other Yamaha", "liability", "yamaha"))
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        assert not dialog.has_unsaved_changes
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("alternative"))
        assert dialog.has_unsaved_changes
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData(known.id))
        assert not dialog.has_unsaved_changes
        dialog.account_combo.setCurrentIndex(0)
        assert dialog.has_unsaved_changes
        dialog.refresh_button.click()
        _ready(app, dialog)
        assert dialog.account_combo.currentData() is None and not dialog.choices
        assert dialog.has_unsaved_changes
        dialog.account_combo.setCurrentIndex(dialog.account_combo.findData(known.id))
        assert not dialog.has_unsaved_changes
        monkeypatch.setattr(
            gui.QMessageBox, "exec", lambda _self: pytest.fail("Reverted choices must close without asking")
        )
        dialog.cancel_button.click()
        assert dialog._closed
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_keep_working_retains_new_account_draft_before_review(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    before = _hash(workspace)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)

        def accept(form):
            form.name.setText("Draft kept while working")
            form.accept()
            return form.result()

        monkeypatch.setattr(V2FinancialAccountDialog, "exec", accept)
        dialog.new_account_button.click()
        account = next(iter(dialog.new_accounts.values()))
        choices = dict(dialog.choices)
        assert dialog.has_unsaved_changes and dialog.pages.currentIndex() == 0
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Cancel)
        assert not dialog.close()
        assert not dialog._closed and dialog.new_accounts == {account.id: account}
        assert dialog.choices == choices and dialog.account_combo.currentData() == account.id
        assert _hash(workspace) == before
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
        assert dialog.close() and _hash(workspace) == before
    finally:
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_successful_apply_consumes_saved_draft_but_unused_draft_still_needs_discard(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        selected = FinancialAccount("selected", "Saved draft", "liability", "yamaha")
        unused = FinancialAccount("unused", "Unused draft", "liability", "yamaha")
        dialog.new_accounts.update({selected.id: selected, unused.id: unused})
        dialog.choices[dialog.plan.groups[0].group_id] = selected.id
        dialog._update_counts()
        dialog.review_button.click()
        dialog.apply_button.click()
        _wait(app, lambda: not dialog.pending)
        assert dialog.assignment_result.created_accounts == 1
        assert not dialog.choices and dialog.new_accounts == {unused.id: unused}
        assert dialog.has_unsaved_changes
        saved_hash = _hash(workspace)
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Cancel)
        assert not dialog.close() and not dialog._closed
        assert dialog.new_accounts == {unused.id: unused}
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.financial_accounts() == (selected,)
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
        assert dialog.close() and _hash(workspace) == saved_hash
    finally:
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_application_shutdown_discards_without_interactive_question(app, archive, monkeypatch):
    workspace, original, _additional = archive
    _seed(workspace, original)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        dialog.account_combo.setCurrentIndex(0)
        assert dialog.has_unsaved_changes
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: pytest.fail("Application shutdown must not ask"))
        monkeypatch.setattr(gui, "_EXITING", False)
        gui._begin_shutdown()
        assert dialog.close() and dialog._closed
    finally:
        dialog.close()


@pytest.mark.parametrize("key", [Qt.Key_Escape, Qt.Key_Return])
def test_actual_discard_question_escape_and_default_enter_keep_working(app, archive, monkeypatch, key):
    workspace, original, _additional = archive
    _seed(workspace, original)
    dialog = gui.V2BatchAccountAssignment(workspace)
    try:
        dialog.show()
        _ready(app, dialog)
        dialog.account_combo.setCurrentIndex(0)
        assert dialog.has_unsaved_changes
        monkeypatch.setattr(gui.QMessageBox, "exec", QDialog.exec)

        def press_default():
            message = QApplication.activeModalWidget()
            assert isinstance(message, gui.QMessageBox)
            assert message.defaultButton().text() == "Keep working"
            QTest.keyClick(message, key)

        QTimer.singleShot(0, press_default)
        dialog.cancel_button.click()
        assert dialog.isVisible() and not dialog._closed and dialog.has_unsaved_changes
    finally:
        monkeypatch.setattr(gui.QMessageBox, "exec", lambda _self: gui.QMessageBox.Discard)
        dialog.close()
        _wait(app, lambda: not dialog.pending)


def test_new_account_context_uses_selected_second_document_without_another_store_read(app, archive, monkeypatch):
    workspace, _original, _additional = archive
    dialog = gui.V2BatchAccountAssignment(workspace)
    captured = []
    try:
        dialog.show()
        _ready(app, dialog)
        dialog.documents.setCurrentRow(1)
        target = dialog._current().targets[1]
        assert target.draft is not None
        assert target.source_sha256 != dialog._current().draft.source_sha256

        class ContextForm:
            def __init__(self, parent, *, draft, staged, profile):
                captured.append((parent, draft, staged, profile))

            def exec(self):
                return QDialog.Rejected

        monkeypatch.setattr(gui, "V2FinancialAccountDialog", ContextForm)
        monkeypatch.setattr(
            V2ProfileStore, "open", lambda *_args, **_kwargs: pytest.fail("Document context must use the verified plan")
        )
        dialog.new_account_button.click()
        assert len(captured) == 1
        parent, draft, staged, profile = captured[0]
        assert parent is dialog and staged and profile == workspace.profile_path
        assert draft.source_sha256 == target.source_sha256
        assert draft.period_start.iso == target.start.isoformat()
        assert draft.period_end.iso == target.end.isoformat()
        assert draft.source_locations
        assert not dialog.new_accounts and not dialog.has_unsaved_changes
    finally:
        dialog.close()
        _wait(app, lambda: not dialog.pending)
