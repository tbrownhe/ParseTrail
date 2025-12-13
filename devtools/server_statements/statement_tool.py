import json
import subprocess
import sys
from pathlib import Path

from aes import decrypt_statement
from db import SessionLocal
from loguru import logger
from orm import StatementUploads
from PyQt5.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


# Make the client modules importable
CLIENT_SRC = Path(__file__).resolve().parents[2] / "client" / "src"
if not CLIENT_SRC.exists():
    raise ImportError("Unable to import ParseTrail client modules")
sys.path.insert(0, str(CLIENT_SRC))

try:
    from parsetrail.core.parse import ParseInput
    from parsetrail.core.plugins import PluginManager
    from parsetrail.gui.plugins import ParseTestDialog
    from parsetrail.build_plugins import main as build_plugins
except Exception as e:  # pragma: no cover - optional dependency
    logger.warning(f"Unable to import ParseTrail client modules: {e}")
    raise


class StatementTableModel(QAbstractTableModel):
    COLUMNS = [
        ("id", "id"),
        ("file_name", "file_name"),
        ("metadata", "metadata_field"),
        ("plugin_status", "plugin_status"),
        ("user_id", "user_id"),
    ]

    def __init__(self, rows: list[StatementUploads] | None = None):
        super().__init__()
        self.rows: list[StatementUploads] = rows or []

    def set_rows(self, rows: list[StatementUploads]):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self.rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # type: ignore[override]
        return len(self.COLUMNS)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # type: ignore[override]
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        row = self.rows[index.row()]
        col = self.COLUMNS[index.column()][1]
        value = getattr(row, col)
        if col == "user_id":
            return str(value) if value else ""
        return value or ""

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole
    ):  # type: ignore[override]
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self.COLUMNS[section][0]
        return section + 1

    def get_row(
        self, proxy_index: QModelIndex, proxy: QSortFilterProxyModel
    ) -> StatementUploads:
        source_index = proxy.mapToSource(proxy_index)
        return self.rows[source_index.row()]


class StatementFilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.filter_text = ""

    def setFilterText(self, text: str):
        self.filter_text = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # type: ignore[override]
        if not self.filter_text:
            return True
        model = self.sourceModel()
        if not isinstance(model, StatementTableModel):
            return True
        row = model.rows[source_row]
        haystack = " ".join(
            [
                row.file_name or "",
                row.metadata_field or "",
                row.plugin_status or "",
                str(row.user_id) if row.user_id else "",
            ]
        ).lower()
        return self.filter_text in haystack


class StatementTool(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Statement Browser (dev)")
        self.resize(1100, 700)

        self.model = StatementTableModel([])
        self.proxy = StatementFilterProxy()
        self.proxy.setSourceModel(self.model)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setFont(QFont("Segoe UI", 10))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)

        filter_label = QLabel("Filter:")
        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("file_name, metadata, user_id")
        self.filter_input.textChanged.connect(self.proxy.setFilterText)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.load_rows)

        decrypt_btn = QPushButton("Decrypt && Parse")
        decrypt_btn.clicked.connect(self.decrypt_and_parse)

        mark_pending_btn = QPushButton("Mark Pending")
        mark_pending_btn.clicked.connect(lambda: self.update_status("pending"))
        mark_ready_btn = QPushButton("Mark Ready")
        mark_ready_btn.clicked.connect(lambda: self.update_status("ready"))

        toolbar = QHBoxLayout()
        toolbar.addWidget(filter_label)
        toolbar.addWidget(self.filter_input)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(decrypt_btn)
        toolbar.addWidget(mark_pending_btn)
        toolbar.addWidget(mark_ready_btn)
        toolbar.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(toolbar)
        layout.addWidget(self.table)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.plugin_manager = PluginManager()
        self.session_maker = SessionLocal

        self.table.clicked.connect(self.show_metadata_dialog)
        self.load_rows()

    def load_rows(self):
        try:
            with self.session_maker() as session:
                rows = (
                    session.query(StatementUploads)
                    .order_by(StatementUploads.id.desc())
                    .all()
                )
            self.model.set_rows(rows)
        except Exception as e:
            QMessageBox.critical(self, "Database Error", str(e))

    def show_metadata_dialog(self, proxy_index: QModelIndex):
        try:
            row = self.model.get_row(proxy_index, self.proxy)
        except Exception:
            return

        metadata = self._parse_metadata_field(row.metadata_field or "")
        dialog = QDialog(self)
        dialog.setWindowTitle("Metadata")

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Key", "Value"])
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)

        if metadata:
            table.setRowCount(len(metadata))
            for i, (k, v) in enumerate(metadata.items()):
                table.setItem(i, 0, QTableWidgetItem(str(k)))
                table.setItem(i, 1, QTableWidgetItem(str(v)))
        else:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("_raw"))
            table.setItem(0, 1, QTableWidgetItem(row.metadata_field or ""))

        layout = QVBoxLayout()
        layout.addWidget(table)
        dialog.setLayout(layout)
        dialog.resize(700, 400)
        dialog.exec_()

    def decrypt_and_parse(self):
        idx = self.table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(
                self, "Select a row", "Select a statement to decrypt."
            )
            return
        try:
            row = self.model.get_row(idx, self.proxy)
            plaintext, metadata = decrypt_statement(row)
            summary = self._parse_with_client(plaintext, row.file_name, metadata)
            QMessageBox.information(self, "Exit Status", summary)
        except subprocess.CalledProcessError as e:
            err = e.stderr or ""
            if isinstance(err, bytes):
                err = err.decode(errors="ignore")
            QMessageBox.critical(self, "SSH Error", err or str(e))
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def update_status(self, status: str):
        idx = self.table.currentIndex()
        if not idx.isValid():
            QMessageBox.information(self, "Select a row", "Select a statement first.")
            return
        try:
            row = self.model.get_row(idx, self.proxy)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unable to resolve row: {e}")
            return
        try:
            with self.session_maker() as session:
                db_row = session.query(StatementUploads).get(row.id)
                if not db_row:
                    QMessageBox.warning(
                        self, "Not Found", f"Row id {row.id} not found."
                    )
                    return
                db_row.plugin_status = status
                session.commit()
            self.load_rows()
            QMessageBox.information(
                self, "Updated", f"Set plugin_status={status} for id={row.id}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Database Error", str(e))

    def _parse_with_client(
        self, plaintext: bytes, enc_name: str, metadata: dict
    ) -> str:
        if not all([self.plugin_manager, ParseTestDialog]):
            return "Parsing unavailable: client modules not loaded"

        # Recompile plugins for each call, since dev may have updated them.
        build_plugins()
        self.plugin_manager.load_plugins()

        fname = metadata.get("filename") or metadata.get("file_name") or enc_name
        suffix = Path(fname).suffix or ".bin"
        parse_input = ParseInput(name=fname, suffix=suffix.lower(), data=plaintext)

        try:
            dialog = ParseTestDialog(
                self.session_maker,
                self.plugin_manager,
                initial_input=parse_input,
                parent=self,
            )
            dialog.setWindowTitle(f"Parse Test: {fname}")
            dialog.exec_()
            return "Exited cleanly: processed in-memory bytes"
        finally:
            # Drop strong references to encourage GC of plaintext
            dialog = None
            parse_input = None

    def _parse_metadata_field(self, raw: str) -> dict:
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            if not raw.strip().endswith("}"):
                try:
                    return json.loads(raw + '"}')
                except Exception:
                    pass
        return {}


def main():
    app = QApplication(sys.argv)
    icon = Path(__file__).resolve().parent / "icon.ico"
    app.setWindowIcon(QIcon(str(icon)))
    window = StatementTool()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
