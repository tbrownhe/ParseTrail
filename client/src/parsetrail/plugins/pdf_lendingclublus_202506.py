import re
from datetime import datetime
from statistics import mode

from loguru import logger
from pdfplumber.page import Page
from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import (
    PDFReader,
    convert_amount_to_float,
    find_line_startswith,
    find_param_in_line,
    find_regex_in_line,
    get_absolute_date,
)
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_lendingclublus_202506"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "LendingClub"
    STATEMENT_TYPE = "LevelUp Savings Monthly Statement"
    SEARCH_STRING = "LLeevveellUUpp SSaavviinnggss"
    INSTRUCTIONS = (
        "Login to https://banking.lendingclub.com/, then navigate to your account."
        " Click 'Statements', then select the account, statement type, and year."
        " Then click 'Download' to the right of the statement date."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}\s")
    TRANSACTION_DATE = re.compile(r"\d{2}/\d{2}")
    AMOUNT = re.compile(r"-?\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?")
    HEADER_COLS = [
        "Date",
        "Description",
        "Withdrawal",
        "(-)",
        "Deposit",
        "(+)",
        "Balance",
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
            lines = reader.extract_lines_clean()
            if not lines:
                raise ValueError("No lines extracted from the PDF.")
            self.reader = reader
            self.reader.lines_layout = self.reader.PDF.pages[0].extract_text(layout=True, x_density=3.45)
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
            dates = []
            for pattern in ["Statement Begin Date:", "Statement End Date:"]:
                _, dateline = find_line_startswith(self.reader.lines_clean, pattern)
                date_str = dateline.split(":")[1].split()[0]
                dates.append(datetime.strptime(date_str, self.HEADER_DATE))
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
        search_str = "Account Number:"
        _, line = find_param_in_line(self.reader.lines_clean, search_str)
        account_num = line.split(search_str)[-1].split()[0].strip()
        return account_num

    def get_statement_balances(self) -> None:
        """Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract balances
        """
        index, _, _ = find_regex_in_line(
            self.reader.lines_clean,
            r"Balance.*Deposits.*Paid.*Withdrawals.*Charge.*Balance",
        )
        amount_strs = self.reader.lines_clean[index + 1].split()
        self.start_balance = convert_amount_to_float(amount_strs[0])
        self.end_balance = convert_amount_to_float(amount_strs[-1])

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

        # Filter out spurious words by removing anything > 2 points from the mode
        y_mode = mode(word.get("bottom") for word in page_words)
        page_words = [word for word in page_words if abs(word.get("bottom") - y_mode) < 2]

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

        # Crop the page to the table size: [x0, top, x1, bottom]
        crop_page = page.crop(
            [
                header[header_cols[0]]["x0"] - 3,  # Date col
                header[header_cols[0]]["bottom"] + 0.1,  # Date col
                header[header_cols[-1]]["x1"] + 2,  # Balance col
                page.height,
            ]
        )

        def calculate_vertical_lines(header):
            """
            Create a list of vertical table separators based on the header coordinates
            0: Date:                        R justified
            1: Description:                 L Justified
            2: Withdrawal / Debit (-):      R Justified
            3: Deposit / Credit (-):        R Justified
            4: Balance:                     R Justified
            """
            return [
                header[header_cols[0]]["x0"] - 3,  # Date left
                header[header_cols[1]]["x0"] - 2,  # Desc left
                header[header_cols[2]]["x0"] - 3,  # Withdrawal left
                header[header_cols[3]]["x1"] + 2,  # Debit (-) right
                header[header_cols[5]]["x1"] + 2,  # Credit (+) right
                header[header_cols[6]]["x1"] + 2,  # Balance right
            ]

        # Extract the table from the cropped page using dynamic vertical separators
        vertical_lines = calculate_vertical_lines(header)
        table_settings = {
            "vertical_strategy": "explicit",
            "horizontal_strategy": "text",
            "explicit_vertical_lines": vertical_lines,
        }
        raw_array = crop_page.extract_table(table_settings=table_settings)

        # Array validation
        array = []
        for i, row in enumerate(raw_array):
            # Make sure each row has the right number of columns
            if len(row) != len(vertical_lines) - 1:
                raise ValueError(f"Incorrect number of columns for row: {row}")

            # Include only rows that have a date in date col. Break early if two rows are missing a date.
            if bool(self.TRANSACTION_DATE.match(row[0])):
                # Skip the fake balance forward transaction
                if row[1] != "Balance Forward":
                    array.append(row)
            elif i > 0:
                if not bool(self.TRANSACTION_DATE.match(raw_array[i - 1][0])):
                    break

        return array

    def parse_transaction_array(self, array: list[list[str]]) -> list[Transaction]:
        """Convert transaction table into structured data.

        Args:
            transaction_lines (listlist[[str]]): Array containing valid transaction data

        Returns:
            list[tuple]: Unsorted transaction array
        """
        # Define column indices
        date_col, desc_col, debit_col, cred_col, bal_col = 0, 1, 2, 3, 4

        def get_full_description(i_row):
            """Lookahead for multi-line transactions"""
            desc = array[i_row][desc_col]
            multilines = 1
            while (
                i_row + multilines < len(array)
                and not array[i_row + multilines][date_col]
                and array[i_row + multilines][desc_col]
            ):
                desc += f" {array[i_row + multilines][desc_col]}"
                multilines += 1
            return desc, multilines - 1

        transactions = []
        i_row = 0
        while i_row < len(array):
            row = array[i_row]

            # Return early if this is not a transaction start line
            if not bool(self.TRANSACTION_DATE.search(row[date_col])):
                i_row += 1
                continue

            # Extract main part of the transaction
            posting_date = get_absolute_date(row[date_col], self.start_date, self.end_date)
            additions = convert_amount_to_float(row[cred_col]) if row[cred_col] else 0.0
            subtractions = convert_amount_to_float(row[debit_col]) if row[debit_col] else 0.0
            amount = additions + subtractions
            balance = convert_amount_to_float(row[bal_col]) if row[bal_col] else None
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
