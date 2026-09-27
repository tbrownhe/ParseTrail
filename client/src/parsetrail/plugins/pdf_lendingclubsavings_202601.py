import re
from datetime import datetime
from decimal import Decimal

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    PLUGIN_NAME = "pdf_lendingclubsavings_202601"
    VERSION = "0.1.1"
    MIN_CLIENT_VERSION = "1.3.0"
    SUFFIX = ".pdf"
    COMPANY = "LendingClub Bank"
    STATEMENT_TYPE = "LevelUp Savings Monthly Statement"
    SEARCH_STRING = '"LevelUp Savings"'
    ROUTING_RULE = {
        "pdf_metadata": {"Creator": '"ImageCentre Statements"'},
        "header": '"Previous Statement Date:" && "Date_Description"',
    }
    INSTRUCTIONS = (
        "Sign in to the bank website, open the LevelUp Savings account, choose 'Statements', "
        "then download the desired statement as a PDF."
    )

    HEADER_DATE = "%m/%d/%y"
    DATE_RANGE = re.compile(
        r"^Statement from\s+(?P<start>\d{2}/\d{2}/\d{2})\s+thru\s+"
        r"(?P<end>\d{2}/\d{2}/\d{2})"
    )
    ACCOUNT = re.compile(r"\*+\s*LevelUp Savings\s+(?P<number>\d{4,})\s+\*+")
    MONEY_TEXT = r"(?:\d[\d,]*)?\.\d{2}-?"
    BALANCE_FORWARD = re.compile(rf"^(?P<date>\d{{2}}/\d{{2}})\s+Balance Forward.*?\s+(?P<balance>{MONEY_TEXT})$")
    TRANSACTION = re.compile(
        rf"^(?:(?P<date>\d{{2}}/\d{{2}})\s+)?(?P<description>.+?)\s+"
        rf"(?P<amount>{MONEY_TEXT})\s+(?P<balance>{MONEY_TEXT})$"
    )

    def parse(self, reader: PDFReader) -> Statement:
        logger.trace("Parsing {} statement", self.STATEMENT_TYPE)
        self.reader = reader
        reader.extract_text_simple()
        self.lines = reader.lines_simple or []
        if not self.lines:
            raise ValueError("No lines extracted from the PDF.")

        start_date, end_date = self.extract_statement_dates()
        account_number = self.extract_account_number()
        start_balance, end_balance = self.extract_summary_balances()
        forward_balance, transactions = self.extract_activity(start_date, end_date)
        if forward_balance != start_balance:
            raise ValueError("Balance Forward does not match the printed beginning balance.")
        running = start_balance
        for transaction in transactions:
            running += transaction.amount
            if running != transaction.balance:
                raise ValueError("Parsed activity does not match its printed running balance.")
        if running != end_balance:
            raise ValueError("Parsed activity does not reconcile to the printed ending balance.")

        return Statement(
            start_date=start_date,
            end_date=end_date,
            accounts=[
                Account(
                    account_num=account_number,
                    start_balance=start_balance,
                    end_balance=end_balance,
                    transactions=transactions,
                )
            ],
        )

    def extract_summary_balances(self) -> tuple[Decimal, Decimal]:
        """Use the printed summary, never the last successfully parsed row."""
        header = "Balance + Deposits + Paid - Deductions- Charge = Balance"
        matches = [index for index, line in enumerate(self.lines) if line == header]
        if len(matches) != 1:
            raise ValueError("Expected exactly one printed balance summary.")
        index = matches[0]
        if index == 0 or self.lines[index - 1] != "Beginning Interest Service Ending":
            raise ValueError("Unrecognized printed balance summary headings.")
        values = next((line.split() for line in self.lines[index + 1 :] if line.strip()), [])
        if len(values) != 6 or any(re.fullmatch(self.MONEY_TEXT, value) is None for value in values):
            raise ValueError("Invalid printed balance summary amounts.")
        opening, deposits, interest, deductions, charges, closing = map(parse_money, values)
        if opening + deposits + interest - deductions - charges != closing:
            raise ValueError("Printed balance summary does not reconcile.")
        return opening, closing

    def extract_statement_dates(self) -> tuple[datetime, datetime]:
        for line in self.lines:
            match = self.DATE_RANGE.match(line)
            if match:
                return (
                    datetime.strptime(match.group("start"), self.HEADER_DATE),
                    datetime.strptime(match.group("end"), self.HEADER_DATE),
                )
        raise ValueError("Statement date range not found.")

    def extract_account_number(self) -> str:
        for line in self.lines:
            match = self.ACCOUNT.search(line)
            if match:
                return match.group("number")
        raise ValueError("Account number not found.")

    def extract_activity(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> tuple[Decimal, list[Transaction]]:
        in_activity = False
        start_balance = None
        current_mmdd = None
        transactions: list[Transaction] = []
        for line in self.lines:
            if "LevelUp Savings" in line and "*" in line:
                in_activity = True
                continue
            if not in_activity:
                continue
            if line.startswith("Previous Statement Date:"):
                break
            forward = self.BALANCE_FORWARD.match(line)
            if forward:
                start_balance = parse_money(forward.group("balance"))
                continue
            match = self.TRANSACTION.match(line)
            if not match:
                continue
            current_mmdd = match.group("date") or current_mmdd
            if match.group("description") == "Interest Paid":
                current_mmdd = end_date.strftime("%m/%d")
            if current_mmdd is None:
                raise ValueError("Transaction date not found.")
            date = get_absolute_date(current_mmdd, start_date, end_date)
            transactions.append(
                Transaction(
                    transaction_date=date,
                    posting_date=date,
                    amount=parse_money(match.group("amount")),
                    balance=parse_money(match.group("balance")),
                    desc=" ".join(match.group("description").split()),
                )
            )
        if start_balance is None:
            raise ValueError("Beginning balance not found.")
        return start_balance, transactions
