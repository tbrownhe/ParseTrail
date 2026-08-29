import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.routes import clients
from app.core.config import settings


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """These catalog checks never touch the database."""
    yield


class _Connection:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        pass


class _Engine:
    @contextmanager
    def begin(self) -> Generator[_Connection, None, None]:
        yield _Connection()


def _write_release(
    client_root: Path,
    *,
    platform: str = "win64",
    version: str = "1.2.3",
    release_sequence: int = 42,
) -> tuple[bytes, bytes]:
    suffix = clients.SUPPORTED_PLATFORMS[platform]
    filename = f"parsetrail_{version}_{platform}_setup{suffix}"
    installer = b"installer"
    release_dir = client_root / platform / clients.CLIENT_RELEASES_DIR / str(release_sequence)
    release_dir.mkdir(parents=True)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "release_sequence": release_sequence,
        "published_at": "2026-08-28T00:00:00+00:00",
        "key_id": "plugin-ed25519-00000000000000000000000000000000",
        "artifacts": [
            {
                "artifact_type": "client_installer",
                "filename": filename,
                "version": version,
                "platform": platform,
                "size": len(installer),
                "sha256": "0" * 64,
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    (release_dir / clients.CLIENT_MANIFEST).write_bytes(manifest_bytes)
    (release_dir / clients.CLIENT_SIGNATURE).write_bytes(b"s" * 64)
    (release_dir / filename).write_bytes(installer)
    pointer = client_root / platform / clients.CURRENT_RELEASE
    pointer.write_text(
        json.dumps({"schema_version": 1, "release_sequence": release_sequence}),
        encoding="utf-8",
    )
    return manifest_bytes, installer


def test_serves_exact_active_manifest_and_signature(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_bytes, _ = _write_release(tmp_path)
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    manifest_response = client.get(f"{settings.API_V1_STR}/clients/win64/manifest")
    signature_response = client.get(f"{settings.API_V1_STR}/clients/win64/manifest-signature")

    assert manifest_response.status_code == 200
    assert manifest_response.content == manifest_bytes
    assert signature_response.status_code == 200
    assert signature_response.content == b"s" * 64
    assert manifest_response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_catalog_is_derived_from_active_manifests(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_release(tmp_path)
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/")

    assert response.status_code == 200
    assert response.json() == [
        {
            "file_name": "parsetrail_1.2.3_win64_setup.exe",
            "version": "1.2.3",
            "platform": "win64",
            "file_path": "win64",
            "size": 9,
            "sha256": "0" * 64,
        }
    ]


@pytest.mark.parametrize(
    "pointer",
    [
        {"schema_version": 1, "release_sequence": "../../outside"},
        {"schema_version": 2, "release_sequence": 42},
        {"schema_version": 1, "release_sequence": True},
        {"schema_version": 1, "release_sequence": 42, "extra": "field"},
    ],
)
def test_rejects_invalid_release_pointer(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pointer: dict[str, Any],
) -> None:
    platform_root = tmp_path / "win64"
    platform_root.mkdir(parents=True)
    (platform_root / clients.CURRENT_RELEASE).write_text(json.dumps(pointer), encoding="utf-8")
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/win64/manifest")

    assert response.status_code == 503
    assert response.json()["detail"] == "Client catalog unavailable"


def test_rejects_manifest_for_another_platform(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_bytes, _ = _write_release(tmp_path)
    release_dir = tmp_path / "win64" / clients.CLIENT_RELEASES_DIR / "42"
    manifest = json.loads(manifest_bytes)
    manifest["artifacts"][0]["platform"] = "macos"
    (release_dir / clients.CLIENT_MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/win64/manifest")

    assert response.status_code == 503


def test_rejects_unlisted_installer_version(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_release(tmp_path)
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/win64/9.9.9")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client installer not found"


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "not-a-version"])
def test_rejects_invalid_semantic_version(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    _write_release(tmp_path)
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/win64/{version}")

    assert response.status_code == 422


def test_rejects_invalid_platform_with_4xx(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_STR}/clients/linux/latest")

    assert response.status_code == 404
    assert response.json()["detail"] == "Platform not found"


@pytest.mark.parametrize("version", ["1.2.3", "latest"])
def test_downloads_only_the_active_manifest_installer(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    _, installer = _write_release(tmp_path)
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)
    monkeypatch.setattr(clients, "engine", _Engine())

    response = client.get(f"{settings.API_V1_STR}/clients/win64/{version}")

    assert response.status_code == 200
    assert response.content == installer
    assert response.headers["content-disposition"].endswith('filename="parsetrail_1.2.3_win64_setup.exe"')


def test_rejects_installer_with_wrong_size(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_release(tmp_path)
    installer_path = tmp_path / "win64" / clients.CLIENT_RELEASES_DIR / "42" / "parsetrail_1.2.3_win64_setup.exe"
    installer_path.write_bytes(b"short")
    monkeypatch.setattr(clients, "CLIENTS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/clients/win64/1.2.3")

    assert response.status_code == 404
    assert response.json()["detail"] == "Client installer not found"
