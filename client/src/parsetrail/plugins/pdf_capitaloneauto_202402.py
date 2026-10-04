import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import PDFReader, find_param_in_line
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_capitaloneauto_202402"
    VERSION = "0.2.2"
    MIN_CLIENT_VERSION = "1.3.0"
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

    # Describes normalized output; never confirms a bank match or source balance.
    ACCOUNTING_CONTRACT = {
        "schema_version": 1,
        "representation": "loan-total-and-interest",
        "label": "Capital One Auto",
        "payment_description": "Payment Received",
        "interest_description": "Interest Fee",
        "association": "same-account-date-statement",
        "balance_basis": "derived-opening-principal",
        "period_basis": "printed-activity-range",
        "date_basis": "unverified",
        "excluded_descriptions": [],
        "unposted_descriptions": [],
    }

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"
    DATE_REGEX = re.compile(r"\d{2}/\d{2}/\d{4}")
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}/\d{4}")
    AMOUNT = re.compile(r"-?\$(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")

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
        """Extract the printed closing principal balance.

        This layout has no printed opening balance. Reconstructing it from
        principal activity is not independent statement reconciliation; that
        requires a separate prior closing balance outside this parser.

        Raises:
            ValueError: Unable to extract balances
        """
        pattern = "Principal Balance:"
        try:
            matches = [line for line in self.lines if pattern in line]
            if len(matches) != 1:
                raise ValueError("Expected exactly one printed principal balance.")
            balance_line = matches[0]
            balance_str = balance_line.split(pattern)[-1].strip().split()[0]
            if self.AMOUNT.fullmatch(balance_str) is None:
                raise ValueError("Invalid printed principal balance.")
            self.end_balance = -parse_money(balance_str)
        except ValueError as e:
            raise ValueError(f"Failed to extract balance for pattern '{pattern}': {e}")

    def parse_transaction_lines(self) -> list[Transaction]:
        """Validate the whole bounded history table and its printed components."""
        starts = [i for i, line in enumerate(self.lines) if line.startswith("Transactions between ")]
        if len(starts) != 1:
            raise ValueError("Expected exactly one transaction history range.")
        first = starts[0] + 1
        last = next(
            (
                i
                for i in range(first, len(self.lines))
                if self.lines[i] == "Please detach and return the portion below with your payment."
            ),
            None,
        )
        if last is None:
            raise ValueError("Transaction history end marker not found.")
        lines = [line for line in self.lines[first:last] if line.strip()]
        headers = {
            "Date Description Principal Total": False,
            "Date Description Principal Interest Total": True,
        }
        if not lines or lines[0] not in headers:
            raise ValueError("Unsupported transaction history columns.")
        header = lines[0]
        has_interest = headers[header]
        self.start_balance = self.end_balance
        transactions = []
        for line in lines[1:]:
            if line == header:
                continue
            words = line.split()
            amount_count = 3 if has_interest else 2
            # Date, nonempty description, principal, optional interest, '=', total.
            if len(words) < amount_count + 3 or words[-2] != "=" or self.LEADING_DATE.match(line) is None:
                raise ValueError("Unrecognized transaction history row.")
            values = words[-(amount_count + 1) : -2] + [words[-1]]
            if any(self.AMOUNT.fullmatch(value) is None for value in values):
                raise ValueError("Invalid transaction history amounts.")
            amounts = list(map(parse_money, values))
            principal, total = amounts[0], amounts[-1]
            interest = amounts[1] if has_interest else parse_money("0")
            if principal + interest != total:
                raise ValueError("Printed principal and interest do not reconcile to the transaction total.")
            posting_date = datetime.strptime(words[0], self.HEADER_DATE)
            if not self.start_date <= posting_date <= self.end_date:
                raise ValueError("Transaction date is outside the printed history range.")
            desc = " ".join(words[1 : -(amount_count + 1)])
            # Liability balances use the opposite sign to the printed principal.
            # Preserve the existing payment/interest representation, but derive
            # the opening from the separately printed principal component.
            self.start_balance += principal
            transactions.append(
                Transaction(
                    transaction_date=posting_date,
                    posting_date=posting_date,
                    amount=-total,
                    desc=desc,
                )
            )
            if has_interest:
                transactions.append(
                    Transaction(
                        transaction_date=posting_date,
                        posting_date=posting_date,
                        amount=interest,
                        desc="Interest Fee",
                    )
                )
        if not transactions:
            raise ValueError("Empty transaction history requires explicit source evidence of no activity.")
        return transactions
