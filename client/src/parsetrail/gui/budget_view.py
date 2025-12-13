from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import pandas as pd
from loguru import logger
from matplotlib.ticker import FuncFormatter
from PyQt5 import QtCore, QtGui

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt5.QtCore import QDate
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableView,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func

from parsetrail.core.orm import Categories, Transactions


class BudgetTab(QWidget):
    """
    Placeholder Budgets tab. Owns its controls, table, and chart canvas.
    Data wiring lives here so ParseTrail stays lean.
    """

    def __init__(self, session_factory: Optional[sessionmaker], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.Session = session_factory
        self._build_ui()

    def set_session_factory(self, session_factory: sessionmaker) -> None:
        """Allow main window to attach Session after DB initialization."""
        self.Session = session_factory

    def _build_ui(self) -> None:
        main_layout = QHBoxLayout(self)

        # Controls
        controls_group = QGroupBox("Budget Controls")
        controls_layout = QFormLayout()

        self.range_mode = QComboBox()
        self.range_mode.addItems(["Month", "Custom Range"])

        self.month_selector = QDateEdit(calendarPopup=True)
        self.month_selector.setDisplayFormat("yyyy-MM")
        first_of_month = QDate.currentDate().addDays(1 - QDate.currentDate().day())
        self.month_selector.setDate(first_of_month)

        self.start_date = QDateEdit(calendarPopup=True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setDate(first_of_month)

        self.end_date = QDateEdit(calendarPopup=True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setDate(QDate.currentDate().addDays(1))  # inclusive end, we will offset in code

        self.group_by_combo = QComboBox()
        self.group_by_combo.addItems(["Category", "Type"])

        self.include_inactive_checkbox = QCheckBox("Include inactive categories")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_view)
        self.range_mode.currentTextChanged.connect(self._on_range_mode_changed)
        self._on_range_mode_changed(self.range_mode.currentText())

        controls_layout.addRow(QLabel("Range Mode:"), self.range_mode)
        controls_layout.addRow(QLabel("Month:"), self.month_selector)
        controls_layout.addRow(QLabel("Start date:"), self.start_date)
        controls_layout.addRow(QLabel("End date (inc):"), self.end_date)
        controls_layout.addRow(QLabel("Group by:"), self.group_by_combo)
        controls_layout.addRow(self.include_inactive_checkbox)
        controls_layout.addRow(self.refresh_button)

        controls_group.setLayout(controls_layout)
        controls_group.setMaximumWidth(int(1.0 * controls_group.sizeHint().width()))
        main_layout.addWidget(controls_group)

        # Right side: chart + table
        right_layout = QVBoxLayout()

        self.figure = Figure(figsize=(6, 4), constrained_layout=True)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        chart_group = QGroupBox("Budget vs Actual")
        chart_layout = QVBoxLayout()
        chart_layout.addWidget(self.canvas)
        chart_group.setLayout(chart_layout)

        self.table = QTableView()
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.table.setSortingEnabled(True)

        # Donut chart for spending share
        self.util_fig = Figure(figsize=(4, 3), constrained_layout=True)
        self.util_axes = self.util_fig.add_subplot(111)
        self.util_canvas = FigureCanvas(self.util_fig)
        self.util_canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        util_group = QGroupBox("Spending Share")
        util_layout = QVBoxLayout()
        util_layout.addWidget(self.util_canvas)
        util_group.setLayout(util_layout)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        right_layout.addWidget(chart_group)
        table_and_util = QHBoxLayout()
        table_and_util.addWidget(self.table, stretch=2)
        table_and_util.addWidget(util_group, stretch=1)
        right_layout.addLayout(table_and_util)
        right_layout.addWidget(self.status_label)

        main_layout.addLayout(right_layout)

        # Initial placeholder view
        self._render_placeholder("Select a range and click Refresh to load budget data.")

    def _on_range_mode_changed(self, mode: str) -> None:
        """Toggle date controls based on selected mode."""
        is_custom = mode == "Custom Range"
        self.month_selector.setEnabled(not is_custom)
        self.start_date.setEnabled(is_custom)
        self.end_date.setEnabled(is_custom)

    def refresh_view(self) -> None:
        """
        Entry point for Refresh button. For now, render placeholder until data wiring is added.
        """
        if self.Session is None:
            self._render_placeholder("Database not ready yet. Please wait for initialization.")
            return
        try:
            mode = self.range_mode.currentText()
            if mode == "Custom Range":
                start_dt = self.start_date.date().toPyDate()
                end_inclusive = self.end_date.date().toPyDate()
                end_dt = end_inclusive + timedelta(days=1)  # make exclusive
                if start_dt >= end_dt:
                    self._render_placeholder("Start date must be before end date.")
                    return
                prorate = True
                range_label = f"{start_dt} to {end_inclusive}"
            else:
                month_start = self.month_selector.date().toPyDate().replace(day=1)
                start_dt = month_start
                end_dt = _first_of_next_month(month_start)
                prorate = False
                range_label = month_start.strftime("%Y-%m")

            range_days = max(1, (end_dt - start_dt).days)
            include_inactive = self.include_inactive_checkbox.isChecked()
            group_by = self.group_by_combo.currentText()
            df = self._load_budget_data(start_dt, end_dt, include_inactive, group_by, prorate, range_days)
            self._populate_table(df)
            self._plot(df, start_dt, end_dt, group_by)
            self._plot_utilization(df, range_label)
            self._update_status(df, start_dt, end_dt, include_inactive, range_label)
        except Exception:
            logger.exception("Failed to refresh budget view")
            self._render_placeholder("Failed to load budgets. See log for details.")

    def _render_placeholder(self, message: str) -> None:
        self.axes.clear()
        self.axes.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
        self.axes.axis("off")
        self.canvas.draw()
        self.status_label.setText(message)

    def _load_budget_data(
        self,
        start: date,
        end: date,
        include_inactive: bool,
        group_by: str,
        prorate: bool,
        range_days: int,
    ) -> pd.DataFrame:
        """
        Fetch budgets and actuals for the given range. Returns a DataFrame with columns:
        label, budget, actual, variance, pct_used, tx_count.
        """
        with self.Session() as session:
            cat_query = session.query(Categories)
            if not include_inactive:
                cat_query = cat_query.filter(Categories.Active == 1)
            categories = cat_query.all()

            tx_rows = (
                session.query(
                    Transactions.CategoryID,
                    func.sum(Transactions.Amount),
                    func.count(Transactions.TransactionID),
                )
                .filter(
                    Transactions.Date >= start.isoformat(),
                    Transactions.Date < end.isoformat(),
                )
                .group_by(Transactions.CategoryID)
                .all()
            )

        actual_map = {cid: float(total or 0) for cid, total, _ in tx_rows}
        count_map = {cid: int(cnt or 0) for cid, _, cnt in tx_rows}

        rows = []

        # Helper to flip budgets for expenses so math aligns with negative actual outflows
        def signed_budget(raw_budget: Optional[float], cat_type: Optional[str]) -> Optional[float]:
            if raw_budget is None:
                return None
            if (cat_type or "").lower() == "expense":
                return -abs(raw_budget)
            return raw_budget

        def prorated_budget(raw_budget: Optional[float], cat_type: Optional[str]) -> Optional[float]:
            if raw_budget is None:
                return None
            if not prorate:
                return signed_budget(raw_budget, cat_type)
            daily_rate = raw_budget / 30.0  # approximate month length
            return signed_budget(daily_rate * range_days, cat_type)

        if group_by == "Type":
            aggregates: dict[str, dict[str, float]] = {}
            for cat in categories:
                label = cat.Type or "Unspecified"
                agg = aggregates.setdefault(label, {"budget": 0.0, "actual": 0.0, "tx_count": 0})
                sb = prorated_budget(float(cat.Budget), cat.Type) if cat.Budget is not None else None
                if sb is not None:
                    agg["budget"] += sb
                agg["actual"] += actual_map.get(cat.CategoryID, 0.0)
                agg["tx_count"] += count_map.get(cat.CategoryID, 0)

            for label, metrics in aggregates.items():
                budget = metrics["budget"] if metrics["budget"] != 0 else None
                actual = metrics["actual"]
                variance = actual - budget if budget is not None else None
                pct_used = (actual / budget * 100) if budget not in (None, 0) else None
                rows.append(
                    {
                        "label": label,
                        "budget": budget,
                        "actual": actual,
                        "variance": variance,
                        "pct_used": pct_used,
                        "tx_count": metrics["tx_count"],
                    }
                )
        else:
            for cat in categories:
                budget = prorated_budget(float(cat.Budget), cat.Type) if cat.Budget is not None else None
                actual = actual_map.get(cat.CategoryID, 0.0)
                variance = actual - budget if budget is not None else None
                pct_used = (actual / budget * 100) if budget not in (None, 0) else None
                rows.append(
                    {
                        "label": cat.Name,
                        "budget": budget,
                        "actual": actual,
                        "variance": variance,
                        "pct_used": pct_used,
                        "tx_count": count_map.get(cat.CategoryID, 0),
                    }
                )

        df = pd.DataFrame(
            rows,
            columns=["label", "budget", "actual", "variance", "pct_used", "tx_count"],
        )
        df = df.sort_values(by="actual", ascending=False).reset_index(drop=True)
        return df

    def _populate_table(self, df: pd.DataFrame) -> None:
        model = QtGui.QStandardItemModel(df.shape[0], df.shape[1])
        model.setHorizontalHeaderLabels(["Label", "Budget", "Actual", "Variance", "% Used", "Transactions"])

        def fmt_money(val: Optional[float]) -> str:
            return "" if val is None or pd.isna(val) else f"${val:,.2f}"

        def fmt_pct(val: Optional[float]) -> str:
            return "" if val is None or pd.isna(val) else f"{val:.0f}%"

        for row_idx, row in df.iterrows():
            numeric_values = [
                None,
                row["budget"],
                row["actual"],
                row["variance"],
                row["pct_used"],
                row["tx_count"],
            ]
            values = [
                row["label"],
                fmt_money(row["budget"]),
                fmt_money(row["actual"]),
                fmt_money(row["variance"]),
                fmt_pct(row["pct_used"]),
                str(int(row["tx_count"])),
            ]
            for col_idx, text in enumerate(values):
                item = QtGui.QStandardItem(text)
                numeric_val = numeric_values[col_idx]
                if numeric_val is not None and not pd.isna(numeric_val):
                    item.setData(float(numeric_val), QtCore.Qt.UserRole)
                if col_idx in (2, 3, 4):
                    item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                model.setItem(row_idx, col_idx, item)

        self.table.setModel(model)
        model.setSortRole(QtCore.Qt.UserRole)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _plot(self, df: pd.DataFrame, start: date, end: date, group_by: str) -> None:
        self.axes.clear()
        if df.empty:
            self._render_placeholder("No budget data for the selected range.")
            return

        labels = df["label"].tolist()
        budget_values = [b if b is not None else 0 for b in df["budget"].tolist()]
        actual_values = df["actual"].tolist()

        x = range(len(labels))
        width = 0.4

        self.axes.bar(
            [i - width / 2 for i in x],
            budget_values,
            width=width,
            label="Budget",
            color="#c7dcef",
        )
        self.axes.bar(
            [i + width / 2 for i in x],
            actual_values,
            width=width,
            label="Actual",
            color="#6ca0dc",
        )

        self.axes.set_xticks(list(x))
        self.axes.set_xticklabels(labels, rotation=30, ha="right")
        self.axes.set_ylabel("Amount")
        title_group = "Category" if group_by == "Category" else "Type"
        range_label = f"{start} to {end - timedelta(days=1)}"
        self.axes.set_title(f"Budget vs Actual by {title_group} ({range_label})")
        self.axes.legend()
        self.axes.yaxis.set_major_formatter(FuncFormatter(lambda val, _: f"${val:,.0f}"))
        self.axes.grid(axis="y", linestyle="--", alpha=0.3)
        self.canvas.draw()

    def _update_status(
        self,
        df: pd.DataFrame,
        start: date,
        end: date,
        include_inactive: bool,
        range_label: str,
    ) -> None:
        total_budget = pd.to_numeric(df["budget"], errors="coerce").fillna(0).sum()
        total_actual = pd.to_numeric(df["actual"], errors="coerce").fillna(0).sum()
        variance = total_actual - total_budget
        scope = "including inactive" if include_inactive else "active only"
        self.status_label.setText(
            f"{range_label}: Budget ${total_budget:,.2f} | "
            f"Actual ${total_actual:,.2f} | Variance ${variance:,.2f} ({scope})"
        )

    def _plot_utilization(self, df: pd.DataFrame, range_label: str) -> None:
        """Donut chart of actual spending share; bins <3% into Other."""
        self.util_axes.clear()
        if df.empty:
            self.util_axes.text(0.5, 0.5, "No data", ha="center", va="center")
            self.util_axes.axis("off")
            self.util_canvas.draw()
            return

        # Focus on outflows; if none, fall back to all magnitudes.
        spend_df = df[df["actual"] < 0]
        if spend_df.empty:
            spend_df = df
        magnitudes = spend_df["actual"].abs()
        total = magnitudes.sum()
        if total <= 0:
            self.util_axes.text(0.5, 0.5, "No spending", ha="center", va="center")
            self.util_axes.axis("off")
            self.util_canvas.draw()
            return

        slices = []
        other_total = 0.0
        for label, value in zip(spend_df["label"], magnitudes):
            pct = value / total
            if pct < 0.03:
                other_total += value
            else:
                slices.append((label, value, pct))
        if other_total > 0:
            slices.append(("Other", other_total, other_total / total))

        # Sort by percentage descending for legend order
        slices.sort(key=lambda x: x[2], reverse=True)
        labels = [s[0] for s in slices]
        values = [s[1] for s in slices]

        wedges, _ = self.util_axes.pie(
            values,
            labels=None,
            startangle=90,
            wedgeprops=dict(width=0.4),
        )
        self.util_axes.legend(
            wedges,
            labels,
            title="Categories",
            loc="center left",
            bbox_to_anchor=(1, 0.5),
            fontsize="x-small",
        )
        self.util_axes.set_title(f"Spending Share ({range_label})", fontsize="small")
        self.util_canvas.draw()


def _first_of_next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)
