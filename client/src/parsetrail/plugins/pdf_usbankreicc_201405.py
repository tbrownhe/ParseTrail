import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_startswith,
    find_param_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_usbankreicc_201405"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "US Bank"
    STATEMENT_TYPE = "REI Credit Card Monthly Statement"
    SEARCH_STRING = "u.s. bank&&(reivisa.com||reimastercard.com)"
    INSTRUCTIONS = (
        "For existing PDFs only. REI transitioned their member Credit Card"
        " to Capital One, so it is not possible to download statements"
        " for this plugin."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"
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
            self.lines_simple = reader.extract_lines_simple()
            self.lines = self.extract_lines_from_reader()
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")
            return self.extract_statement()
        except Exception as e:
            logger.error(f"Error parsing {self.STATEMENT_TYPE} statement: {e}")
            raise

    def extract_lines_from_reader(self) -> list[str]:
        """Uses custom pdfplumber layout tolerances to exclude
        QR code embedded in statement so metadata extraction is possible

        Returns:
            list[str]: Whitespace normalized text extracted from pdf
        """
        pages = [
            page.extract_text(layout=True, x_tolerance=0.5, y_tolerance=0.5) or "" for page in self.reader.PDF.pages
        ]
        text = "\n".join(pages)
        lines_raw = [line for line in text.splitlines() if line.strip()]
        lines_clean = [" ".join(line.split()) for line in lines_raw]
        return lines_clean

    def extract_statement(self) -> Statement:
        """Extracts all statement data

        Returns:
            Statement: Statement dataclass
        """
        self.get_statement_metadata()
        accounts = self.extract_accounts()
        if not accounts:
            raise ValueError("No accounts were extracted from the statement.")

        return Statement(
            start_date=self.start_date,
            end_date=self.end_date,
            accounts=accounts,
        )

    def get_statement_metadata(self) -> None:
        """
        Parse the statement date range into datetime.
        Must use lines extracted via custom layout tolerance

        Raises:
            ValueError: If dates cannot be parsed or are invalid.

        Notes:
            self.start_date, self.end_date, and self.account_num are set
        """
        logger.trace("Attempting to parse dates from text.")
        patterns = {
            "start_date": "Open Date:",
            "end_date": "Closing Date:",
            "account_num": "Account:",
        }
        values = {}
        try:
            _, info_line = find_param_in_line(self.lines, patterns["start_date"])
            for key, pattern in patterns.items():
                right_str = info_line.split(pattern)[-1].strip()
                parts = right_str.split()
                if key == "account_num":
                    values[key] = "".join(parts)
                else:
                    values[key] = parts[0]

            self.start_date = datetime.strptime(values["start_date"], self.HEADER_DATE)
            self.end_date = datetime.strptime(values["end_date"], self.HEADER_DATE)
            self.account_num = values["account_num"]
        except Exception as e:
            logger.trace(f"Failed to parse metadata from text: {e}")
            raise ValueError(f"Failed to metadata statement dates: {e}")

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
        # Account number is extracted via self.get_statement_metadata before this
        # account_num = self.extract_account_number()

        # Extract statement balances
        try:
            start_balance, end_balance = self.get_statement_balances()
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {self.account_num}: {e}")

        # Extract transaction lines
        try:
            transaction_lines = self.get_transaction_lines()
        except Exception as e:
            raise ValueError(f"Failed to extract transactions for account {self.account_num}: {e}")

        # Parse transactions
        try:
            transactions = self.parse_transaction_lines(transaction_lines)
        except Exception as e:
            raise ValueError(f"Failed to parse transactions for account {self.account_num}: {e}")

        # Return the Account dataclass
        return Account(
            account_num=self.account_num,
            start_balance=start_balance,
            end_balance=end_balance,
            transactions=transactions,
        )

    def extract_account_number(self) -> str:
        """Retrieve the account number from the statement
        This is handled in get_statement_metadata() for this parser

        Returns:
            str: Account number
        """
        pass

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["Previous Balance", "New Balance"]
        balances = {}

        for pattern in patterns:
            try:
                _, balance_line = find_line_startswith(self.lines, pattern)
                balance_str = balance_line.split()[-1]
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
        Must use lines extracted via simple method, since it groups the
        dates, desc, amount, and `CR` credit indicator consistently.
        USBank statement format changed slightly in 05/2017 making this necessary.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []
        for line in self.lines_simple:
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
