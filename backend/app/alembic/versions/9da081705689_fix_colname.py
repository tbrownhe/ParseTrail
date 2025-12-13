"""Fix colname

Revision ID: 9da081705689
Revises: d8abce57e25d
Create Date: 2025-01-29 00:44:02.910424

"""

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "9da081705689"
down_revision = "d8abce57e25d"
branch_labels = None
depends_on = None


def upgrade():
    # Rename 'request_ip' column to 'client_ip' in key_requests
    op.alter_column("key_requests", "request_ip", new_column_name="client_ip")


def downgrade():
    # Rollback: Rename 'client_ip' back to 'request_ip' in key_requests
    op.alter_column("key_requests", "client_ip", new_column_name="request_ip")
