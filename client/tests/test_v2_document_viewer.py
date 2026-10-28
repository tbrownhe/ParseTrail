"""Real memory-backed PDF rendering and lossless read-only CSV display."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import subprocess
import sys
import textwrap
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import SavedImport, V2ProfileStore
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card
from parsetrail.gui import v2_document_viewer as module
from PySide6.QtCore import QIODevice, QSize, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from shiboken6 import delete

from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha


def _rc4(key, data):
    """Fixture-only PDF Standard Security R2 encryption; never application crypto."""
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) % 256
        state[i], state[j] = state[j], state[i]
    result, i, j = bytearray(), 0, 0
    for value in data:
        i = (i + 1) % 256
        j = (j + state[i]) % 256
        state[i], state[j] = state[j], state[i]
        result.append(value ^ state[(state[i] + state[j]) % 256])
    return bytes(result)


def synthetic_pdf(*, password=None):
    """Small valid two-page document with selectable Helvetica text, built in memory."""
    streams = (
        b"BT /F1 20 Tf 72 720 Td (Synthetic statement) Tj 0 -32 Td (Account 1234 - Balance $100.00) Tj ET",
        b"BT /F1 20 Tf 72 720 Td (Second page - orchid) Tj 0 -32 Td (Payment $20.00) Tj ET",
    )
    encryption = None
    identifier = hashlib.md5(b"public synthetic PDF fixture", usedforsecurity=False).digest()
    if password is not None:
        padding = bytes.fromhex("28bf4e5e4e758a4164004e56fffa01082e2e00b6d0683e802f0ca9fe6453697a")

        def padded(value):
            return (value.encode("ascii") + padding)[:32]

        owner = _rc4(hashlib.md5(padded("synthetic-owner"), usedforsecurity=False).digest()[:5], padded(password))
        key = hashlib.md5(
            padded(password) + owner + struct.pack("<i", -4) + identifier, usedforsecurity=False
        ).digest()[:5]
        user = _rc4(key, padding)
        streams = tuple(
            _rc4(hashlib.md5(key + bytes((number, 0, 0, 0, 0)), usedforsecurity=False).digest()[:10], stream)
            for number, stream in zip((4, 6), streams, strict=True)
        )
        encryption = f"<< /Filter /Standard /V 1 /R 2 /Length 40 /O <{owner.hex()}> /U <{user.hex()}> /P -4 >>".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(streams[0])).encode() + b" >>\nstream\n" + streams[0] + b"\nendstream",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",
        b"<< /Length " + str(len(streams[1])).encode() + b" >>\nstream\n" + streams[1] + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    if encryption is not None:
        objects.append(encryption)
    result, offsets = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"), [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{number} 0 obj\n".encode() + value + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        result.extend(f"{offset:010} 00000 n \n".encode())
    security = f" /Encrypt 8 0 R /ID [<{identifier.hex()}> <{identifier.hex()}>]" if encryption else ""
    result.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R{security} >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def saved_original(source=None, suffix=".pdf"):
    source = synthetic_pdf() if source is None else source
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    evidence = evidence.model_copy(update={"source_sha256": hashlib.sha256(source).hexdigest()})
    return SavedImport(source, yamaha.DEFINITION, evidence, suffix)


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setattr(
        QDesktopServices, "openUrl", lambda _url: pytest.fail("Embedded viewer must never dispatch to the OS")
    )
    app = QApplication.instance() or QApplication([])
    yield app
    for viewer in tuple(module._VIEWERS):
        viewer.close()
    wait_until(lambda: not module._CSV_READERS)


def wait_until(predicate, timeout=5000):
    deadline = time.monotonic() + timeout / 1000
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)
    assert predicate()


def test_valid_pdf_is_memory_backed_renders_and_navigation_search_text_work(tmp_path):
    saved = saved_original()
    profile = tmp_path / "profile.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(saved.source, saved.definition, saved.evidence, suffix=".pdf")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    with V2ProfileStore.open(profile, read_only=True) as store:
        verified = store.load_import(saved.evidence.source_sha256)
    parent = QDialog()
    parent.show()
    viewer = module.show_saved_document(verified, parent, context="Synthetic checking")
    wait_until(lambda: not viewer.pending)
    assert viewer.ready and viewer.error is None
    assert viewer.windowModality() == Qt.WindowModal and parent.isVisible()
    assert viewer.pdf_buffer.isOpen() and viewer.pdf_buffer.openMode() & QIODevice.ReadOnly
    assert not viewer.pdf_buffer.isWritable()
    assert bytes(viewer.pdf_buffer.data()) == saved.source
    assert viewer.pdf_document.pageCount() == 2
    image = viewer.pdf_document.render(0, QSize(612, 792))
    assert not image.isNull()
    assert any(image.pixelColor(x, y).value() < 100 for x in range(72, 500, 4) for y in range(65, 140, 2))
    assert viewer.pdf_view.zoomMode() == module.QPdfView.ZoomMode.FitToWidth
    assert not viewer.previous_page.isEnabled() and viewer.next_page.isEnabled()
    viewer.next_page.click()
    assert viewer.page.value() == 2 and not viewer.next_page.isEnabled()
    viewer.page_text_toggle.setChecked(True)
    assert "orchid" in viewer.page_text.toPlainText()
    viewer.zoom_in.click()
    assert viewer.pdf_view.zoomMode() == module.QPdfView.ZoomMode.Custom
    viewer.fit_width.click()
    assert viewer.pdf_view.zoomMode() == module.QPdfView.ZoomMode.FitToWidth
    viewer.find_text.setText("statement")
    viewer._search()
    wait_until(lambda: viewer.search_model.count() == 1)
    assert viewer.page.value() == 1
    assert "Synthetic statement" in viewer.page_text.toPlainText()
    viewer.close()
    assert viewer.pdf_document.pageCount() == 0
    assert not viewer.pdf_buffer.isOpen() and viewer.pdf_buffer.data().isEmpty()
    assert viewer._saved is None
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
    parent.close()


@pytest.mark.parametrize("initial_page,expected", [(2, 2), (0, 1), (99, 1), (None, 1)])
def test_optional_source_page_is_one_based_and_invalid_page_falls_back(initial_page, expected):
    viewer = module.show_saved_document(saved_original(), initial_page=initial_page)
    wait_until(lambda: not viewer.pending)
    assert viewer.ready and viewer.page.value() == expected
    assert viewer.pdf_view.pageNavigator().currentPage() == expected - 1
    assert "Full document; may contain other accounts" in viewer.scope.text()


def test_real_encrypted_pdf_password_is_session_only_and_wrong_password_can_retry():
    viewer = module.show_saved_document(saved_original(synthetic_pdf(password="synthetic-password")))
    wait_until(lambda: not viewer.pending)
    assert not viewer.ready and viewer.needs_password
    assert viewer.password_controls.isVisible()
    viewer.password.setText("wrong")
    viewer.unlock.click()
    wait_until(lambda: not viewer.pending)
    assert not viewer.ready and viewer.needs_password and viewer.password.text() == ""
    viewer.password.setText("synthetic-password")
    viewer.unlock.click()
    wait_until(lambda: not viewer.pending)
    assert viewer.ready and viewer.pdf_document.pageCount() == 2
    assert "Synthetic statement" in viewer.pdf_document.getAllText(0).text()
    viewer.close()
    assert viewer.password.text() == "" and viewer.pdf_document.password() == ""


@pytest.mark.parametrize("failure", ["invalid", "digest", "extension", "size", "runtime"])
def test_pdf_errors_are_visible_without_blank_success_or_external_fallback(monkeypatch, failure):
    saved = saved_original(b"%PDF-broken" if failure == "invalid" else None)
    if failure == "digest":
        saved = replace(saved, source=b"tampered")
    elif failure == "extension":
        saved = replace(saved, suffix=".xlsx")
    elif failure == "size":
        monkeypatch.setattr(module, "MAX_SOURCE_BYTES", 10)
    elif failure == "runtime":
        monkeypatch.setattr(module, "QPdfDocument", None)
    viewer = module.show_saved_document(saved)
    wait_until(lambda: not viewer.pending)
    assert not viewer.ready and viewer.error
    assert viewer.body.currentWidget() is viewer.message and viewer.message.text()
    assert not viewer.pdf_controls.isEnabled()


def test_csv_raw_strings_headers_zero_values_multiline_and_copy_survive():
    source = b'Code,Amount,Date,Description\r\n00001234,0.00,01/02/26,"line one\nline two"\r\n00000000,-0.00,unknown,=SUM(A1:A2)\r\n'
    viewer = module.show_saved_document(saved_original(source, ".csv"))
    wait_until(lambda: not viewer.pending)
    assert viewer.ready and viewer.csv_model.rowCount() == 2
    assert viewer.csv_model.headerData(0, Qt.Horizontal) == "Code"
    assert viewer.csv_model.data(viewer.csv_model.index(0, 0)) == "00001234"
    assert viewer.csv_model.data(viewer.csv_model.index(1, 1)) == "-0.00"
    assert viewer.csv_model.data(viewer.csv_model.index(1, 3)) == "=SUM(A1:A2)"
    viewer.csv_table.setCurrentIndex(viewer.csv_model.index(0, 3))
    assert viewer.csv_cell.toPlainText() == "line one\nline two"
    viewer.csv_table.selectRow(0)
    viewer._copy_csv_cells()
    assert "00001234\t0.00\t01/02/26" in QApplication.clipboard().text()
    assert "no date or money conversion" in viewer.status.text()
    viewer.close()
    assert viewer.csv_model.rowCount() == 0 and viewer._saved is None


@pytest.mark.parametrize("source,success", [(b"\n", True), (b'Header\n"unterminated', False), (b"\xff\xfe", False)])
def test_empty_and_unreadable_csv_states_are_explicit(source, success):
    viewer = module.show_saved_document(saved_original(source, ".csv"))
    wait_until(lambda: not viewer.pending)
    assert viewer.ready == success
    assert viewer.body.currentWidget() is viewer.message
    assert viewer.message.text()


def test_csv_limits_are_visible_and_do_not_drop_zero_strings_silently(monkeypatch):
    monkeypatch.setattr(module, "MAX_CSV_ROWS", 2)
    viewer = module.show_saved_document(saved_original(b"Number,Amount\n0001,0\n0002,0.00\n0003,0\n", ".csv"))
    wait_until(lambda: not viewer.pending)
    assert viewer.ready and viewer.csv_model.rowCount() == 2
    assert viewer.csv_model.data(viewer.csv_model.index(0, 0)) == "0001"
    assert "only part of the original" in viewer.status.text()


def test_parent_rejection_or_destruction_releases_pdf_buffer_and_hidden_close_cancels():
    for destroy_parent in (False, True):
        parent = QDialog()
        viewer = module.show_saved_document(saved_original(), parent)
        wait_until(lambda viewer=viewer: not viewer.pending)
        assert viewer.ready
        if destroy_parent:
            delete(parent)
        else:
            parent.reject()
        assert viewer._closed and viewer._saved is None
        assert viewer not in module._VIEWERS
    hidden = module.V2DocumentViewer(saved_original())
    hidden.close()
    QApplication.processEvents()
    assert hidden._closed and hidden.pdf_document is None and hidden._saved is None


def test_escape_closes_only_viewer_and_retains_parent_edits():
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout

    parent = QDialog()
    layout = QVBoxLayout(parent)
    edit = QLineEdit("Synthetic unsaved account name")
    layout.addWidget(edit)
    parent.show()
    viewer = module.show_saved_document(saved_original(), parent)
    wait_until(lambda: not viewer.pending)
    QTest.keyClick(viewer, Qt.Key_Escape)
    assert viewer._closed and not viewer.isVisible()
    assert parent.isVisible() and edit.text() == "Synthetic unsaved account name"
    parent.close()


def test_close_during_csv_parse_drains_worker_and_releases_result_memory(monkeypatch):
    original = module._CsvReader.run
    started, release = threading.Event(), threading.Event()

    def delayed(reader):
        started.set()
        assert release.wait(5)
        original(reader)

    monkeypatch.setattr(module._CsvReader, "run", delayed)
    viewer = module.show_saved_document(saved_original(b"Account,Amount\n0001,0.00\n", ".csv"))
    try:
        wait_until(started.is_set)
        reader = viewer._csv_reader
        viewer.close()
        assert viewer._saved is None and viewer._csv_reader is None
        release.set()
        wait_until(lambda: not module._CSV_READERS)
        assert reader.source == b"" and reader.rows == () and reader.headers == ()
        assert viewer.csv_model.rowCount() == 0
    finally:
        release.set()


@pytest.mark.parametrize("event_loop", [False, True])
def test_csv_worker_shutdown_is_safe_without_default_apps_or_temp_files(tmp_path, event_loop):
    script = textwrap.dedent(
        """
        import json,sys,time,threading
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from parsetrail.gui import v2_document_viewer as module
        from client.tests.test_v2_document_viewer import saved_original
        app=QApplication([]);started=threading.Event();original=module._CsvReader.run
        def delayed(reader):
            started.set();time.sleep(.3);original(reader)
        module._CsvReader.run=delayed
        viewer=module.show_saved_document(saved_original(b'Account,Amount\\n0001,0.00\\n','.csv'))
        if sys.argv[1]=='True':
            def stop():
                if started.is_set():app.quit()
                else:QTimer.singleShot(5,stop)
            QTimer.singleShot(0,stop);app.exec()
        else:
            deadline=time.monotonic()+5
            while not started.is_set() and time.monotonic()<deadline:
                app.processEvents();time.sleep(.005)
            assert started.is_set()
        print(json.dumps({'started':started.is_set()}),flush=True)
        """
    )
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join((str(root), str(root / "client/src"), str(root / "client")))
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script, str(event_loop)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"started": True}
    assert not tuple(tmp_path.iterdir())
