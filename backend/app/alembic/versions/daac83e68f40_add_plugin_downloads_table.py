"""Add plugin_downloads table

Revision ID: daac83e68f40
Revises: 1a31ce608336
Create Date: 2025-01-08 23:37:30.185406

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "daac83e68f40"
down_revision = "1a31ce608336"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plugin_downloads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plugin_name", sa.String, nullable=False),
        sa.Column("file_type", sa.String, nullable=False),
        sa.Column("client_ip", sa.String, nullable=False),
        sa.Column("user_agent", sa.Text),
        sa.Column("downloaded_at", sa.TIMESTAMP, server_default=sa.func.now()),
    )

    op.create_table(
        "client_downloads",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("platform", sa.String, nullable=False),
        sa.Column("version", sa.String, nullable=False),
        sa.Column("client_ip", sa.String, nullable=False),
        sa.Column("user_agent", sa.Text),
        sa.Column("downloaded_at", sa.TIMESTAMP, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("client_downloads")
    op.drop_table("plugin_downloads")
