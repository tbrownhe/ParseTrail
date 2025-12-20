import re
from datetime import datetime, timedelta

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.utils import PDFReader, convert_amount_to_float, find_param_in_line
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_wfloanper_202306"
    VERSION = "0.1.1"
    SUFFIX = ".pdf"
    COMPANY = "Wells Fargo"
    STATEMENT_TYPE = "Personal Loan Monthly Statement"
    SEARCH_STRING = "wells fargo&&personal loan statement"
    INSTRUCTIONS = (
        "Login to https://www.wellsfargo.com/, then navigate to"
        " Accounts > 'View Statements and Documents' > 'Statements and Disclosures'."
        " Select your personal loan account, then click the link for"
        " a statement. Click the Save icon to save the PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%y"
    LEADING_DATE = re.compile(r"^\d{2}/\d{2}/\d{2}\s")

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
        logger.trace("Attempting to parse dates from text.")
        try:
            pattern = re.compile(r"Statement Date (\d{2}/\d{2}/\d{2})")
            end_date_str = pattern.search(self.reader.text_simple).group(1)
            self.end_date = datetime.strptime(end_date_str, self.HEADER_DATE)

            # No start date or number of days in statement are given in the text.
            # Use 31 days to ensure coverage calculations still work
            self.start_date = self.end_date - timedelta(days=31)
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
            account_num = self.extract_account_number()
        except Exception as e:
            raise ValueError(f"Failed to extract account number: {e}")

        # Extract statement balances
        try:
            self.start_balance, self.end_balance = self.get_statement_balances()
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

        # Return the Account dataclass
        return Account(
            account_num=account_num,
            start_balance=self.start_balance,
            end_balance=self.end_balance,
            transactions=transactions,
        )

    def extract_account_number(self) -> str:
        """Retrieve the account  number from the statement

        Returns:
            str: Account number
        """
        pattern = "Account Number "
        _, line = find_param_in_line(self.lines, pattern)
        rline = line.split(pattern)[-1]
        return rline.split()[0].strip()

    def get_statement_balances(self) -> tuple[float, float]:
        """
        Extract the starting balance from the statement.

        Raises:
            ValueError: Unable to extract both balances.
        """
        patterns = ["Prior Principal Balance", "Ending Principal Balance"]
        balances = {}

        for pattern in patterns:
            try:
                _, balance_line = find_param_in_line(self.lines, pattern)
                balance_str = balance_line.split(pattern)[-1].strip().split()[0]
                balance_str = balance_str.replace("*", "")
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

        Returns:
            list[str]: Processed lines containing dates and amounts for this statement.
        """
        transaction_lines = []
        for line in self.lines:
            if "Ending Principal Balance" in line:
                break
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

        # Deal with loan origination
        if len(transaction_lines) == 0:
            transactions.append(
                Transaction(
                    transaction_date=self.end_date,
                    posting_date=self.end_date,
                    amount=0.0,
                    desc="LOAN ORIGINATION",
                )
            )
            return transactions

        interest = None
        principal = []

        for line in transaction_lines:
            # Split the line into words
            words = line.split()

            if len(words) < 3:
                raise ValueError(f"Invalid transaction line: {line}")

            # Each transaction has mm/dd/yy format
            posting_date = datetime.strptime(words[0], self.HEADER_DATE)

            # Extract amount
            try:
                amount = convert_amount_to_float(words[-1])
            except ValueError as e:
                raise ValueError(f"Error parsing amounts in line '{line}': {e}")

            # Get the description
            desc = " ".join(words[1:-1])
            if not desc:
                raise ValueError(f"Missing description in transaction line: {line}")

            # Deal with bizarre accounting
            if "INTEREST PAYMENT" in desc:
                if interest is not None:
                    raise ValueError("Found more than one Interest charge")
                interest = Transaction(
                    transaction_date=posting_date,
                    posting_date=posting_date,
                    amount=-amount,
                    desc="INTEREST PAYMENT",
                )
            elif "PRINCIPAL PAYMENT" in desc:
                # Overpayments show up as multiple principal payments
                principal.append(
                    Transaction(
                        transaction_date=posting_date,
                        posting_date=posting_date,
                        amount=amount,
                        desc=desc,
                    )
                )
            else:
                # Catch any other transactions, this would be weird
                transactions.append(
                    Transaction(
                        transaction_date=posting_date,
                        posting_date=posting_date,
                        amount=amount,
                        desc=desc,
                    )
                )

        # Deal with bizarre accounting
        if interest is None or principal == []:
            raise ValueError("Interest and Principal must both be present")

        # Include the fee in transactions
        transactions.append(interest)

        # Bundle all interest + principal amounts from the same date into a single transfer from bank
        amount = -interest.amount
        for payment in principal:
            if payment.transaction_date == interest.transaction_date:
                amount += payment.amount
            else:
                # Extra principal payments not on the payment date
                transactions.append(payment)

        transactions.append(
            Transaction(
                transaction_date=interest.transaction_date,
                posting_date=interest.posting_date,
                amount=round(amount, 2),
                desc="PAYMENT",
            )
        )

        return transactions
