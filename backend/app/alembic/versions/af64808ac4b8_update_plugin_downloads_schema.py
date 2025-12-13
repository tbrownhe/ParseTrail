"""Update plugin_downloads schema

Revision ID: af64808ac4b8
Revises: daac83e68f40
Create Date: 2025-01-11 12:37:44.766464

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "af64808ac4b8"
down_revision = "daac83e68f40"
branch_labels = None
depends_on = None


def upgrade():
    # Drop the existing table, including all data
    op.drop_table("plugin_downloads")

    # Recreate the table with the new schema
    op.create_table(
        "plugin_downloads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plugin_file", sa.String, nullable=False),
        sa.Column("client_ip", sa.String, nullable=False),
        sa.Column("user_agent", sa.Text),
        sa.Column("downloaded_at", sa.TIMESTAMP, server_default=sa.func.now()),
    )


def downgrade():
    # Drop the modified table
    op.drop_table("plugin_downloads")

    # Recreate the original table with the old schema
    op.create_table(
        "plugin_downloads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plugin_name", sa.String, nullable=False),
        sa.Column("file_type", sa.String, nullable=False),
        sa.Column("client_ip", sa.String, nullable=False),
        sa.Column("user_agent", sa.Text),
        sa.Column("downloaded_at", sa.TIMESTAMP, server_default=sa.func.now()),
    )
