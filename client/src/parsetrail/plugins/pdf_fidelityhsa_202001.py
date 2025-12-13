import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_startswith,
    find_param_in_line,
    find_regex_in_line,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_fidelityhsa_202001"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Fidelity"
    STATEMENT_TYPE = "Health Savings Account Monthly Statement"
    SEARCH_STRING = "FIDELITY HEALTH SAVINGS ACCOUNT"
    INSTRUCTIONS = (
        "Login to https://www.fidelity.com and navigate to your HSA account."
        " Click 'Documents', then select the time range if necessary."
        " Click the Download icon and click 'Download as PDF'."
        " Click the Save icon and save the PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%B %d, %Y"
    DATE_REGEX = re.compile(r"[ADFJMNOS]\w*\s\d{1,2}\,\s\d{4}\s-\s")

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
        try:
            logger.trace("Attempting to parse dates from text.")

            _, date_line, _ = find_regex_in_line(self.lines, self.DATE_REGEX)
            date_strs = [word.strip() for word in date_line.split("-")]
            self.start_date = datetime.strptime(date_strs[0], self.HEADER_DATE)
            self.end_date = datetime.strptime(date_strs[1], self.HEADER_DATE)
        except Exception as e:
            logger.trace(f"Failed to parse dates from text: {e}")
            raise ValueError(f"Failed to parse statement dates: {e}")

    def extract_accounts(self) -> list[Account]:
        """
        One account per Fidelity HSA statement

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
        search_str = "Account Number:"
        _, line = find_param_in_line(self.lines, search_str)
        rline = line.split(search_str)[-1]
        account_num = rline.split()[0]
        return account_num

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting and ending balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["Beginning Account Value", "Ending Account Value"]
        balances = {}
        indices = {}

        for pattern in patterns:
            try:
                i_line, balance_line = find_line_startswith(self.lines, pattern)
                balance_str = balance_line.split()[-2]
                balance_str = "0" if balance_str == "-" else balance_str
                indices[pattern] = i_line
                balances[pattern] = convert_amount_to_float(balance_str)
                logger.trace(f"Extracted {pattern}: {balances[pattern]}")
            except ValueError as e:
                logger.warning(f"Failed to extract balance for pattern '{pattern}': {e}")

        # Ensure both balances are found
        missing = [p for p in patterns if p not in balances]
        if missing:
            raise ValueError(f"Could not extract balances for patterns: {', '.join(missing)}")

        return (
            balances[patterns[0]],
            balances[patterns[1]],
            indices[patterns[0]],
            indices[patterns[1]],
        )

    def get_transaction_lines(self, i_start: int, i_end: int) -> list[str]:
        """
        Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        return self.lines[i_start + 1 : i_end]

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

            # Extract amount
            amount_str = "0" if words[-2] == "-" else words[-2]
            try:
                amount = convert_amount_to_float(amount_str)
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Extract description
            desc = " ".join(words[:-2]).replace("*", "")

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
