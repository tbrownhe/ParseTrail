import json
from pathlib import Path

from loguru import logger
from pydantic import BaseModel, ValidationError
from PyQt5.QtWidgets import QMessageBox
from sqlalchemy.orm import Session

from parsetrail.core import orm, query
from parsetrail.core.settings import settings


class Account(BaseModel):
    AccountID: int
    AccountName: str
    AccountTypeID: int
    Company: str
    Description: str
    AppreciationRate: float


class AccountNumber(BaseModel):
    AccountNumberID: int
    AccountID: int
    AccountNumber: str


class AccountConfig(BaseModel):
    Accounts: list[Account]
    AccountNumbers: list[AccountNumber]


def export_init_accounts(session: Session):
    accounts = query.accounts_table(session)
    account_numbers = query.account_numbers_table(session)

    data = {"Accounts": accounts, "AccountNumbers": account_numbers}
    with settings.accounts_json.open("w") as f:
        json.dump(data, f, indent=2)

    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Information)
    msg_box.setText("Successfully exported Accounts configuration.")
    msg_box.setWindowTitle("Configuration Saved")
    msg_box.setStandardButtons(QMessageBox.Ok)
    msg_box.exec_()


def validate_using_model(fpath: Path, model: BaseModel):
    logger.info(f"Validating JSON file: {fpath}")
    with fpath.open("r") as f:
        data = json.load(f)

    try:
        validated_data = model(**data)
        logger.info("Validation successful.")
        return validated_data
    except ValidationError as e:
        logger.error(f"Validation error: {e}")
        raise ValueError(f"Invalid configuration format: {e}")


def import_init_accounts(session: Session, parent=None):
    """Import account configuration, if available"""
    # Try to grab from default location
    fpath = settings.accounts_json
    if not fpath.exists():
        logger.info(f"Account metadata file {fpath} could not be found. A blank database will be initialized.")
        return

    reply = QMessageBox.question(
        parent,
        "Load Previous Account Metadata?",
        (
            "Account metadata from a previous database was found."
            " Do you want to initialize the new database with it?\n\n"
            "Click Yes if you want to load previous account names and"
            " account numbers into the new database."
        ),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply == QMessageBox.No:
        return

    # Import and validate data
    try:
        validated_data = validate_using_model(fpath, AccountConfig)
    except Exception as e:
        logger.error(f"Validation error: {e}")
        raise

    # Convert Pydantic models to dicts for database insertion
    accounts = [item.dict() for item in validated_data.Accounts]
    account_numbers = [item.dict() for item in validated_data.AccountNumbers]

    # Load into new database
    query.insert_rows_batched(
        session,
        orm.Accounts,
        accounts,
    )
    query.insert_rows_batched(
        session,
        orm.AccountNumbers,
        account_numbers,
    )
