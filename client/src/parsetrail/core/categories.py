"""Headless category queries and mutations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from parsetrail.core.money import exact_decimal, require_minor_units
from parsetrail.core.orm import Categories, Transactions

CATEGORY_TYPES = ("Expense", "Income", "Transfer")


class CategoryServiceError(RuntimeError):
    """Base class for expected failures at the category boundary."""


class CategoryNotFoundError(CategoryServiceError):
    """Raised when a requested category no longer exists."""


class DuplicateCategoryError(CategoryServiceError):
    """Raised when a category name is already present."""


class InvalidCategoryError(CategoryServiceError):
    """Raised when category input is invalid."""


class CategoryPersistenceError(CategoryServiceError):
    """Raised when an unexpected database failure prevents an operation."""


@dataclass(frozen=True)
class CategorySummary:
    category_id: int
    name: str
    category_type: str
    budget: Decimal | None
    active: bool
    transaction_count: int


@dataclass(frozen=True)
class CategoryImpact:
    category_id: int
    name: str
    category_type: str
    transaction_count: int
    verified_transaction_count: int


@dataclass(frozen=True)
class CategoryChange:
    source_name: str
    target_name: str
    affected_transactions: int


class CategoryService:
    """Own category database sessions and transaction boundaries."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def list_categories(self, *, include_inactive: bool = False) -> list[CategorySummary]:
        statement = (
            select(Categories, func.count(Transactions.TransactionID))
            .outerjoin(Transactions, Transactions.CategoryID == Categories.CategoryID)
            .group_by(Categories.CategoryID)
            .order_by(Categories.Name.asc())
        )
        if not include_inactive:
            statement = statement.where(Categories.Active.is_(True))

        try:
            with self.SessionFactory() as session:
                rows = session.execute(statement).all()
                return [
                    CategorySummary(
                        category_id=category.CategoryID,
                        name=category.Name,
                        category_type=category.Type,
                        budget=category.Budget,
                        active=bool(category.Active),
                        transaction_count=count,
                    )
                    for category, count in rows
                ]
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to load categories.") from exc

    def category_pairs(self, *, include_inactive: bool = True) -> list[tuple[int, str]]:
        return [
            (category.category_id, category.name)
            for category in self.list_categories(include_inactive=include_inactive)
        ]

    def describe(self, category_id: int) -> CategoryImpact:
        try:
            with self.SessionFactory() as session:
                return self._describe(session, category_id)
        except CategoryServiceError:
            raise
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to inspect the category.") from exc

    def add(self, name: str, category_type: str) -> CategorySummary:
        normalized_name = self._validate_name(name)
        normalized_type = self._validate_type(category_type)

        try:
            with self.SessionFactory.begin() as session:
                category = Categories(Name=normalized_name, Type=normalized_type, Active=1)
                session.add(category)
                session.flush()
                return self._summary(category)
        except IntegrityError as exc:
            raise DuplicateCategoryError(f"A category named '{normalized_name}' already exists.") from exc
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to add the category.") from exc

    def set_type(self, category_id: int, category_type: str) -> CategorySummary:
        normalized_type = self._validate_type(category_type)
        return self._update(category_id, category_type=normalized_type)

    def set_budget(self, category_id: int, budget: Decimal | int | str | None) -> CategorySummary:
        normalized_budget: Decimal | None
        if budget is None or (isinstance(budget, str) and not budget.strip()):
            normalized_budget = None
        else:
            try:
                normalized_budget = require_minor_units(exact_decimal(budget))
            except (TypeError, ValueError) as exc:
                raise InvalidCategoryError("Please enter a valid USD amount (for example, 1250.00).") from exc
        return self._update(category_id, budget=normalized_budget)

    def set_active(self, category_id: int, active: bool) -> CategorySummary:
        return self._update(category_id, active=bool(active))

    def rename(self, source_id: int, new_name: str, *, unverify: bool = False) -> CategoryChange:
        normalized_name = self._validate_name(new_name)
        try:
            with self.SessionFactory.begin() as session:
                source = self._get(session, source_id)
                existing = session.scalar(select(Categories.CategoryID).where(Categories.Name == normalized_name))
                if existing is not None:
                    raise DuplicateCategoryError(f"A category named '{normalized_name}' already exists.")

                target = Categories(Name=normalized_name, Type=source.Type, Active=1)
                session.add(target)
                session.flush()
                affected = self._reassign_transactions(
                    session,
                    source_id=source.CategoryID,
                    target_id=target.CategoryID,
                    unverify=unverify,
                )
                source.Active = 0
                return CategoryChange(source.Name, normalized_name, affected)
        except CategoryServiceError:
            raise
        except IntegrityError as exc:
            raise DuplicateCategoryError(f"A category named '{normalized_name}' already exists.") from exc
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to rename the category.") from exc

    def merge(self, source_id: int, target_id: int, *, unverify: bool = False) -> CategoryChange:
        if source_id == target_id:
            raise InvalidCategoryError("Source and target categories must be different.")

        try:
            with self.SessionFactory.begin() as session:
                source = self._get(session, source_id)
                target = self._get(session, target_id)
                affected = self._reassign_transactions(
                    session,
                    source_id=source.CategoryID,
                    target_id=target.CategoryID,
                    unverify=unverify,
                )
                source.Active = 0
                target.Active = 1
                return CategoryChange(source.Name, target.Name, affected)
        except CategoryServiceError:
            raise
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to merge the categories.") from exc

    def _update(
        self,
        category_id: int,
        *,
        category_type: str | None = None,
        budget: Decimal | None = None,
        active: bool | None = None,
    ) -> CategorySummary:
        set_budget = budget is not None
        # None is also the meaningful value for clearing a budget.
        if category_type is None and active is None:
            set_budget = True

        try:
            with self.SessionFactory.begin() as session:
                category = self._get(session, category_id)
                if category_type is not None:
                    category.Type = category_type
                if set_budget:
                    category.Budget = budget
                if active is not None:
                    category.Active = active
                session.flush()
                return self._summary(category)
        except CategoryServiceError:
            raise
        except (TypeError, ValueError) as exc:
            raise InvalidCategoryError("The category value is invalid.") from exc
        except SQLAlchemyError as exc:
            raise CategoryPersistenceError("Failed to update the category.") from exc

    @staticmethod
    def _get(session: Session, category_id: int) -> Categories:
        category = session.get(Categories, category_id)
        if category is None:
            raise CategoryNotFoundError(f"Category {category_id} no longer exists.")
        return category

    @classmethod
    def _describe(cls, session: Session, category_id: int) -> CategoryImpact:
        category = cls._get(session, category_id)
        transaction_count = session.scalar(
            select(func.count()).select_from(Transactions).where(Transactions.CategoryID == category_id)
        )
        verified_count = session.scalar(
            select(func.count())
            .select_from(Transactions)
            .where(Transactions.CategoryID == category_id, Transactions.Verified.is_(True))
        )
        return CategoryImpact(
            category_id=category.CategoryID,
            name=category.Name,
            category_type=category.Type,
            transaction_count=transaction_count or 0,
            verified_transaction_count=verified_count or 0,
        )

    @staticmethod
    def _reassign_transactions(
        session: Session,
        *,
        source_id: int,
        target_id: int,
        unverify: bool,
    ) -> int:
        values: dict[str, object] = {
            "CategoryID": target_id,
            "ConfidenceScore": None,
        }
        if unverify:
            values["Verified"] = False
        result = session.execute(update(Transactions).where(Transactions.CategoryID == source_id).values(**values))
        return result.rowcount or 0

    @staticmethod
    def _summary(category: Categories, transaction_count: int = 0) -> CategorySummary:
        return CategorySummary(
            category_id=category.CategoryID,
            name=category.Name,
            category_type=category.Type,
            budget=category.Budget,
            active=bool(category.Active),
            transaction_count=transaction_count,
        )

    @staticmethod
    def _validate_name(name: str) -> str:
        normalized = name.strip()
        if not normalized:
            raise InvalidCategoryError("Category name cannot be empty.")
        return normalized

    @staticmethod
    def _validate_type(category_type: str) -> str:
        normalized = category_type.strip()
        if normalized not in CATEGORY_TYPES:
            raise InvalidCategoryError(f"Type must be one of: {', '.join(CATEGORY_TYPES)}.")
        return normalized
