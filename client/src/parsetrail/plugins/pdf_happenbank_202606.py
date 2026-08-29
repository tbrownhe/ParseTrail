import re
from datetime import datetime
from decimal import Decimal

from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.money import parse_money
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.core.validation import Account, Statement, Transaction


class Parser(IParser):
    PLUGIN_NAME = "pdf_happenbank_202606"
    VERSION = "0.1.0"
    MIN_CLIENT_VERSION = "1.3.0"
    SUFFIX = ".pdf"
    COMPANY = "Happen Bank"
    STATEMENT_TYPE = "LevelUp Savings Monthly Statement"
    SEARCH_STRING = '"LevelUp Savings"'
    ROUTING_RULE = {
        "pdf_metadata": {"Creator": '"VCTransaction"', "Title": '"StmtAPISvc"'},
        "header": '"Summary of Accounts" && "LevelUp Savings Account Number:"',
    }
    INSTRUCTIONS = (
        "Sign in to the Happen Bank website, open the LevelUp Savings account, choose 'Statements', "
        "then download the desired statement as a PDF."
    )

    HEADER_DATE = "%m/%d/%Y"
    DATE_RANGE = re.compile(
        r"^Statement Period:\s*(?P<start>\d{2}/\d{2}/\d{4})\s*-\s*"
        r"(?P<end>\d{2}/\d{2}/\d{4})$"
    )
    ACCOUNT = re.compile(r"LevelUp Savings Account Number:\s+X+(?P<number>\d{4})$")
    BALANCE = re.compile(
        r"^(?P<label>Beginning|Ending) Balance as of\d{2}/\d{2}/\d{2}\s+"
        r"(?P<amount>(?:\d[\d,]*)?\.\d{2})"
    )
    MONEY_TEXT = r"(?:\d[\d,]*)?\.\d{2}-?"
    TRANSACTION = re.compile(
        rf"^(?P<date>\d{{2}}/\d{{2}})\s+(?P<description>.+?)\s+"
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
            match = self.ACCOUNT.search(line)
            if match:
                return match.group("number")
        raise ValueError("Account number not found.")

    def extract_balances(self) -> tuple[Decimal, Decimal]:
        balances: dict[str, Decimal] = {}
        for line in self.lines:
            for match in self.BALANCE.finditer(line):
                balances[match.group("label")] = parse_money(match.group("amount"))
        try:
            return balances["Beginning"], balances["Ending"]
        except KeyError as exc:
            raise ValueError("Beginning or ending balance not found.") from exc

    def extract_transactions(self, start_date: datetime, end_date: datetime) -> list[Transaction]:
        in_activity = False
        transactions: list[Transaction] = []
        for line in self.lines:
            if line == "Transactional Detail":
                in_activity = True
                continue
            if not in_activity:
                continue
            if line.startswith("Overdraft/Return Item Summary"):
                break
            match = self.TRANSACTION.match(line)
            if not match or match.group("description") in {"Beginning Balance", "Ending Balance"}:
                continue
            date = get_absolute_date(match.group("date"), start_date, end_date)
            transactions.append(
                Transaction(
                    transaction_date=date,
                    posting_date=date,
                    amount=parse_money(match.group("amount")),
                    balance=parse_money(match.group("balance")),
                    desc=" ".join(match.group("description").split()),
                )
            )
        return transactions
