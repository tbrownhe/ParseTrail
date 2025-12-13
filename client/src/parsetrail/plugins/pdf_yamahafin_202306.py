import re
from datetime import datetime, timedelta

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_param_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_yamahafin_202306"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Yamaha Motor Finance"
    STATEMENT_TYPE = "Auto Loan Monthly Statement"
    SEARCH_STRING = "yamaha motor finance"
    INSTRUCTIONS = (
        "Login to https://www.yamahamotorfinanceusa.com/, then click"
        " Statement History. Click the statement date of a statement, then"
        " click the Save icon to download the PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%y"
    DATE_REGEX = re.compile(r"\d{2}/\d{2}")
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}\s")

    def parse(self, reader: PDFReader) -> Statement:
        """Entry point

        Args:
            reader (PDFReader): pdfplumber child class

        Returns:
            Statement: Statement dataclass
        """
        logger.trace(f"Parsing {self.STATEMENT_TYPE} statement")
        self.reader = reader
        try:
            self.lines = reader.extract_lines_simple()
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")
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
            pattern = re.compile(r"Closing Date (\d{2}/\d{2}/\d{2})")
            result = pattern.search(self.reader.text_simple)
            end_date_str = result.group(1)
            self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)

            pattern = re.compile(r"Days in Billing Cycle (\d{1,2})")
            result = pattern.search(self.reader.text_simple)
            ndays = int(result.group(1))
            self.start_date = self.end_date - timedelta(days=ndays - 1)
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
            account_num = self.get_account_number()
        except Exception as e:
            raise ValueError(f"Failed to extract account number: {e}")

        # Extract statement balances
        try:
            start_balance, end_balance = self.get_statement_balances()
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {account_num}: {e}")

        # Extract transaction lines
        try:
            transaction_lines = self.get_transaction_lines()
        except Exception as e:
            raise ValueError(f"Failed to extract transactions for account {account_num}: {e}")

        # Parse transactions
        try:
            transactions = self.parse_transaction_lines(transaction_lines)
        except Exception as e:
            raise ValueError(f"Failed to parse transactions for account {account_num}: {e}")

        return Account(
            account_num=account_num,
            start_balance=start_balance,
            end_balance=end_balance,
            transactions=transactions,
        )

    def get_account_number(self) -> str:
        """Retrieve the account number from the statement.

        Returns:
            str: Account number
        """
        pattern = "Account Number:"
        _, line = find_param_in_line(self.lines, pattern)
        account_num = "".join(line.split(pattern)[-1].split())
        return account_num

    def get_statement_balances(self) -> tuple[float, float]:
        """Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract balances
        """
        patterns = ["Previous Balance", "New Balance:"]
        balances = {}

        for pattern in patterns:
            try:
                _, balance_line = find_param_in_line(self.lines, pattern)
                balance_str = balance_line.split(pattern)[-1].strip().split()[0]
                balance = -convert_amount_to_float(balance_str)
                balances[pattern] = balance
            except ValueError as e:
                raise ValueError(f"Failed to extract balance for pattern '{pattern}': {e}")

        if len(balances) != 2:
            raise ValueError("Could not extract both starting and ending balances.")

        return balances[patterns[0]], balances[patterns[1]]

    def get_transaction_lines(self) -> list[str]:
        """Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement
        """
        transaction_lines = []
        for line in self.lines:
            if self.LEADING_DATE.search(line):
                transaction_lines.append(line)
        return transaction_lines

    def parse_transaction_lines(self, transaction_lines: list[str]) -> list[Transaction]:
        """Convert raw transaction lines into structured data.

        Args:
            transaction_lines (list[str]): Lines containing valid transaction data

        Returns:
            list[tuple]: Unsorted transaction array
        """
        transactions = []
        for line in transaction_lines:
            words = line.split()

            if len(words) < 3:
                raise ValueError(f"Invalid transaction line: {line}")

            # Convert leading mm/dd to full datetime
            mmdd = words.pop(0)
            transaction_date = get_absolute_date(words[0], self.start_date, self.end_date)

            # If there is a second date, it is the posting date
            if words and self.DATE_REGEX.search(words[0]):
                mmdd = words.pop(0)
                posting_date = get_absolute_date(mmdd, self.start_date, self.end_date)
            else:
                # The single date is the posting date
                posting_date = transaction_date

            # Extract the first amount-like string
            i_amount, amount_str = [(i, word) for i, word in enumerate(words) if "$" in word][0]
            amount = -convert_amount_to_float(amount_str)

            # Extract the description
            desc = " ".join(words[:i_amount])

            # Append transaction
            transactions.append(
                Transaction(
                    transaction_date=transaction_date,
                    posting_date=posting_date,
                    amount=amount,
                    desc=desc,
                )
            )

        return transactions
