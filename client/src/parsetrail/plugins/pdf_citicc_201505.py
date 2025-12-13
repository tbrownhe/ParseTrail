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
    PLUGIN_NAME = "pdf_citicc_201505"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Citibank"
    STATEMENT_TYPE = "Credit Account Monthly Statement"
    SEARCH_STRING = "www.citicards.com"
    INSTRUCTIONS = (
        "Login to https://www.citi.com/, then navigate to your account."
        " Click 'View Statements', then click 'View All Statements'."
        " Select the year, then click 'Download' to the right of"
        " the statement date."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%y"
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}\s")
    TRANSACTION_DATE = re.compile(r"\d{2}/\d{2}")
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
            lines = reader.extract_lines_clean()
            if not lines:
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
            _, dateline = find_line_startswith(self.reader.lines_clean, "Billing Period:")
            parts = dateline.split(":")[1].split()[0]
            self.start_date, self.end_date = [datetime.strptime(date, self.HEADER_DATE) for date in parts.split("-")]
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
            start_balance=self.start_balance,
            end_balance=self.end_balance,
            transactions=transactions,
        )

    def get_account_number(self) -> str:
        """Retrieve the account number from the statement.

        Returns:
            str: Account number
        """
        search_str = "Account number ending in:"
        _, line = find_param_in_line(self.reader.lines_clean, search_str)
        account_num = line.split(search_str)[-1].split()[0].strip()
        return account_num

    def get_statement_balances(self) -> None:
        """Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract balances
        """
        patterns = ["Previous balance ", "New balance "]
        balances = []

        for pattern in patterns:
            try:
                _, balance_line = find_param_in_line(self.reader.lines_clean, pattern)
                balance_str = balance_line.split()[-1]
                balance = -convert_amount_to_float(balance_str)
                balances.append(balance)
            except ValueError as e:
                raise ValueError(f"Failed to extract balance for pattern '{pattern}': {e}")

        if len(balances) != 2:
            raise ValueError("Could not extract both starting and ending balances.")

        self.start_balance, self.end_balance = balances

    def get_transaction_lines(self) -> list[str]:
        """Extract lines containing transaction information.

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement
        """
        transaction_lines = []
        for i, page in enumerate(self.reader.pages_layout):
            try:
                transaction_lines.extend(self.get_transactions_from_page(page))
            except Exception as e:
                raise ValueError(f"Failed to extract transactions from page {i}: {e}")
        return transaction_lines

    def get_transactions_from_page(self, page: str) -> list[str]:
        """Extracts transaction lines from each page of the pdf.
        Lines must start with a date and include an amount.
        Multi-line transactions are concatenated until an amount
        is found or the next transaction starts.

        Args:
            page (str): Extracted via the pdfplumber.extract_text(layout=True) method

        Returns:
            list[str]: Processed lines containing dates and amounts for this page
        """
        # Get the raw lines and word array for this page
        lines_raw = [line for line in page.splitlines() if line.strip()]
        word_array = [[word for word in line.split()] for line in lines_raw]
        lines_clean = [" ".join(words) for words in word_array]

        # Find the line containing the transaction table header
        search_words = ["date", "description", "amount"]
        header = None
        for line in lines_raw:
            if all(word in line.lower().split() for word in search_words):
                header = line.lower()
                break

        if header is None:
            # No transactions on this page
            return []

        # Get the index of the end of "Amount"
        # No valid words start past this index
        max_index = header.index("amount") + len("amount")

        def has_date(line: str) -> bool:
            """Check if a line starts with a valid date."""
            return bool(re.search(self.LEADING_DATE, line))

        def has_amount(line: str) -> bool:
            """Check if a line contains an amount."""
            return bool(re.search(self.AMOUNT, line))

        def truncate_words(line: str, max_index: int) -> str:
            """Do not include words that start farther than max_index unless there is
            only a single space between the last included word and the current word.
            """
            words, start, last_end = [], 0, -1
            for word in line.split():
                start = line.find(word, start)
                if start > max_index and (last_end == -1 or start - last_end > 1):
                    break
                words.append(word)
                last_end = start + len(word)
                start += len(word)
            return " ".join(words)

        # Identify indices of potential transaction start lines
        transaction_indices = [i for i, line in enumerate(lines_clean) if has_date(line)]

        # Process each potential transaction line
        transaction_lines = []
        max_lookahead = 5
        for i in transaction_indices:
            line = truncate_words(lines_raw[i], max_index)

            # Look ahead for multi-line transactions
            for k in range(1, max_lookahead + 1):
                if has_amount(line):
                    break
                next_index = i + k
                if next_index >= len(lines_raw) or next_index in transaction_indices:
                    # Stop if end of document or next transaction start is reached
                    break
                next_line = truncate_words(lines_raw[next_index], max_index)
                line = f"{line} {next_line}"

            if has_amount(line):
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

            # Convert leading mm/dd to full datetime
            mmdd = words.pop(0)
            transaction_date = get_absolute_date(mmdd, self.start_date, self.end_date)

            # If there is a second date, it is the posting date
            if words and re.search(self.TRANSACTION_DATE, words[0]):
                mmdd = words.pop(0)
                posting_date = get_absolute_date(mmdd, self.start_date, self.end_date)
            else:
                # The single date is the posting date
                posting_date = transaction_date

            # Extract the first amount-like string
            i_amount, amount_str = [(i, word) for i, word in enumerate(words) if re.search(self.AMOUNT, word)][0]
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
