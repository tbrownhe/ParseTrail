"""Specialized workers preserve scope, explicit confirmation and useful Qt space."""

from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from PySide6.QtCore import QDate, Qt, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from .test_v2_cash_movement import _profile as cash_profile
from .test_v2_loan_payments import _profile as loan_profile
from .test_v2_settlements import profile as settlement_profile
from .test_v2_statement_journal_comparison import _profile as coverage_profile
from .v2_job_wait import wait_for_jobs


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    font_path = Path("C:/Windows/Fonts/segoeui.ttf")
    if font_path.exists():
        assert QFontDatabase.addApplicationFont(str(font_path)) >= 0
    previous = app.font()
    app.setFont(QFont("Segoe UI", 9))
    monkeypatch.setattr(QMessageBox, "question", lambda *_: QMessageBox.Yes)
    yield app
    app.setFont(previous)


def workspace(path):
    return V2Workspace.open(
        path,
        path.parent / f"{path.stem}-catalog",
        trusted_keys={},
        preferences_path=path.parent / f"{path.stem}-preferences.json",
    )


def until(predicate, app):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert predicate()


@pytest.mark.parametrize("kind", ["loan", "settlement", "coverage"])
def test_shell_and_close_remain_responsive_during_snapshot(tmp_path, app, monkeypatch, kind):
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
    from parsetrail.gui.v2_settlement_review import V2SettlementReview
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog

    path = tmp_path / "shell.db"
    with V2ProfileStore.create(path):
        pass
    started, release = threading.Event(), threading.Event()
    method = {
        "loan": "loan_review_snapshot",
        "settlement": "settlement_review_snapshot",
        "coverage": "reconciliation_snapshot",
    }[kind]
    original = getattr(V2ProfileStore, method)
    threads = []

    def delayed(store, *args, **kwargs):
        threads.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, method, delayed)
    constructors = {
        "loan": lambda: V2LoanPaymentReview(workspace(path)),
        "settlement": lambda: V2SettlementReview(workspace(path)),
        "coverage": lambda: V2StatementCoverageDialog(path),
    }
    start = time.monotonic()
    view = constructors[kind]()
    assert time.monotonic() - start < 0.5
    ticks = []
    timer = QTimer(view)
    timer.timeout.connect(lambda: ticks.append(True))
    timer.start(5)
    try:
        view.show()
        until(lambda: started.is_set() and len(ticks) >= 2, app)
        assert view.jobs.pending and threads != [threading.get_ident()]
        assert view.close()
        release.set()
        wait_for_jobs(view)
        assert not view.isVisible()
        if kind != "coverage":
            assert view.snapshot is None
    finally:
        release.set()
        view.close()


def test_loan_stale_preview_is_discarded_and_confirmed_write_cannot_be_closed(tmp_path, app, monkeypatch):
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview

    path = tmp_path / "loan.db"
    bank, rows = loan_profile(path)
    work = workspace(path)
    work.set_allow_assumed_posting_dates(True)
    view = V2LoanPaymentReview(work)
    assert view.assumed_dates.isChecked()
    wait_for_jobs(view)
    original = V2ProfileStore.loan_payment_preview
    started, release = threading.Event(), threading.Event()

    def delayed(store, *args, **kwargs):
        started.set()
        assert release.wait(5)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "loan_payment_preview", delayed)
    try:
        view.bank.setCurrentIndex(view.bank.findData(bank))
        view.components.item(0, 0).setCheckState(Qt.Checked)
        until(started.is_set, app)
        view.bank.setCurrentIndex(0)
        release.set()
        wait_for_jobs(view)
        assert view.preview is None and not view.confirm.isEnabled()
        monkeypatch.setattr(V2ProfileStore, "loan_payment_preview", original)
        view.bank.setCurrentIndex(view.bank.findData(bank))
        wait_for_jobs(view)
        view.reference.setText("Full bank and printed component references")
        view.reason.setText("Explicit whole payment review")
        assert view.preview.manifest.components[0].row_id == rows[0]
        assert view.confirm.isEnabled()
        started.clear()
        release.clear()
        post = V2ProfileStore.post_reviewed_loan_payment

        def delayed_post(store, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return post(store, *args, **kwargs)

        monkeypatch.setattr(V2ProfileStore, "post_reviewed_loan_payment", delayed_post)
        view.show()
        view.confirm.click()
        until(started.is_set, app)
        assert view.jobs.writing and not view.tabs.isEnabled()
        assert not view.close() and view.isVisible()
        release.set()
        wait_for_jobs(view)
        assert view.selected_event.status == "active" and view.tabs.isEnabled()
        with V2ProfileStore.open(path, read_only=True) as store:
            assert len(store.loan_history()) == 1
    finally:
        release.set()
        wait_for_jobs(view)
        view.close()


def test_cash_movement_date_edits_coalesce_to_latest_scope(tmp_path, app, monkeypatch):
    from parsetrail.gui import v2_cash_movement as module

    path = tmp_path / "cash.db"
    cash_profile(path)
    view = module.V2CashMovementDialog(path)
    wait_for_jobs(view)
    requests = []
    original = module.read_cash_movement

    def read(profile, accounts, **kwargs):
        requests.append((accounts, kwargs["start"], kwargs["end"], threading.get_ident()))
        return original(profile, accounts, **kwargs)

    monkeypatch.setattr(module, "read_cash_movement", read)
    try:
        app.processEvents()
        view.accounts.item(0).setCheckState(Qt.Checked)
        for day in (1, 2, 3, 4):
            view.start.setDate(QDate(2026, 10, day))
        view.end.setDate(QDate(2026, 11, 1))
        assert view.report is None and not view.preview.isEnabled()
        wait_for_jobs(view)
        assert len(requests) == 1
        assert requests[0][1].isoformat() == "2026-10-04"
        assert requests[0][3] != threading.get_ident()
        assert view.report.journal.start.isoformat() == "2026-10-04"
        view.accounts.item(0).setCheckState(Qt.Unchecked)
        assert view.report is None and "No cash scope" in view.total.text()
    finally:
        view.close()


def test_working_font_layouts_and_discoverable_coverage_details(tmp_path, app):
    from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
    from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
    from parsetrail.gui.v2_settlement_review import V2SettlementReview
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog

    paths = {name: tmp_path / f"{name}.db" for name in ("loan", "settlement", "coverage", "cash")}
    for name, builder in (
        ("loan", loan_profile),
        ("settlement", settlement_profile),
        ("coverage", coverage_profile),
        ("cash", cash_profile),
    ):
        builder(paths[name])
    with V2ProfileStore.open(paths["loan"]) as store:
        for account in store.financial_accounts():
            store.update_financial_account(
                replace(account, name=f"{account.name} - extended synthetic product and servicer label")
            )
    with V2ProfileStore.open(paths["cash"]) as store:
        for index in range(24):
            store.add_financial_account(
                FinancialAccount(
                    f"extra:{index}", f"Synthetic reserve {index:02d} with a long account label", "asset", "synthetic"
                )
            )
    views = [
        V2LoanPaymentReview(workspace(paths["loan"])),
        V2SettlementReview(workspace(paths["settlement"])),
        V2StatementCoverageDialog(paths["coverage"]),
        V2CashMovementDialog(paths["cash"]),
    ]
    try:
        for view in views:
            wait_for_jobs(view)
            view.resize(1100, 650)
            view.show()
            app.processEvents()
        loan, settlement, coverage, cash = views
        assert cash.accounts.count() == 25 and cash.accounts.verticalScrollBar().maximum() > 0
        assert loan.components.viewport().height() >= 150
        assert settlement.receipts.viewport().height() >= 150
        assert coverage.table.columnWidth(0) >= 200
        assert coverage.table.isColumnHidden(3) and coverage.table.isColumnHidden(9)
        coverage.table.selectRow(0)
        assert "Opening:" in coverage.coverage_details.toPlainText()
        assert coverage.model.rows[0].source_sha256 in coverage.coverage_details.toPlainText()
        coverage.show_all_columns.click()
        assert not coverage.table.isColumnHidden(3) and not coverage.table.isColumnHidden(9)
        coverage.show_all_columns.click()
        for name, view in zip(("loan", "settlement", "coverage", "cash"), views, strict=True):
            target = tmp_path / f"{name}-1100x650.png"
            assert view.grab().save(str(target))
            print(f"UI_EVIDENCE={target}")
            assert view.size().width() == 1100 and view.size().height() == 650
        loan.assumed_dates.click()
        wait_for_jobs(loan)
        loan.bank.setCurrentIndex(1)
        loan.components.item(0, 0).setCheckState(Qt.Checked)
        loan.components.selectRow(0)
        wait_for_jobs(loan)
        assert loan.components.viewport().height() >= 100
        loan.activateWindow()
        app.processEvents()
        loan.profile_path.setFocus()
        assert loan.profile_path.hasFocus()
        assert loan.profile_path.isReadOnly()
        loan.profile_path.selectAll()
        assert loan.profile_path.selectedText() == str(paths["loan"])
        from PySide6.QtTest import QTest

        QTest.keyClick(loan.profile_path, Qt.Key_Tab)
        assert loan.reload.hasFocus()
        loan.tabs.setCurrentIndex(1)
        app.processEvents()
        assert loan.preview is not None and not loan.confirm.isEnabled()
        assert loan.grab().save(str(tmp_path / "loan-exact-preview-1100x650.png"))
        settlement.outgoing.setCurrentIndex(1)
        app.processEvents()
        assert settlement.expected_panel.isVisible() and settlement.preview is None
        assert settlement.receipts.viewport().height() >= 100
        assert settlement.expected_scroll.verticalScrollBar().maximum() == 0
        assert settlement.grab().save(str(tmp_path / "settlement-missing-receipt-1100x650.png"))
        settlement.receipts.item(0, 0).setCheckState(Qt.Checked)
        wait_for_jobs(settlement)
        settlement.tabs.setCurrentIndex(2)
        app.processEvents()
        assert settlement.preview is not None and not settlement.confirm.isEnabled()
        assert settlement.grab().save(str(tmp_path / "settlement-exact-preview-1100x650.png"))
        cash.start.setDate(QDate(2026, 10, 1))
        cash.end.setDate(QDate(2026, 11, 1))
        cash.accounts.item(0).setCheckState(Qt.Checked)
        wait_for_jobs(cash)
        app.processEvents()
        assert cash.entries.viewport().height() >= 80
        assert cash.grab().save(str(tmp_path / "cash-reviewed-1100x650.png"))
    finally:
        for view in views:
            view.close()
