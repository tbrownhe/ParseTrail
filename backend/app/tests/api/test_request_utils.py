from collections.abc import Generator

import pytest
from fastapi import Request

from app.api.request_utils import get_client_host
from app.core.config import settings


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Request metadata handling is independent of database integration."""
    yield


def _request(*, client: str = "172.18.0.2", cloudflare_host: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if cloudflare_host is not None:
        headers.append((b"cf-connecting-ip", cloudflare_host.encode("ascii")))
    return Request(
        {
            "type": "http",
            "headers": headers,
            "client": (client, 443),
        }
    )


@pytest.mark.parametrize("address", ["203.0.113.9", "2001:db8::9"])
def test_production_uses_valid_cloudflare_client_address(
    monkeypatch: pytest.MonkeyPatch,
    address: str,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    assert get_client_host(_request(cloudflare_host=address)) == address


def test_production_rejects_malformed_cloudflare_client_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")

    assert get_client_host(_request(cloudflare_host="not-an-address")) == "172.18.0.2"


def test_nonproduction_ignores_cloudflare_client_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENVIRONMENT", "staging")

    assert get_client_host(_request(cloudflare_host="203.0.113.9")) == "172.18.0.2"
