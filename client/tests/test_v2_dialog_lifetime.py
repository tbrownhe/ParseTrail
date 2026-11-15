"""Bounded Qt disposal checks retain wrappers and inspect native invalidation."""

from __future__ import annotations

import threading

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_cash_activity_review import V2CashActivityReview
from parsetrail.gui.v2_evidence_preview import V2EvidencePreview
from parsetrail.gui.v2_gui_lifetime import exec_disposable
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from parsetrail.gui.v2_report_drilldown import V2ReviewedEntryDrilldown
from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog, _ReportReader
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtWidgets import QDialog, QStackedWidget, QTableView, QWidget
from shiboken6 import isValid

from .ordinary_staging_helpers import review_reason
from .test_v2_report_drilldown import END, START, _profile


@pytest.fixture
def profile(tmp_path):
    path = tmp_path / "dialog-lifetime.db"
    evidence, _coffee, _tea = _profile(path)
    return path, evidence


@pytest.fixture
def parent(qtbot):
    # Only register the persistent parent. Disposable children must not remain
    # registered with qtbot after their C++ objects have been deleted.
    widget = QWidget()
    qtbot.addWidget(widget)
    return widget


def watch_hierarchy(dialog):
    widgets = [dialog, *dialog.findChildren(QStackedWidget), *dialog.findChildren(QTableView)]
    destroyed_on = []
    for widget in widgets:
        widget.destroyed.connect(lambda: destroyed_on.append(threading.get_ident()), Qt.DirectConnection)
    return widgets, destroyed_on


def assert_disposed(watched):
    widgets, destroyed_on = watched
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert all(not isValid(widget) for widget in widgets)
    assert len(destroyed_on) == len(widgets)
    assert set(destroyed_on) == {threading.get_ident()}


def dismiss_real_modal(monkeypatch, dialog_type, observed):
    def run(dialog):
        observed.append(watch_hierarchy(dialog))
        QTimer.singleShot(0, dialog, dialog.reject)
        return QDialog.exec(dialog)

    monkeypatch.setattr(dialog_type, "exec", run)


@pytest.mark.parametrize("result", [QDialog.Accepted, QDialog.Rejected])
def test_evidence_modal_disposes_tab_and_table_hierarchy(profile, parent, result):
    path, evidence = profile
    with V2ProfileStore.open(path, read_only=True) as store:
        saved = store.load_import(evidence.source_sha256)
    preview = V2EvidencePreview(saved, parent)
    watched = watch_hierarchy(preview)
    assert len(watched[0]) >= 4  # Preview, the tab stack and both tables.
    QTimer.singleShot(0, preview, lambda: preview.done(result))
    assert exec_disposable(preview) == result
    assert_disposed(watched)
    assert isValid(parent)


def test_evidence_explicit_close_disposes_even_without_exec(profile, parent):
    path, evidence = profile
    with V2ProfileStore.open(path, read_only=True) as store:
        saved = store.load_import(evidence.source_sha256)
    preview = V2EvidencePreview(saved, parent)
    watched = watch_hierarchy(preview)
    assert preview.close()
    assert_disposed(watched)


def test_exec_failure_still_disposes_native_dialog(parent):
    class RefusedDialog(QDialog):
        def exec(self):
            raise RuntimeError("synthetic modal failure")

    dialog = RefusedDialog(parent)
    watched = watch_hierarchy(dialog)
    with pytest.raises(RuntimeError, match="synthetic modal failure"):
        exec_disposable(dialog)
    assert_disposed(watched)


def test_ordinary_preview_disposes_without_destroying_reusable_review(profile, parent, qtbot, monkeypatch):
    path, evidence = profile
    review = V2CashActivityReview(path, evidence.source_sha256, parent)
    observed = []
    dismiss_real_modal(monkeypatch, V2EvidencePreview, observed)
    try:
        qtbot.waitUntil(lambda: not review.review_pending, timeout=5000)
        assert review.batch.review is review
        review_reason(review).setText("Draft survives preview and hide")
        review.show()
        review.hide()
        review.show()
        assert review_reason(review).text() == "Draft survives preview and hide"
        review._preview_evidence()
        qtbot.waitUntil(lambda: bool(observed) and not review.review_pending, timeout=5000)
        assert_disposed(observed[0])
        assert isValid(review) and review.batch.review is review
        assert review_reason(review).text() == "Draft survives preview and hide"
    finally:
        assert review.request_cancel()
        review.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_report_inspection_disposes_drilldown_and_its_table(profile, parent, qtbot, monkeypatch):
    path, _evidence = profile
    reports = V2ReviewedReportsDialog(path, parent)
    observed = []
    dismiss_real_modal(monkeypatch, V2ReviewedEntryDrilldown, observed)
    try:
        reports.set_period(START, END)
        qtbot.waitUntil(lambda: not reports.reports_pending, timeout=5000)
        assert reports.model.rowCount()
        reports._inspect_report_row(0, reports.model.index(0, 0))
        assert len(observed) == 1
        assert_disposed(observed[0])
        assert isValid(reports) and reports.model.rowCount()
    finally:
        assert reports.shutdown()
        qtbot.waitUntil(lambda: reports._reader is None, timeout=5000)
        reports.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_report_error_delivery_releases_tracebacks_and_worker_payload_then_retries(profile, parent, qtbot, monkeypatch):
    path, _evidence = profile
    workers, errors = [], []
    initialize = _ReportReader.__init__
    read_summary = V2ProfileStore.reviewed_category_summary

    def record_reader(reader, *args, **kwargs):
        initialize(reader, *args, **kwargs)
        workers.append(reader)

    def refused_read(_store, **_kwargs):
        try:
            raise ValueError("synthetic report cause")
        except ValueError as cause:
            error = RuntimeError("synthetic report refusal")
            errors.append(error)
            raise error from cause

    monkeypatch.setattr(_ReportReader, "__init__", record_reader)
    monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", refused_read)
    reports = V2ReviewedReportsDialog(path, parent)
    try:
        reports.set_period(START, END)
        qtbot.waitUntil(lambda: not reports.reports_pending, timeout=5000)
        assert errors and "synthetic report refusal" in reports.report_error
        assert all(error.__traceback__ is None and error.__cause__.__traceback__ is None for error in errors)
        assert all(reader.result is None and reader.error is None for reader in workers)
        monkeypatch.setattr(V2ProfileStore, "reviewed_category_summary", read_summary)
        reports.refresh()
        qtbot.waitUntil(lambda: not reports.reports_pending, timeout=5000)
        assert reports.report_error is None and reports.model.rowCount()
    finally:
        assert reports.shutdown()
        qtbot.waitUntil(lambda: reports._reader is None, timeout=5000)
        reports.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_drilldown_source_preview_disposes_without_destroying_inspection(profile, parent, monkeypatch):
    path, _evidence = profile
    drilldown = V2ReviewedEntryDrilldown(path, "expense:food", start=START, end=END, parent=parent)
    observed = []
    dismiss_real_modal(monkeypatch, V2EvidencePreview, observed)
    try:
        assert drilldown.preview.isEnabled()
        drilldown._preview()
        assert len(observed) == 1
        assert_disposed(observed[0])
        assert isValid(drilldown) and drilldown.model.rowCount()
    finally:
        drilldown.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_import_preview_dispatch_survives_hide_and_pending_focus_is_cancelled(parent, monkeypatch):
    review = V2ImportAccountReview(parent=parent)
    decisions = []
    monkeypatch.setattr(review, "_import", lambda: decisions.append("import"))
    monkeypatch.setattr(review, "_skip", lambda: decisions.append("skip"))
    monkeypatch.setattr(review, "reject", lambda: decisions.append("cancel"))
    review.name.setText("Unapplied account draft")
    review.show()
    review.hide()
    review.show()
    assert review.name.text() == "Unapplied account draft"
    review.preview._import()
    review.preview._skip()
    review.preview.reject()
    assert decisions == ["import", "skip", "cancel"]
    review.account_choice.addItem("Choose an account")
    review.account_choice.addItem("Create a new account", "__create_new_account__")
    review.account_choice.setCurrentIndex(review.account_choice.count() - 1)
    review._focus_account_draft()
    focus_timer = review._draft_focus_timer
    assert focus_timer.isActive()
    watched = watch_hierarchy(review)
    review.deleteLater()
    assert_disposed(watched)
    assert not isValid(focus_timer)
    QCoreApplication.processEvents()  # The deleted parented timer cannot touch the deleted editor.
