from pathlib import Path

from sqlalchemy import (
    Column,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy.pool import NullPool

Base = declarative_base()


class BaseModel(Base):
    __abstract__ = True


class AccountTypes(Base):
    __tablename__ = "AccountTypes"
    AccountTypeID = Column(Integer, primary_key=True, autoincrement=True)
    AccountType = Column(String, unique=True, nullable=True)
    AssetType = Column(String, nullable=True)

    accounts = relationship("Accounts", back_populates="account_types")


class Accounts(Base):
    __tablename__ = "Accounts"
    AccountID = Column(Integer, primary_key=True, autoincrement=True)
    AccountName = Column(String, nullable=False, unique=True)
    AccountTypeID = Column(Integer, ForeignKey("AccountTypes.AccountTypeID"))
    Company = Column(String)
    Description = Column(Text)
    AppreciationRate = Column(Numeric, default=0)

    account_types = relationship("AccountTypes", back_populates="accounts")
    account_numbers = relationship("AccountNumbers", back_populates="accounts")
    statements = relationship("Statements", back_populates="accounts")
    transactions = relationship("Transactions", back_populates="accounts")


class AccountNumbers(Base):
    __tablename__ = "AccountNumbers"
    AccountNumberID = Column(Integer, primary_key=True, autoincrement=True)
    AccountID = Column(Integer, ForeignKey("Accounts.AccountID"))
    AccountNumber = Column(String, unique=True)

    accounts = relationship("Accounts", back_populates="account_numbers")


class Categories(Base):
    __tablename__ = "Categories"
    CategoryID = Column(Integer, primary_key=True, autoincrement=True)
    Name = Column(String, nullable=False, unique=True)
    Type = Column(String)
    Active = Column(Integer, default=1, server_default=text("1"), nullable=False)
    ParentID = Column(Integer, ForeignKey("Categories.CategoryID"))
    Budget = Column(Numeric(12, 2), nullable=True)

    transactions = relationship("Transactions", back_populates="category")


class Plugins(Base):
    __tablename__ = "Plugins"
    PluginID = Column(Integer, primary_key=True, autoincrement=True)
    PluginName = Column(String)
    Version = Column(String)
    Suffix = Column(String)
    Company = Column(String)
    StatementType = Column(String)

    statements = relationship("Statements", back_populates="plugins")


class Statements(Base):
    __tablename__ = "Statements"
    StatementID = Column(Integer, primary_key=True, autoincrement=True)
    PluginID = Column(Integer, ForeignKey("Plugins.PluginID"))
    AccountID = Column(Integer, ForeignKey("Accounts.AccountID"))
    ImportDate = Column(String)
    StartDate = Column(String)
    EndDate = Column(String)
    StartBalance = Column(Numeric)
    EndBalance = Column(Numeric)
    TransactionCount = Column(Integer)
    Filename = Column(String)
    MD5 = Column(String)

    accounts = relationship("Accounts", back_populates="statements")
    plugins = relationship("Plugins", back_populates="statements")
    transactions = relationship("Transactions", back_populates="statements")


class Transactions(Base):
    __tablename__ = "Transactions"
    TransactionID = Column(Integer, primary_key=True, autoincrement=True)
    StatementID = Column(Integer, ForeignKey("Statements.StatementID"))
    AccountID = Column(Integer, ForeignKey("Accounts.AccountID"))
    Date = Column(String)
    Amount = Column(Float)
    Balance = Column(Float)
    Description = Column(String)
    MD5 = Column(String, unique=True)
    CategoryID = Column(Integer, ForeignKey("Categories.CategoryID"))
    Verified = Column(Integer, default=0, nullable=False)
    ConfidenceScore = Column(Numeric)

    statements = relationship("Statements", back_populates="transactions")
    accounts = relationship("Accounts", back_populates="transactions")
    category = relationship("Categories", back_populates="transactions")


# Create Engine and Session
def create_database(db_path: Path, echo: bool = False) -> sessionmaker:
    """Creates a sessionmaker object to use with context manager.

    Args:
        db_path (Path): Path to sqlite3 database
        echo (bool, optional): _description_. Defaults to False.

    Returns:
        sessionmaker: Reference to sqlite database

    Notes:
        NullPool is used to prevent SQLAlchemy from trying to maintain multiple
        connections. If a connection remains open, the db file can't be opened
        externally, for example with utils.open_file_in_os.
    """
    engine = create_engine(f"sqlite:///{db_path}?check_same_thread=False", poolclass=NullPool, echo=echo)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
