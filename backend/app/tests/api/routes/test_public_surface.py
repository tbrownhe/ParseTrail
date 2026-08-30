from fastapi.testclient import TestClient
from sqlmodel import SQLModel

from app.core.config import settings
from app.main import app


def test_template_items_surface_is_removed(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/items/")

    assert response.status_code == 404
    assert "item" not in SQLModel.metadata.tables

    openapi = app.openapi()
    assert not any(path.startswith(f"{settings.API_V1_STR}/items") for path in openapi["paths"])
    assert not any(name.startswith("Item") for name in openapi["components"]["schemas"])
