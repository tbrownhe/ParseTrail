import re
from datetime import datetime

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    PLUGIN_NAME = "pdf_chasecc_202602"
    VERSION = "0.1.0"
    MIN_CLIENT_VERSION = "1.3.0"
    SUFFIX = ".pdf"
    COMPANY = "JPMorgan Chase Bank, N.A."
    STATEMENT_TYPE = "Credit Account Monthly Statement"
    SEARCH_STRING = '"www.chase.com/cardhelp" && "Account Number:"'
    ROUTING_RULE = {
        "pdf_metadata": {"Producer": '"OpenText Output Transformation Engine"'},
        "header": '"Transaction Merchant Name or Transaction Description $ Amount"',
    }
    INSTRUCTIONS = (
        "Sign in to https://www.chase.com/, select the card, choose 'Statements & documents', "
        "then download the desired statement as a PDF."
    )

    HEADER_DATE = "%m/%d/%y"
    DATE_RANGE = re.compile(
        r"^Opening/Closing Date\s+(?P<start>\d{2}/\d{2}/\d{2})\s+-\s+"
        r"(?P<end>\d{2}/\d{2}/\d{2})$"
    )
    ACCOUNT_NUMBER = re.compile(r"^Account Number:\s+(?:X{4}\s+){3}(?P<number>\d{4})$")
    BALANCE = re.compile(r"^(?P<label>Previous Balance|New Balance)\s+(?P<amount>\$[\d,]+\.\d{2})$")
    TRANSACTION = re.compile(
        r"^\s*(?P<date>\d{2}/\d{2})\s{2,}(?P<description>.+?)\s+"
        r"(?P<amount>-?\$?(?:\d{1,3}(?:,\d{3})*)?\.\d{2})\s*$"
    )

    def parse(self, reader: PDFReader) -> Statement:
        logger.trace("Parsing {} statement", self.STATEMENT_TYPE)
        self.reader = reader
        self.lines = reader.extract_lines_simple()
        if not self.lines:
            raise ValueError("No lines extracted from the PDF.")

        start_date, end_date = self.extract_statement_dates()
        account_number = self.extract_account_number()
        start_balance, end_balance = self.extract_balances()
        transactions = self.extract_transactions(start_date, end_date)

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
            match = self.ACCOUNT_NUMBER.match(line)
            if match:
                return match.group("number")
        raise ValueError("Account number not found.")

    def extract_balances(self):
        balances = {}
        for line in self.lines:
            match = self.BALANCE.match(line)
            if match and match.group("label") not in balances:
                balances[match.group("label")] = -parse_money(match.group("amount"))
        try:
            return balances["Previous Balance"], balances["New Balance"]
        except KeyError as exc:
            raise ValueError("Previous or new balance not found.") from exc

    def extract_transactions(self, start_date: datetime, end_date: datetime) -> list[Transaction]:
        transactions = []
        for page_text in self.reader.pages_simple or []:
            for line in page_text.splitlines():
                match = self.TRANSACTION.match(line)
                if not match:
                    continue
                transaction_date = get_absolute_date(match.group("date"), start_date, end_date)
                # Chase exposes only a transaction date. A charge can post in
                # this cycle one day after a transaction on the prior close date,
                # so use the nearest statement boundary as its posting-date proxy.
                posting_date = min(max(transaction_date, start_date), end_date)
                transactions.append(
                    Transaction(
                        transaction_date=transaction_date,
                        posting_date=posting_date,
                        amount=-parse_money(match.group("amount")),
                        desc=" ".join(match.group("description").split()),
                    )
                )
        return transactions
