"""Add budget

Revision ID: e0ecdd6abcc6
Revises: 0001_initial_schema
Create Date: 2025-12-07 00:37:23.820685

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e0ecdd6abcc6"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize existing Types before enforcing constraint.
    op.execute("UPDATE \"Categories\" SET Type='Expense' WHERE Type IS NULL OR Type=''")

    # Add a per-category monthly budget amount and enforce Type values.
    with op.batch_alter_table("Categories", schema=None) as batch_op:
        batch_op.add_column(sa.Column("Budget", sa.Numeric(12, 2), nullable=True))
        batch_op.alter_column("Type", existing_type=sa.String(), nullable=False)
        batch_op.create_check_constraint(
            "ck_categories_type_valid",
            "Type IN ('Expense','Income','Transfer')",
        )


def downgrade() -> None:
    with op.batch_alter_table("Categories", schema=None) as batch_op:
        batch_op.drop_constraint("ck_categories_type_valid", type_="check")
        batch_op.alter_column("Type", existing_type=sa.String(), nullable=True)
        batch_op.drop_column("Budget")
