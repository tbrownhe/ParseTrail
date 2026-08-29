import os

import pytest

from app.tests.safety import configure_test_environment, validate_test_database_target

configure_test_environment()

from app.core.config import settings  # noqa: E402


@pytest.mark.parametrize(
    ("server", "database"),
    [
        ("127.0.0.1", "parsetrail"),
        ("db", "production"),
        ("database.example.com", "parsetrail_test"),
    ],
)
def test_rejects_unsafe_test_database_targets(server: str, database: str) -> None:
    with pytest.raises(RuntimeError, match="Refusing to run tests"):
        validate_test_database_target(server=server, database=database)


@pytest.mark.parametrize(
    ("server", "database"),
    [
        ("127.0.0.1", "parsetrail_test"),
        ("localhost", "test_parsetrail"),
        ("db", "test"),
    ],
)
def test_accepts_local_test_database_targets(server: str, database: str) -> None:
    validate_test_database_target(server=server, database=database)


def test_configuration_ignores_normal_database_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_SERVER", "production.example.com")
    monkeypatch.setenv("POSTGRES_DB", "parsetrail")
    monkeypatch.delenv("PARSETRAIL_TEST_POSTGRES_SERVER", raising=False)
    monkeypatch.delenv("PARSETRAIL_TEST_POSTGRES_DB", raising=False)

    configure_test_environment()

    assert settings.POSTGRES_DB == "parsetrail_test"
    assert settings.POSTGRES_SERVER == "127.0.0.1"
    assert os.environ["PARSETRAIL_ENV_FILE"] == ""
    assert settings.ENVIRONMENT == "local"
    assert settings.FIRST_SUPERUSER == "admin@example.com"
    assert settings.EMAIL_TEST_USER == "user@example.com"
