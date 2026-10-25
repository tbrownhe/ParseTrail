"""A matching movement needs reviewed endpoints and exact ledger positions."""

from __future__ import annotations

from pathlib import Path

from parsetrail.core.v2_profile_store import V2ProfileStore

from .test_v2_statement_journal_comparison import _profile
from .test_v2_statement_source_review import _later_source


def _review_and_post(store: V2ProfileStore, evidence) -> None:
    store.record_statement_source_review(
        "cash",
        evidence.source_sha256,
        expected_revision_id=None,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference="Synthetic printed summary and dates",
    )
    store.post_reviewed_opening("cash")
    interest, withdrawal = evidence.payload.accounts[0].rows
    store.post_reviewed_cash_category(interest.row_id, "income:interest", reason="Reviewed interest")
    store.post_reviewed_cash_category(withdrawal.row_id, "expense:other", reason="Reviewed withdrawal")


def test_reconciliation_needs_positions_provenance_and_allocation(tmp_path: Path):
    path = tmp_path / "reconciliation.db"
    evidence = _profile(path, capture_verified=True)
    with V2ProfileStore.open(path) as store:
        pending = store.statement_reconciliation_checks()[0]
        assert not pending.reconciled
        assert "unallocated_source_movements" in pending.exceptions
        assert "source_endpoints_not_reviewed" in pending.exceptions
        assert "opening_position_unverified_or_stale" in pending.exceptions
        _review_and_post(store, evidence)
        checked = store.statement_reconciliation_checks()[0]
        assert checked.reconciled and checked.exceptions == (), checked.exceptions
        assert checked.printed_opening_minor == checked.journal_opening_minor == 10_000
        assert checked.printed_closing_minor == checked.journal_closing_minor == 9_000
        assert checked.source_difference_minor == 0
        assert checked.posted_interpretations_reviewed
        assert checked.input_version != pending.input_version
        original = f"review:cash:expense:{evidence.payload.accounts[0].rows[1].row_id}"
        store.correct_reviewed_cash_category(original, "expense:travel", reason="Reviewed correction")
        corrected = store.statement_reconciliation_checks()[0]
        assert corrected.reconciled and corrected.input_version != checked.input_version
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.statement_reconciliation_checks()[0] == corrected


def test_later_statement_needs_its_own_source_review_but_not_new_opening(tmp_path: Path):
    path = tmp_path / "later-reconciliation.db"
    evidence = _profile(path, capture_verified=True)
    with V2ProfileStore.open(path) as store:
        _review_and_post(store, evidence)
        later = _later_source(store, evidence)
        checks = {item.source_sha256: item for item in store.statement_reconciliation_checks()}
        assert checks[evidence.source_sha256].reconciled
        assert not checks[later.source_sha256].reconciled
        assert "source_endpoints_not_reviewed" in checks[later.source_sha256].exceptions
        assert "opening_position_unverified_or_stale" not in checks[later.source_sha256].exceptions
        before_review_version = checks[later.source_sha256].input_version
        store.record_statement_source_review(
            "cash",
            later.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Later synthetic statement",
        )
        later_check = next(
            item for item in store.statement_reconciliation_checks() if item.source_sha256 == later.source_sha256
        )
        assert later_check.reconciled and later_check.exceptions == ()
        assert later_check.input_version != before_review_version
        assert later_check.printed_opening_minor == later_check.printed_closing_minor == 9_000
        assert later_check.journal_opening_minor == later_check.journal_closing_minor == 9_000


def test_coverage_dialog_shows_reconciliation_blockers_and_exact_positions(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "reconciliation-ui.db"
    _profile(path)
    dialog = V2StatementCoverageDialog(path)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.reconciliation_model.rowCount() == 1
        assert "Needs review" in dialog.reconciliation_model.data(dialog.reconciliation_model.index(0, 2))
        dialog.reconciliation_table.selectRow(0)
        app.processEvents()
        assert "Printed opening $100.00; journal opening $0.00" in dialog.reconciliation_details.text()
        assert "Source page capture incomplete" in dialog.reconciliation_details.text()
        assert "Opening decision missing or stale" in dialog.reconciliation_details.text()
    finally:
        dialog.close()
        app.processEvents()
