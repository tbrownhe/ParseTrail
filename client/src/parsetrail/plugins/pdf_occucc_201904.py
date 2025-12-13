import re
from datetime import datetime, timedelta

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_startswith,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_occucc_201904"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Oregon Community Credit Union"
    STATEMENT_TYPE = "NICE Credit Card Monthly Statement"
    SEARCH_STRING = "www.myoccu.org&&cardservices"
    INSTRUCTIONS = "Login to https://myoccu.org/ and download the PDF statement for your account."

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

        try:
            # OCCU NICE statements require layout text extraction
            self.lines = reader.extract_lines_clean()
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
            close_str = "StatementClosingDate"
            ndays_str = "DaysinBillingCycle"
            _, close_line = find_line_startswith(self.lines, close_str)
            _, ndays_line = find_line_startswith(self.lines, ndays_str)

            close_line_r = close_line.split(close_str)[-1]
            ndays_line_r = ndays_line.split(ndays_str)[-1]
            end_date_str = close_line_r.split()[0]
            ndays_str = ndays_line_r.split()[0]
            ndays = int(ndays_str)

            self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)
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
            account_num = self.extract_account_number()
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

        # Append any interest charges to transactions
        try:
            transactions.append(self.interest_transaction())
        except Exception as e:
            raise ValueError(f"Failed to parse interest charge for account {account_num}: {e}")

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
        search_str = "AccountNumber "
        _, line = find_line_startswith(self.lines, search_str)
        rline = line.split(search_str)[-1]
        return rline.split()[0]

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["PreviousBalance", "NewBalance"]
        balances = {}

        for pattern in patterns:
            try:
                _, balance_line = find_line_startswith(self.lines, pattern)
                balance_str = balance_line.split(pattern)[-1].strip().split()[0]
                balances[pattern] = -convert_amount_to_float(balance_str)
                logger.trace(f"Extracted {pattern}: {balances[pattern]}")
            except ValueError as e:
                logger.warning(f"Failed to extract balance for pattern '{pattern}': {e}")

        # Ensure both balances are found
        if len(balances) != len(patterns):
            missing = [p for p in patterns if p not in balances]
            raise ValueError(f"Could not extract balances for patterns: {', '.join(missing)}")

        return balances[patterns[0]], balances[patterns[1]]

    def get_transaction_lines(self) -> list[str]:
        """
        Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []
        for line in self.lines:
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

            # Convert leading mm/dd to full datetime
            posting_date = get_absolute_date(words.pop(0), self.start_date, self.end_date)

            # If there is a second date, it is the transaction date
            if words and self.DATE_REGEX.search(words[0]):
                transaction_date = get_absolute_date(words.pop(0), self.start_date, self.end_date)
            else:
                # The single date is the posting date
                transaction_date = posting_date

            # Extract amount
            try:
                amount = -convert_amount_to_float(words[-1])
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Get the description
            desc = " ".join(words[:-1])
            if not desc:
                raise ValueError(f"Missing description in transaction line: {line}")

            # Create the Transaction object
            transaction = Transaction(
                transaction_date=transaction_date,
                posting_date=posting_date,
                amount=amount,
                desc=desc,
            )

            transactions.append(transaction)

        return transactions

    def interest_transaction(self) -> Transaction:
        """OCCU NICE statements show interest charges in the header
        instead of their own transaction line.

        Returns:
            Transaction: Interest charge
        """
        pattern = "InterestCharged"

        try:
            _, amount_line = find_line_startswith(self.lines, pattern)
            amount_str = amount_line.split()[2]
            amount = -convert_amount_to_float(amount_str)
            logger.trace(f"Extracted {pattern}: {amount}")
        except ValueError as e:
            logger.warning(f"Failed to extract balance for pattern '{pattern}': {e}")
            raise ValueError(f"Could not extract balances for pattern: {pattern}")

        return Transaction(
            transaction_date=self.end_date,
            posting_date=self.end_date,
            amount=amount,
            desc="Interest Charged",
        )
