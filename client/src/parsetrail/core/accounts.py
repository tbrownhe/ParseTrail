"""Headless account queries and mutations."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from parsetrail.core.money import exact_decimal
from parsetrail.core.orm import AccountNumbers, Accounts, AccountTypes


class AccountServiceError(RuntimeError):
    """Base class for expected failures at the account boundary."""


class AccountNotFoundError(AccountServiceError):
    """Raised when an account or account type no longer exists."""


class DuplicateAccountError(AccountServiceError):
    """Raised when an account name is already present."""


class DuplicateAccountNumberError(AccountServiceError):
    """Raised when an imported account number is already assigned."""


class AccountInUseError(AccountServiceError):
    """Raised when statement or transaction history prevents account deletion."""


class InvalidAccountError(AccountServiceError):
    """Raised when account input is invalid."""


class AccountPersistenceError(AccountServiceError):
    """Raised when an unexpected database failure prevents an operation."""


@dataclass(frozen=True)
class AccountSummary:
    account_id: int
    name: str
    company: str
    description: str
    account_type: str
    appreciation_rate: Decimal


class AccountService:
    """Own account database sessions and transaction boundaries."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def list_accounts(self) -> list[AccountSummary]:
        statement = (
            select(Accounts, AccountTypes.AccountType)
            .join(AccountTypes, Accounts.AccountTypeID == AccountTypes.AccountTypeID)
            .order_by(Accounts.AccountID)
        )
        try:
            with self.SessionFactory() as session:
                return [
                    self._summary(account, account_type) for account, account_type in session.execute(statement).all()
                ]
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to load accounts.") from exc

    def account_types(self) -> list[str]:
        statement = select(AccountTypes.AccountType).order_by(AccountTypes.AccountTypeID)
        try:
            with self.SessionFactory() as session:
                return list(session.scalars(statement))
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to load account types.") from exc

    def add(
        self,
        *,
        name: str,
        account_type: str,
        company: str,
        description: str,
        appreciation_rate: Decimal | int | str = Decimal(0),
    ) -> AccountSummary:
        self._validate_required(name, company, description, account_type)
        normalized_rate = self._appreciation_rate(appreciation_rate)

        try:
            with self.SessionFactory.begin() as session:
                account_type_row = self._get_account_type(session, account_type)
                account = Accounts(
                    AccountName=name,
                    AccountTypeID=account_type_row.AccountTypeID,
                    Company=company,
                    Description=description,
                    AppreciationRate=normalized_rate,
                )
                session.add(account)
                session.flush()
                return self._summary(account, account_type_row.AccountType)
        except AccountServiceError:
            raise
        except IntegrityError as exc:
            raise DuplicateAccountError(f"An account named '{name}' already exists.") from exc
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to add the account.") from exc

    def update(
        self,
        account_name: str,
        *,
        account_type: str,
        company: str,
        description: str,
        appreciation_rate: Decimal | int | str = Decimal(0),
    ) -> AccountSummary:
        self._validate_required(account_name, company, description, account_type)
        normalized_rate = self._appreciation_rate(appreciation_rate)

        try:
            with self.SessionFactory.begin() as session:
                account = self._get_by_name(session, account_name)
                account_type_row = self._get_account_type(session, account_type)
                account.AccountTypeID = account_type_row.AccountTypeID
                account.Company = company
                account.Description = description
                account.AppreciationRate = normalized_rate
                session.flush()
                return self._summary(account, account_type_row.AccountType)
        except AccountServiceError:
            raise
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to update the account.") from exc

    def delete(self, account_name: str) -> None:
        try:
            with self.SessionFactory.begin() as session:
                result = session.execute(delete(Accounts).where(Accounts.AccountName == account_name))
                if not result.rowcount:
                    raise AccountNotFoundError(f"Account '{account_name}' no longer exists.")
        except AccountServiceError:
            raise
        except IntegrityError as exc:
            raise AccountInUseError(
                f"Account '{account_name}' cannot be deleted while it has statements or transactions."
            ) from exc
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to delete the account.") from exc

    def assign_number(self, account_name: str, account_number: str) -> int:
        if not account_number:
            raise InvalidAccountError("Account number cannot be empty.")

        try:
            with self.SessionFactory.begin() as session:
                account = self._get_by_name(session, account_name)
                session.add(AccountNumbers(AccountID=account.AccountID, AccountNumber=account_number))
                session.flush()
                return account.AccountID
        except AccountServiceError:
            raise
        except IntegrityError as exc:
            raise DuplicateAccountNumberError(f"Account number '{account_number}' is already assigned.") from exc
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to assign the account number.") from exc

    def account_id_for_number(self, account_number: str) -> int:
        try:
            with self.SessionFactory() as session:
                account_id = session.scalar(
                    select(AccountNumbers.AccountID).where(AccountNumbers.AccountNumber == account_number)
                )
                if account_id is None:
                    raise AccountNotFoundError(f"Account number '{account_number}' is not assigned.")
                return account_id
        except AccountServiceError:
            raise
        except SQLAlchemyError as exc:
            raise AccountPersistenceError("Failed to look up the account number.") from exc

    @staticmethod
    def _get_by_name(session: Session, account_name: str) -> Accounts:
        account = session.scalar(select(Accounts).where(Accounts.AccountName == account_name))
        if account is None:
            raise AccountNotFoundError(f"Account '{account_name}' no longer exists.")
        return account

    @staticmethod
    def _get_account_type(session: Session, account_type: str) -> AccountTypes:
        account_type_row = session.scalar(select(AccountTypes).where(AccountTypes.AccountType == account_type))
        if account_type_row is None:
            raise AccountNotFoundError(f"Account type '{account_type}' no longer exists.")
        return account_type_row

    @staticmethod
    def _summary(account: Accounts, account_type: str) -> AccountSummary:
        return AccountSummary(
            account_id=account.AccountID,
            name=account.AccountName,
            company=account.Company,
            description=account.Description,
            account_type=account_type,
            appreciation_rate=Decimal(account.AppreciationRate),
        )

    @staticmethod
    def _validate_required(name: str, company: str, description: str, account_type: str) -> None:
        if not all((name, company, description, account_type)):
            raise InvalidAccountError("Please fill in all required account fields.")

    @staticmethod
    def _appreciation_rate(value: Decimal | int | str) -> Decimal:
        try:
            return exact_decimal(value)
        except (TypeError, ValueError) as exc:
            raise InvalidAccountError("Please enter a valid number for appreciation rate.") from exc
