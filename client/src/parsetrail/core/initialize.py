from pathlib import Path

from loguru import logger
from PyQt5.QtWidgets import QFileDialog, QMessageBox
from sqlalchemy.orm import sessionmaker

from parsetrail.core import orm
from parsetrail.core.config import import_init_accounts
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.query import insert_rows_batched, optimize_db
from parsetrail.core.settings import save_settings, settings
from parsetrail.core.utils import create_directory

# Define AccountTypes table
ACCOUNT_TYPES = [
    {"AccountTypeID": 1, "AccountType": "Checking", "AssetType": "Asset"},
    {"AccountTypeID": 2, "AccountType": "Savings", "AssetType": "Asset"},
    {"AccountTypeID": 3, "AccountType": "Credit Card", "AssetType": "Debt"},
    {"AccountTypeID": 4, "AccountType": "401k", "AssetType": "Asset"},
    {"AccountTypeID": 5, "AccountType": "HSA", "AssetType": "Asset"},
    {"AccountTypeID": 6, "AccountType": "Loan", "AssetType": "Debt"},
    {
        "AccountTypeID": 7,
        "AccountType": "TangibleAsset",
        "AssetType": "TangibleAsset",
    },
]


def initialize_dirs() -> None:
    """Ensure all required dirs in settings exist."""
    create_directory(settings.db_path.parent)
    create_directory(settings.import_dir)
    create_directory(settings.success_dir)
    create_directory(settings.fail_dir)
    create_directory(settings.duplicate_dir)
    create_directory(settings.report_dir)
    create_directory(settings.plugin_dir)
    create_directory(settings.model_dir)


def initialize_db(parent=None) -> sessionmaker:
    """Ensure db file exists and return sessionmaker.

    Args:
        parent (optional): GUI instance that called this function. Defaults to None.

    Returns:
        sessionmaker: Database Session maker
    """
    # Prompt for a database path if the configured file is missing
    _ensure_db_path(parent)

    # Keep the database and data lake folders in sync with the selected db_path
    initialize_dirs()

    db_existed = settings.db_path.exists()
    upgrade_db(settings.db_path)

    if db_existed:
        # Connect to and clean up the existing db
        Session = orm.create_database(settings.db_path)
        with Session() as session:
            optimize_db(session)
        logger.info(f"Connected to database at {settings.db_path}")
        return Session
    else:
        # Initialize a new db and import any saved account metadata
        create_directory(settings.db_path.parent)
        Session = orm.create_database(settings.db_path)
        QMessageBox.information(
            parent,
            "New Database Created",
            f"Initialized new database at <pre>{settings.db_path}</pre>",
        )

        # Initialize AccountTypes and Accounts
        with Session() as session:
            insert_rows_batched(
                session,
                orm.AccountTypes,
                ACCOUNT_TYPES,
            )
            import_init_accounts(session)

        logger.info(f"Initialized new database at {settings.db_path}")
        return Session


def _ensure_db_path(parent=None) -> None:
    """If the configured db_path is missing, prompt the user to pick a name/location."""
    if settings.db_path.exists():
        return

    default_path = settings.db_path
    fname = _prompt_for_db_path(default_path, parent)

    if not fname:
        raise RuntimeError("Database setup canceled before initialization.")

    chosen_path = _normalize_db_path(fname)
    settings.db_path = chosen_path
    save_settings(settings)
    logger.info(f"Database path set to {settings.db_path}")


def _normalize_db_path(fname: str) -> Path:
    """Ensure the selected db path has a .db suffix and is absolute."""
    fpath = Path(fname)
    if fpath.suffix.lower() != ".db":
        fpath = fpath.with_suffix(".db")
    return fpath.expanduser().resolve()


def _prompt_for_db_path(default_path: Path, parent=None) -> str:
    """
    Show a single dialog that works for both creating a new db and selecting an existing one.

    AcceptSave + AnyFile lets the user type a new filename or pick an existing file, while
    DontConfirmOverwrite avoids the false overwrite warning when reusing an existing db.
    """
    default_dir = default_path.parent
    default_dir.mkdir(parents=True, exist_ok=True)

    dialog = QFileDialog(parent, "Select or Create a Database")
    dialog.setAcceptMode(QFileDialog.AcceptSave)
    dialog.setFileMode(QFileDialog.AnyFile)
    dialog.setDefaultSuffix("db")
    dialog.setNameFilters(["Database Files (*.db)", "All Files (*)"])
    dialog.setOption(QFileDialog.DontConfirmOverwrite, True)
    dialog.setDirectory(str(default_dir.resolve()))
    dialog.selectFile(str(default_path.name))

    if dialog.exec_():
        selected_files = dialog.selectedFiles()
        return selected_files[0] if selected_files else ""
    return ""
