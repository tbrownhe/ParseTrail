"""Headless transaction review queries and mutations."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload, sessionmaker

from parsetrail.core.orm import Categories, Transactions


class TransactionReviewError(RuntimeError):
    """Base class for expected failures at the transaction-review boundary."""


class InvalidReviewChangesError(TransactionReviewError):
    """Raised when pending review changes cannot be persisted safely."""


class ReviewTransactionNotFoundError(TransactionReviewError):
    """Raised when a transaction changed after it was loaded for review."""


class ReviewPersistenceError(TransactionReviewError):
    """Raised when an unexpected database failure prevents review work."""


class AutoCategorizationError(TransactionReviewError):
    """Raised when model-based categorization cannot complete."""


@dataclass
class TransactionRecord:
    transaction_id: int
    date: date
    account_name: str
    description: str
    amount: Decimal
    category_id: int | None
    category_name: str
    verified: bool
    category_active: bool
    confidence: float | None = None
    cluster: int | None = None
    orig_category_id: int | None = field(init=False)
    orig_verified: bool = field(init=False)

    def __post_init__(self) -> None:
        self.orig_category_id = self.category_id
        self.orig_verified = self.verified


@dataclass(frozen=True)
class AutoCategorizationResult:
    completed: bool
    added_categories: tuple[str, ...] = ()


MissingCategoryDecision = Callable[[Sequence[str]], bool]


class TransactionReviewService:
    """Own transaction review sessions and save boundaries."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def active_categories(self) -> list[tuple[int, str]]:
        statement = (
            select(Categories.CategoryID, Categories.Name).where(Categories.Active.is_(True)).order_by(Categories.Name)
        )
        try:
            with self.SessionFactory() as session:
                return [(category_id, name) for category_id, name in session.execute(statement)]
        except SQLAlchemyError as exc:
            raise ReviewPersistenceError("Failed to load categories for review.") from exc

    def list_transactions(
        self,
        *,
        only_unverified: bool = True,
        only_archived_categories: bool = False,
    ) -> list[TransactionRecord]:
        statement = (
            select(Transactions)
            .options(
                joinedload(Transactions.accounts),
                joinedload(Transactions.category),
            )
            .order_by(Transactions.PostingDate)
        )
        if only_unverified:
            statement = statement.where(Transactions.Verified.is_(False))
        if only_archived_categories:
            statement = statement.join(Transactions.category).where(Categories.Active.is_(False))

        try:
            with self.SessionFactory() as session:
                rows = list(session.scalars(statement))
                return [self._record(transaction) for transaction in rows]
        except SQLAlchemyError as exc:
            raise ReviewPersistenceError("Failed to load transactions for review.") from exc

    def save_changes(self, records: Sequence[TransactionRecord]) -> int:
        modified = [
            record
            for record in records
            if record.category_id != record.orig_category_id or record.verified != record.orig_verified
        ]
        if not modified:
            return 0
        if any(record.category_id is None for record in modified):
            raise InvalidReviewChangesError(
                "Some modified transactions have no category selected. Apply a valid category before saving."
            )
        transaction_ids = [record.transaction_id for record in modified]
        if len(transaction_ids) != len(set(transaction_ids)):
            raise InvalidReviewChangesError("The review changes contain a duplicate transaction.")

        category_ids = {record.category_id for record in modified if record.category_id is not None}
        try:
            with self.SessionFactory.begin() as session:
                existing_categories = set(
                    session.scalars(select(Categories.CategoryID).where(Categories.CategoryID.in_(category_ids)))
                )
                missing_categories = sorted(category_ids - existing_categories)
                if missing_categories:
                    raise InvalidReviewChangesError(
                        f"Category IDs no longer exist: {', '.join(map(str, missing_categories))}."
                    )

                transactions = {
                    transaction.TransactionID: transaction
                    for transaction in session.scalars(
                        select(Transactions).where(Transactions.TransactionID.in_(transaction_ids))
                    )
                }
                missing_transactions = sorted(set(transaction_ids) - transactions.keys())
                if missing_transactions:
                    raise ReviewTransactionNotFoundError(
                        f"Transactions no longer exist: {', '.join(map(str, missing_transactions))}."
                    )

                for record in modified:
                    transaction = transactions[record.transaction_id]
                    transaction.CategoryID = record.category_id
                    transaction.Verified = record.verified
                    transaction.ConfidenceScore = None
                session.flush()
                return len(modified)
        except TransactionReviewError:
            raise
        except SQLAlchemyError as exc:
            raise ReviewPersistenceError("Failed to save transaction review changes.") from exc

    def auto_categorize(
        self,
        model_path: Path,
        *,
        missing_category_decision: MissingCategoryDecision,
        unverified: bool = True,
        uncategorized: bool = False,
    ) -> AutoCategorizationResult:
        # Imported lazily to keep ordinary review queries lightweight.
        from parsetrail.core import learn
        from parsetrail.core.categorize import add_missing_categories
        from parsetrail.core.categorize import transactions as categorize_transactions

        try:
            with self.SessionFactory() as session:
                try:
                    categorize_transactions(
                        session=session,
                        model_path=model_path,
                        unverified=unverified,
                        uncategorized=uncategorized,
                    )
                    return AutoCategorizationResult(completed=True)
                except learn.CategoryCompatibilityError as exc:
                    missing = tuple(exc.missing_categories)
                    if not missing_category_decision(missing):
                        return AutoCategorizationResult(completed=False)
                    add_missing_categories(session, missing)
                    categorize_transactions(
                        session=session,
                        model_path=model_path,
                        unverified=unverified,
                        uncategorized=uncategorized,
                    )
                    return AutoCategorizationResult(completed=True, added_categories=missing)
        except TransactionReviewError:
            raise
        except Exception as exc:
            raise AutoCategorizationError("Auto-categorization failed.") from exc

    @staticmethod
    def _record(transaction: Transactions) -> TransactionRecord:
        category = transaction.category
        return TransactionRecord(
            transaction_id=transaction.TransactionID,
            date=transaction.PostingDate,
            account_name=transaction.accounts.AccountName,
            description=transaction.Description or "",
            amount=transaction.Amount,
            category_id=transaction.CategoryID if category is not None else None,
            category_name=category.Name if category is not None else "",
            verified=bool(transaction.Verified),
            category_active=bool(category.Active) if category is not None else True,
            confidence=float(transaction.ConfidenceScore) if transaction.ConfidenceScore is not None else None,
            cluster=None,
        )
