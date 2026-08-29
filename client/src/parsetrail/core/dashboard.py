"""Headless queries used to populate the desktop dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from parsetrail.core import query


class DashboardServiceError(RuntimeError):
    """Base class for expected failures at the dashboard query boundary."""


class DashboardDataUnavailableError(DashboardServiceError):
    """Raised when a dashboard use case has no required source data."""


class DashboardPersistenceError(DashboardServiceError):
    """Raised when an unexpected database failure prevents a dashboard query."""


@dataclass(frozen=True)
class LatestBalance:
    account_name: str
    balance: Decimal
    date: date


@dataclass(frozen=True)
class StatementDiscrepancyData:
    balances: tuple[LatestBalance, ...]
    latest_statement_date: date


class DashboardQueryService:
    """Own dashboard and model-training read sessions."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def latest_balances(self) -> list[LatestBalance]:
        try:
            with self.SessionFactory() as session:
                return [
                    LatestBalance(account_name=name, balance=balance, date=balance_date)
                    for name, balance, balance_date in query.latest_balances(session)
                ]
        except SQLAlchemyError as exc:
            raise DashboardPersistenceError("Failed to load latest balances.") from exc

    def statement_discrepancy_data(self) -> StatementDiscrepancyData:
        try:
            with self.SessionFactory() as session:
                balances = tuple(
                    LatestBalance(account_name=name, balance=balance, date=balance_date)
                    for name, balance, balance_date in query.latest_balances(session)
                )
                latest_statement_date = query.statement_max_date(session)
                return StatementDiscrepancyData(
                    balances=balances,
                    latest_statement_date=latest_statement_date,
                )
        except ValueError as exc:
            raise DashboardDataUnavailableError(str(exc)) from exc
        except SQLAlchemyError as exc:
            raise DashboardPersistenceError("Failed to inspect statement discrepancies.") from exc

    def account_names(self) -> list[str]:
        try:
            with self.SessionFactory() as session:
                return sorted(query.account_names(session))
        except SQLAlchemyError as exc:
            raise DashboardPersistenceError("Failed to load account names.") from exc

    def category_names(self) -> list[str]:
        try:
            with self.SessionFactory() as session:
                return query.distinct_categories(session)
        except SQLAlchemyError as exc:
            raise DashboardPersistenceError("Failed to load category names.") from exc

    def balance_history(self) -> tuple[pd.DataFrame, list[str]]:
        from parsetrail.core.plot import get_balance_data

        try:
            with self.SessionFactory() as session:
                return get_balance_data(session)
        except (SQLAlchemyError, KeyError, ValueError) as exc:
            raise DashboardPersistenceError("Failed to build balance history.") from exc

    def category_spending(self) -> pd.DataFrame:
        from parsetrail.core.plot import get_category_data

        try:
            with self.SessionFactory() as session:
                return get_category_data(session)
        except (SQLAlchemyError, KeyError, ValueError) as exc:
            raise DashboardPersistenceError("Failed to build category spending history.") from exc

    def training_set(self) -> tuple[list[tuple], list[str]]:
        try:
            with self.SessionFactory() as session:
                return query.training_set(session, verified=True)
        except (SQLAlchemyError, ValueError) as exc:
            raise DashboardPersistenceError("Failed to load verified model-training data.") from exc
