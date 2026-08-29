import uuid
from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from app.core.statement_quota import (
    MAX_PENDING_STATEMENTS_PER_USER,
    MAX_STATEMENTS_PER_USER_PER_DAY,
    StatementQuotaExceeded,
    enforce_statement_quota,
)
from sqlalchemy import Connection


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Quota unit tests use a bounded fake database response."""
    yield


def _connection_with_counts(*, pending: int, daily: int, lock_user: bool) -> MagicMock:
    connection = MagicMock(spec=Connection)
    result = MagicMock()
    result.mappings.return_value.one.return_value = {
        "pending_count": pending,
        "daily_count": daily,
    }
    if lock_user:
        connection.execute.side_effect = [MagicMock(), result]
    else:
        connection.execute.return_value = result
    return connection


def test_allows_submission_below_both_limits() -> None:
    connection = _connection_with_counts(pending=2, daily=3, lock_user=False)

    enforce_statement_quota(connection, uuid.uuid4(), lock_user=False)

    connection.execute.assert_called_once()


def test_final_check_acquires_user_advisory_lock_before_counting() -> None:
    connection = _connection_with_counts(pending=2, daily=3, lock_user=True)

    enforce_statement_quota(connection, uuid.uuid4(), lock_user=True)

    assert connection.execute.call_count == 2
    first_query = str(connection.execute.call_args_list[0].args[0])
    assert "pg_advisory_xact_lock" in first_query


@pytest.mark.parametrize(
    ("pending", "daily", "message"),
    [
        (MAX_PENDING_STATEMENTS_PER_USER, 0, "awaiting parser development"),
        (0, MAX_STATEMENTS_PER_USER_PER_DAY, "Daily statement contribution limit"),
    ],
)
def test_rejects_users_at_either_limit(pending: int, daily: int, message: str) -> None:
    connection = _connection_with_counts(pending=pending, daily=daily, lock_user=False)

    with pytest.raises(StatementQuotaExceeded, match=message):
        enforce_statement_quota(connection, uuid.uuid4(), lock_user=False)
