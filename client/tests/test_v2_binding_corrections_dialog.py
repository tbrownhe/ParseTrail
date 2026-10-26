"""Reviewed binding correction changes source context without moving old books."""

from __future__ import annotations

import hashlib
import json
import sqlite3

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import BindingCorrectionTarget, FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace

from .test_v2_cash_activity_review import DEFINITION, SOURCE
from .test_v2_reviewed_openings import _profile as opening_profile
from .test_v2_source_overlap_dialog import _profile as overlap_profile
from .test_v2_transfers import _profile as transfer_profile


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected)
    return QApplication.instance() or QApplication([])


def _profile(profile, mode="source", *, posted=False):
    definition, source = DEFINITION, SOURCE
    if mode != "source":
        parsed = json.loads(DEFINITION)
        parsed["parser_id"] = "synthetic_accountless_binding_repair"
        parsed["header"].remove("Account")
        del parsed["columns"]["account"]
        parsed["account_key"] = "unknown"
        definition = json.dumps(parsed).encode()
        source = b"Date,Description,Amount,ReportedBalance\n10/01/2026,Coffee,-$4.00,$996.00\n10/02/2026,Deposit,$10.00,$1006.00\n"
    evidence = build_source_evidence(source, definition, suffix=".csv")
    row_ids = tuple(row.row_id for row in evidence.payload.rows)
    with V2ProfileStore.create(profile) as store:
        store.import_source(source, definition, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("a", "Checking A", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("b", "Checking B", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        if mode == "source":
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "a")
        elif mode == "file":
            store.assert_file_account(evidence.source_sha256, "a")
        else:
            store.assign_rows_account(evidence.source_sha256, row_ids, "a")
        key = (
            store.post_reviewed_cash_category(row_ids[0], "expense:food", reason="Reviewed original purchase")
            if posted
            else None
        )
    target = BindingCorrectionTarget(
        evidence.source_sha256,
        mode,
        source_identity="Checking A" if mode == "source" else None,
        source_identity_form="opaque" if mode == "source" else None,
        row_ids=(row_ids[0],) if mode == "rows" else (),
    )
    return evidence, target, key


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
def test_transfer_suggestion_history_alone_disables_ordinary_reassignment(tmp_path, app, mode):
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

    profile = tmp_path / "transfer-only-lock.db"
    evidence, _target, _key = _profile(profile, mode)
    incoming_source = (
        b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Savings C,Independent deposit,$4.00,$1004.00\n"
    )
    incoming = build_source_evidence(incoming_source, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("c", "Savings C", "asset", "synthetic"))
        store.import_source(incoming_source, DEFINITION, incoming, suffix=".csv")
        store.bind_source_account(incoming.source_sha256, "Savings C", "opaque", "c")
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        pair = next(pair for pair in snapshot.candidates if pair.outgoing.row_id == evidence.payload.rows[0].row_id)
        store.record_transfer_pair_review(
            pair.outgoing.row_id,
            pair.incoming.row_id,
            decision="dismiss",
            expected_basis_sha256=snapshot.basis_sha256,
            preferences=V2Preferences(),
            reason="These equal movements are not one owned transfer",
        )
        assert not store.journal_history_row_ids(evidence.source_sha256)
        assert not store.source_overlap_history_row_ids(evidence.source_sha256)
    if mode == "source":
        workspace = V2Workspace.open(
            profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
        )
        dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    else:
        dialog = V2AccountBindingReview(profile, evidence.source_sha256)
        dialog.table.selectRow(0)
    try:
        assert "transfer-suggestion review history" in dialog.lock_notice.text()
        if mode == "source":
            dialog.account_combo.setCurrentIndex(dialog.account_combo.findData("b"))
            assert not dialog.assign_button.isEnabled() and not dialog.clear_button.isEnabled()
            assert dialog.correction_button.isEnabled()
        elif mode == "file":
            assert not dialog.file_button.isEnabled() and not dialog.clear_file_button.isEnabled()
            assert dialog.correct_file_button.isEnabled()
        else:
            assert not dialog.assign_rows_button.isEnabled() and not dialog.clear_rows_button.isEnabled()
            assert dialog.correct_rows_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def _dialog(profile, target):
    from parsetrail.gui.v2_binding_correction import V2BindingCorrection

    return V2BindingCorrection(profile, target)


def _destination(dialog, account_id):
    dialog.destination.setCurrentIndex(1 if account_id is None else dialog.destination.findData(account_id))


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
def test_active_interpretation_blocks_then_withdrawal_allows_explicit_correction_without_moving_history(
    tmp_path, app, monkeypatch, mode
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "withdraw-then-correct.db"
    evidence, target, old_key = _profile(profile, mode, posted=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Original source belongs to the other checking account")
        assert not dialog.save_button.isEnabled()
        assert "Active source allocations remain" in dialog.blockers.text()
        with V2ProfileStore.open(profile) as store:
            snapshot = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
            store.withdraw_reviewed_interpretation(
                old_key,
                expected_basis_sha256=snapshot.basis_sha256,
                reason="Withdraw before changing the source account",
            )
            journals_before = store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key").fetchall()
        dialog.refresh()
        assert dialog.destination.currentData() == "b"
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert dialog.changed
        assert "recorded" in dialog.status.text()
        assert dialog.history_table.rowCount() == 1
        assert "Checking A" in dialog.history_table.item(0, 1).text()
        assert "Checking B" in dialog.history_table.item(0, 2).text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert (
                store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key").fetchall()
                == journals_before
            )
            assert store._active_consumed() == {}
            bindings = {binding.row_id: binding for binding in store.account_bindings(evidence.source_sha256)}
            assert bindings[evidence.payload.rows[0].row_id].ledger_account_id == "b"
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(profile, target)
    try:
        assert reopened.history_table.rowCount() == 1
        assert "Prior account IDs" in reopened.history_details.toPlainText()
    finally:
        reopened.close()
        app.processEvents()


def test_repeat_context_returns_pending_after_a_to_b_to_a_without_posting(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "repeat-context.db"
    evidence = overlap_profile(profile)[0]
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("b", "Checking B", "asset", "synthetic"))
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="repeat",
            retained_row_id=pair.left.row_id,
            expected_basis_sha256=pair.basis_sha256,
            reason="Originally confirmed same occurrence",
        )
    target = BindingCorrectionTarget(evidence.source_sha256, "source", "Checking A", "opaque")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        for destination in ("b", "checking"):
            _destination(dialog, destination)
            dialog.reason.setText("Explicitly corrected source identity after checking the original")
            assert len(dialog.snapshot.affected_review_pairs) == 1
            assert dialog.save_button.isEnabled()
            dialog.save_button.click()
        assert dialog.history_table.rowCount() == 2
        with V2ProfileStore.open(profile, read_only=True) as store:
            pair = store.source_overlap_inventory().candidates[0]
            assert pair.state == "pending" and pair.retained_row_id is None
            assert store._active_consumed() == {}
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
def test_cancel_clear_and_stale_confirmation_do_not_change_binding(tmp_path, app, monkeypatch, mode):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cancel-stale.db"
    evidence, target, _key = _profile(profile, mode)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, None)
        dialog.reason.setText("Considered clearing the selected scope")
        assert dialog.save_button.isEnabled()
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.save_button.click()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        _destination(dialog, "b")
        old_basis = dialog.snapshot.basis_sha256
        with V2ProfileStore.open(profile) as store:
            store.add_category_account("expense:concurrent", "Concurrent account context", "expense")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
        dialog.save_button.click()
        assert len(warnings) == 1 and "context changed" in warnings[0]
        assert dialog.snapshot.basis_sha256 != old_basis
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert not dialog.changed
    finally:
        dialog.close()
        app.processEvents()


def test_file_row_modes_require_explicit_clear_and_unassign_posts_no_money(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "modes.db"
    evidence, file_target, _key = _profile(profile, "file")
    row_target = BindingCorrectionTarget(evidence.source_sha256, "rows", row_ids=(evidence.payload.rows[0].row_id,))
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    blocked = _dialog(profile, row_target)
    try:
        _destination(blocked, "b")
        blocked.reason.setText("Cannot silently convert file mode to rows")
        assert "Clear the whole-file assertion" in blocked.blockers.text()
        assert not blocked.save_button.isEnabled()
    finally:
        blocked.close()
        app.processEvents()
    clearing = _dialog(profile, file_target)
    try:
        _destination(clearing, None)
        clearing.reason.setText("Clear whole-file scope before row-by-row review")
        clearing.save_button.click()
        assert clearing.changed
    finally:
        clearing.close()
        app.processEvents()
    rows = _dialog(profile, row_target)
    try:
        _destination(rows, "b")
        rows.reason.setText("One row belongs to a different account")
        assert rows.save_button.isEnabled()
        rows.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            bindings = store.account_bindings(evidence.source_sha256)
            assert [(binding.ledger_account_id, binding.basis) for binding in bindings] == [("b", "row"), (None, None)]
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        rows.close()
        app.processEvents()
    blocked_file = _dialog(profile, file_target)
    try:
        _destination(blocked_file, "a")
        blocked_file.reason.setText("Cannot silently convert rows to a whole-file assertion")
        assert "Clear individual row assignments" in blocked_file.blockers.text()
        assert not blocked_file.save_button.isEnabled()
    finally:
        blocked_file.close()
        app.processEvents()


@pytest.mark.parametrize("opening_minor", [0, 10_000])
def test_source_backed_opening_anchor_remains_blocking_even_without_active_row_allocations(
    tmp_path, app, opening_minor
):
    profile = tmp_path / "opening.db"
    evidence = opening_profile(profile, amount_minor=opening_minor)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("b", "Other account", "asset", "synthetic"))
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Reviewed opening anchor",
        )
        store.post_reviewed_opening("cash")
        assert store._active_consumed() == {}
    target = BindingCorrectionTarget(
        evidence.source_sha256, "source", section.source_identity, section.source_identity_form
    )
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("This needs the separate opening withdrawal workflow")
        assert "source-backed opening decision" in dialog.blockers.text()
        assert "Opening anchor accounts: Savings" in dialog.blockers.text()
        assert not dialog.save_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_transfer_consumption_blocks_until_whole_event_is_withdrawn(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "transfer.db"
    outgoing, incoming = transfer_profile(profile, bank_date="01/03/2026")
    with V2ProfileStore.open(profile) as store:
        event_id = store.post_reviewed_transfer(
            outgoing, incoming, preferences=V2Preferences(), reason="Originally confirmed whole event"
        )
        store.add_financial_account(FinancialAccount("b", "Other account", "asset", "synthetic"))
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
    target = BindingCorrectionTarget(source_id, "source", "Checking A", "opaque")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Correct after complete transfer withdrawal")
        assert not dialog.save_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            transfer_snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
            store.withdraw_reviewed_transfer(
                event_id, expected_basis_sha256=transfer_snapshot.basis_sha256, reason="Withdraw the whole event first"
            )
        dialog.refresh()
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            assert store.transfer_history()[0].status == "cancelled"
            assert store.account_bindings(source_id)[0].ledger_account_id == "b"
            assert store._active_consumed() == {}
    finally:
        dialog.close()
        app.processEvents()


def test_parent_entrypoints_keep_ordinary_history_locks_and_launch_explicit_scopes(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
    from parsetrail.gui.v2_binding_correction import V2BindingCorrection
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

    opened = []
    monkeypatch.setattr(V2BindingCorrection, "exec", lambda dialog: opened.append(dialog.target))
    for mode in ("source", "file", "rows"):
        profile = tmp_path / f"{mode}.db"
        evidence, target, _key = _profile(profile, mode, posted=True)
        if mode == "source":
            workspace = V2Workspace.open(
                profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
            )
            parent = V2SourceAccountReview(workspace, evidence.source_sha256)
        else:
            parent = V2AccountBindingReview(profile, evidence.source_sha256)
            parent.table.selectRow(0)
        try:
            if mode == "source":
                assert not parent.assign_button.isEnabled()
                assert parent.correction_button.isEnabled()
                parent.correction_button.click()
            elif mode == "file":
                assert not parent.clear_file_button.isEnabled()
                assert not parent.correct_rows_button.isEnabled()
                parent.correct_file_button.click()
            else:
                assert not parent.assign_rows_button.isEnabled()
                parent.correct_rows_button.click()
            assert opened[-1].mode == target.mode
            assert opened[-1].source_sha256 == target.source_sha256
        finally:
            parent.close()
            app.processEvents()


def test_failed_correction_snapshot_clears_cached_tables_and_disables_confirmation(tmp_path, app, monkeypatch):
    profile = tmp_path / "failure.db"
    _evidence, target, _key = _profile(profile)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Prepared review")
        assert dialog.save_button.isEnabled()

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("Synthetic correction snapshot failure")

        monkeypatch.setattr(V2ProfileStore, "binding_correction_snapshot", unavailable)
        dialog.refresh()
        assert dialog.snapshot is None
        assert dialog.rows_table.rowCount() == dialog.history_table.rowCount() == 0
        assert not dialog.save_button.isEnabled()
        assert "unavailable" in dialog.summary.text()
    finally:
        dialog.close()
        app.processEvents()


def test_empty_printed_section_retains_explicit_prior_and_new_account_context(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "empty-section.db"
    original = opening_profile(profile)
    source = b"synthetic empty printed bank section"
    section = original.payload.accounts[0].model_copy(update={"rows": ()})
    empty = original.model_copy(
        update={
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "payload": original.payload.model_copy(
                update={"accounts": (section,), "independent_balance_verified": False}
            ),
        }
    )
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("b", "Checking B", "asset", "synthetic"))
        definition = store.load_import(original.source_sha256).definition
        store.import_source(source, definition, empty, suffix=".pdf")
        store.bind_source_account(empty.source_sha256, section.source_identity, section.source_identity_form, "cash")
    target = BindingCorrectionTarget(
        empty.source_sha256, "source", section.source_identity, section.source_identity_form
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Correct the account represented by an empty printed period")
        assert dialog.rows_table.rowCount() == 0
        assert "Savings (1 assignment)" in dialog.summary.text()
        assert dialog.snapshot.current_account_ids == ("cash",)
        assert dialog.save_button.isEnabled()
        dialog.save_button.click()
        assert "Savings" in dialog.history_table.item(0, 1).text()
        assert "Checking B" in dialog.history_table.item(0, 2).text()
        with V2ProfileStore.open(profile, read_only=True) as store:
            record = store.binding_correction_history(empty.source_sha256)[0]
            assert record.prior_bindings == record.new_bindings == ()
            assert record.prior_account_ids == ("cash",) and record.new_account_ids == ("b",)
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()


def test_mixed_export_refuses_whole_file_correction_without_writes(tmp_path, app):
    profile = tmp_path / "mixed.db"
    original, _target, _key = _profile(profile, "rows")
    source = b"synthetic mixed identity export"
    first, second = original.payload.rows
    mixed = original.model_copy(
        update={
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "payload": original.payload.model_copy(
                update={
                    "rows": (
                        first.model_copy(
                            update={
                                "row_id": hashlib.sha256(source + b"first").hexdigest(),
                                "source_account": "Printed account",
                                "source_account_form": "opaque",
                            }
                        ),
                        second.model_copy(update={"row_id": hashlib.sha256(source + b"second").hexdigest()}),
                    )
                }
            ),
        }
    )
    with V2ProfileStore.open(profile) as store:
        definition = store.load_import(original.source_sha256).definition
        store.import_source(source, definition, mixed, suffix=".csv")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile, BindingCorrectionTarget(mixed.source_sha256, "file"))
    try:
        assert dialog.snapshot is None
        assert not dialog.save_button.isEnabled()
        assert "unavailable" in dialog.summary.text()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("mode", ["source", "file"])
def test_parent_read_failure_disables_ordinary_and_correction_controls(tmp_path, app, monkeypatch, mode):
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

    profile = tmp_path / "parent-failure.db"
    evidence, _target, _key = _profile(profile, mode)
    if mode == "source":
        workspace = V2Workspace.open(
            profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
        )
        dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    else:
        dialog = V2AccountBindingReview(profile, evidence.source_sha256)
        dialog.table.selectRow(0)
    try:

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("Synthetic source read failure")

        monkeypatch.setattr(V2ProfileStore, "load_import", unavailable)
        dialog._reload()
        assert "unavailable" in dialog.status.text()
        buttons = (
            (dialog.assign_button, dialog.clear_button, dialog.correction_button)
            if mode == "source"
            else (
                dialog.file_button,
                dialog.clear_file_button,
                dialog.assign_rows_button,
                dialog.clear_rows_button,
                dialog.correct_file_button,
                dialog.correct_rows_button,
            )
        )
        assert not any(button.isEnabled() for button in buttons)
    finally:
        dialog.close()
        app.processEvents()


@pytest.mark.parametrize("mode", ["source", "file", "rows"])
def test_parent_ordinary_controls_respect_correction_history_without_journal_history(tmp_path, app, mode):
    from parsetrail.gui.v2_account_binding_review import V2AccountBindingReview
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview

    profile = tmp_path / "ordinary-lock.db"
    evidence, target, _key = _profile(profile, mode)
    with V2ProfileStore.open(profile) as store:
        snapshot = store.binding_correction_snapshot(target, destination_account_id="b")
        store.correct_reviewed_binding(
            target,
            destination_account_id="b",
            expected_basis_sha256=snapshot.basis_sha256,
            reason="First explicit correction",
        )
        assert not store.journal_history_row_ids(evidence.source_sha256)
    if mode == "source":
        workspace = V2Workspace.open(
            profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
        )
        dialog = V2SourceAccountReview(workspace, evidence.source_sha256)
    else:
        dialog = V2AccountBindingReview(profile, evidence.source_sha256)
        dialog.table.selectRow(0)
    try:
        assert "account-correction history" in dialog.lock_notice.text()
        if mode == "source":
            assert not dialog.assign_button.isEnabled() and not dialog.clear_button.isEnabled()
            assert dialog.correction_button.isEnabled()
        elif mode == "file":
            assert not dialog.file_button.isEnabled() and not dialog.clear_file_button.isEnabled()
            assert dialog.correct_file_button.isEnabled()
        else:
            assert not dialog.assign_rows_button.isEnabled() and not dialog.clear_rows_button.isEnabled()
            assert dialog.correct_rows_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_connected_repeat_preview_lists_other_sources_with_readable_context(tmp_path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "connected-relationships.db"
    sources = overlap_profile(profile, variants=("original", "exported", "third"))
    root, supporting, third = (source.payload.rows[0].row_id for source in sources)
    with V2ProfileStore.open(profile) as store:
        store.add_financial_account(FinancialAccount("b", "Checking B", "asset", "synthetic"))
        for other in (supporting, third):
            pair = next(
                pair
                for pair in store.source_overlap_inventory().candidates
                if {pair.left.row_id, pair.right.row_id} == {root, other}
            )
            store.record_source_overlap_review(
                pair.left.row_id,
                pair.right.row_id,
                decision="repeat",
                retained_row_id=root,
                expected_basis_sha256=pair.basis_sha256,
                reason="Confirmed source occurrences in connected group",
            )
    target = BindingCorrectionTarget(sources[1].source_sha256, "source", "Checking A", "opaque")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Correct one supporting source's account context")
        assert len(dialog.snapshot.affected_row_ids) == 1
        assert dialog.affected_table.rowCount() == 2
        assert len(dialog.snapshot.affected_review_rows) == 3
        visible = " ".join(dialog.affected_table.item(row, column).text() for row in range(2) for column in range(7))
        assert all(
            label in visible
            for label in ("Coffee original", "Coffee exported", "Coffee third", "2026-10-01", "Synthetic checking")
        )
        assert "Source A:" in dialog.affected_details.toPlainText()
        dialog.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            remaining = next(
                pair
                for pair in store.source_overlap_inventory().candidates
                if {pair.left.row_id, pair.right.row_id} == {root, third}
            )
            assert remaining.state == "pending"
            assert store._active_consumed() == {}
    finally:
        dialog.close()
        app.processEvents()


def test_transfer_suggestion_invalidation_is_visible_and_cannot_reactivate_after_account_return(
    tmp_path, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "transfer-suggestions.db"
    outgoing, incoming = transfer_profile(profile, bank_date="01/03/2026")
    with V2ProfileStore.open(profile) as store:
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        dismissed = store.record_transfer_pair_review(
            outgoing,
            incoming,
            decision="dismiss",
            expected_basis_sha256=snapshot.basis_sha256,
            preferences=V2Preferences(),
            reason="Previously dismissed suggested pair",
        )
        store.add_financial_account(FinancialAccount("b", "Other checking", "asset", "synthetic"))
        source_id = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
    target = BindingCorrectionTarget(source_id, "source", "Checking A", "opaque")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    dialog = _dialog(profile, target)
    try:
        _destination(dialog, "b")
        dialog.reason.setText("Correct source context after inspecting the original")
        assert dialog.snapshot.affected_transfer_review_ids == (dismissed.revision_id,)
        assert dialog.affected_table.rowCount() == 1
        assert dialog.affected_table.item(0, 0).text() == "Transfer suggestion"
        assert "Previously dismissed suggested pair" in dialog.affected_details.toPlainText()
        assert "2026-01-03" in dialog.affected_table.item(0, 1).text()
        assert "2026-01-05" in dialog.affected_table.item(0, 4).text()
        dialog.save_button.click()
        assert "1 transfer" in dialog.history_table.item(0, 3).text()
        _destination(dialog, "checking")
        dialog.reason.setText("Explicitly return to the prior account context")
        dialog.save_button.click()
        with V2ProfileStore.open(profile, read_only=True) as store:
            refreshed = store.transfer_review_snapshot(preferences=V2Preferences())
            assert len(refreshed.candidates) == 1
            assert not next(
                review for review in refreshed.pair_reviews if review.revision_id == dismissed.revision_id
            ).context_current
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone()[0] == 0
    finally:
        dialog.close()
        app.processEvents()
