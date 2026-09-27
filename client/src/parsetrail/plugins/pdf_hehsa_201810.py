import re
from datetime import datetime
from decimal import Decimal

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import (
    PDFReader,
    find_param_in_line,
    find_regex_in_line,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_hehsa_201810"
    VERSION = "0.2.1"
    MIN_CLIENT_VERSION = "1.3.0"
    SUFFIX = ".pdf"
    COMPANY = "HealthEquity"
    STATEMENT_TYPE = "Health Savings Account Monthly Statement"
    SEARCH_STRING = "healthequity&&healthsavingsaccount"
    INSTRUCTIONS = (
        "Login to https://my.healthequity.com/, then"
        " navigate to My Account > View Statements."
        " Select a year and click the month of the statement."
        " Click the Save icon and save the PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%y"
    TRANSACTION_DATE = r"%m/%d/%Y"
    DATE_REGEX = re.compile(r"Period:\d{2}/\d{2}/\d{2}")
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}\s")

    def parse(self, reader: PDFReader) -> Statement:
        """Entry point

        Args:
            reader (PDFReader): pdfplumber child class

        Returns:
            Statement: Statement dataclass
        """
        logger.trace(f"Parsing {self.STATEMENT_TYPE} statement")

        try:
            # Some statement table borders are extracted as leading underscores.
            self.lines = [line.lstrip("_ ") for line in reader.extract_lines_simple()]
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")

            self.reader = reader
            return self.extract_statement()
        except Exception as e:
            logger.error("Parser {} failed with {}.", self.PLUGIN_NAME, type(e).__name__)
            raise

    def extract_statement(self) -> Statement:
        """Extracts all statement data

        Returns:
            Statement: Statement dataclass
        """
        self.get_statement_dates()
        accounts = self.extract_accounts()
        if not accounts:
            raise ValueError("No accounts were extracted from the statement.")

        return Statement(
            start_date=self.start_date,
            end_date=self.end_date,
            accounts=accounts,
        )

    def get_statement_dates(self) -> None:
        """
        Parse the statement date range into datetime.

        Raises:
            ValueError: If dates cannot be parsed or are invalid.
        """
        logger.trace("Attempting to parse dates from text.")
        try:
            _, date_line, _ = find_regex_in_line(self.lines, self.DATE_REGEX)
            date_line_r = date_line.split("Period:")[-1]
            dates = [d.strip() for d in date_line_r.split("through")]
            self.start_date = datetime.strptime(dates[0], self.HEADER_DATE)
            self.end_date = datetime.strptime(dates[1], self.HEADER_DATE)
        except Exception as e:
            logger.trace(f"Failed to parse dates from text: {e}")
            raise ValueError(f"Failed to parse statement dates: {e}")

    def extract_accounts(self) -> list[Account]:
        """
        One account per statement

        Returns:
            list[Account]: List of accounts for this statement.
        """
        return [self.extract_account()]

    def extract_account(self) -> Account:
        """
        Extracts account-level data, including balances and transactions.

        Args:
            account_num (str): The account number.
            lines (list[str]): The lines of text corresponding to the account section.

        Returns:
            Account: The extracted account as a dataclass instance.

        Raises:
            ValueError: If account number is invalid or data extraction fails.
        """
        # Extract account number
        try:
            account_num = self.extract_account_number()
        except Exception as e:
            raise ValueError(f"Failed to extract account number: {e}")

        # Extract statement balances
        try:
            start_balance, end_balance, i_start, i_end = self.get_statement_balances()
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {account_num}: {e}")

        # Extract transaction lines
        try:
            transaction_lines = self.get_transaction_lines(i_start, i_end)
        except Exception as e:
            raise ValueError(f"Failed to extract transactions for account {account_num}: {e}")

        # Parse transactions
        try:
            transactions = self.parse_transaction_lines(transaction_lines)
        except Exception as e:
            raise ValueError(f"Failed to parse transactions for account {account_num}: {e}")

        # Validate against the independently printed cash closing balance. A
        # self-derived closing balance would hide truncated continuation pages.
        running = start_balance
        for transaction in transactions:
            running += transaction.amount
            if transaction.balance != running:
                raise ValueError("Parsed cash transaction does not reconcile to its printed running balance.")
        if running != end_balance:
            raise ValueError("Parsed cash activity does not reconcile to the printed ending balance.")

        # Return the Account dataclass
        return Account(
            account_num=account_num,
            start_balance=start_balance,
            end_balance=end_balance,
            transactions=transactions,
        )

    def extract_account_number(self) -> str:
        """
        Fidelity 401k statements don't have an account number.
        Instead retrieve the statement description (e.g. "Company 401k").
        First line that contains the word '401(k)' is assumed as account number.
        """
        search_str = "AccountNumber:"
        _, line = find_param_in_line(self.lines, search_str)
        rline = line.split(search_str)[-1]
        account_num = rline.split()[0]
        return account_num

    def get_statement_balances(self) -> tuple[Decimal, Decimal, int, int]:
        """Locate exactly one printed opening/closing cash boundary."""
        boundaries = []
        for label in ("BeginningBalance", "EndingBalance"):
            matches = [(index, line) for index, line in enumerate(self.lines) if line.startswith(label)]
            if len(matches) != 1:
                raise ValueError(f"Expected exactly one printed {label}.")
            index, line = matches[0]
            boundaries.append((parse_money(line.removeprefix(label).strip()), index))
        (opening, first), (closing, last) = boundaries
        if first >= last:
            raise ValueError("Printed cash balance boundaries are out of order.")
        return opening, closing, first, last

    def get_transaction_lines(self, i_start: int, i_end: int) -> list[str]:
        """
        Extract lines containing transaction information.

        Args:
            i_start (int): Index to start searching for transaction lines.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []
        # Rate/fee tables may be page footers before continued cash activity.
        # Only the printed ending cash balance closes this section; investment
        # portfolio rows following that boundary belong to a different scope.
        for line in self.lines[i_start + 1 : i_end]:
            # Check if the line starts with a valid date
            if self.LEADING_DATE.search(line):
                transaction_lines.append(line)

        return transaction_lines

    def parse_transaction_lines(self, transaction_lines: list[str]) -> list[Transaction]:
        """
        Converts the raw transaction text into an organized list of Transaction objects.

        Args:
            transaction_list (list[str]): List of raw transaction strings.

        Returns:
            list[Transaction]: Parsed transaction objects.
        """
        transactions = []

        for line in transaction_lines:
            # Split the line into words
            words = line.split()

            if len(words) < 3:
                raise ValueError(f"Invalid transaction line: {line}")

            # Get the date
            date_str = words[0]
            date = datetime.strptime(date_str, self.TRANSACTION_DATE)

            # Extract amount and balance
            try:
                amount = parse_money(words[-2])
                balance = parse_money(words[-1])
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Get the description
            desc = " ".join(words[1:-2])
            if not desc:
                desc = "Interest"

            # Create the Transaction object
            transaction = Transaction(
                transaction_date=date,
                posting_date=date,
                amount=amount,
                desc=desc,
                balance=balance,
            )

            transactions.append(transaction)

        return transactions
