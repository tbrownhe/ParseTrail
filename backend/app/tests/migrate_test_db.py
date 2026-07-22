"""Apply Alembic migrations to the guarded disposable test database."""

from app.tests.safety import configure_test_environment

configure_test_environment()

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402


def main() -> None:
    command.upgrade(Config("alembic.ini"), "head")


if __name__ == "__main__":
    main()
