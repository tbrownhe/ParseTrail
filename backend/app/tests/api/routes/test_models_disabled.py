from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """The removed route check never touches the database."""
    yield


def test_unsigned_model_distribution_is_not_routed(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/models/")

    assert response.status_code == 404
