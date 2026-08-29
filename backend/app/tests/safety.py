"""Test-environment guards that must run before application imports."""

import os

_LOCAL_TEST_HOSTS = {"127.0.0.1", "::1", "db", "db-test", "localhost"}


def validate_test_database_target(*, server: str, database: str) -> None:
    """Reject database targets that could plausibly be a deployed database."""
    normalized_server = server.strip().lower().strip("[]")
    normalized_database = database.strip().lower()

    is_test_name = (
        normalized_database == "test"
        or normalized_database.startswith("test_")
        or normalized_database.endswith("_test")
    )
    if not is_test_name:
        raise RuntimeError(
            "Refusing to run tests: PARSETRAIL_TEST_POSTGRES_DB must be named "
            "'test', start with 'test_', or end with '_test'."
        )

    if normalized_server not in _LOCAL_TEST_HOSTS:
        raise RuntimeError(
            "Refusing to run tests against a non-local database server. Use a "
            "loopback address or the dedicated 'db'/'db-test' Compose service."
        )


def configure_test_environment() -> None:
    """Install deterministic, test-only settings before importing ``app`` modules.

    Test configuration deliberately uses its own ``PARSETRAIL_TEST_*`` namespace.
    Ordinary ``POSTGRES_*`` variables and the repository ``.env`` are ignored so
    a developer cannot accidentally point pytest at a deployed database.
    """
    server = os.getenv("PARSETRAIL_TEST_POSTGRES_SERVER", "127.0.0.1")
    database = os.getenv("PARSETRAIL_TEST_POSTGRES_DB", "parsetrail_test")
    validate_test_database_target(server=server, database=database)

    test_settings = {
        "PARSETRAIL_ENV_FILE": "",
        "ENVIRONMENT": "local",
        "PROJECT_NAME": "ParseTrail Test",
        "FRONTEND_HOST": "http://localhost:5173",
        "BACKEND_CORS_ORIGINS": "[]",
        "SECRET_KEY": "test-only-secret-key-do-not-use-in-production",
        "POSTGRES_SERVER": server,
        "POSTGRES_PORT": os.getenv("PARSETRAIL_TEST_POSTGRES_PORT", "64321"),
        "POSTGRES_USER": os.getenv("PARSETRAIL_TEST_POSTGRES_USER", "postgres"),
        "POSTGRES_PASSWORD": os.getenv("PARSETRAIL_TEST_POSTGRES_PASSWORD", "parsetrail-test-only"),
        "POSTGRES_DB": database,
        "FIRST_SUPERUSER": "admin@example.com",
        "FIRST_SUPERUSER_PASSWORD": "test-only-superuser-password",
        "EMAIL_TEST_USER": "user@example.com",
        # Base64 for 32 zero bytes. This is intentionally public test material.
        "MASTER_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "SENTRY_DSN": "",
    }
    os.environ.update(test_settings)
