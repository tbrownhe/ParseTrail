from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.tests.safety import configure_test_environment

configure_test_environment()

from app.core.config import settings  # noqa: E402
from app.core.db import engine, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Item, User  # noqa: E402
from app.tests.utils.user import authentication_token_from_email  # noqa: E402
from app.tests.utils.utils import get_superuser_token_headers  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(engine) as session:
        init_db(session)
        existing_item_ids = set(session.exec(select(Item.id)).all())
        existing_user_ids = set(session.exec(select(User.id)).all())
        yield session
        session.rollback()
        for item in session.exec(select(Item)).all():
            if item.id not in existing_item_ids:
                session.delete(item)
        session.commit()
        for user in session.exec(select(User)).all():
            if user.id not in existing_user_ids:
                session.delete(user)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
