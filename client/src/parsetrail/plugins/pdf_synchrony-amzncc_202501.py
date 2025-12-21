import re
from datetime import datetime
from statistics import median

from loguru import logger
from pdfplumber.page import Page
from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_param_in_line,
    find_regex_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_synchrony-amzncc_202501.py"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Synchrony"
    STATEMENT_TYPE = "Amazon Store Card by Synchrony Bank"
    SEARCH_STRING = "amazon.syf.com"
    INSTRUCTIONS = (
        "Login to amazon.syf.com, then navigate to your account."
        " Click 'View Statements', then download the statement"
        " for the date you need."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}\s")
    TRANSACTION_DATE = re.compile(r"\d{2}/\d{2}")
    AMOUNT = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
    HEADER_COLS = [
        "Date",
        "Reference",
        "Description",
        "Amount",
    ]

    def parse(self, reader: PDFReader) -> Statement:
        """Entry point

        Args:
            reader (PDFReader): pdfplumber child class

        Returns:
            Statement: Statement dataclass
        """
        logger.trace(f"Parsing {self.STATEMENT_TYPE} statement")
        try:
            self.lines = reader.extract_lines_clean()
            self.lower = [line.lower() for line in self.lines]
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")
            self.reader = reader
            # Extract raw chars from first page
            self.chars = "".join([c["text"] for c in self.reader.PDF.pages[0].chars])
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
        patterns = [
            re.compile(r"previous balance as of (\d{2}/\d{2}/\d{4})"),
            re.compile(r"new balance as of (\d{2}/\d{2}/\d{4})"),
        ]
        dates = []
        try:
            for pattern in patterns:
                _, _, match = find_regex_in_line(self.lower, pattern)
                dates.append(datetime.strptime(match.group(1), self.HEADER_DATE))
            self.start_date, self.end_date = dates
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
            transaction_array = self.get_transaction_array()
        except Exception as e:
            raise ValueError(f"Failed to extract transactions for account {account_num}: {e}")

        # Parse transactions
        try:
            transactions = self.parse_transaction_array(transaction_array)
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
        pattern = re.compile(r"account number ending in (\d{4})")
        _, _, match = find_regex_in_line(self.lower, pattern)
        account_num = match.group(1)
        return account_num

    def get_statement_balances(self) -> None:
        """Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract balances
        """
        patterns = ["previous balance as of ", "new balance as of "]
        balances = []

        for pattern in patterns:
            try:
                _, balance_line = find_param_in_line(self.lower, pattern)
                balance_line_right = balance_line.split(pattern)[-1]
                amount_str = balance_line_right.split()[1]
                balance = -convert_amount_to_float(amount_str)
                balances.append(balance)
            except ValueError as e:
                raise ValueError(f"Failed to extract balance for pattern '{pattern}': {e}")

        if len(balances) != 2:
            raise ValueError("Could not extract both starting and ending balances.")

        self.start_balance, self.end_balance = balances

    def get_transaction_array(self) -> list[list[str]]:
        """Extract lines containing transaction information.

        Returns:
            list[list[str]]: Processed lines containing dates and amounts for this statement
        """
        transaction_array = []
        for i, page in enumerate(self.reader.PDF.pages):
            try:
                transaction_array.extend(self.get_transactions_from_page(page))
            except Exception as e:
                raise ValueError(f"Failed to extract transactions from page {i}: {e}")
        return transaction_array

    def get_transactions_from_page(self, page: Page) -> list[list[str]]:
        """Extracts transaction array from each page of the pdf.

        Args:
            page (Page): pdfplumber PDF.pages object

        Returns:
            list[list[str]]: Processed lines containing dates and amounts for this page
        """
        # Get the metadata and text of every word in the header.
        page_words_all = page.extract_words()

        # Dynamically correct partial matches for columns
        word_list = [word.get("text") for word in page_words_all]
        word_set = set(word_list)
        header_cols = []
        for col in self.HEADER_COLS:
            if col in word_set:
                # Use the col word as is
                header_cols.append(col)
            else:
                # Attempt to find the largest partial match
                matches = [word for word in word_set if col.endswith(word) and len(word) >= 3]
                if matches:
                    best_match = sorted(
                        matches,
                        key=lambda x: len(x),
                        reverse=True,
                    )[0]
                    logger.debug(f"Matching fragment '{best_match}' to missing header '{col}'")
                    header_cols.append(best_match)
                else:
                    # Use the original word
                    header_cols.append(col)

        # Return empty if not all header names were found, even after partial match detection
        missing_words = [word for word in header_cols if word not in word_set]
        if missing_words:
            logger.debug(f"Skipping page {page.page_number} because a table header was not found.")
            return []

        # Get all the word objects that match the corrected header_cols
        page_words = [word for word in page_words_all if word.get("text") in header_cols]

        # Filter out spurious words by removing anything > 10 points from the mode
        y_mode = median(word.get("bottom") for word in page_words)
        page_words = [word for word in page_words if abs(word.get("bottom") - y_mode) < 10]

        # Make sure there are the right number of matches, or return empty
        if len(page_words) != len(self.HEADER_COLS):
            word_list = [word.get("text") for word in page_words]
            logger.debug(f"Header keywords could not be matched. Expected: {self.HEADER_COLS}\nGot: {word_list}")
            return []

        # Remap words list[dict] so it's addressable by column name
        header = {}
        for word in page_words:
            header[word.get("text")] = {
                "x0": word.get("x0"),
                "x1": word.get("x1"),
                "top": word.get("top"),
                "bottom": word.get("bottom"),
            }

        def calculate_vertical_lines(header):
            """
            Create a list of vertical table separators based on the header coordinates
            0: Date:            L justified
            1: Reference:       L Justified
            2: Description:     L Justified
            3: Amount:          R Justified
            """
            return [
                header[header_cols[0]]["x0"] - 3,  # Date left
                header[header_cols[1]]["x0"] - 8,  # Reference left
                header[header_cols[2]]["x0"] - 8,  # Description left
                header[header_cols[3]]["x0"] - 20,  # Amount left
                header[header_cols[3]]["x1"] + 3,  # Amount right
            ]

        # Extract the table from the cropped page using dynamic vertical separators
        vertical_lines = calculate_vertical_lines(header)
        table_settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "text",
            "explicit_vertical_lines": vertical_lines,
        }

        raw_array = page.extract_table(table_settings=table_settings)

        # Array validation
        array = []
        for row in raw_array:
            # Make sure each row has the right number of columns
            if len(row) != len(vertical_lines) - 1:
                raise ValueError(f"Incorrect number of columns for row: {row}")

            # Skip empty rows
            if all([item == "" for item in row]):
                continue

            # Include only rows that have a date or empty in date col.
            # And have either an amount or nothing in in amount col
            valid0 = bool(self.TRANSACTION_DATE.match(row[0])) or not row[0]
            valid1 = bool(self.AMOUNT.match(row[3])) or not row[3]
            if valid0 and valid1:
                array.append(row)

        return array

    def parse_transaction_array(self, array: list[list[str]]) -> list[Transaction]:
        """Convert transaction table into structured data.

        Args:
            transaction_lines (listlist[[str]]): Array containing valid transaction data

        Returns:
            list[tuple]: Unsorted transaction array
        """

        # Define column indices
        date_col, desc_col, amount_col = 0, 2, 3

        def get_full_description(i_row):
            """Lookahead for multi-line transactions"""
            desc = []
            multilines = 0
            while i_row + multilines < len(array):
                if multilines > 0 and array[i_row + multilines][date_col]:
                    break
                desc.append(array[i_row + multilines][desc_col])
                amount_str = array[i_row + multilines][amount_col]
                if self.AMOUNT.match(amount_str):
                    return multilines, " ".join(desc), amount_str
                if multilines > 3:
                    break
                multilines += 1
            return multilines, None, None

        transactions = []
        i_row = 0
        while i_row < len(array):
            row = array[i_row]

            # Return early if this is not a transaction start line
            if not bool(self.TRANSACTION_DATE.search(row[date_col])):
                i_row += 1
                continue

            # Extract main part of the transaction
            date = get_absolute_date(row[date_col], self.start_date, self.end_date)

            # Deal with posting/transaction date ambiguity
            if date < self.start_date:
                posting_date = self.start_date
            elif date > self.end_date:
                posting_date = self.end_date
            else:
                posting_date = date

            # Lookahead to get full description
            multilines, desc, amount_str = get_full_description(i_row)
            i_row += multilines
            if amount_str is None:
                continue
            amount = -convert_amount_to_float(amount_str)

            # Append transaction
            transactions.append(
                Transaction(
                    transaction_date=date,
                    posting_date=posting_date,
                    amount=amount,
                    desc=desc,
                )
            )

            # Increase counter
            i_row += 1

        return transactions
