"""Reusable Qt models and canvases used by the desktop dashboard."""

import matplotlib.dates as mdates
import pandas as pd
from loguru import logger
from matplotlib import rcParams
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from PySide6.QtCore import QAbstractTableModel, Qt
from PySide6.QtGui import QColor


class MatplotlibCanvas(FigureCanvas):
    def __init__(self, parent=None, width=3, height=4, dpi=100):
        self.fig = Figure(figsize=(width, height), dpi=dpi, constrained_layout=True)
        self.axes = self.fig.add_subplot(111)
        super().__init__(self.fig)
        self.setParent(parent)

        rcParams["savefig.dpi"] = 300
        self.resize_event_id = self.fig.canvas.mpl_connect("resize_event", self.on_resize)
        self.fig.canvas.mpl_connect("pick_event", self.on_legend_click)
        self.fig.canvas.mpl_connect("button_press_event", self.on_mouse_press)
        self.fig.canvas.mpl_connect("button_release_event", self.on_mouse_release)
        self.fig.canvas.mpl_connect("motion_notify_event", self.on_mouse_move)
        self.legend_dragging = False

    def on_resize(self, event):
        width, height = self.get_width_height()
        max_x_ticks = int(width / 80)
        max_y_ticks = int(height / 50)
        locator = mdates.AutoDateLocator(maxticks=max_x_ticks)
        formatter = mdates.ConciseDateFormatter(locator)
        self.axes.xaxis.set_major_locator(locator)
        self.axes.xaxis.set_major_formatter(formatter)
        self.axes.yaxis.set_major_locator(MaxNLocator(nbins=max_y_ticks))
        self.axes.yaxis.set_major_formatter(FuncFormatter(lambda x, _: f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"))
        self.draw()

    def plot(
        self,
        df: pd.DataFrame,
        selected_accounts: list[str],
        left=None,
        right=None,
        title="",
        xlabel="",
        ylabel="",
        dashed=None,
    ):
        self.axes.clear()
        dashed = dashed or []
        if df.empty or not selected_accounts:
            self.axes.text(
                0.5,
                0.5,
                "No data selected",
                transform=self.axes.transAxes,
                ha="center",
            )
            self.draw()
            return

        self.lines = {}
        for account_name in selected_accounts:
            linestyle = "dashed" if account_name in dashed else "solid"
            (line,) = self.axes.plot(
                df.index,
                df[account_name],
                label=account_name,
                picker=True,
                linestyle=linestyle,
            )
            self.lines[account_name] = line

        left = left if left else df.index.min()
        right = right if right else df.index.max()
        self.axes.set_xlim(left=left, right=right)
        self.axes.axhline(0, color="black", linewidth=1.5, linestyle="-")
        self.axes.axvline(right, color="red", linewidth=1.5, linestyle="-")
        self.axes.set_title(title)
        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        self.axes.grid(True)
        self.axes.fmt_xdata = lambda x: mdates.num2date(x).strftime(r"%Y-%m-%d")

        self.legend = self.axes.legend(loc="upper left", fontsize="x-small")
        for legend_entry in self.legend.get_lines():
            legend_entry.set_picker(5.0)
        self.on_resize(None)

    def on_legend_click(self, event):
        legend_entry = event.artist
        label = legend_entry.get_label()
        line = self.lines.get(label)
        if line is None:
            logger.warning("No line found for label {}", label)
            return
        visible = not line.get_visible()
        line.set_visible(visible)
        legend_entry.set_alpha(1.0 if visible else 0.2)
        self.draw()

    def on_mouse_press(self, event):
        if self.legend and self.legend.contains(event)[0]:
            self.legend_dragging = True

    def on_mouse_release(self, event):
        if self.legend_dragging:
            self.legend_dragging = False

    def on_mouse_move(self, event):
        if self.legend_dragging and event.inaxes:
            self.legend.set_bbox_to_anchor((event.xdata, event.ydata), transform=self.axes.transData)
            self.draw()


class PandasModel(QAbstractTableModel):
    def __init__(self, data):
        super().__init__()
        self._data = data

    def rowCount(self, parent=None):
        return self._data.shape[0]

    def columnCount(self, parent=None):
        return self._data.shape[1]

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        value = self._data.iloc[index.row(), index.column()]
        if role == Qt.DisplayRole:
            if index.column() == 1:
                try:
                    return f"{float(value):,.2f}"
                except (TypeError, ValueError):
                    return str(value)
            return str(value)
        if role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        if role == Qt.BackgroundRole:
            try:
                numeric_value = float(value)
                if numeric_value > 0:
                    return QColor(140, 225, 140)
                if numeric_value < 0:
                    return QColor(225, 160, 160)
            except (TypeError, ValueError):
                return None
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return self._data.columns[section]
            if orientation == Qt.Vertical:
                return self._data.index[section]
        return None

    def sort(self, column, order):
        column_name = self._data.columns[column]
        ascending = order == Qt.AscendingOrder
        self.layoutAboutToBeChanged.emit()
        self._data.sort_values(by=column_name, ascending=ascending, inplace=True)
        self._data.reset_index(drop=True, inplace=True)
        self.layoutChanged.emit()
