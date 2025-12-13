# ParseTrail - Personal Finance Tracker

## Overview

ParseTrail is a privacy-first desktop app for personal finance. It ingests bank and card statements (PDF, XLSX, CSV) into a local SQLite database, categorizes spending with a tunable ML model, flags recurring charges, and surfaces balance history, net worth, and category trends in one place. Everything runs on your machine.

If you just want to use the app, download the ready-made client from [parsetrail.com](https://parsetrail.com/). Builders and contributors can use this repo to run or extend the codebase.

## What it does

- **Own your data**: Statements, models, and results stay on disk; the app can run fully offline.
- **Fast ingestion**: Plugins parse statements from many institutions; new parsers can be added easily.
- **Smart categorization**: Local NLP model auto-tags transactions; retrain it to match your own taxonomy.
- **Recurring + anomalies**: Identify subscriptions, regular bills, and outliers that need attention.
- **Insights**: Balance, net worth, and category visualizations to track progress over time.
- **Exports and reports**: Generate summaries for budgeting, taxes, or audit trails.

## Technical Details

ParseTrail is built using:
- [PyQt5](https://www.riverbankcomputing.com/static/Docs/PyQt5/) for the graphical user interface (GUI)
- [pdfplumber](https://pypi.org/project/pdfplumber/) for PDF mining
- [SQLAlchemy](https://www.sqlalchemy.org/) for database operations
- [alembic](https://alembic.sqlalchemy.org/en/latest/) for database migrations
- [pandas](https://pandas.pydata.org/) for table operations
- [matplotlib](https://matplotlib.org/) and [seaborn](https://seaborn.pydata.org/) for dashboards and visualizations
- [nltk](https://www.nltk.org/) and [scikit-learn](https://scikit-learn.org/) to categorize transactions based on description

### Plugin Architecture

ParseTrail uses a comprehensive set of parsing plugins that are designed to read and validate information stored in official bank statements from various institutions.

The plugin architecture allows for easy extension by adding new parsers for different bank statement formats. Each parser implements an `IParser` interface, ensuring consistent behavior across all parsing operations.

#### Example IParser Implementation

```python
from parsetrail.core.interfaces import IParser
from parsetrail.core.validation import Account, Statement, Transaction
client/src/parsetrail/plugins/pdf_fidelity401k.py
class Parser(IParser):
    # Plugin metadata required by IParser
    PLUGIN_NAME = "pdf_fidelity401k"
    VERSION = "0.1.0"
    SUFFIX = ".pdf"
    COMPANY = "Fidelity"
    STATEMENT_TYPE = "Retirement Savings Monthly Statement"
    SEARCH_STRING = "Fidelity Brokerage Services&&Retirement Savings Statement"
    INSTRUCTIONS = (
        "Login to https://www.fidelity.com and navigate to your 401(k) account."
        " Click 'Statements', then select 'Monthly' for 'Time Period'."
        " Select the month and year you want, then click 'Get Statement'."
        " Click 'Download or Print This Statement', then save as PDF."
    )

    # Parsing constants
    HEADER_DATE = r"%m/%d/%Y"

    def parse(self, reader: PDFReader) -> Statement:
        ...

    def extract_statement(self) -> Statement:
        ...

    def get_statement_dates(self) -> None:
        ...

    def extract_accounts(self) -> list[Account]:
        ...

    def extract_account(self) -> Account:
        ...

    def extract_account_number(self) -> str:
        ...

    def get_statement_balances(self) -> tuple[float, float]:
        ...

    def get_transaction_lines(self, i_start: int, i_end: int) -> list[str]:
        ...

    def parse_transaction_lines(self, transaction_lines: list[str]) -> list[Transaction]:
        ...
```
See [pdf_fidelity401k_201810](client/src/parsetrail/plugins/pdf_fidelity401k_201810.py) for the full module.

## Development and Deployment

### Local Development

To set up a local development environment, see the [client README](client/README.md).


## Contributing

We welcome contributions from the community! If you have developed a new parser for a bank statement that is not currently supported, please submit a [pull request](https://github.com/tbrownhe/parsetrail/pulls).

Our development team can also develop plugins for statement files submitted via our secure zero-trust encryption protocol. Statement files will be stored encrypted on our production-grade server built using the FullStack FastAPI template.

## License

ParseTrail is released under the MIT License. See `LICENSE.txt` for more details.

## Acknowledgments

This project was partially based on the FullStack FastAPI template, a robust backend framework that powers various financial applications. For more information about the FullStack FastAPI template and its capabilities, visit [Full Stack FastAPI Template](https://github.com/fastapi/full-stack-fastapi-template).

The [ParseTrail Website](https://parsetrail.com/) was built using a template available from [HTML5 UP](https://html5up.net/).

---

We hope you find ParseTrail to be an invaluable tool for managing your personal finances. If you encounter any issues or have suggestions for new features, please don't hesitate to reach out to our support team or submit an [issue](https://github.com/tbrownhe/parsetrail/issues).
