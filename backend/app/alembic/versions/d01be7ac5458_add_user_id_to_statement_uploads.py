"""Add user_id to statement_uploads

Revision ID: d01be7ac5458
Revises: 2d1784f083e6
Create Date: 2025-11-25 22:34:58.614245

"""

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d01be7ac5458"
down_revision = "2d1784f083e6"
branch_labels = None
depends_on = None


def upgrade():
    # Add user_id column to statement_uploads
    op.add_column(
        "statement_uploads",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    # Drop user_id column from plugin_downloads
    op.drop_column("statement_uploads", "user_id")
