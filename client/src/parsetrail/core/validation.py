import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Union

from loguru import logger


# Exceptions
class ValidationError(Exception):
    pass


# Data structures
@dataclass
class Transaction:
    transaction_date: datetime
    posting_date: datetime
    amount: float
    desc: str
    balance: Optional[float] = None
    md5hash: Optional[str] = None

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        if not isinstance(self.transaction_date, datetime):
            errors.append(f"transaction_date must be datetime, got {type(self.transaction_date).__name__}")
        if not isinstance(self.posting_date, datetime):
            errors.append(f"posting_date must be datetime, got {type(self.posting_date).__name__}")
        if not isinstance(self.amount, float):
            errors.append(f"amount must be float, got {type(self.amount).__name__}")
        if not isinstance(self.desc, str):
            errors.append(f"desc must be str, got {type(self.desc).__name__}")
        if not self.desc:
            errors.append("desc cannot be empty")
        if self.balance is not None and not isinstance(self.balance, float):
            errors.append(f"balance must be float or None, got {type(self.balance).__name__}")
        if self.md5hash is not None and not isinstance(self.md5hash, str):
            errors.append(f"md5hash must be str or None, got {type(self.md5hash).__name__}")
        if errors:
            raise TypeError("\n".join(errors))

    @staticmethod
    def sort_and_compute_balances(transactions: list["Transaction"], start_balance: float) -> list["Transaction"]:
        """
        Sorts transactions by posting date and computes running balances.
        Note the sorted() method is stable and preserves transaction order
        of appearance within the same date.

        Args:
            transactions (list[Transaction]): List of transactions to process.
            start_balance (float): The starting balance for the account.

        Returns:
            list[Transaction]: Transactions sorted by posting date with computed balances.
        """
        if not transactions:
            return transactions

        sorted_transactions = sorted(transactions, key=lambda t: t.posting_date)

        # Check if all transactions already have balances
        if all(isinstance(t.balance, float) for t in sorted_transactions):
            logger.trace("Balances are already populated; skipping recalculation.")
            return sorted_transactions

        current_balance = start_balance
        for transaction in sorted_transactions:
            current_balance = round(current_balance + transaction.amount, 2)
            transaction.balance = current_balance

        return sorted_transactions

    @staticmethod
    def hash_transactions(account_id: int, transactions: list["Transaction"]) -> list["Transaction"]:
        """
        Generates and appends MD5 hashes for the transactions.
        """
        if any(not isinstance(t.balance, float) for t in transactions):
            raise ValueError(
                "All transactions must have valid balances to hash. Run the sort_and_compute_balances() method."
            )

        md5hash_set = set()
        for transaction in transactions:
            attempt = 0
            while True:
                # Build the hash string
                hash_str = "".join(
                    [
                        str(account_id),
                        transaction.posting_date.strftime(r"%Y-%m-%d"),
                        f"{transaction.amount:.2f}",
                        f"{transaction.balance:.2f}",
                        transaction.desc,
                        str(attempt),
                    ]
                )
                md5hash = hashlib.md5(hash_str.encode()).hexdigest()

                if md5hash not in md5hash_set:
                    md5hash_set.add(md5hash)
                    break

                logger.warning(f"Hash collision detected for transaction '{transaction.desc}'. Retrying...")
                attempt += 1

            transaction.md5hash = md5hash

        return transactions

    @staticmethod
    def to_db_rows(
        statement_id: Union[int, None],
        account_id: int,
        transactions: list["Transaction"],
    ) -> list[dict[str, Any]]:
        """
        Converts the Transaction instance to a tuple compatible with database insertion.

        Returns:
            tuple: A tuple of the transaction's fields in the required order.
        """
        rows = []
        for t in transactions:
            if not isinstance(t.balance, float):
                raise ValueError(f"Transaction {t.desc} is missing a balance and cannot be inserted.")
            if not isinstance(t.md5hash, str):
                raise ValueError(f"Transaction {t.desc} is missing an MD5 hash and cannot be inserted.")
            rows.append(
                {
                    "StatementID": statement_id,
                    "AccountID": account_id,
                    "Date": t.posting_date.strftime(r"%Y-%m-%d"),
                    "Amount": t.amount,
                    "Balance": t.balance,
                    "Description": t.desc,
                    "MD5": t.md5hash,
                }
            )
        return rows

    @staticmethod
    def validate_balances(transactions: list["Transaction"]) -> list[str]:
        """
        Validates that all transactions have valid balances.
        """
        errors = [
            f"Invalid balance for transaction: {t.desc}" for t in transactions if not isinstance(t.balance, float)
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
            if t.balance is not None and not isinstance(t.balance, (int, float)):
                errors.append(
                    f"Transaction {i + 1}: 'balance' must be a number or None, got {type(t.balance).__name__}."
                )

            # Validate md5
            if t.md5hash is not None and not isinstance(t.md5hash, str):
                errors.append(
                    f"Transaction {i + 1}: 'md5hash' must be a string or None, got {type(t.md5hash).__name__}."
                )

        return errors


@dataclass
class Account:
    account_num: str
    start_balance: float
    end_balance: float
    transactions: list[Transaction]
    account_id: Optional[int] = None
    account_name: Optional[str] = None
    statement_id: Optional[int] = None

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        if not isinstance(self.account_num, str):
            errors.append(f"account_num must be str, got {type(self.account_num).__name__}")
        if not isinstance(self.start_balance, float):
            errors.append(f"start_balance must be float, got {type(self.start_balance).__name__}")
        if not isinstance(self.end_balance, float):
            errors.append(f"end_balance must be float, got {type(self.end_balance).__name__}")
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
        self.transactions = Transaction.hash_transactions(self.account_id, self.transactions)

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
        if not isinstance(self.start_balance, float):
            errors.append("start_balance must be a float")
        if not isinstance(self.end_balance, float):
            errors.append("end_balance must be a float")
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
    start_date: datetime
    end_date: datetime
    accounts: list[Account]
    plugin_name: Optional[str] = None
    fpath: Optional[Path] = None
    dpath: Optional[Path] = None
    md5hash: Optional[str] = None

    def __post_init__(self):
        """Validate all inputs immediately after instantiation.

        Raises:
            TypeError: Any invalid types
        """
        errors = []
        if not isinstance(self.start_date, datetime):
            errors.append(f"start_date must be datetime, got {type(self.start_date).__name__}")
        if not isinstance(self.end_date, datetime):
            errors.append(f"end_date must be datetime, got {type(self.end_date).__name__}")
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
        if self.md5hash is not None and not isinstance(self.md5hash, str):
            errors.append(f"md5hash must be str or None, got {type(self.md5hash).__name__}")
        if errors:
            raise TypeError("\n".join(errors))

    def add_metadata(self, fpath: Path, plugin_name: str):
        if not isinstance(fpath, Path):
            raise ValidationError("fpath must be a Path")
        if not isinstance(plugin_name, str):
            raise ValidationError("plugin_name must be str")
        self.fpath = fpath
        self.plugin_name = plugin_name

    def add_md5hash(self, md5hash: str):
        if not isinstance(md5hash, str):
            raise ValidationError("md5hash must be a str")
        self.md5hash = md5hash

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
            "ImportDate": datetime.now().strftime(r"%Y-%m-%d"),
            "StartDate": self.start_date.strftime(r"%Y-%m-%d"),
            "EndDate": self.end_date.strftime(r"%Y-%m-%d"),
            "StartBalance": account.start_balance,
            "EndBalance": account.end_balance,
            "TransactionCount": len(account.transactions),
            "Filename": self.dpath.name,
            "MD5": self.md5hash,
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
        if not isinstance(self.md5hash, str):
            errors.append("md5hash must be str")
        return errors


# Validation framework
VALIDATION_CHECKS: list[Callable[[Statement], list[str]]] = []


def register_validation(check: Callable[[Statement], list[str]]):
    VALIDATION_CHECKS.append(check)


def validate_statement(statement: Statement):
    errors = []
    for check in VALIDATION_CHECKS:
        errors.extend(check(statement))
    return errors


# Validation functions
def validate_metadata(statement: Statement) -> list[str]:
    return statement.validate_metadata()


def validate_transactions(statement: Statement) -> list[str]:
    errors = []
    for account in statement.accounts:
        for transaction in account.transactions:
            # Posting date must be within the satement date range
            if not isinstance(transaction.posting_date, datetime):
                errors.append(f"Invalid date: {transaction.posting_date}")
            if (transaction.posting_date < statement.start_date) or (transaction.posting_date > statement.end_date):
                errors.append(
                    f"Transaction date {transaction.posting_date} is outside the statement"
                    f" date range {statement.start_date} - {statement.end_date}"
                )

            # Transaction date (if available) must be within 60 days of the posting date
            # Foreign transactions in particular can take over a month to post
            posting_days = 60
            if transaction.transaction_date:
                if not isinstance(transaction.transaction_date, datetime):
                    errors.append(f"Invalid date: {transaction.transaction_date}")
                if abs((transaction.transaction_date - transaction.posting_date).days) > posting_days:
                    errors.append(
                        f"Transaction date {transaction.transaction_date} is more than {posting_days} days"
                        f" from posting date {transaction.posting_date}"
                    )

            # Amount, balance, and description must exist with correct type
            if not isinstance(transaction.amount, float):
                errors.append(f"Invalid amount: {transaction.amount}")
            if not isinstance(transaction.balance, float):
                errors.append(f"Invalid balance: {transaction.balance}")
            if not isinstance(transaction.desc, str):
                errors.append(f"Invalid description: {transaction.desc}")
            if transaction.desc.strip() == "":
                errors.append(f"Empty description: {transaction}")

    return errors


def validate_balances(statement: Statement) -> list[str]:
    errors = []
    for account in statement.accounts:
        # Ensure transaction amounts add up to statement balance difference
        balance_change = account.end_balance - account.start_balance
        sum_amounts = sum(transaction.amount for transaction in account.transactions)
        discrepancy = abs(balance_change - sum_amounts)
        if discrepancy > 0.01:
            errors.append(
                f"Validation failed for account '{account.account_num}'. "
                f"Balance change ({balance_change:.2f}) does not match "
                f"sum of transactions ({sum_amounts:.2f}). Discrepancy: {discrepancy:.2f}"
            )

    return errors


# Register validation checks
register_validation(validate_metadata)
register_validation(validate_transactions)
register_validation(validate_balances)
# register_validation(some_new_check)
