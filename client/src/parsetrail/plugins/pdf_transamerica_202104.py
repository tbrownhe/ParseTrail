import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_startswith,
    find_param_in_line,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_transamerica_202104"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Transamerica"
    STATEMENT_TYPE = "Retirement Savings Account Quarterly Statement"
    SEARCH_STRING = "transamerica&&retirement account statement"
    INSTRUCTIONS = "Login to https://www.transamerica.com/ and download your quarterly statement as PDF"

    # Parsing constants
    HEADER_DATE = r"%B %d, %Y"
    DATE_REGEX = re.compile(r"([A-Za-z]+\s\d{1,2},\s\d{4})\s-\s([A-Za-z]+\s\d{1,2},\s\d{4})")
    AMOUNT = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")

    def parse(self, reader: PDFReader) -> Statement:
        """Entry point

        Args:
            reader (PDFReader): pdfplumber child class

        Returns:
            Statement: Statement dataclass
        """
        logger.trace(f"Parsing {self.STATEMENT_TYPE} statement")
        try:
            self.lines = reader.extract_lines_simple()
            # self.text = reader.text_simple
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")

            self.reader = reader
            return self.extract_statement()
        except Exception as e:
            logger.error(f"Error parsing {self.STATEMENT_TYPE} statement: {e}")
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
            results = self.DATE_REGEX.search(self.reader.text_simple)
            start_date_str = results.group(1)
            end_date_str = results.group(2)
            self.start_date = datetime.strptime(start_date_str, self.HEADER_DATE)
            self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)
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

        # Return the Account dataclass
        return Account(
            account_num=account_num,
            start_balance=start_balance,
            end_balance=end_balance,
            transactions=transactions,
        )

    def extract_account_number(self) -> str:
        """Retrieve the account  number from the statement

        Returns:
            str: Account number
        """
        search_str = " 401(k) Plan "
        _, line = find_param_in_line(self.lines, search_str, case_sensitive=False)
        words = line.split()
        return words[0]

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting and ending balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        try:
            # Get starting balance
            pattern = "Beginning Balance"
            i_start, balance_line = find_line_startswith(self.lines, pattern)
            balance_str = balance_line.split(pattern)[-1].strip().split()[0]
            start_balance = convert_amount_to_float(balance_str)
            logger.trace(f"Extracted {pattern}: {start_balance}")

            # Get ending balance
            pattern = "Ending Balance"
            i_end, balance_line = find_line_startswith(self.lines, pattern, start=i_start + 1)
            balance_str = balance_line.split(pattern)[-1].strip().split()[0]
            end_balance = convert_amount_to_float(balance_str)
            logger.trace(f"Extracted {pattern}: {end_balance}")
        except ValueError as e:
            logger.warning(f"Failed to extract balance for pattern '{pattern}': {e}")

        return start_balance, end_balance, i_start, i_end

    def get_transaction_lines(self, i_start: int, i_end: int) -> list[str]:
        """
        Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []

        for line in self.lines[i_start + 1 : i_end]:
            if any("$" in word for word in line.split()[1:4]):
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

            result = [(i, word) for i, word in enumerate(words) if self.AMOUNT.search(word)]
            if not result:
                # Skip this line, it's not a transaction line
                continue

            # Extract amount and balance
            i_amount, amount_str = result[0]
            try:
                amount = convert_amount_to_float(amount_str)
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Extract description
            desc = " ".join(words[:i_amount])

            # Validate description
            if not desc:
                raise ValueError(f"Missing description in transaction line: {line}")

            # Create the Transaction object
            transaction = Transaction(
                transaction_date=self.end_date,
                posting_date=self.end_date,
                amount=amount,
                desc=desc,
            )

            transactions.append(transaction)

        return transactions
