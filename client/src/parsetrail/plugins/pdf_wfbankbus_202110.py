import re
from datetime import datetime, timedelta
from statistics import mode

from loguru import logger
from pdfplumber.page import Page

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
    PLUGIN_NAME = "pdf_wfbankbus_202110"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Wells Fargo"
    STATEMENT_TYPE = "Business Banking Monthly Statement"
    SEARCH_STRING = "wells fargo&&(initiate business checking||business market rate savings)"
    INSTRUCTIONS = (
        "Login to https://www.wellsfargo.com/, then navigate to"
        " Accounts > 'View Statements and Documents' > 'Statements and Disclosures'."
        " Select your business checking or savings account, then click the link for"
        " a statement. Click the Save icon to save the PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%B %d, %Y"
    HEADER_DATE_REGEX = re.compile(r"[A-Za-z]+\s\d{1,2},\s\d{4}")
    TRANSACTION_DATE = re.compile(r"\d{1,2}/\d{1,2}")
    AMOUNT = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
    HEADER_COLS = [
        "Date",
        "Description",
        "Credits",
        "Debits",
        "balance",
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
            lines = reader.extract_lines_simple()
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
        The year is only given in the %B %d, %Y format for
        statement end date at the very top of page 1.

        Raises:
            ValueError: If dates cannot be parsed or are invalid.
        """
        logger.trace("Attempting to parse dates from text.")
        try:
            # First get the full statement end date
            result = self.HEADER_DATE_REGEX.search(self.reader.text_simple)
            if not result:
                raise ValueError("Unable to find statement end date in PDF")
            date_str = result.group()
            self.end_date = datetime.strptime(date_str, self.HEADER_DATE)

            # Now get the start date in mm/dd format and resolve to datetime
            pattern = re.compile(r"Beginning balance on\s+(\d{1,2}/\d{1,2})")
            result = pattern.search(self.reader.text_simple)
            if not result:
                raise ValueError("Unable to find statement start date in PDF")
            mmdd = result.group(1)

            # Some savings statements are quarterly, some are monthly. Guess carefully.
            mm, dd = mmdd.split("/")
            months = (self.end_date.month - int(mm)) % 12
            days = self.end_date.day - int(dd)
            approx_start_date = self.end_date - timedelta(days=30 * months + days)
            self.start_date = get_absolute_date(mmdd, approx_start_date, self.end_date)
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
            start_balance=start_balance,
            end_balance=end_balance,
            transactions=transactions,
        )

    def get_account_number(self) -> str:
        """Retrieve the account number from the statement.

        Returns:
            str: Account number
        """
        pattern = re.compile(r"Account number:\s*(\d{4,})")
        result = pattern.search(self.reader.text_simple)
        if not result:
            raise ValueError("Unable to locate Account Number in PDF")
        return result.group(1)

    def get_statement_balances(self) -> tuple[float, float]:
        """Extract the starting balance from the statement.
        There is sometimes a spurious space in the word 'ba lance'
        Some statements contain "Closing Balance" instead of "Ending Balance"

        Raises:
            ValueError: Unable to extract balances
        """
        try_patterns = ["Beginning ba", "Ending ba", "Closing ba"]
        patterns = []
        balances = {}

        for pattern in try_patterns:
            try:
                _, balance_line = find_line_startswith(self.reader.lines_simple, pattern)
                result = self.AMOUNT.search(balance_line)
                amount_str = result.group()
                balance = convert_amount_to_float(amount_str)
                balances[pattern] = balance
                patterns.append(pattern)
            except Exception as e:
                logger.trace(f"Failed to extract balance for pattern '{pattern}': {e}")

        if len(balances) != 2:
            logger.error(f"Failed to extract balances: {balances}")
            raise ValueError("Could not extract both starting and ending balances.")

        return balances[patterns[0]], balances[patterns[1]]

    def get_transaction_array(self) -> list[list[str]]:
        """Extract lines containing transaction information.

        Wells Fargo statements are quite tricky. They must be extracted via pdfplumber's
        table methods, but the table dimensions vary from page to page so must
        be adjusted dynamically.

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
        page_words = [word for word in page_words_all if word.get("text") in self.HEADER_COLS]
        page_word_list = [pword.get("text") for pword in page_words]

        # Make sure all header words were found. If not, return empty row
        missing_words = [word for word in self.HEADER_COLS if word not in page_word_list]
        if missing_words:
            logger.trace(f"Skipping {page.page_number} because a table header was not found.")
            return []

        # Filter out spurious words by removing anything > 2 points from the mode
        y_mode = mode(word.get("bottom") for word in page_words)
        page_words = [word for word in page_words if abs(word.get("bottom") - y_mode) < 2]

        # Make sure there are no duplicates
        if len(page_words) != len(self.HEADER_COLS):
            word_list = [word.get("text") for word in page_words]
            raise ValueError(f"Too many header keywords were found. Expected: {self.HEADER_COLS}\nGot: {word_list}")

        # Remap words list[dict] so it's addressable by column name
        header = {}
        for word in page_words:
            header[word.get("text")] = {
                "x0": word.get("x0"),
                "x1": word.get("x1"),
                "top": word.get("top"),
                "bottom": word.get("bottom"),
            }

        # Crop the page to the table size: [x0, top, x1, bottom]
        crop_page = page.crop(
            [
                header[self.HEADER_COLS[0]]["x0"] - 3,  # Date col
                header[self.HEADER_COLS[0]]["bottom"] + 0.1,  # Date col
                header[self.HEADER_COLS[-1]]["x1"] + 2,  # balance col
                page.height,
            ]
        )

        def calculate_vertical_lines(header):
            """
            Create a list of vertical table separators based on the header coordinates
            0: Date:         L justified
            -: Number:       R justified, need a placeholder col for this, checking only
            1: Description:  L Justified
            2: Additions:    R Justified (or Credits)
            3: Subtractions: R Justified (or Debits)
            4: balance:      R Justified
            """
            return [
                header[self.HEADER_COLS[0]]["x0"] - 3,  # date col left
                header[self.HEADER_COLS[0]]["x1"] + 2,  # number, placeholder col left
                header[self.HEADER_COLS[1]]["x0"] - 2,  # desc col left
                header[self.HEADER_COLS[2]]["x0"] - 3,  # addition/credit col left
                header[self.HEADER_COLS[2]]["x1"] + 2,  # subtraction
                header[self.HEADER_COLS[3]]["x1"] + 2,  # balance col left
                header[self.HEADER_COLS[4]]["x1"] + 2,  # balance col right
            ]

        # Extract the table from the cropped page using dynamic vertical separators
        vertical_lines = calculate_vertical_lines(header)
        table_settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "text",
            "explicit_vertical_lines": vertical_lines,
        }
        array = crop_page.extract_table(table_settings=table_settings)

        # Array validation
        for i, row in enumerate(array):
            # Make sure each row has the right number of columns
            if len(row) != len(vertical_lines) - 1:
                raise ValueError(f"Incorrect number of columns for row: {row}")

            # Drop any rows that are empty or below an empty row
            if not any(row) or row[0].startswith("Ending"):
                array = array[:i]
                break

        return array

    def parse_transaction_array(self, array: list[list[str]]) -> list[Transaction]:
        """Convert transaction table into structured data.

        Args:
            transaction_lines (listlist[[str]]): Array containing valid transaction data

        Returns:
            list[tuple]: Unsorted transaction array
        """

        def get_full_description(i_row):
            """Lookahead for multi-line transactions"""
            desc = array[i_row][2]
            multilines = 1
            while i_row + multilines < len(array) and not array[i_row + multilines][0] and array[i_row + multilines][2]:
                desc += f" {array[i_row + multilines][2]}"
                multilines += 1
            return desc, multilines - 1

        transactions = []
        i_row = 0
        while i_row < len(array):
            row = array[i_row]

            # Return early if this is not a transaction start line
            if not bool(self.TRANSACTION_DATE.search(row[0])):
                i_row += 1
                continue

            # Extract main part of the transaction
            posting_date = get_absolute_date(row[0], self.start_date, self.end_date)
            additions = convert_amount_to_float(row[3]) if row[3] else 0.0
            subtractions = convert_amount_to_float(row[4]) if row[4] else 0.0
            amount = additions - subtractions
            balance = convert_amount_to_float(row[5]) if row[5] else None
            desc, multilines = get_full_description(i_row)
            i_row += multilines

            # Append transaction
            # Note: Balance is appended only at the end of each transaction day
            # and ends up being overwritten by Transaction.sort_and_compute_balances()
            transactions.append(
                Transaction(
                    transaction_date=posting_date,
                    posting_date=posting_date,
                    amount=amount,
                    balance=balance,
                    desc=desc,
                )
            )

            # Increase counter
            i_row += 1

        return transactions
