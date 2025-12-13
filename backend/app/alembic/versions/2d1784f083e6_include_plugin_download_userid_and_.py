"""Include plugin download UserID and models table

Revision ID: 2d1784f083e6
Revises: 9da081705689
Create Date: 2025-11-23 11:21:20.177238

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2d1784f083e6"
down_revision = "9da081705689"
branch_labels = None
depends_on = None


def upgrade():
    # Add user_id column to plugin_downloads
    op.add_column(
        "plugin_downloads",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    # Create model_downloads table
    op.create_table(
        "model_downloads",
        sa.Column(
            "id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False
        ),
        sa.Column("model_file", sa.String(), nullable=False),
        sa.Column("client_ip", sa.String(), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "downloaded_at",
            postgresql.TIMESTAMP(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    # Drop model_downloads
    op.drop_table("model_downloads")

    # Drop user_id column from plugin_downloads
    op.drop_column("plugin_downloads", "user_id")
