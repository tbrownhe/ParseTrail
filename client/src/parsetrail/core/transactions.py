"""Headless transaction queries and manual-entry persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from parsetrail.core.orm import Accounts, Categories, Transactions
from parsetrail.core.validation import Transaction, ValidationError


class TransactionServiceError(RuntimeError):
    """Base class for expected failures at the transaction boundary."""


class TransactionAccountNotFoundError(TransactionServiceError):
    """Raised when a transaction targets a missing account."""


class InvalidManualTransactionError(TransactionServiceError):
    """Raised when manual transaction data fails validation."""


class TransactionPersistenceError(TransactionServiceError):
    """Raised when an unexpected database failure prevents an operation."""


@dataclass(frozen=True)
class TransactionRangeRow:
    account_name: str
    date: date
    amount: Decimal
    category: str | None
    description: str


@dataclass(frozen=True)
class ManualTransactionResult:
    inserted: int
    duplicates: int


class TransactionService:
    """Own common transaction query and manual-entry session boundaries."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def accounts(self) -> list[tuple[int, str]]:
        statement = select(Accounts.AccountID, Accounts.AccountName).order_by(Accounts.AccountID)
        try:
            with self.SessionFactory() as session:
                return [(account_id, name) for account_id, name in session.execute(statement)]
        except SQLAlchemyError as exc:
            raise TransactionPersistenceError("Failed to load accounts.") from exc

    def latest_balance(self, account_id: int) -> tuple[date, Decimal] | None:
        statement = (
            select(Transactions.PostingDate, Transactions.Balance)
            .where(Transactions.AccountID == account_id)
            .order_by(Transactions.PostingDate.desc(), Transactions.TransactionID.desc())
            .limit(1)
        )
        try:
            with self.SessionFactory() as session:
                row = session.execute(statement).one_or_none()
                return (row[0], row[1]) if row is not None else None
        except SQLAlchemyError as exc:
            raise TransactionPersistenceError("Failed to load the latest account balance.") from exc

    def in_range(self, start: date | None = None, end: date | None = None) -> list[TransactionRangeRow]:
        statement = (
            select(
                Accounts.AccountName,
                Transactions.PostingDate,
                Transactions.Amount,
                Categories.Name,
                Transactions.Description,
            )
            .join(Accounts, Transactions.AccountID == Accounts.AccountID)
            .outerjoin(Categories, Transactions.CategoryID == Categories.CategoryID)
            .order_by(Transactions.PostingDate, Transactions.TransactionID)
        )
        if start is not None:
            statement = statement.where(Transactions.PostingDate >= start)
        if end is not None:
            statement = statement.where(Transactions.PostingDate <= end)

        try:
            with self.SessionFactory() as session:
                return [
                    TransactionRangeRow(
                        account_name=account_name,
                        date=posting_date,
                        amount=amount,
                        category=category,
                        description=description,
                    )
                    for account_name, posting_date, amount, category, description in session.execute(statement)
                ]
        except SQLAlchemyError as exc:
            raise TransactionPersistenceError("Failed to load transactions in the requested range.") from exc

    def insert_manual(self, account_id: int, transactions: list[Transaction]) -> ManualTransactionResult:
        try:
            hashed = Transaction.hash_transactions(account_id, transactions)
            errors = Transaction.validate_complete(hashed)
            if errors:
                raise InvalidManualTransactionError("\n".join(errors))
            rows = Transaction.to_db_rows(account_id, hashed)
        except (TypeError, ValueError, ValidationError) as exc:
            raise InvalidManualTransactionError(str(exc)) from exc

        try:
            with self.SessionFactory.begin() as session:
                if session.get(Accounts, account_id) is None:
                    raise TransactionAccountNotFoundError(f"Account {account_id} no longer exists.")
                fingerprints = {row["Fingerprint"] for row in rows}
                existing = set(
                    session.scalars(select(Transactions.Fingerprint).where(Transactions.Fingerprint.in_(fingerprints)))
                )
                inserted = 0
                seen = set(existing)
                for row in rows:
                    fingerprint = row["Fingerprint"]
                    if fingerprint in seen:
                        continue
                    session.add(Transactions(**row))
                    seen.add(fingerprint)
                    inserted += 1
                session.flush()
                return ManualTransactionResult(inserted=inserted, duplicates=len(rows) - inserted)
        except TransactionServiceError:
            raise
        except SQLAlchemyError as exc:
            raise TransactionPersistenceError("Failed to insert the manual transaction.") from exc
