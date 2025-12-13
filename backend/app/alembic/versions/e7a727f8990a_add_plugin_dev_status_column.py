"""Add plugin dev status column

Revision ID: e7a727f8990a
Revises: d01be7ac5458
Create Date: 2025-12-07 21:20:26.195610

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e7a727f8990a"
down_revision = "d01be7ac5458"
branch_labels = None
depends_on = None


def upgrade():
    # Create enum type and add status column to statement_uploads
    status_enum = sa.Enum("pending", "ready", name="plugin_status")
    status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "statement_uploads",
        sa.Column(
            "plugin_status",
            status_enum,
            nullable=False,
            server_default="pending",
        ),
    )
    # Drop server default after backfill (new rows still need explicit default in code/DB)
    op.alter_column("statement_uploads", "plugin_status", server_default=None)


def downgrade():
    op.drop_column("statement_uploads", "plugin_status")
    status_enum = sa.Enum("pending", "ready", name="plugin_status")
    status_enum.drop(op.get_bind(), checkfirst=True)
