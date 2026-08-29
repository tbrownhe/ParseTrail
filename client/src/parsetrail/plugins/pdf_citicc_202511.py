import re
from collections import Counter
from datetime import datetime
from statistics import median

from loguru import logger
from pdfplumber.page import Page

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import (
    PDFReader,
    find_param_in_line,
    find_regex_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_citicc_202511"
    VERSION = "0.4.0"
    MIN_CLIENT_VERSION = "1.3.0"
    SUFFIX = ".pdf"
    COMPANY = "Citibank"
    STATEMENT_TYPE = "Credit Account Monthly Statement"
    SEARCH_STRING = "www.citicards.com"
    ROUTING_RULE = {
        "pdf_metadata": {"Author": '"Citibank, N.A."'},
        "header": '"sale post description amount" || ("sale post" && "date date description amount")',
    }
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
    HEADER_COLS = [
        "Sale",
        "Post",
        "Description",
        "Amount",
    ]
    INTEREST_LINE = r"^\d{2}/\d{2} INTEREST CHARGED TO STANDARD PURCH"
    MAX_DESC_LINES = 4
    TEXT_TRANSACTION = re.compile(
        r"^\s*(?:\d+\s+)*(?:(?P<transaction_date>\d{2}/\d{2})\s+"
        r"(?P<posting_date>\d{2}/\d{2})|(?P<single_date>\d{2}/\d{2}))\s+"
        r"(?P<description>.+?)\s+"
        r"(?P<amount>-?\$\d{1,3}(?:,\d{3})*\.\d{2})\s*$"
    )
    DATE_PREFIX = re.compile(r"^\s*(?:\d+\s+)*(?P<date>\d{2}/\d{2})\s+(?P<description>.+)$")

    def __init__(self):
        self.vertical_lines = None
        self.crop_settings = None
        self.stop = False

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
            if not self.lines:
                raise ValueError("No lines extracted from the PDF.")
            reader.extract_text_simple()
            self.reader = reader
            # Extract raw chars from first page
            self.chars = "".join([c["text"] for c in self.reader.PDF.pages[0].chars])
            return self.extract_statement()
        except Exception as e:
            logger.error("Parser {} failed with {}.", self.PLUGIN_NAME, type(e).__name__)
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
        pattern = re.compile(r"Billing Period:\s{0,4}(\d{2}/\d{2}/\d{2})-(\d{2}/\d{2}/\d{2})")
        try:
            match = re.search(pattern, self.chars)
            if not match:
                raise ValueError("Statement date range not found.")
            self.start_date = datetime.strptime(match.group(1), self.HEADER_DATE)
            self.end_date = datetime.strptime(match.group(2), self.HEADER_DATE)
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
            raise ValueError(f"Failed to extract account number: {e}") from e

        # Extract statement balances
        try:
            self.get_statement_balances()
        except Exception as e:
            raise ValueError(f"Failed to extract balances for account {account_num}: {e}") from e

        # Extract transaction lines
        try:
            transaction_array = self.get_transaction_array()
        except Exception as e:
            raise ValueError(f"Failed to extract transactions for account {account_num}: {e}") from e

        # Parse transactions
        try:
            transactions = self.parse_transaction_array(transaction_array)
            transactions.extend(self.extract_missing_text_transactions(transactions))
            transactions.extend(self.extract_missing_fees(transactions))
        except Exception as e:
            raise ValueError(f"Failed to parse transactions for account {account_num}: {e}") from e

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
        pattern = re.compile(r"Account number ending in: (\d{4})")
        match = re.search(pattern, self.chars)
        if not match:
            raise ValueError("Account number not found.")
        account_num = match.group(1)
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
                balance = -parse_money(balance_str)
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
            if self.stop:
                logger.debug(f"Found end of transactions on page {i + 1}")
                return transaction_array
            if not self.vertical_lines:
                self.get_vertical_lines(page)
            if not self.vertical_lines:
                continue
            try:
                transaction_array.extend(self.get_transactions_from_page(page))
            except Exception as e:
                raise ValueError(f"Failed to extract transactions from page {i}: {e}")
        return transaction_array

    def get_vertical_lines(self, page: Page):
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
            return

        # Get all the word objects that match the corrected header_cols
        page_words = [word for word in page_words_all if word.get("text") in header_cols]

        # Filter out spurious words by removing anything > 10 points from the mode
        y_median = median(word.get("bottom") for word in page_words)
        page_words = [word for word in page_words if abs(word.get("bottom") - y_median) < 10]

        # Make sure there are the right number of matches, or return empty
        if len(page_words) != len(self.HEADER_COLS):
            word_list = [word.get("text") for word in page_words]
            logger.debug(f"Header keywords could not be matched. Expected: {self.HEADER_COLS}\nGot: {word_list}")
            return

        # Remap words list[dict] so it's addressable by column name
        header = {}
        for word in page_words:
            header[word.get("text")] = {
                "x0": word.get("x0"),
                "x1": word.get("x1"),
                "top": word.get("top"),
                "bottom": word.get("bottom"),
            }

        # Crop the page to the table size: [left, top, right, bottom]
        self.crop_settings = [
            header[header_cols[0]]["x0"] - 3,  # Date col
            0,
            header[header_cols[-1]]["x1"] + 2,  # Amount col
            page.height,
        ]

        def calculate_lines(header):
            """
            Create a list of vertical table separators based on the header coordinates
            0: Sale Date:     L justified
            1: Post Date:       L Justified
            2: Description:     L Justified
            4: Amount:          R Justified
            """
            return [
                header[header_cols[0]]["x0"] - 3,  # Sale Date left
                header[header_cols[1]]["x0"] - 2,  # Post Date left
                header[header_cols[2]]["x0"] - 2,  # Description left
                header[header_cols[3]]["x0"] - 20,  # Amount left
                header[header_cols[3]]["x1"] + 2,  # Amount right
            ]

        # Extract the table from the cropped page using dynamic vertical separators
        self.vertical_lines = calculate_lines(header)

    def get_transactions_from_page(self, page: Page) -> list[list[str]]:
        """Extracts transaction array from each page of the pdf.

        Args:
            page (Page): pdfplumber PDF.pages object

        Returns:
            list[list[str]]: Processed lines containing dates and amounts for this page
        """
        crop_page = page.crop(self.crop_settings)
        table_settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "lines",
            "explicit_vertical_lines": self.vertical_lines,
        }
        raw_array = crop_page.extract_table(table_settings=table_settings)
        if raw_array is None:
            raw_array = []

        # Array validation
        array = []
        for row in raw_array:
            # Make sure each row has the right number of columns
            if len(row) != len(self.vertical_lines) - 1:
                raise ValueError(f"Incorrect number of columns for row: {row}")

            # pdfplumber represents empty table cells as either None or an empty
            # string depending on the PDF producer. Normalize before matching.
            row = [cell or "" for cell in row]

            # Skip empty rows
            if all(item == "" for item in row):
                continue

            # Include only rows that have a date or empty in date col.
            # Break early if two rows are missing a date.
            valid0 = bool(self.TRANSACTION_DATE.match(row[0])) or not row[0]
            valid1 = bool(self.TRANSACTION_DATE.match(row[1])) or not row[1]
            if valid0 and valid1:
                array.append(row)

        # Stop parsing more pages
        txt = page.extract_text_simple()
        if "TOTAL INTEREST FOR THIS PERIOD" in txt:
            # Stop parsing pages
            self.stop = True

            # Table extraction misses the interest fee. Find and append it manually.
            try:
                _, line, _ = find_regex_in_line(txt.splitlines(), self.INTEREST_LINE)
            except ValueError:
                # Zero-interest statements contain only the total line.
                pass
            else:
                parts = line.split()
                row = ["", parts[0], " ".join(parts[1:-1]), parts[-1]]
                array.append(row)

        return array

    def parse_transaction_array(self, array: list[list[str]]) -> list[Transaction]:
        """Convert transaction table into structured data.

        Args:
            transaction_lines (listlist[[str]]): Array containing valid transaction data

        Returns:
            list[tuple]: Unsorted transaction array
        """

        # Strip all newlines
        array = [[elem.replace("\n", " ") for elem in row] for row in array]

        # Define column indices
        tdate_col, pdate_col, desc_col, amount_col = 0, 1, 2, 3

        def get_full_description(i_row):
            """Lookahead for multi-line transactions"""
            desc = []
            multilines = 0
            while i_row + multilines < len(array):
                if multilines > 0 and array[i_row + multilines][pdate_col]:
                    break
                desc.append(array[i_row + multilines][desc_col])
                amount_str = array[i_row + multilines][amount_col]
                if self.AMOUNT.match(amount_str):
                    return multilines, " ".join(desc), amount_str
                if multilines > self.MAX_DESC_LINES - 1:
                    break
                multilines += 1
            return multilines, None, None

        transactions = []
        i_row = 0
        while i_row < len(array):
            row = array[i_row]

            # Accessible-PDF tags can leak adjacent text into a date cell. Use
            # only the first mm/dd token rather than passing the full cell on.
            transaction_match = self.TRANSACTION_DATE.search(row[tdate_col])
            posting_match = self.TRANSACTION_DATE.search(row[pdate_col])
            if not transaction_match and not posting_match:
                i_row += 1
                continue

            # Extract main part of the transaction
            tdate, pdate = self._normalize_dates(
                transaction_match.group() if transaction_match else "",
                posting_match.group() if posting_match else "",
            )
            transaction_date = get_absolute_date(tdate, self.start_date, self.end_date)
            posting_date = get_absolute_date(pdate, self.start_date, self.end_date)

            multilines, desc, amount_str = get_full_description(i_row)
            i_row += multilines
            if amount_str is None:
                continue
            amount = -parse_money(amount_str)

            # Append transaction
            transactions.append(
                Transaction(
                    transaction_date=transaction_date,
                    posting_date=posting_date,
                    amount=amount,
                    desc=desc,
                )
            )

            # Increase counter
            i_row += 1

        return transactions

    def extract_missing_text_transactions(self, extracted: list[Transaction]) -> list[Transaction]:
        """Recover rows omitted by PDF table geometry without duplicating rows.

        Citi's accessible-PDF renderer can place decorative digits over a row or
        put a continuation-page row above the first horizontal rule. Those rows
        remain intact in simple text even though ``extract_table`` omits them.
        """
        extracted_keys = Counter(
            (transaction.transaction_date, transaction.posting_date, transaction.amount) for transaction in extracted
        )
        missing: list[Transaction] = []
        for page_text in self.reader.pages_simple or []:
            for line in page_text.splitlines():
                match = self.TEXT_TRANSACTION.match(line)
                if not match:
                    continue
                transaction_mmdd = match.group("transaction_date") or match.group("single_date")
                posting_mmdd = match.group("posting_date") or match.group("single_date")
                transaction_date = get_absolute_date(transaction_mmdd, self.start_date, self.end_date)
                posting_date = get_absolute_date(posting_mmdd, self.start_date, self.end_date)
                amount = -parse_money(match.group("amount"))
                candidate = Transaction(
                    transaction_date=transaction_date,
                    posting_date=posting_date,
                    amount=amount,
                    desc=" ".join(match.group("description").split()),
                )
                key = (candidate.transaction_date, candidate.posting_date, candidate.amount)
                if extracted_keys[key]:
                    extracted_keys[key] -= 1
                    continue
                missing.append(candidate)
        if missing:
            logger.debug("Recovered {} transaction row(s) from text.", len(missing))
        return missing

    def extract_missing_fees(self, extracted: list[Transaction]) -> list[Transaction]:
        """Recover multiline fee rows emitted outside Citi's table geometry."""
        extracted_keys = Counter((transaction.posting_date, transaction.amount) for transaction in extracted)
        missing: list[Transaction] = []
        for page_text in self.reader.pages_simple or []:
            in_fees = False
            pending: tuple[str, list[str]] | None = None
            for raw_line in page_text.splitlines():
                line = " ".join(raw_line.split())
                if line == "Fees Charged":
                    in_fees = True
                    continue
                if not in_fees:
                    continue
                if "TOTAL FEES FOR THIS PERIOD" in line:
                    pending = None
                    break
                date_match = self.DATE_PREFIX.match(line)
                if date_match:
                    pending = (date_match.group("date"), [date_match.group("description")])
                elif pending:
                    pending[1].append(line)
                if not pending:
                    continue
                amount_match = self.AMOUNT.search(line)
                if not amount_match:
                    continue
                date = get_absolute_date(pending[0], self.start_date, self.end_date)
                amount = -parse_money(amount_match.group())
                candidate = Transaction(
                    transaction_date=date,
                    posting_date=date,
                    amount=amount,
                    desc=" ".join(pending[1]),
                )
                key = (candidate.posting_date, candidate.amount)
                if extracted_keys[key]:
                    extracted_keys[key] -= 1
                else:
                    missing.append(candidate)
                pending = None
        if missing:
            logger.debug("Recovered {} fee row(s) from text.", len(missing))
        return missing

    def _normalize_dates(self, tdate: str, pdate: str) -> tuple[str, str]:
        if tdate and not pdate:
            pdate = tdate
        if pdate and not tdate:
            tdate = pdate
        return tdate, pdate
