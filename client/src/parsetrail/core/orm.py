from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    cast,
    create_engine,
    event,
    inspect,
    text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.types import TypeDecorator

from parsetrail.core.money import DEFAULT_CURRENCY, from_minor_units, to_minor_units

Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Store UTC in SQLite DATETIME and always return an aware UTC datetime."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise TypeError("UTC timestamps must be timezone-aware datetime values.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def _money_expression(column):
    return cast(column, Numeric(24, 2)) / Decimal(100)


class BaseModel(Base):
    __abstract__ = True


class Currencies(Base):
    __tablename__ = "Currencies"
    CurrencyCode = Column(String(3), primary_key=True)
    MinorUnit = Column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("length(CurrencyCode) = 3 AND CurrencyCode = upper(CurrencyCode)", name="ck_currency_code"),
        CheckConstraint("MinorUnit BETWEEN 0 AND 6", name="ck_currency_minor_unit"),
    )


class AccountTypes(Base):
    __tablename__ = "AccountTypes"
    AccountTypeID = Column(Integer, primary_key=True, autoincrement=True)
    AccountType = Column(String, unique=True, nullable=False)
    AssetType = Column(String, nullable=False)

    accounts = relationship("Accounts", back_populates="account_types")


class Accounts(Base):
    __tablename__ = "Accounts"
    AccountID = Column(Integer, primary_key=True, autoincrement=True)
    AccountName = Column(String, nullable=False, unique=True)
    AccountTypeID = Column(
        Integer,
        ForeignKey("AccountTypes.AccountTypeID", ondelete="RESTRICT"),
        nullable=False,
    )
    CurrencyCode = Column(
        String(3),
        ForeignKey("Currencies.CurrencyCode", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )
    Company = Column(String, nullable=False, default="", server_default="")
    Description = Column(Text, nullable=False, default="", server_default="")
    AppreciationRate = Column(Numeric, nullable=False, default=Decimal(0), server_default=text("0"))

    account_types = relationship("AccountTypes", back_populates="accounts")
    account_numbers = relationship(
        "AccountNumbers",
        back_populates="accounts",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    statements = relationship("Statements", back_populates="accounts")
    transactions = relationship("Transactions", back_populates="accounts")


class AccountNumbers(Base):
    __tablename__ = "AccountNumbers"
    AccountNumberID = Column(Integer, primary_key=True, autoincrement=True)
    AccountID = Column(
        Integer,
        ForeignKey("Accounts.AccountID", ondelete="CASCADE"),
        nullable=False,
    )
    AccountNumber = Column(String, unique=True, nullable=False)

    accounts = relationship("Accounts", back_populates="account_numbers")


class Categories(Base):
    __tablename__ = "Categories"
    CategoryID = Column(Integer, primary_key=True, autoincrement=True)
    Name = Column(String, nullable=False, unique=True)
    Type = Column(String, nullable=False)
    Active = Column(Boolean, default=True, server_default=text("1"), nullable=False)
    ParentID = Column(
        Integer,
        ForeignKey("Categories.CategoryID", ondelete="SET NULL"),
    )
    BudgetMinor = Column(Integer, nullable=True)
    BudgetCurrencyCode = Column(
        String(3),
        ForeignKey("Currencies.CurrencyCode", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )
    __table_args__ = (CheckConstraint("Type IN ('Expense','Income','Transfer')", name="ck_categories_type_valid"),)

    transactions = relationship("Transactions", back_populates="category")

    @hybrid_property
    def Budget(self) -> Decimal | None:
        return None if self.BudgetMinor is None else from_minor_units(self.BudgetMinor, self.BudgetCurrencyCode)

    @Budget.setter
    def Budget(self, value: Decimal | int | str | None) -> None:
        self.BudgetMinor = None if value is None else to_minor_units(value, self.BudgetCurrencyCode or DEFAULT_CURRENCY)

    @Budget.expression
    def Budget(cls):
        return _money_expression(cls.BudgetMinor)


class Plugins(Base):
    __tablename__ = "Plugins"
    PluginID = Column(Integer, primary_key=True, autoincrement=True)
    PluginName = Column(String, nullable=False)
    Version = Column(String, nullable=False)
    Suffix = Column(String, nullable=False)
    Company = Column(String, nullable=False)
    StatementType = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint("PluginName", "Version", name="uq_plugins_name_version"),)

    statements = relationship("Statements", back_populates="plugins")


class Statements(Base):
    __tablename__ = "Statements"
    StatementID = Column(Integer, primary_key=True, autoincrement=True)
    PluginID = Column(
        Integer,
        ForeignKey("Plugins.PluginID", ondelete="RESTRICT"),
        nullable=False,
    )
    AccountID = Column(
        Integer,
        ForeignKey("Accounts.AccountID", ondelete="RESTRICT"),
        nullable=False,
    )
    ImportedAt = Column(UTCDateTime(), nullable=False)
    StartDate = Column(Date, nullable=False)
    EndDate = Column(Date, nullable=False)
    StartBalanceMinor = Column(Integer, nullable=False)
    EndBalanceMinor = Column(Integer, nullable=False)
    CurrencyCode = Column(
        String(3),
        ForeignKey("Currencies.CurrencyCode", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )
    TransactionCount = Column(Integer, nullable=False)
    Filename = Column(String, nullable=False)
    ContentHashAlgorithm = Column(String(8), nullable=False)
    ContentHash = Column(String(64), nullable=False)
    __table_args__ = (
        CheckConstraint("EndDate >= StartDate", name="ck_statements_date_order"),
        CheckConstraint("TransactionCount >= 0", name="ck_statements_transaction_count"),
        CheckConstraint(
            "(ContentHashAlgorithm = 'md5' AND length(ContentHash) = 32) OR "
            "(ContentHashAlgorithm = 'sha256' AND length(ContentHash) = 64)",
            name="ck_statements_content_hash",
        ),
        UniqueConstraint(
            "AccountID",
            "ContentHashAlgorithm",
            "ContentHash",
            name="uq_statements_account_content_hash",
        ),
    )

    accounts = relationship("Accounts", back_populates="statements")
    plugins = relationship("Plugins", back_populates="statements")
    transaction_links = relationship(
        "StatementTransactions",
        back_populates="statement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    transactions = relationship(
        "Transactions",
        secondary="StatementTransactions",
        back_populates="statements",
        viewonly=True,
    )

    @hybrid_property
    def StartBalance(self) -> Decimal:
        return from_minor_units(self.StartBalanceMinor, self.CurrencyCode)

    @StartBalance.setter
    def StartBalance(self, value: Decimal | int | str) -> None:
        self.StartBalanceMinor = to_minor_units(value, self.CurrencyCode or DEFAULT_CURRENCY)

    @StartBalance.expression
    def StartBalance(cls):
        return _money_expression(cls.StartBalanceMinor)

    @hybrid_property
    def EndBalance(self) -> Decimal:
        return from_minor_units(self.EndBalanceMinor, self.CurrencyCode)

    @EndBalance.setter
    def EndBalance(self, value: Decimal | int | str) -> None:
        self.EndBalanceMinor = to_minor_units(value, self.CurrencyCode or DEFAULT_CURRENCY)

    @EndBalance.expression
    def EndBalance(cls):
        return _money_expression(cls.EndBalanceMinor)


class Transactions(Base):
    __tablename__ = "Transactions"
    TransactionID = Column(Integer, primary_key=True, autoincrement=True)
    AccountID = Column(
        Integer,
        ForeignKey("Accounts.AccountID", ondelete="RESTRICT"),
        nullable=False,
    )
    TransactionDate = Column(Date, nullable=True)
    PostingDate = Column(Date, nullable=False)
    AmountMinor = Column(Integer, nullable=False)
    BalanceMinor = Column(Integer, nullable=False)
    CurrencyCode = Column(
        String(3),
        ForeignKey("Currencies.CurrencyCode", ondelete="RESTRICT"),
        nullable=False,
        default=DEFAULT_CURRENCY,
        server_default=DEFAULT_CURRENCY,
    )
    Description = Column(Text, nullable=False)
    Fingerprint = Column(String(64), unique=True, nullable=False)
    FingerprintVersion = Column(Integer, nullable=False)
    CategoryID = Column(
        Integer,
        ForeignKey("Categories.CategoryID", ondelete="SET NULL"),
        nullable=True,
    )
    Verified = Column(Boolean, default=False, server_default=text("0"), nullable=False)
    ConfidenceScore = Column(Numeric, nullable=True)
    __table_args__ = (
        CheckConstraint("length(Fingerprint) = 64", name="ck_transactions_fingerprint_length"),
        CheckConstraint("FingerprintVersion > 0", name="ck_transactions_fingerprint_version"),
    )

    accounts = relationship("Accounts", back_populates="transactions")
    category = relationship("Categories", back_populates="transactions")
    statement_links = relationship(
        "StatementTransactions",
        back_populates="transaction",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    statements = relationship(
        "Statements",
        secondary="StatementTransactions",
        back_populates="transactions",
        viewonly=True,
    )

    @hybrid_property
    def Amount(self) -> Decimal:
        return from_minor_units(self.AmountMinor, self.CurrencyCode)

    @Amount.setter
    def Amount(self, value: Decimal | int | str) -> None:
        self.AmountMinor = to_minor_units(value, self.CurrencyCode or DEFAULT_CURRENCY)

    @Amount.expression
    def Amount(cls):
        return _money_expression(cls.AmountMinor)

    @hybrid_property
    def Balance(self) -> Decimal:
        return from_minor_units(self.BalanceMinor, self.CurrencyCode)

    @Balance.setter
    def Balance(self, value: Decimal | int | str) -> None:
        self.BalanceMinor = to_minor_units(value, self.CurrencyCode or DEFAULT_CURRENCY)

    @Balance.expression
    def Balance(cls):
        return _money_expression(cls.BalanceMinor)


class StatementTransactions(Base):
    __tablename__ = "StatementTransactions"
    StatementID = Column(
        Integer,
        ForeignKey("Statements.StatementID", ondelete="CASCADE"),
        primary_key=True,
    )
    TransactionID = Column(
        Integer,
        ForeignKey("Transactions.TransactionID", ondelete="CASCADE"),
        primary_key=True,
    )
    StatementRow = Column(Integer, nullable=False)
    __table_args__ = (
        CheckConstraint("StatementRow > 0", name="ck_statement_transactions_row"),
        UniqueConstraint("StatementID", "StatementRow", name="uq_statement_transactions_row"),
    )

    statement = relationship("Statements", back_populates="transaction_links")
    transaction = relationship("Transactions", back_populates="statement_links")


def _create_engine(db_path: Path, echo: bool = False):
    engine = create_engine(
        f"sqlite:///{db_path}?check_same_thread=False",
        poolclass=NullPool,
        echo=echo,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_database(db_path: Path, echo: bool = False) -> sessionmaker:
    """Connect to a migrated ParseTrail database without mutating its schema."""
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"Database does not exist: {db_path}. Run upgrade_db() before connecting.")

    engine = _create_engine(db_path, echo=echo)
    actual_tables = set(inspect(engine).get_table_names())
    expected_tables = set(Base.metadata.tables)
    missing = sorted(expected_tables - actual_tables)
    if missing:
        engine.dispose()
        raise RuntimeError(f"Database schema is incomplete; missing tables: {', '.join(missing)}")
    return sessionmaker(bind=engine)
