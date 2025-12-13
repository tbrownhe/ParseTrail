import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import PDFReader, convert_amount_to_float, find_param_in_line
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_capitaloneauto_202402"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Capital One"
    STATEMENT_TYPE = "Auto Finance Monthly Statement"
    SEARCH_STRING = "capital one auto finance"
    INSTRUCTIONS = (
        "Login to https://www.capitalone.com/."
        " Navigate to your auto loan account."
        " Click View Statements, then in the window that appears,"
        " select the statement date you want and click Download."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"
    DATE_REGEX = re.compile(r"\d{2}/\d{2}/\d{4}")
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}")
    AMOUNT = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")

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
            pattern = re.compile(r"Transactions between (\d{2}/\d{2}/\d{4}) - (\d{2}/\d{2}/\d{4})")
            result = pattern.search(self.reader.text_simple)
            self.start_date = datetime.strptime(result.group(1), self.HEADER_DATE)
            self.end_date = datetime.strptime(result.group(2), self.HEADER_DATE)
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
            self.get_statement_balances()
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {account_num}: {e}")

        # Parse transactions
        try:
            transactions = self.parse_transaction_lines()
        except Exception as e:
            raise ValueError(f"Failed to parse transactions for account {account_num}: {e}")

        return Account(
            account_num=account_num,
            start_balance=round(self.start_balance, 2),
            end_balance=self.end_balance,
            transactions=transactions,
        )

    def get_account_number(self) -> str:
        """Retrieve the account number from the statement.

        Returns:
            str: Account number
        """
        pattern = "Account Number:"
        _, line = find_param_in_line(self.lines, pattern)
        account_num = line.split(pattern)[-1].strip().split()[0]
        return account_num

    def get_statement_balances(self) -> None:
        """Extract the starting balance from the statement.
        Only the ending principle balance is given.
        Starting balance must be estimated from transaction.

        Raises:
            ValueError: Unable to extract balances
        """
        pattern = "Principal Balance:"
        try:
            _, balance_line = find_param_in_line(self.lines, pattern)
            balance_str = balance_line.split(pattern)[-1].strip().split()[0]
            self.end_balance = -convert_amount_to_float(balance_str)
        except ValueError as e:
            raise ValueError(f"Failed to extract balance for pattern '{pattern}': {e}")

    def parse_transaction_lines(self) -> list[Transaction]:
        """Convert raw transaction table into structured data.

        Returns:
            list[tuple]: Unsorted transaction array
        """

        def column_names(lines: list[str]):
            # Get the column headers
            for i, line in enumerate(lines):
                if all(word in line for word in ["Date", "Description", "Principal", "Total"]):
                    return i, line.split()
            raise ValueError("Column header not found in statement")

        # Get the header position and column names
        i, columns = column_names(self.lines)

        # Get the entries in the table.
        transaction_lines = []
        for line in self.lines[i + 1 :]:
            if self.LEADING_DATE.search(line):
                transaction_lines.append(line)
            else:
                # reached end of table
                break

        self.start_balance = float(self.end_balance)
        transactions = []
        for line in transaction_lines:
            words = line.split()

            if len(words) < len(columns):
                raise ValueError(f"Invalid transaction line: {line}")

            # Remove equals sign
            if words[-2] == "=":
                words.pop(-2)

            # Get date
            posting_date = datetime.strptime(words[0], self.HEADER_DATE)

            # Get the amounts
            amounts = {}
            for i, col in enumerate(reversed(columns)):
                if col == "Principal":
                    break
                amount = convert_amount_to_float(words[-1 - i])
                amounts[col] = amount if col == "Interest" else -amount

            # Get the description
            desc = " ".join(words[1 : -i - 1])

            # Melt the table into a transaction list
            for col, amount in amounts.items():
                self.start_balance -= amount
                if col == "Total":
                    transactions.append(
                        Transaction(
                            transaction_date=posting_date,
                            posting_date=posting_date,
                            amount=amount,
                            desc=desc,
                        )
                    )
                elif col == "Interest":
                    transactions.append(
                        Transaction(
                            transaction_date=posting_date,
                            posting_date=posting_date,
                            amount=amount,
                            desc="Interest Fee",
                        )
                    )
                else:
                    raise ValueError(f"Unexpected column {col}")

        return transactions
