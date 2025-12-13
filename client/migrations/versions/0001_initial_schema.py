"""Initial SQLite schema for ParseTrail client."""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "AccountTypes",
        sa.Column("AccountTypeID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("AccountType", sa.String(), nullable=True, unique=True),
        sa.Column("AssetType", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("AccountTypeID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "Accounts",
        sa.Column("AccountID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("AccountName", sa.String(), nullable=False, unique=True),
        sa.Column("AccountTypeID", sa.Integer(), nullable=True),
        sa.Column("Company", sa.String(), nullable=True),
        sa.Column("Description", sa.Text(), nullable=True),
        sa.Column("AppreciationRate", sa.Numeric(), nullable=True),
        sa.ForeignKeyConstraint(
            ["AccountTypeID"],
            ["AccountTypes.AccountTypeID"],
        ),
        sa.PrimaryKeyConstraint("AccountID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "AccountNumbers",
        sa.Column("AccountNumberID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("AccountID", sa.Integer(), nullable=True),
        sa.Column("AccountNumber", sa.String(), nullable=True, unique=True),
        sa.ForeignKeyConstraint(
            ["AccountID"],
            ["Accounts.AccountID"],
        ),
        sa.PrimaryKeyConstraint("AccountNumberID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "Categories",
        sa.Column("CategoryID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("Name", sa.String(), nullable=False, unique=True),
        sa.Column("Type", sa.String(), nullable=True),
        sa.Column("Active", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("ParentID", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["ParentID"],
            ["Categories.CategoryID"],
        ),
        sa.PrimaryKeyConstraint("CategoryID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "Plugins",
        sa.Column("PluginID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("PluginName", sa.String(), nullable=True),
        sa.Column("Version", sa.String(), nullable=True),
        sa.Column("Suffix", sa.String(), nullable=True),
        sa.Column("Company", sa.String(), nullable=True),
        sa.Column("StatementType", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("PluginID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "Statements",
        sa.Column("StatementID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("PluginID", sa.Integer(), nullable=True),
        sa.Column("AccountID", sa.Integer(), nullable=True),
        sa.Column("ImportDate", sa.String(), nullable=True),
        sa.Column("StartDate", sa.String(), nullable=True),
        sa.Column("EndDate", sa.String(), nullable=True),
        sa.Column("StartBalance", sa.Numeric(), nullable=True),
        sa.Column("EndBalance", sa.Numeric(), nullable=True),
        sa.Column("TransactionCount", sa.Integer(), nullable=True),
        sa.Column("Filename", sa.String(), nullable=True),
        sa.Column("MD5", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["AccountID"],
            ["Accounts.AccountID"],
        ),
        sa.ForeignKeyConstraint(
            ["PluginID"],
            ["Plugins.PluginID"],
        ),
        sa.PrimaryKeyConstraint("StatementID"),
        sqlite_autoincrement=True,
    )

    op.create_table(
        "Transactions",
        sa.Column("TransactionID", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("StatementID", sa.Integer(), nullable=True),
        sa.Column("AccountID", sa.Integer(), nullable=True),
        sa.Column("Date", sa.String(), nullable=True),
        sa.Column("Amount", sa.Float(), nullable=True),
        sa.Column("Balance", sa.Float(), nullable=True),
        sa.Column("Description", sa.String(), nullable=True),
        sa.Column("MD5", sa.String(), nullable=True, unique=True),
        sa.Column("CategoryID", sa.Integer(), nullable=True),
        sa.Column("Verified", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("ConfidenceScore", sa.Numeric(), nullable=True),
        sa.ForeignKeyConstraint(
            ["AccountID"],
            ["Accounts.AccountID"],
        ),
        sa.ForeignKeyConstraint(
            ["CategoryID"],
            ["Categories.CategoryID"],
        ),
        sa.ForeignKeyConstraint(
            ["StatementID"],
            ["Statements.StatementID"],
        ),
        sa.PrimaryKeyConstraint("TransactionID"),
        sqlite_autoincrement=True,
    )


def downgrade() -> None:
    op.drop_table("Transactions")
    op.drop_table("Statements")
    op.drop_table("Plugins")
    op.drop_table("Categories")
    op.drop_table("AccountNumbers")
    op.drop_table("Accounts")
    op.drop_table("AccountTypes")
