"""Captured database bytes, real in-memory rendering and nested account edits."""

from __future__ import annotations

import gc
import hashlib
import time
from dataclasses import replace
from threading import Event

import pytest
from parsetrail.core import v2_original_document as storage
from parsetrail.core.source_evidence import PdfLine
from parsetrail.core.v2_account_creation import suggest_account_creation
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui import v2_original_document as gui
from parsetrail.gui.v2_financial_account import V2FinancialAccountDialog, _date_context, _money_context
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from shiboken6 import delete

from .test_v2_account_creation_context import _catalog, _evidence, _suggest
from .test_v2_document_viewer import saved_original, synthetic_pdf


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(gui, "_EXITING", False)
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda *_: pytest.fail("No external dispatch"))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: None)
    monkeypatch.setattr(storage, "OriginalDocumentSession", lambda *_: pytest.fail("No temporary copy"))
    app = QApplication.instance() or QApplication([])
    yield app
    for operation in tuple(gui._ORIGINAL_OPENERS):
        operation.cancel()
    _wait(app, lambda: not gui._ORIGINAL_READERS)


@pytest.fixture
def profile(tmp_path):
    saved = saved_original()
    path = tmp_path / "source.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(saved.source, saved.definition, saved.evidence, suffix=saved.suffix)
    return path, saved


def _wait(app, predicate):
    deadline = time.monotonic() + 15
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate()


def test_verified_database_original_renders_on_selected_page_and_closes_with_host(app, profile):
    path, saved = profile
    before = hashlib.sha256(path.read_bytes()).digest()
    parent = QDialog()
    parent.show()
    action = gui.open_original_document(
        path, saved.evidence.source_sha256, parent, initial_page=2, context="Selected account"
    )
    _wait(app, lambda operation=action: not operation.pending)
    assert action.error is None and action.viewer.ready
    viewer = action.viewer
    assert viewer.pdf_document.pageCount() == 2 and viewer.page.value() == 2
    assert bytes(viewer.pdf_buffer.data()) == saved.source
    assert action._reader.result is action._reader.saved is None
    assert "ParseTrail" in action.status
    assert action in gui._ORIGINAL_OPENERS
    del action
    gc.collect()
    parent.reject()
    _wait(app, lambda: viewer._closed)
    assert viewer._saved is None and bytes(viewer.pdf_buffer.data()) == b""
    assert hashlib.sha256(path.read_bytes()).digest() == before


@pytest.mark.parametrize("destroy", [False, True])
def test_host_close_during_database_read_suppresses_late_viewer(app, profile, monkeypatch, destroy):
    path, saved = profile
    started, release = Event(), Event()
    read = gui.read_saved_original

    def delayed(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return read(*args, **kwargs)

    monkeypatch.setattr(gui, "read_saved_original", delayed)
    parent = QDialog()
    action = gui.open_original_document(path, saved.evidence.source_sha256, parent)
    try:
        _wait(app, started.is_set)
        delete(parent) if destroy else parent.reject()
        release.set()
        _wait(app, lambda: not action.pending)
        assert action.viewer is None and "cancelled" in action.status
    finally:
        release.set()
        _wait(app, lambda: not gui._ORIGINAL_READERS)


def test_new_account_context_and_nested_original_preserve_unsaved_edits(app, profile):
    path, saved = profile
    draft = suggest_account_creation(
        saved.evidence,
        catalog=None,
        source_identity=saved.evidence.payload.accounts[0].source_identity,
        source_form=saved.evidence.payload.accounts[0].source_identity_form,
    )
    draft = replace(draft, source_locations=(PdfLine(kind="pdf_line", page=2, line=1),))
    before = path.read_bytes()
    form = V2FinancialAccountDialog(draft=draft, profile=path)
    form.show()
    form.name.setText("Unsaved personal label")
    form.kind.setCurrentIndex(form.kind.findData("liability"))
    assert form.view_original_button.isEnabled()
    form.view_original_button.click()
    _wait(app, lambda: form.original_open is not None and not form.original_open.pending)
    viewer = form.original_open.viewer
    assert viewer.ready and viewer.page.value() == 2
    assert "123456XXXXXX7890" in viewer.heading.text()
    viewer.reject()
    app.processEvents()
    assert form.isVisible() and form.name.text() == "Unsaved personal label"
    assert form.kind.currentData() == "liability"
    assert form.view_original_button.isEnabled()
    assert path.read_bytes() == before
    form.reject()


def test_selected_context_renders_printed_values_and_qualified_unknowns(app):
    assert QApplication.instance() is app
    evidence = _evidence()
    draft = _suggest(evidence, catalog=_catalog(evidence))
    form = V2FinancialAccountDialog(draft=draft)
    try:
        assert form.name.text() == "Occu 3479"
        assert "$200.00 (printed)" in form.document_values.text()
        assert "$195.00 (printed)" in form.document_values.text()
        assert "Source page 2" in form.document_scope.text()
        assert "not identified" in form.document_type.text()
        assert not form.view_original_button.isEnabled()
        assert _money_context(None) == _date_context(None) == "Unknown"
        zero = draft.opening_balance.model_copy(update={"raw": "$0.00", "minor": 0})
        assert _money_context(zero) == "$0.00 (printed)"
        assumed = draft.period_start.model_copy(update={"raw": None, "provenance": "assumed"})
        assert "estimated" in _date_context(assumed)
    finally:
        form.reject()


def test_encrypted_original_waits_for_password_then_reports_success_once(app):
    action = gui.open_saved_original(saved_original(synthetic_pdf(password="synthetic-password")))
    finished, statuses = [], []
    action.finished.connect(finished.append)
    action.status_changed.connect(statuses.append)
    _wait(app, lambda: action.viewer is not None and action.viewer.needs_password)
    assert action.pending and finished == [] and "password" in statuses[-1]
    action.viewer.password.setText("wrong")
    action.viewer.unlock.click()
    app.processEvents()
    assert action.pending and finished == []
    action.viewer.password.setText("synthetic-password")
    action.viewer.unlock.click()
    _wait(app, lambda: not action.pending)
    assert finished == [True] and action.viewer.ready and action.error is None
    assert statuses[-1] == "Original document opened in ParseTrail."
    action.viewer.reject()
