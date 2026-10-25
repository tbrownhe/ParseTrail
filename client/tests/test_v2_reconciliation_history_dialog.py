"""Only explicit successful current checks become retained reconciliation decisions."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import ReconciliationSnapshot, V2ProfileStore

from .test_v2_reconciliation_history import _add_ambiguous_source
from .test_v2_source_openings import _variant
from .test_v2_source_overlap import review as review_overlap
from .test_v2_statement_journal_comparison import _profile
from .test_v2_statement_reconciliation import _review_and_post


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _reviewed_profile(profile: Path):
    evidence = _profile(profile)
    with V2ProfileStore.open(profile) as store:
        _review_and_post(store, evidence)
    return evidence


def _dialog(profile: Path):
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog

    dialog = V2StatementCoverageDialog(profile)
    dialog.tabs.setCurrentIndex(3)
    dialog.reconciliation_table.selectRow(0)
    return dialog


def _cell(model, row: int, column: int):
    return model.data(model.index(row, column))


def test_cancel_successful_check_does_not_write(tmp_path: Path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cancel.db"
    _reviewed_profile(profile)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    questions = []

    def cancel(_parent, _title, message):
        questions.append(message)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", cancel)
    dialog = _dialog(profile)
    try:
        assert dialog.save_reconciliation_button.isEnabled()
        dialog.reconciliation_reason.setText("Inspected source")
        dialog.save_reconciliation_button.click()
        assert len(questions) == 1
        assert "through 2026-01-31" in questions[0]
        assert "Page capture and period coverage remain separate" in questions[0]
        assert dialog.reconciliation_history_model.rowCount() == 0
        assert dialog.reconciliation_reason.text() == "Inspected source"
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_save_reopen_stale_history_and_position_cutoffs(tmp_path: Path, app, monkeypatch):
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "saved.db"
    evidence = _reviewed_profile(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = _dialog(profile)
    try:
        dialog.show()
        app.processEvents()
        dialog.reconciliation_reason.setText("Inspected printed balances")
        dialog.save_reconciliation_button.click()
        assert "Saved reconciliation through 2026-01-31" in dialog.reconciliation_status.text()
        assert dialog.reconciliation_history_model.rowCount() == 1
        assert _cell(dialog.reconciliation_history_model, 0, 2) == "Current inputs"
        assert "Retained versions of 3 journal entry(s)" in dialog.reconciliation_history_details.text()
        assert "Source page capture incomplete" in dialog.reconciliation_history_details.text()
        assert dialog.reconciliation_history_table.viewport().height() > 100
        dialog.reconciliation_reason.setText("A second click must retain the original reason")
        dialog.save_reconciliation_button.click()
        assert dialog.reconciliation_history_model.rowCount() == 1
        assert _cell(dialog.reconciliation_history_model, 0, 4) == (
            "Confirmed statement reconciliation: Inspected printed balances"
        )
    finally:
        dialog.close()
        app.processEvents()
    dialog = _dialog(profile)
    try:
        assert dialog.reconciliation_history_model.rowCount() == 1
        assert "input version:" in dialog.reconciliation_history_details.text()
        assert "Matches current check inputs" in dialog.reconciliation_history_details.text()
    finally:
        dialog.close()
        app.processEvents()
    positions = V2ReviewedReportsDialog(profile)
    try:
        positions.tabs.setCurrentIndex(4)
        positions.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(positions.positions_model, 0, 6) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 8) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 9) == "2026-01-31"
        assert "Latest saved cutoff: 2026-01-31" in positions.position_details.text()
        positions.as_of.setDate(QDate(2026, 1, 30))
        assert _cell(positions.positions_model, 0, 8) == "None saved"
        assert _cell(positions.positions_model, 0, 9) == "None current"
    finally:
        positions.close()
        app.processEvents()
    with V2ProfileStore.open(profile) as store:
        original = f"review:cash:expense:{evidence.payload.accounts[0].rows[1].row_id}"
        store.correct_reviewed_cash_category(original, "expense:travel", reason="Correct reviewed category")
    positions = V2ReviewedReportsDialog(profile)
    try:
        positions.tabs.setCurrentIndex(4)
        positions.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(positions.positions_model, 0, 6) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 8) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 9) == "None current"
    finally:
        positions.close()
        app.processEvents()
    dialog = _dialog(profile)
    try:
        assert "Stale" in _cell(dialog.reconciliation_history_model, 0, 2)
        assert "retained as historical evidence" in dialog.reconciliation_history_details.text()
        dialog.save_reconciliation_button.click()
        assert dialog.reconciliation_history_model.rowCount() == 2
        assert _cell(dialog.reconciliation_history_model, 0, 2) == "Current inputs"
        assert "Stale" in _cell(dialog.reconciliation_history_model, 1, 2)
    finally:
        dialog.close()
        app.processEvents()


def test_stale_save_refuses_and_refreshes_current_check_then_failed_check_disables_save(
    tmp_path: Path, app, monkeypatch
):
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    evidence = _reviewed_profile(profile)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    dialog = _dialog(profile)
    try:
        first_version = dialog.reconciliation_model.rows[0].input_version
        with V2ProfileStore.open(profile) as store:
            store.add_category_account("expense:extra", "Extra", "expense")
        dialog.save_reconciliation_button.click()
        assert len(warnings) == 1
        assert "Inputs changed" in warnings[0]
        assert dialog.reconciliation_history_model.rowCount() == 0
        assert dialog.reconciliation_model.rows[0].input_version != first_version
        assert dialog.save_reconciliation_button.isEnabled()
        dialog.save_reconciliation_button.click()
        assert dialog.reconciliation_history_model.rowCount() == 1
        with V2ProfileStore.open(profile) as store:
            latest = store.statement_source_reviews("cash")[0]
            store.record_statement_source_review(
                "cash",
                evidence.source_sha256,
                expected_revision_id=latest.revision_id,
                opening_origin="reported",
                closing_origin="unestablished",
                timing_confirmed=True,
                posting_dates="reported",
                source_reference="Closing balance needs review",
            )
        dialog._refresh_reconciliation()
        assert not dialog.save_reconciliation_button.isEnabled()
        assert "Stale" in _cell(dialog.reconciliation_history_model, 0, 2)
        assert "Needs review" in _cell(dialog.reconciliation_model, 0, 2)
        dialog._save_reconciliation()
        assert dialog.reconciliation_history_model.rowCount() == 1
    finally:
        dialog.close()
        app.processEvents()
    positions = V2ReviewedReportsDialog(profile)
    try:
        positions.tabs.setCurrentIndex(4)
        positions.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(positions.positions_model, 0, 6) == "None passing"
        assert _cell(positions.positions_model, 0, 8) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 9) == "None current"
        assert "saved cutoff matching current inputs: none" in positions.position_details.text()
    finally:
        positions.close()
        app.processEvents()


def test_failed_live_check_and_failed_refresh_never_offer_save(tmp_path: Path, app, monkeypatch):
    profile = tmp_path / "pending.db"
    _profile(profile)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        assert not dialog.save_reconciliation_button.isEnabled()
        assert dialog.reconciliation_history_model.rowCount() == 0

        def unavailable(*_args, **_kwargs):
            raise sqlite3.OperationalError("synthetic history read failed")

        monkeypatch.setattr(V2ProfileStore, "reconciliation_snapshot", unavailable)
        dialog._refresh_reconciliation()
        assert dialog.reconciliation_model.rowCount() == 0
        assert dialog.reconciliation_history_model.rowCount() == 0
        assert not dialog.save_reconciliation_button.isEnabled()
        assert "Refresh failed" in dialog.reconciliation_status.text()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_unsupported_returned_codes_are_visible_and_never_certify_or_enable_save(tmp_path: Path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "unsupported.db"
    evidence = _reviewed_profile(profile)
    with V2ProfileStore.open(profile) as store:
        check = store.statement_reconciliation_checks()[0]
        decision = store.save_reconciliation_decision(
            "cash",
            evidence.source_sha256,
            expected_input_version=check.input_version,
            reason="Confirmed synthetic check",
        )
    # Defend the adapter as well as strict storage decoding: an unknown model code
    # must remain visibly unsupported even if its supplied success flag is true.
    unsupported_check = replace(
        check, exceptions=("unknown_balance_rule",), coverage_warnings=("unknown_capture_rule",)
    )
    unsupported_decision = replace(decision, check=unsupported_check)
    monkeypatch.setattr(
        V2ProfileStore,
        "reconciliation_snapshot",
        lambda _self: ReconciliationSnapshot((unsupported_check,), (unsupported_decision,)),
    )

    def must_not_confirm(*_args):
        raise AssertionError("Unsupported checks must not offer confirmation")

    monkeypatch.setattr(QMessageBox, "question", must_not_confirm)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        assert "Unsupported check result" == _cell(dialog.reconciliation_model, 0, 2)
        assert not dialog.save_reconciliation_button.isEnabled()
        assert _cell(dialog.reconciliation_history_model, 0, 2) == "Unsupported saved check"
        assert "Unsupported check code (unknown_capture_rule)" in dialog.reconciliation_history_details.text()
        assert "Unsupported check code (unknown_balance_rule)" in dialog.reconciliation_history_details.text()
        assert "Matches current check inputs" not in dialog.reconciliation_history_details.text()
        dialog._save_reconciliation()
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_real_overlap_warning_codes_remain_supported_and_repeats_are_not_allocations(tmp_path: Path, app):
    profile = tmp_path / "overlap.db"
    original = _profile(profile)
    repeated_source = b"synthetic repeated bank statement bytes for coverage UI"
    repeated = _variant(original, repeated_source)
    section = original.payload.accounts[0]
    with V2ProfileStore.open(profile) as store:
        saved = store.load_import(original.source_sha256)
        store.import_source(repeated_source, saved.definition, repeated, suffix=".pdf")
        store.bind_source_account(repeated.source_sha256, section.source_identity, section.source_identity_form, "cash")
    dialog = _dialog(profile)
    try:
        assert "Repeated activity across sources needs review" in _cell(dialog.reconciliation_model, 0, 6)
        assert "Unsupported" not in _cell(dialog.reconciliation_model, 0, 2)
        assert not dialog.save_reconciliation_button.isEnabled()
        with V2ProfileStore.open(profile) as store:
            for retained, supporting in zip(section.rows, repeated.payload.accounts[0].rows, strict=True):
                review_overlap(store, retained.row_id, supporting.row_id, retained=retained.row_id)
        dialog._refresh_reconciliation()
        supporting_index = next(
            index
            for index, row in enumerate(dialog.reconciliation_model.rows)
            if row.source_sha256 == repeated.source_sha256
        )
        dialog.reconciliation_table.selectRow(supporting_index)
        assert "Confirmed supporting repeats remain separate source evidence" in _cell(
            dialog.reconciliation_model, supporting_index, 6
        )
        assert "Unsupported" not in _cell(dialog.reconciliation_model, supporting_index, 2)
        assert "Source movements awaiting allocation" in dialog.reconciliation_details.text()
        assert not dialog.save_reconciliation_button.isEnabled()
    finally:
        dialog.close()
        app.processEvents()


def test_constructor_and_refresh_use_one_coherent_snapshot_despite_concurrent_change(tmp_path: Path, app, monkeypatch):
    profile = tmp_path / "snapshot.db"
    evidence = _reviewed_profile(profile)
    with V2ProfileStore.open(profile) as store:
        check = store.statement_reconciliation_checks()[0]
        store.save_reconciliation_decision(
            "cash", evidence.source_sha256, expected_input_version=check.input_version, reason="Confirmed before race"
        )
    original_snapshot = V2ProfileStore.reconciliation_snapshot
    calls = []

    def concurrent_change(store):
        snapshot = original_snapshot(store)
        calls.append(snapshot)
        if len(calls) == 1:
            # A writer commits immediately after the read, before the adapter uses
            # its result. Both displayed parts must still use that same read.
            with V2ProfileStore.open(profile) as writer:
                writer.add_category_account("expense:concurrent", "Concurrent change", "expense")
        return snapshot

    def independent_read_forbidden(*_args, **_kwargs):
        raise AssertionError("Coverage must read checks and saved history in one service snapshot")

    monkeypatch.setattr(V2ProfileStore, "reconciliation_snapshot", concurrent_change)
    monkeypatch.setattr(V2ProfileStore, "statement_reconciliation_checks", independent_read_forbidden)
    monkeypatch.setattr(V2ProfileStore, "reconciliation_history", independent_read_forbidden)
    dialog = _dialog(profile)
    try:
        assert len(calls) == 1
        assert dialog.reconciliation_model.rows[0].input_version == check.input_version
        assert _cell(dialog.reconciliation_history_model, 0, 2) == "Current inputs"
        assert (
            dialog.reconciliation_history_model.rows[0].input_version
            == dialog.reconciliation_model.rows[0].input_version
        )
        dialog._refresh_reconciliation()
        assert len(calls) == 2
        assert dialog.reconciliation_model.rows[0].input_version != check.input_version
        assert "Stale" in _cell(dialog.reconciliation_history_model, 0, 2)
    finally:
        dialog.close()
        app.processEvents()


def test_multiple_bound_sections_keep_history_visible_and_positions_qualified(tmp_path: Path, app):
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate

    profile = tmp_path / "multiple-sections.db"
    evidence = _reviewed_profile(profile)
    with V2ProfileStore.open(profile) as store:
        check = store.statement_reconciliation_checks()[0]
        store.save_reconciliation_decision(
            "cash",
            evidence.source_sha256,
            expected_input_version=check.input_version,
            reason="Before additional sections",
        )
        _add_ambiguous_source(store, evidence)
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        assert dialog.reconciliation_model.rowCount() == 0
        assert "multiple sections in a bound source" in dialog.reconciliation_status.text()
        assert not dialog.save_reconciliation_button.isEnabled()
        assert dialog.reconciliation_history_model.rowCount() == 1
        assert "Stale" in _cell(dialog.reconciliation_history_model, 0, 2)
        dialog._refresh_reconciliation()
        assert "multiple sections in a bound source" in dialog.reconciliation_status.text()
        assert dialog.reconciliation_history_model.rowCount() == 1
    finally:
        dialog.close()
        app.processEvents()
    positions = V2ReviewedReportsDialog(profile)
    try:
        positions.tabs.setCurrentIndex(4)
        positions.as_of.setDate(QDate(2026, 1, 31))
        assert _cell(positions.positions_model, 0, 6) == "Unavailable"
        assert _cell(positions.positions_model, 0, 8) == "2026-01-31"
        assert _cell(positions.positions_model, 0, 9) == "None current"
        assert "Live reconciliation unavailable" in positions.position_details.text()
    finally:
        positions.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
