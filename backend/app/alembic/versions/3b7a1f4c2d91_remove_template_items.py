"""Remove the unused template Items table.

Revision ID: 3b7a1f4c2d91
Revises: 39e1c1c2a803
"""

import sqlalchemy as sa
from alembic import op

revision = "3b7a1f4c2d91"
down_revision = "39e1c1c2a803"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("item")


def downgrade() -> None:
    op.create_table(
        "item",
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["user.id"],
            name="item_owner_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="item_pkey"),
    )
