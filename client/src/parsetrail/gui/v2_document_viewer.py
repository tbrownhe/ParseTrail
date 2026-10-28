"""Read-only original PDF/CSV viewing from verified bytes, entirely in memory."""

from __future__ import annotations

import atexit
import csv
import hashlib
import io
import time

from PySide6.QtCore import (
    QAbstractTableModel,
    QBuffer,
    QByteArray,
    QCoreApplication,
    QIODevice,
    QModelIndex,
    QPointF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES, SavedImport

try:
    from PySide6.QtPdf import QPdfDocument, QPdfSearchModel
    from PySide6.QtPdfWidgets import QPdfView
except ImportError:
    QPdfDocument = QPdfSearchModel = QPdfView = None

MAX_CSV_ROWS = 100_000
MAX_CSV_COLUMNS = 256
MAX_CSV_CELLS = 500_000
_CSV_READERS: set[QThread] = set()
_VIEWERS: set[V2DocumentViewer] = set()


def _finish_viewers() -> None:
    for viewer in tuple(_VIEWERS):
        viewer.close()
    for reader in tuple(_CSV_READERS):
        reader.requestInterruption()
        while reader.isRunning():
            reader.wait(10)
            time.sleep(0.001)
        reader.wait()
        _CSV_READERS.discard(reader)


atexit.register(_finish_viewers)


class _CsvReader(QThread):
    def __init__(self, source: bytes):
        super().__init__()
        self.source = source
        self.headers: tuple[str, ...] = ()
        self.rows: tuple[tuple[str, ...], ...] = ()
        self.truncated = False
        self.error: str | None = None

    def run(self) -> None:
        try:
            if self.isInterruptionRequested():
                return
            records = csv.reader(io.StringIO(self.source.decode("utf-8-sig"), newline=""), strict=True)
            first = next(records, [])
            self.headers = tuple(first[:MAX_CSV_COLUMNS])
            self.truncated = len(first) > MAX_CSV_COLUMNS
            rows, cells = [], len(self.headers)
            for record in records:
                if self.isInterruptionRequested():
                    return
                values = tuple(record[:MAX_CSV_COLUMNS])
                if len(rows) >= MAX_CSV_ROWS or cells + len(values) > MAX_CSV_CELLS:
                    self.truncated = True
                    break
                self.truncated |= len(record) > MAX_CSV_COLUMNS
                rows.append(values)
                cells += len(values)
            self.rows = tuple(rows)
        except (UnicodeError, csv.Error):
            self.error = "This original CSV cannot be displayed as a UTF-8 CSV table."
        finally:
            self.source = b""
            if self.isInterruptionRequested():
                self.headers, self.rows = (), ()


class _CsvModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.headers: tuple[str, ...] = ()
        self.rows: tuple[tuple[str, ...], ...] = ()
        self.columns = 0

    def replace(self, headers=(), rows=()) -> None:
        self.beginResetModel()
        self.headers, self.rows = headers, rows
        self.columns = max((len(headers), *(len(row) for row in rows)))
        self.endResetModel()

    def rowCount(self, _parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, _parent=QModelIndex()):
        return self.columns

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        if orientation == Qt.Vertical:
            return str(section + 1)
        return self.headers[section] if section < len(self.headers) else ""

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        row = self.rows[index.row()]
        return row[index.column()] if index.column() < len(row) else ""


class V2DocumentViewer(QDialog):
    """Own every buffer/model until rendering closes; never create an original file."""

    load_finished = Signal(bool)

    def __init__(self, saved: SavedImport, parent=None, *, initial_page: int | None = None, context: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Original document")
        self.setWindowModality(Qt.WindowModal)
        self.resize(1024, 768)
        self._saved: SavedImport | None = saved
        self._initial_page = initial_page
        self._closed = False
        self.pending, self.ready = True, False
        self.error: str | None = None
        self.needs_password = False
        self.pdf_document = self.pdf_view = self.pdf_buffer = self.search_model = None
        self._csv_reader: _CsvReader | None = None
        self._search_index = -1
        layout = QVBoxLayout(self)
        self.heading = QLabel((context[:240] + "…" if len(context) > 240 else context) or "Original document")
        self.heading.setToolTip(context)
        self.heading.setTextFormat(Qt.PlainText)
        self.heading.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.heading.setWordWrap(True)
        layout.addWidget(self.heading)
        self.scope = QLabel("Full document; may contain other accounts. Read-only; opened in memory.")
        self.scope.setWordWrap(True)
        layout.addWidget(self.scope)
        self.pdf_controls = QWidget()
        controls = QHBoxLayout(self.pdf_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        self.previous_page = QPushButton("Previous")
        self.next_page = QPushButton("Next")
        self.page = QSpinBox()
        self.page.setPrefix("Page ")
        self.page.setRange(1, 1)
        self.page.setAccessibleName("Original document page")
        self.previous_page.clicked.connect(lambda: self.page.setValue(self.page.value() - 1))
        self.next_page.clicked.connect(lambda: self.page.setValue(self.page.value() + 1))
        self.page.valueChanged.connect(self._go_to_page)
        self.zoom_out = QPushButton("−")
        self.zoom_out.setAccessibleName("Zoom out")
        self.zoom_out.setToolTip("Zoom out")
        self.zoom_out.clicked.connect(lambda: self._zoom(1 / 1.2))
        self.zoom_in = QPushButton("+")
        self.zoom_in.setAccessibleName("Zoom in")
        self.zoom_in.setToolTip("Zoom in")
        self.zoom_in.clicked.connect(lambda: self._zoom(1.2))
        self.fit_width = QPushButton("Fit width")
        self.fit_width.clicked.connect(self._fit_width)
        self.zoom_label = QLabel("Fit width")
        self.page_text_toggle = QCheckBox("Page text")
        self.page_text_toggle.toggled.connect(self._show_page_text)
        for widget in (
            self.previous_page,
            self.next_page,
            self.page,
            self.zoom_out,
            self.zoom_in,
            self.fit_width,
            self.zoom_label,
        ):
            controls.addWidget(widget)
        controls.addStretch()
        controls.addWidget(self.page_text_toggle)
        layout.addWidget(self.pdf_controls)
        self.find_controls = QWidget()
        find = QHBoxLayout(self.find_controls)
        find.setContentsMargins(0, 0, 0, 0)
        self.find_text = QLineEdit()
        self.find_text.setPlaceholderText("Find in document (Ctrl+F)")
        self.find_text.setAccessibleName("Find in original document")
        self.find_previous = QPushButton("Previous match")
        self.find_next = QPushButton("Next match")
        self.find_previous.clicked.connect(lambda: self._find_result(-1))
        self.find_next.clicked.connect(lambda: self._find_result(1))
        self.find_text.returnPressed.connect(lambda: self._find_result(1))
        self.find_count = QLabel()
        for widget in (self.find_text, self.find_previous, self.find_next, self.find_count):
            find.addWidget(widget)
        layout.addWidget(self.find_controls)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._search)
        self.find_text.textChanged.connect(lambda: self._search_timer.start(200))
        self.password_controls = QWidget()
        password_layout = QHBoxLayout(self.password_controls)
        password_layout.setContentsMargins(0, 0, 0, 0)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("PDF password; this session only")
        self.password.setAccessibleName("Original PDF password")
        self.unlock = QPushButton("Unlock PDF")
        self.unlock.clicked.connect(self._unlock)
        self.password.returnPressed.connect(self._unlock)
        password_layout.addWidget(self.password)
        password_layout.addWidget(self.unlock)
        layout.addWidget(self.password_controls)
        self.password_controls.hide()
        self.body = QStackedWidget()
        self.message = QLabel("Loading original document…")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.message)
        self.pdf_panel = QSplitter(Qt.Vertical)
        self.page_text = QPlainTextEdit()
        self.page_text.setReadOnly(True)
        self.page_text.setAccessibleName("Selectable text from the current PDF page")
        self.csv_panel = QWidget()
        csv_layout = QVBoxLayout(self.csv_panel)
        csv_layout.setContentsMargins(0, 0, 0, 0)
        self.csv_model = _CsvModel(self)
        self.csv_table = QTableView()
        self.csv_table.setModel(self.csv_model)
        self.csv_table.setEditTriggers(QTableView.NoEditTriggers)
        self.csv_table.setAlternatingRowColors(True)
        self.csv_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.csv_table.horizontalHeader().setDefaultSectionSize(160)
        self.csv_table.selectionModel().currentChanged.connect(self._selected_csv_cell)
        csv_layout.addWidget(self.csv_table)
        csv_layout.addWidget(QLabel("Selected cell (full value; select and copy as needed)"))
        self.csv_cell = QPlainTextEdit()
        self.csv_cell.setReadOnly(True)
        self.csv_cell.setMaximumHeight(90)
        csv_layout.addWidget(self.csv_cell)
        self.body.addWidget(self.csv_panel)
        layout.addWidget(self.body, 1)
        self.status = QLabel("Loading original document…")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._set_pdf_controls(False)
        self.pdf_controls.hide()
        self.find_controls.hide()
        QShortcut(QKeySequence.Find, self, activated=self._focus_find)
        QShortcut(QKeySequence.Copy, self.csv_table, activated=self._copy_csv_cells)
        self._load_timer = QTimer(self)
        self._load_timer.setSingleShot(True)
        self._load_timer.timeout.connect(self._load)
        self._load_timer.start(0)
        _VIEWERS.add(self)
        if parent is not None:
            parent.destroyed.connect(self._parent_finished)
            if isinstance(parent, QDialog):
                parent.finished.connect(self._parent_finished)
        app = QCoreApplication.instance()
        if app is not None and not app.property("parsetrailDocumentViewerExitHook"):
            app.setProperty("parsetrailDocumentViewerExitHook", True)
            app.aboutToQuit.connect(_finish_viewers)

    def _load(self) -> None:
        if self._closed:
            return
        saved = self._saved
        if (
            not isinstance(saved, SavedImport)
            or saved.suffix not in (".pdf", ".csv")
            or type(saved.source) is not bytes
            or not 0 < len(saved.source) <= MAX_SOURCE_BYTES
            or hashlib.sha256(saved.source).hexdigest() != saved.evidence.source_sha256
            or hashlib.sha256(saved.definition).hexdigest() != saved.evidence.definition_sha256
        ):
            self._fail("The retained original failed its integrity or size check. Reopen it to retry.")
            return
        if saved.suffix == ".csv":
            reader = _CsvReader(saved.source)
            self._csv_reader = reader
            _CSV_READERS.add(reader)
            reader.finished.connect(self._csv_finished)
            reader.finished.connect(lambda: _CSV_READERS.discard(reader))
            reader.finished.connect(reader.deleteLater)
            reader.start()
            return
        if QPdfDocument is None or QPdfView is None:
            self._fail("PDF viewing is unavailable in this installation. Install a build with the Qt PDF runtime.")
            return
        self.pdf_buffer = QBuffer(self)
        self.pdf_buffer.setData(QByteArray(saved.source))
        self.pdf_buffer.open(QIODevice.ReadOnly)
        self.pdf_document = QPdfDocument(self)
        self.pdf_document.passwordRequired.connect(self._password_required)
        self.pdf_view = QPdfView(self)
        self.pdf_view.setPageMode(QPdfView.PageMode.SinglePage)
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.pdf_view.setDocument(self.pdf_document)
        self.pdf_view.pageNavigator().currentPageChanged.connect(self._page_changed)
        self.search_model = QPdfSearchModel(self)
        self.search_model.setDocument(self.pdf_document)
        self.search_model.countChanged.connect(self._search_results)
        self.pdf_view.setSearchModel(self.search_model)
        self.pdf_document.statusChanged.connect(self._pdf_status)
        self.pdf_panel.addWidget(self.pdf_view)
        self.pdf_panel.addWidget(self.page_text)
        self.pdf_panel.setSizes([500, 180])
        self.page_text.hide()
        self.body.addWidget(self.pdf_panel)
        self.pdf_document.load(self.pdf_buffer)

    def _pdf_status(self, status) -> None:
        if self._closed:
            return
        if status == QPdfDocument.Status.Ready:
            count = self.pdf_document.pageCount()
            if not count:
                self._fail("This PDF contains no viewable pages.")
                return
            self.pending, self.ready, self.error, self.needs_password = False, True, None, False
            self.password_controls.hide()
            self.pdf_controls.show()
            self.find_controls.show()
            self._set_pdf_controls(True)
            self.body.setCurrentWidget(self.pdf_panel)
            self.page.setMaximum(count)
            self.page.setSuffix(f" of {count}")
            selected = (
                self._initial_page if isinstance(self._initial_page, int) and 1 <= self._initial_page <= count else 1
            )
            self.page.setValue(selected)
            self._go_to_page(selected)
            self._page_changed(selected - 1)
            self.status.setText("Original PDF · Full document; may contain other accounts.")
            self.load_finished.emit(True)
        elif status == QPdfDocument.Status.Error:
            if self.pdf_document.error() == QPdfDocument.Error.IncorrectPassword:
                self._password_required()
            else:
                self._fail(
                    "This original PDF could not be displayed. It may be damaged or use unsupported PDF security."
                )

    def _password_required(self) -> None:
        if self._closed:
            return
        if self.needs_password and not self.pending:
            return
        self.pending, self.ready, self.needs_password = False, False, True
        self.message.setText("This original PDF requires a password. Enter it above for this session only.")
        self.body.setCurrentWidget(self.message)
        self.status.setText("Password required to view this original PDF.")
        self.password_controls.show()
        self.password.setFocus()
        self.load_finished.emit(False)

    def _unlock(self) -> None:
        if self._closed or not self.needs_password or not self.password.text():
            return
        self.pending = True
        self.pdf_document.setPassword(self.password.text())
        self.password.clear()
        self.pdf_buffer.seek(0)
        self.pdf_document.load(self.pdf_buffer)

    def _set_pdf_controls(self, enabled: bool) -> None:
        self.pdf_controls.setEnabled(enabled)
        self.find_controls.setEnabled(enabled)
        self.find_previous.setEnabled(False)
        self.find_next.setEnabled(False)

    def _go_to_page(self, page: int) -> None:
        if self.ready and self.pdf_view is not None:
            self.pdf_view.pageNavigator().jump(page - 1, QPointF())

    def _page_changed(self, index: int) -> None:
        if self._closed or self.pdf_document is None:
            return
        self.page.blockSignals(True)
        self.page.setValue(index + 1)
        self.page.blockSignals(False)
        self.previous_page.setEnabled(index > 0)
        self.next_page.setEnabled(index + 1 < self.pdf_document.pageCount())
        if self.page_text_toggle.isChecked():
            self._show_page_text(True)

    def _fit_width(self) -> None:
        if self.ready and self.pdf_view is not None:
            self.pdf_view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
            self.zoom_label.setText("Fit width")

    def _zoom(self, multiplier: float) -> None:
        if not self.ready or self.pdf_view is None:
            return
        factor = self.pdf_view.zoomFactor()
        if self.pdf_view.zoomMode() != QPdfView.ZoomMode.Custom:
            width = self.pdf_document.pagePointSize(self.page.value() - 1).width()
            factor = (self.pdf_view.viewport().width() - 12) / max(1, width * self.pdf_view.logicalDpiX() / 72)
        factor = max(0.25, min(4.0, factor * multiplier))
        self.pdf_view.setZoomMode(QPdfView.ZoomMode.Custom)
        self.pdf_view.setZoomFactor(factor)
        self.zoom_label.setText(f"{round(factor * 100)}%")

    def _show_page_text(self, visible: bool) -> None:
        self.page_text.setVisible(visible)
        if visible and self.ready and self.pdf_document is not None:
            text = self.pdf_document.getAllText(self.page.value() - 1).text()
            self.page_text.setPlainText(text or "No selectable text on this page; it may be scanned.")

    def _focus_find(self) -> None:
        if self.ready and self.pdf_view is not None:
            self.find_text.setFocus()
            self.find_text.selectAll()

    def _search(self) -> None:
        if not self.ready or self.search_model is None:
            return
        self._search_index = -1
        self.search_model.setSearchString(self.find_text.text())
        self._search_results()

    def _search_results(self) -> None:
        if self._closed or self.search_model is None:
            return
        count = self.search_model.count()
        self.find_previous.setEnabled(count > 0)
        self.find_next.setEnabled(count > 0)
        self.find_count.setText(f"{count} match(es)" if self.find_text.text() else "")
        if count and self._search_index < 0:
            self._find_result(1)

    def _find_result(self, direction: int) -> None:
        if self.search_model is None or not self.search_model.count():
            return
        self._search_index = (self._search_index + direction) % self.search_model.count()
        self.pdf_view.setCurrentSearchResultIndex(self._search_index)
        self.pdf_view.pageNavigator().jump(self.search_model.resultAtIndex(self._search_index))
        self.find_count.setText(f"{self._search_index + 1} of {self.search_model.count()}")

    def _csv_finished(self) -> None:
        reader = self._csv_reader
        self._csv_reader = None
        if self._closed or reader is None:
            return
        if reader.error:
            self._fail(reader.error)
            return
        self.csv_model.replace(reader.headers, reader.rows)
        self.pending, self.ready, self.error = False, True, None
        self.status.setText(
            f"Original CSV · {len(reader.rows)} data row(s) displayed as text; no date or money conversion."
            + (" Viewer limit reached: this table shows only part of the original." if reader.truncated else "")
        )
        if not self.csv_model.columnCount():
            self.message.setText("This CSV contains no cells.")
            self.body.setCurrentWidget(self.message)
        else:
            self.body.setCurrentWidget(self.csv_panel)
        self.load_finished.emit(True)

    def _selected_csv_cell(self, current, _prior) -> None:
        self.csv_cell.setPlainText(self.csv_model.data(current) or "")

    def _copy_csv_cells(self) -> None:
        indexes = sorted(self.csv_table.selectedIndexes(), key=lambda item: (item.row(), item.column()))
        if not indexes:
            return
        first, last = indexes[0].row(), indexes[-1].row()
        columns = sorted({index.column() for index in indexes})
        selected = {(index.row(), index.column()) for index in indexes}
        output = io.StringIO(newline="")
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        for row in range(first, last + 1):
            writer.writerow(
                self.csv_model.data(self.csv_model.index(row, column)) if (row, column) in selected else ""
                for column in columns
            )
        QApplication.clipboard().setText(output.getvalue())

    def _fail(self, message: str) -> None:
        self.pending, self.ready, self.error = False, False, message
        self.status.setText(message)
        self.message.setText(message)
        self.body.setCurrentWidget(self.message)
        self._set_pdf_controls(False)
        self.load_finished.emit(False)

    def _release_memory(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.pending, self.ready = False, False
        self._load_timer.stop()
        self._search_timer.stop()
        if self._csv_reader is not None:
            reader = self._csv_reader
            self._csv_reader = None
            reader.requestInterruption()
            if not reader.isRunning():
                reader.source, reader.headers, reader.rows = b"", (), ()
        if self.search_model is not None:
            self.search_model.setDocument(None)
        if self.pdf_view is not None:
            self.pdf_view.setDocument(None)
        if self.pdf_document is not None:
            self.pdf_document.close()
            self.pdf_document.setPassword("")
        if self.pdf_buffer is not None:
            self.pdf_buffer.close()
            self.pdf_buffer.setData(QByteArray())
        self._saved = None
        self.page_text.clear()
        self.csv_cell.clear()
        self.password.clear()
        self.csv_model.replace()
        _VIEWERS.discard(self)

    def done(self, result: int) -> None:
        self._release_memory()
        super().done(result)

    def _parent_finished(self, *_args) -> None:
        self.close()

    def close(self) -> bool:
        self._release_memory()
        return super().close()

    def closeEvent(self, event) -> None:
        self._release_memory()
        super().closeEvent(event)


def show_saved_document(
    saved: SavedImport, parent=None, *, initial_page: int | None = None, context: str = ""
) -> V2DocumentViewer:
    """Show a retained window-modal viewer without entering another blocking event loop."""
    viewer = V2DocumentViewer(saved, parent, initial_page=initial_page, context=context)
    viewer.show()
    return viewer
