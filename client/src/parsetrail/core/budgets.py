"""Headless budget reporting queries and calculations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from parsetrail.core.orm import Categories, Transactions

BudgetGrouping = Literal["Category", "Type"]


class BudgetServiceError(RuntimeError):
    """Base class for expected failures at the budget boundary."""


class InvalidBudgetQueryError(BudgetServiceError):
    """Raised when a requested report range or grouping is invalid."""


class BudgetPersistenceError(BudgetServiceError):
    """Raised when an unexpected database failure prevents a report."""


@dataclass(frozen=True)
class BudgetRow:
    label: str
    budget: Decimal | None
    actual: Decimal
    variance: Decimal | None
    pct_used: Decimal | None
    transaction_count: int


class BudgetQueryService:
    """Own budget reporting sessions while returning UI-independent rows."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def report(
        self,
        *,
        start: date,
        end: date,
        include_inactive: bool = False,
        group_by: BudgetGrouping = "Category",
        prorate: bool = False,
    ) -> list[BudgetRow]:
        if start >= end:
            raise InvalidBudgetQueryError("Budget report start date must be before its end date.")
        if group_by not in ("Category", "Type"):
            raise InvalidBudgetQueryError("Budget reports can be grouped only by Category or Type.")

        category_statement = select(Categories).order_by(Categories.CategoryID)
        if not include_inactive:
            category_statement = category_statement.where(Categories.Active.is_(True))
        transaction_statement = (
            select(
                Transactions.CategoryID,
                func.sum(Transactions.Amount),
                func.count(Transactions.TransactionID),
            )
            .where(Transactions.PostingDate >= start, Transactions.PostingDate < end)
            .group_by(Transactions.CategoryID)
        )

        try:
            with self.SessionFactory() as session:
                categories = list(session.scalars(category_statement))
                transaction_rows = session.execute(transaction_statement).all()
                category_values = [
                    (
                        category.CategoryID,
                        category.Name,
                        category.Type,
                        category.Budget,
                    )
                    for category in categories
                ]
        except SQLAlchemyError as exc:
            raise BudgetPersistenceError("Failed to load budget data.") from exc

        actuals = {category_id: Decimal(total or 0) for category_id, total, _count in transaction_rows}
        counts = {category_id: int(count or 0) for category_id, _total, count in transaction_rows}
        range_days = (end - start).days

        if group_by == "Type":
            rows = self._by_type(category_values, actuals, counts, prorate=prorate, range_days=range_days)
        else:
            rows = self._by_category(category_values, actuals, counts, prorate=prorate, range_days=range_days)
        return sorted(rows, key=lambda row: row.actual, reverse=True)

    @classmethod
    def _by_category(
        cls,
        categories: list[tuple[int, str, str, Decimal | None]],
        actuals: dict[int | None, Decimal],
        counts: dict[int | None, int],
        *,
        prorate: bool,
        range_days: int,
    ) -> list[BudgetRow]:
        rows = []
        for category_id, name, category_type, raw_budget in categories:
            budget = cls._budget(raw_budget, category_type, prorate=prorate, range_days=range_days)
            rows.append(
                cls._row(
                    label=name,
                    budget=budget,
                    actual=actuals.get(category_id, Decimal(0)),
                    transaction_count=counts.get(category_id, 0),
                )
            )
        return rows

    @classmethod
    def _by_type(
        cls,
        categories: list[tuple[int, str, str, Decimal | None]],
        actuals: dict[int | None, Decimal],
        counts: dict[int | None, int],
        *,
        prorate: bool,
        range_days: int,
    ) -> list[BudgetRow]:
        aggregates: dict[str, dict[str, Decimal | int]] = {}
        for category_id, _name, category_type, raw_budget in categories:
            label = category_type or "Unspecified"
            aggregate = aggregates.setdefault(
                label,
                {"budget": Decimal(0), "actual": Decimal(0), "transaction_count": 0},
            )
            budget = cls._budget(raw_budget, category_type, prorate=prorate, range_days=range_days)
            if budget is not None:
                aggregate["budget"] += budget
            aggregate["actual"] += actuals.get(category_id, Decimal(0))
            aggregate["transaction_count"] += counts.get(category_id, 0)

        return [
            cls._row(
                label=label,
                budget=values["budget"] if values["budget"] != 0 else None,
                actual=values["actual"],
                transaction_count=int(values["transaction_count"]),
            )
            for label, values in aggregates.items()
        ]

    @staticmethod
    def _budget(
        raw_budget: Decimal | None,
        category_type: str,
        *,
        prorate: bool,
        range_days: int,
    ) -> Decimal | None:
        if raw_budget is None:
            return None
        budget = raw_budget / Decimal(30) * range_days if prorate else raw_budget
        return -abs(budget) if category_type.lower() == "expense" else budget

    @staticmethod
    def _row(
        *,
        label: str,
        budget: Decimal | None,
        actual: Decimal,
        transaction_count: int,
    ) -> BudgetRow:
        variance = actual - budget if budget is not None else None
        pct_used = actual / budget * 100 if budget not in (None, 0) else None
        return BudgetRow(
            label=label,
            budget=budget,
            actual=actual,
            variance=variance,
            pct_used=pct_used,
            transaction_count=transaction_count,
        )
