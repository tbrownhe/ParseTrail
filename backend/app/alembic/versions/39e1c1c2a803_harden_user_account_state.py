"""Harden user account state and token revocation.

Revision ID: 39e1c1c2a803
Revises: e7a727f8990a
Create Date: 2026-08-29
"""

import sqlalchemy as sa
from alembic import op

revision = "39e1c1c2a803"
down_revision = "e7a727f8990a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("pending_email", sa.String(length=255), nullable=True))
    op.add_column(
        "user",
        sa.Column("session_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "user",
        sa.Column("password_reset_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "user",
        sa.Column("email_verification_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_user_pending_email", "user", ["pending_email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_pending_email", table_name="user")
    op.drop_column("user", "email_verification_version")
    op.drop_column("user", "password_reset_version")
    op.drop_column("user", "session_version")
    op.drop_column("user", "pending_email")
