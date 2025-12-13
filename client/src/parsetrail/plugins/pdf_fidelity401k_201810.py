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
    PLUGIN_NAME = "pdf_fidelity401k_201810"
    VERSION = "0.1.1"
    SUFFIX = ".pdf"
    COMPANY = "Fidelity"
    STATEMENT_TYPE = "Retirement Savings Monthly Statement"
    SEARCH_STRING = "Fidelity Brokerage Services&&Retirement Savings Statement"
    INSTRUCTIONS = (
        "Login to https://www.fidelity.com and navigate to your 401(k) account."
        " Click 'Statements', then select 'Monthly' for 'Time Period'."
        " Select the month and year you want, then click 'Get Statement'."
        " Click 'Download or Print This Statement', then save as PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"

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
            # Declare the search pattern and dateformat
            search_str = "Statement Period: "

            _, date_line = find_param_in_line(self.lines, search_str)
            date_line_r = date_line.split(search_str)[-1]

            date_strs = [word for word in date_line_r.split() if "/" in word]
            self.start_date = datetime.strptime(date_strs[0], self.HEADER_DATE)
            self.end_date = datetime.strptime(date_strs[1], self.HEADER_DATE)
        except Exception as e:
            logger.trace(f"Failed to parse dates from text: {e}")
            raise ValueError(f"Failed to parse statement dates: {e}")

    def extract_accounts(self) -> list[Account]:
        """
        One account per Fidelity statement

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
        Fidelity retirement savings statements don't contain an account number.
        Instead use the account description: First line containing text after
        "Statement Details", and before "Retirement Savings Statement"
        """
        row0, _ = find_param_in_line(self.lines, "Statement Details")
        row1, _ = find_param_in_line(self.lines, "Retirement Savings Statement")
        account = " ".join([line for line in self.lines[row0 + 1 : row1] if line])
        return account

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting and ending balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["Beginning Balance", "Ending Balance"]
        balances = {}
        indices = {}

        for pattern in patterns:
            try:
                i_line, balance_line = find_line_startswith(self.lines, pattern)
                balance_str = balance_line.split(pattern)[-1].strip()
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
            balances["Beginning Balance"],
            balances["Ending Balance"],
            indices["Beginning Balance"],
            indices["Ending Balance"],
        )

    def get_transaction_lines(self, i_start: int, i_end: int) -> list[str]:
        """
        Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []

        for line in self.lines[i_start + 1 : i_end]:
            if "$" in line:
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

            if len(words) < 2:
                raise ValueError(f"Invalid transaction line: {line}")

            # Extract amount and balance
            try:
                amount = convert_amount_to_float(words[-1])
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Extract description
            desc = " ".join(words[:-1])

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
