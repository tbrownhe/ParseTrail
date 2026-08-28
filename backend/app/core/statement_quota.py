"""Database-backed abuse limits for encrypted statement contributions."""

import uuid

from sqlalchemy import Connection, text

MAX_PENDING_STATEMENTS_PER_USER = 10
MAX_STATEMENTS_PER_USER_PER_DAY = 20


class StatementQuotaExceeded(RuntimeError):
    """Raised when a user must wait for processing or the rolling window."""


def enforce_statement_quota(
    connection: Connection,
    user_id: uuid.UUID,
    *,
    lock_user: bool,
) -> None:
    """Check per-user limits, optionally serializing the final insert transaction."""
    parameters = {"user_id": str(user_id)}
    if lock_user:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
            parameters,
        )

    counts = (
        connection.execute(
            text(
                """
                SELECT
                    count(*) FILTER (WHERE plugin_status = 'pending') AS pending_count,
                    count(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '24 hours') AS daily_count
                FROM statement_uploads
                WHERE user_id = CAST(:user_id AS uuid)
                """
            ),
            parameters,
        )
        .mappings()
        .one()
    )
    if int(counts["pending_count"]) >= MAX_PENDING_STATEMENTS_PER_USER:
        raise StatementQuotaExceeded(
            "Too many statements are awaiting parser development; try again after one is processed"
        )
    if int(counts["daily_count"]) >= MAX_STATEMENTS_PER_USER_PER_DAY:
        raise StatementQuotaExceeded("Daily statement contribution limit reached; try again later")
