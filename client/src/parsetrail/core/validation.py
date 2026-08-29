from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from loguru import logger

from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity
from parsetrail.core.fingerprint import TRANSACTION_FINGERPRINT_VERSION, transaction_fingerprint
from parsetrail.core.money import DEFAULT_CURRENCY, require_minor_units, to_minor_units


# Exceptions
class ValidationError(Exception):
    pass


def _date_only(value: date, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, date):
        raise TypeError(f"{field} must be date, got {type(value).__name__}")
    return value


# Data structures
@dataclass
class Transaction:
    transaction_date: date
    posting_date: date
    amount: Decimal
    desc: str
    balance: Decimal | None = None
    fingerprint: str | None = None

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        try:
            self.transaction_date = _date_only(self.transaction_date, "transaction_date")
            self.posting_date = _date_only(self.posting_date, "posting_date")
        except TypeError as exc:
            errors.append(str(exc))
        try:
            self.amount = require_minor_units(self.amount)
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid amount: {exc}")
        if not isinstance(self.desc, str):
            errors.append(f"desc must be str, got {type(self.desc).__name__}")
        if not self.desc:
            errors.append("desc cannot be empty")
        if self.balance is not None:
            try:
                self.balance = require_minor_units(self.balance)
            except (TypeError, ValueError) as exc:
                errors.append(f"invalid balance: {exc}")
        if self.fingerprint is not None and not isinstance(self.fingerprint, str):
            errors.append(f"fingerprint must be str or None, got {type(self.fingerprint).__name__}")
        if errors:
            raise TypeError("\n".join(errors))

    @staticmethod
    def sort_and_compute_balances(transactions: list["Transaction"], start_balance: Decimal) -> list["Transaction"]:
        """
        Sorts transactions by posting date and computes running balances.
        Note the sorted() method is stable and preserves transaction order
        of appearance within the same date.

        Args:
            transactions (list[Transaction]): List of transactions to process.
            start_balance (Decimal): The starting balance for the account.

        Returns:
            list[Transaction]: Transactions sorted by posting date with computed balances.
        """
        if not transactions:
            return transactions

        sorted_transactions = sorted(transactions, key=lambda t: t.posting_date)

        # Check if all transactions already have balances
        if all(isinstance(t.balance, Decimal) for t in sorted_transactions):
            logger.trace("Balances are already populated; skipping recalculation.")
            return sorted_transactions

        current_balance = start_balance
        for transaction in sorted_transactions:
            current_balance = require_minor_units(current_balance + transaction.amount)
            transaction.balance = current_balance

        return sorted_transactions

    @staticmethod
    def hash_transactions(
        account_id: int,
        transactions: list["Transaction"],
        currency_code: str = DEFAULT_CURRENCY,
    ) -> list["Transaction"]:
        """
        Generates versioned SHA-256 fingerprints for the transactions.
        """
        if any(not isinstance(t.balance, Decimal) for t in transactions):
            raise ValueError(
                "All transactions must have valid balances to hash. Run the sort_and_compute_balances() method."
            )

        fingerprints: set[str] = set()
        for transaction in transactions:
            occurrence = 0
            while True:
                fingerprint = transaction_fingerprint(
                    account_id=account_id,
                    posting_date=transaction.posting_date,
                    amount=transaction.amount,
                    balance=transaction.balance,
                    description=transaction.desc,
                    occurrence=occurrence,
                    currency_code=currency_code,
                )
                if fingerprint not in fingerprints:
                    fingerprints.add(fingerprint)
                    break

                logger.warning("Transaction fingerprint collision detected; retrying with an occurrence index.")
                occurrence += 1

            transaction.fingerprint = fingerprint

        return transactions

    @staticmethod
    def to_db_rows(
        account_id: int,
        transactions: list["Transaction"],
        currency_code: str = DEFAULT_CURRENCY,
    ) -> list[dict[str, Any]]:
        """
        Converts the Transaction instance to a tuple compatible with database insertion.

        Returns:
            tuple: A tuple of the transaction's fields in the required order.
        """
        rows = []
        for row_number, t in enumerate(transactions, start=1):
            if not isinstance(t.balance, Decimal):
                raise ValueError(f"Transaction row {row_number} is missing a balance and cannot be inserted.")
            if not isinstance(t.fingerprint, str):
                raise ValueError(f"Transaction row {row_number} is missing a fingerprint and cannot be inserted.")
            rows.append(
                {
                    "AccountID": account_id,
                    "TransactionDate": t.transaction_date,
                    "PostingDate": t.posting_date,
                    "AmountMinor": to_minor_units(t.amount, currency_code),
                    "BalanceMinor": to_minor_units(t.balance, currency_code),
                    "CurrencyCode": currency_code,
                    "Description": t.desc,
                    "Fingerprint": t.fingerprint,
                    "FingerprintVersion": TRANSACTION_FINGERPRINT_VERSION,
                }
            )
        return rows

    @staticmethod
    def validate_balances(transactions: list["Transaction"]) -> list[str]:
        """
        Validates that all transactions have valid balances.
        """
        errors = [
            f"Invalid balance for transaction row {row_number}"
            for row_number, transaction in enumerate(transactions, start=1)
            if not isinstance(transaction.balance, Decimal)
        ]
        return errors

    @staticmethod
    def validate_complete(transactions: list["Transaction"]) -> list[str]:
        """
        Validates all optional attributes of a list of Transaction objects.

        Args:
            transactions (list[Transaction]): List of transactions to validate.

        Returns:
            list[str]: A list of validation error messages. Empty if all are valid.
        """
        errors = []
        for i, t in enumerate(transactions):
            # Validate balance
            if t.balance is not None and not isinstance(t.balance, Decimal):
                errors.append(
                    f"Transaction {i + 1}: 'balance' must be a number or None, got {type(t.balance).__name__}."
                )

            # Validate fingerprint
            if t.fingerprint is not None and not isinstance(t.fingerprint, str):
                errors.append(
                    f"Transaction {i + 1}: 'fingerprint' must be a string or None, got {type(t.fingerprint).__name__}."
                )

        return errors


@dataclass
class Account:
    account_num: str
    start_balance: Decimal
    end_balance: Decimal
    transactions: list[Transaction]
    currency_code: str = DEFAULT_CURRENCY
    account_id: int | None = None
    account_name: str | None = None
    statement_id: int | None = None

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        if not isinstance(self.account_num, str):
            errors.append(f"account_num must be str, got {type(self.account_num).__name__}")
        try:
            self.start_balance = require_minor_units(self.start_balance, self.currency_code)
            self.end_balance = require_minor_units(self.end_balance, self.currency_code)
        except (TypeError, ValueError) as exc:
            errors.append(f"invalid account balance: {exc}")
        if not isinstance(self.transactions, list):
            errors.append(f"transactions must be list, got {type(self.transactions).__name__}")
        if not all(isinstance(tx, Transaction) for tx in self.transactions):
            errors.append("All items in transactions must be instances of Transaction")
        if self.account_id is not None and not isinstance(self.account_id, int):
            errors.append(f"account_id must be int or None, got {type(self.account_id).__name__}")
        if self.account_name is not None and not isinstance(self.account_name, str):
            errors.append(f"account_name must be str or None, got {type(self.account_name).__name__}")
        if self.statement_id is not None and not isinstance(self.statement_id, int):
            errors.append(f"statement_id must be int or None, got {type(self.statement_id).__name__}")
        if errors:
            raise TypeError("\n".join(errors))

    def sort_and_compute_balances(self):
        """
        Sort transactions and calculate balances within an instance of Account.
        """
        self.transactions = Transaction.sort_and_compute_balances(self.transactions, self.start_balance)

    def add_account_info(self, account_id: int, account_name: str):
        if not isinstance(account_id, int):
            raise ValidationError("account_id must be an int")
        if not isinstance(account_name, str):
            raise ValidationError("account_name must be a string")
        self.account_id = account_id
        self.account_name = account_name

    def hash_transactions(self):
        self.transactions = Transaction.hash_transactions(
            self.account_id,
            self.transactions,
            self.currency_code,
        )

    def add_statement_id(self, statement_id: int):
        if not isinstance(statement_id, int):
            raise ValidationError("statement_id must be an int")
        self.statement_id = statement_id

    def validate_initial(self):
        """Validate fields required before assigning account_id and account_name."""
        errors = []

        errors.extend(Transaction.validate_balances(self.transactions))

        if not isinstance(self.account_num, str):
            errors.append("account_num must be a string")
        if not isinstance(self.start_balance, Decimal):
            errors.append("start_balance must be a Decimal")
        if not isinstance(self.end_balance, Decimal):
            errors.append("end_balance must be a Decimal")
        if errors:
            raise ValidationError("\n".join(errors))

    def validate_account_info(self):
        """Validate fields required before assigning statement_id."""
        errors = []
        if not isinstance(self.account_id, int):
            errors.append("account_id must be an integer")
        if not isinstance(self.account_name, str):
            errors.append("account_name must be a string")
        if errors:
            raise ValidationError("\n".join(errors))

    def validate_complete(self):
        """Validate all fields for final processing."""
        # self.validate_initial()
        # self.validate_account_info()
        if not isinstance(self.statement_id, int):
            raise ValidationError("statement_id must be an integer")


@dataclass
class Statement:
    start_date: date
    end_date: date
    accounts: list[Account]
    plugin_name: str | None = None
    fpath: Path | None = None
    dpath: Path | None = None
    content_hash: str | None = None
    content_hash_algorithm: str = "sha256"

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        try:
            self.start_date = _date_only(self.start_date, "start_date")
            self.end_date = _date_only(self.end_date, "end_date")
        except TypeError as exc:
            errors.append(str(exc))
        if not isinstance(self.accounts, list):
            errors.append(f"accounts must be list, got {type(self.accounts).__name__}")
        if not all(isinstance(acc, Account) for acc in self.accounts):
            errors.append("All items in accounts must be instances of Account")
        if self.plugin_name is not None and not isinstance(self.plugin_name, str):
            errors.append(f"plugin_name must be str or None, got {type(self.plugin_name).__name__}")
        if self.fpath is not None and not isinstance(self.fpath, Path):
            errors.append(f"fpath must be Path or None, got {type(self.fpath).__name__}")
        if self.dpath is not None and not isinstance(self.dpath, Path):
            errors.append(f"dpath must be Path or None, got {type(self.dpath).__name__}")
        if self.content_hash is not None and not isinstance(self.content_hash, str):
            errors.append(f"content_hash must be str or None, got {type(self.content_hash).__name__}")
        if errors:
            raise TypeError("\n".join(errors))

    def add_metadata(self, fpath: Path, plugin_name: str):
        if not isinstance(fpath, Path):
            raise ValidationError("fpath must be a Path")
        if not isinstance(plugin_name, str):
            raise ValidationError("plugin_name must be str")
        self.fpath = fpath
        self.plugin_name = plugin_name

    def add_content_hash(self, content_hash: str, algorithm: str = "sha256"):
        if not isinstance(content_hash, str):
            raise ValidationError("content_hash must be a str")
        if algorithm not in {"md5", "sha256"}:
            raise ValidationError("Unsupported content hash algorithm")
        self.content_hash = content_hash
        self.content_hash_algorithm = algorithm

    def set_standard_dpath(self, success_dir: Path):
        if not isinstance(self.accounts[0].account_name, str):
            raise ValueError("Account Name must be set on Statement Accounts before setting destination path")
        dname = (
            "_".join(
                [
                    self.accounts[0].account_name,
                    self.start_date.strftime(r"%Y%m%d"),
                    self.end_date.strftime(r"%Y%m%d"),
                ]
            )
            + self.fpath.suffix.lower()
        )
        self.dpath = success_dir / dname

    def to_db_row(self, account: Account):
        metadata = {
            "AccountID": account.account_id,
            "ImportedAt": datetime.now(timezone.utc),
            "StartDate": self.start_date,
            "EndDate": self.end_date,
            "StartBalanceMinor": to_minor_units(account.start_balance, account.currency_code),
            "EndBalanceMinor": to_minor_units(account.end_balance, account.currency_code),
            "CurrencyCode": account.currency_code,
            "TransactionCount": len(account.transactions),
            "Filename": self.dpath.name,
            "ContentHash": self.content_hash,
            "ContentHashAlgorithm": self.content_hash_algorithm,
        }
        return metadata

    def validate_metadata(self) -> list[str]:
        errors = []
        if not isinstance(self.fpath, Path):
            errors.append("fpath must be a Path")
        if not isinstance(self.plugin_name, str):
            errors.append("plugin_name must be str")
        return errors

    def validate_complete(self) -> list[str]:
        errors = []
        if not isinstance(self.dpath, Path):
            errors.append("dpath must be a Path")
        if not isinstance(self.content_hash, str):
            errors.append("content_hash must be str")
        return errors


# Validation framework
VALIDATION_CHECKS: list[Callable[[Statement], list[Diagnostic]]] = []


@dataclass(frozen=True, slots=True)
class ValidationReport:
    diagnostics: tuple[Diagnostic, ...]

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is DiagnosticSeverity.ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(item for item in self.diagnostics if item.severity is DiagnosticSeverity.WARNING)


def register_validation(check: Callable[[Statement], list[Diagnostic]]):
    VALIDATION_CHECKS.append(check)


def validate_statement(statement: Statement) -> ValidationReport:
    diagnostics: list[Diagnostic] = []
    for check in VALIDATION_CHECKS:
        diagnostics.extend(check(statement))
    return ValidationReport(tuple(diagnostics))


# Validation functions
def validate_metadata(statement: Statement) -> list[Diagnostic]:
    return [
        Diagnostic(
            code="statement.metadata.invalid",
            message=message,
            severity=DiagnosticSeverity.ERROR,
        )
        for message in statement.validate_metadata()
    ]


def validate_transactions(statement: Statement) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for account_number, account in enumerate(statement.accounts, start=1):
        for row_number, transaction in enumerate(account.transactions, start=1):
            row = f"account {account_number}, transaction row {row_number}"
            # Posting date must be within the satement date range
            if not isinstance(transaction.posting_date, date):
                diagnostics.append(
                    Diagnostic(
                        code="transaction.posting_date.invalid",
                        message=f"Invalid posting date type at {row}.",
                        severity=DiagnosticSeverity.ERROR,
                    )
                )
            elif (transaction.posting_date < statement.start_date) or (transaction.posting_date > statement.end_date):
                diagnostics.append(
                    Diagnostic(
                        code="transaction.posting_date.outside_statement",
                        message=(
                            f"Posting date at {row} is outside statement range "
                            f"{statement.start_date:%Y-%m-%d} through {statement.end_date:%Y-%m-%d}."
                        ),
                        severity=DiagnosticSeverity.ERROR,
                    )
                )

            # Transaction date (if available) must be within 60 days of the posting date
            # Foreign transactions in particular can take over a month to post
            posting_days = 60
            if transaction.transaction_date:
                if not isinstance(transaction.transaction_date, date):
                    diagnostics.append(
                        Diagnostic(
                            code="transaction.transaction_date.invalid",
                            message=f"Invalid transaction date type at {row}.",
                            severity=DiagnosticSeverity.ERROR,
                        )
                    )
                elif isinstance(transaction.posting_date, date) and (
                    abs((transaction.transaction_date - transaction.posting_date).days) > posting_days
                ):
                    diagnostics.append(
                        Diagnostic(
                            code="transaction.dates.unusual_gap",
                            message=(
                                f"Transaction and posting dates at {row} are more than {posting_days} days apart."
                            ),
                            severity=DiagnosticSeverity.WARNING,
                        )
                    )

            # Amount, balance, and description must exist with correct type
            if not isinstance(transaction.amount, Decimal):
                diagnostics.append(
                    Diagnostic(
                        code="transaction.amount.invalid",
                        message=f"Invalid amount type at {row}.",
                        severity=DiagnosticSeverity.ERROR,
                    )
                )
            if not isinstance(transaction.balance, Decimal):
                diagnostics.append(
                    Diagnostic(
                        code="transaction.balance.invalid",
                        message=f"Invalid balance type at {row}.",
                        severity=DiagnosticSeverity.ERROR,
                    )
                )
            if not isinstance(transaction.desc, str):
                diagnostics.append(
                    Diagnostic(
                        code="transaction.description.invalid",
                        message=f"Invalid description type at {row}.",
                        severity=DiagnosticSeverity.ERROR,
                    )
                )
            elif transaction.desc.strip() == "":
                diagnostics.append(
                    Diagnostic(
                        code="transaction.description.empty",
                        message=f"Empty description at {row}.",
                        severity=DiagnosticSeverity.ERROR,
                    )
                )

    return diagnostics


def validate_balances(statement: Statement) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for account_number, account in enumerate(statement.accounts, start=1):
        # Ensure transaction amounts add up to statement balance difference
        balance_change = account.end_balance - account.start_balance
        sum_amounts = sum((transaction.amount for transaction in account.transactions), start=Decimal(0))
        discrepancy = abs(balance_change - sum_amounts)
        if discrepancy > Decimal("0.01"):
            diagnostics.append(
                Diagnostic(
                    code="account.balance.discrepancy",
                    message=(
                        f"Balance change for account {account_number} ({balance_change:.2f}) does not match "
                        f"the transaction sum ({sum_amounts:.2f}); discrepancy {discrepancy:.2f}."
                    ),
                    severity=DiagnosticSeverity.ERROR,
                )
            )

    return diagnostics


# Register validation checks
register_validation(validate_metadata)
register_validation(validate_transactions)
register_validation(validate_balances)
# register_validation(some_new_check)
