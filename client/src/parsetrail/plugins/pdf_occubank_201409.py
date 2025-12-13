import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_re_search,
    find_line_startswith,
    find_param_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_occubank_201409"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Oregon Community Credit Union"
    STATEMENT_TYPE = "Checking & Savings Monthly Statement"
    SEARCH_STRING = "oregon community credit union&&membernumber"
    INSTRUCTIONS = "Login to https://myoccu.org/ and download the PDF statement for your account."

    # Parsing constants
    FROM_DATE = re.compile(r"FROM \d{2}/\d{2}/\d{2}")
    TO_DATE = re.compile(r"TO \d{2}/\d{2}/\d{2}")
    HEADER_DATE = r"%m/%d/%y"
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
            self.lines = reader.extract_lines_simple()
            self.text = reader.text_simple
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
            self.dates_from_text()
        except Exception as e1:
            logger.trace(f"Failed to parse dates from text: {e1}")
            try:
                logger.trace("Attempting to parse dates from annotations.")
                self.dates_from_annotations()
            except Exception as e2:
                logger.error(f"Failed to parse dates from annotations: {e2}")
                errors = "\n".join([str(e1), str(e2)])
                raise ValueError(f"Failed to parse statement dates:\n{errors}")

    def dates_from_text(self):
        """
        Extract dates from text lines.

        Raises:
            ValueError: If FROM or TO dates are not found or cannot be parsed.
        """
        _, from_line = find_line_re_search(self.lines, self.FROM_DATE)
        _, to_line = find_line_re_search(self.lines, self.TO_DATE)

        # Parse the lines into datetime
        start_date_str = from_line.split()[1]
        end_date_str = to_line.split()[1]
        self.start_date = datetime.strptime(start_date_str, self.HEADER_DATE)
        self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)
        logger.trace(f"Parsed dates from text: {self.start_date} to {self.end_date}")

    def dates_from_annotations(self):
        """
        Extract dates from annotations.

        Raises:
            KeyError: If annotations are missing or do not match the expected pattern.
        """
        page = self.reader.PDF.pages[0]
        start_date_str = self.extract_from_annotations(page, "FROM_DATE")
        end_date_str = self.extract_from_annotations(page, "TO_DATE")
        self.start_date = datetime.strptime(start_date_str, self.HEADER_DATE)
        self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)
        logger.trace(f"Parsed dates from annotations: {self.start_date} to {self.end_date}")

    def extract_from_annotations(self, page, pattern: str) -> str:
        """
        Extracts the value of a PDF page annotation matching a pattern.

        Args:
            page: The pdfplumber page object.
            pattern: The prefix pattern of the annotation title to search for.

        Returns:
            str: The value of the matching annotation.

        Raises:
            KeyError: If no annotation matches the given pattern.
        """
        for annot in page.annots or []:
            title = annot.get("title")
            if title and title.startswith(pattern):
                value = annot["data"]["V"].decode("utf-8")
                logger.trace(f"Found annotation for {pattern}: {value}")
                return value
        raise KeyError(f"Unable to find {pattern} in page annotations.")

    def extract_accounts(self) -> list[Account]:
        """
        Split the statement text into account sections and extract account details.

        Returns:
            list[Account]: List of accounts for this statement.
        """
        # Section markers
        sections = {
            "savings": "PRIMARY SAVINGS",
            "checking": "REMARKABLE CHECKING",
            "other": "XXXXX",
            "loan": "PERSONAL CREDIT LINE",
        }

        # Determine line indices for each section
        i_sav, sav_line = find_param_in_line(self.lines, sections["savings"])
        i_chk, chk_line = find_param_in_line(self.lines, sections["checking"], start=i_sav + 1)

        i_other = (
            find_line_startswith(self.lines, sections["other"], start=i_chk + 1)[0]
            if sections["other"] in self.text
            else float("inf")
        )
        i_loan = find_param_in_line(self.lines, sections["loan"])[0] if sections["loan"] in self.text else float("inf")

        # Determine the maximum valid index
        i_max = min(i_other, i_loan, len(self.lines))

        # Extract lines for each section
        lines_sav = self.lines[i_sav:i_chk]
        lines_chk = self.lines[i_chk:i_max]

        # Extract account numbers
        account_sav = sav_line.split()[0]
        account_chk = chk_line.split()[0]

        # Validate account numbers
        if not account_sav or not account_chk:
            raise ValueError("Failed to extract valid account numbers.")

        # Create accounts
        account_dict = {account_chk: lines_chk, account_sav: lines_sav}
        accounts = [self.extract_account(account_num, lines) for account_num, lines in account_dict.items()]

        return accounts

    def extract_account(self, account_num: str, lines: list[str]) -> Account:
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
        # Extract statement balances
        try:
            start_balance, end_balance = self.get_statement_balances(lines)
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {account_num}: {e}")

        # Extract transaction lines
        try:
            transaction_lines = self.get_transaction_lines(lines)
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

    def get_statement_balances(self, lines: list[str]) -> tuple[float, float]:
        """
        Extract the starting and ending balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["Previous Balance", "Ending Balance"]
        balances = {}

        for pattern in patterns:
            try:
                _, balance_line = find_param_in_line(lines, pattern)
                balance_str = balance_line.split()[-1].strip()
                balances[pattern] = convert_amount_to_float(balance_str)
                logger.trace(f"Extracted {pattern}: {balances[pattern]}")
            except ValueError as e:
                logger.warning(f"Failed to extract balance for pattern '{pattern}': {e}")

        # Ensure both balances are found
        if len(balances) != len(patterns):
            missing = [p for p in patterns if p not in balances]
            raise ValueError(f"Could not extract balances for patterns: {', '.join(missing)}")

        return balances["Previous Balance"], balances["Ending Balance"]

    def get_transaction_lines(self, lines: list[str]) -> list[str]:
        """
        Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """

        def is_transaction_line(line: str) -> bool:
            words = line.split()
            return len(words) >= 2 and "$" in words[-2] and "$" in words[-1]

        def has_leading_date(pattern, line: str) -> bool:
            return bool(re.search(pattern, line))

        transaction_lines = []

        for line in lines:
            # Process only lines with a leading date, amount, and balance
            if has_leading_date(self.LEADING_DATE, line) and is_transaction_line(line):
                transaction_lines.append(line)

        return transaction_lines

    def parse_transaction_lines(self, transaction_list: list[str]) -> list[Transaction]:
        """
        Converts the raw transaction text into an organized list of Transaction objects.

        Args:
            transaction_list (list[str]): List of raw transaction strings.

        Returns:
            list[Transaction]: Parsed transaction objects.
        """
        transactions = []

        for line in transaction_list:
            # Split the line into words
            words = line.split()

            if len(words) < 3:
                raise ValueError(f"Invalid transaction line: {line}")

            # Extract date and convert to datetime
            date_str = words[0]
            date = get_absolute_date(date_str, self.start_date, self.end_date)

            # Extract amount and balance
            try:
                amount = convert_amount_to_float(words[-2])
                balance = convert_amount_to_float(words[-1])
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Handle optional "#" token after date
            desc_start = 1 if words[1] != "#" else 2

            # Extract description
            desc = " ".join(words[desc_start:-2]).strip()

            # Validate description
            if not desc:
                raise ValueError(f"Missing description in transaction line: {line}")

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
