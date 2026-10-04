"""Retain parser accounting declarations; old statements remain undeclared."""

import sqlalchemy as sa
from alembic import op

revision = "0004_statement_accounting"
down_revision = "0003_precise_financial_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("Statements", sa.Column("AccountingContract", sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError("Restore the pre-migration backup to retain accounting evidence safely.")
