import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes import plugins
from app.core.config import settings


def _write_release(plugin_root: Path, release_sequence: int = 42) -> bytes:
    release_dir = plugin_root / "releases" / str(release_sequence)
    release_dir.mkdir(parents=True)
    manifest = {
        "schema_version": 1,
        "release_sequence": release_sequence,
        "published_at": "2026-07-23T00:00:00+00:00",
        "key_id": "plugin-ed25519-00000000000000000000000000000000",
        "artifacts": [
            {
                "artifact_type": "plugin",
                "filename": "example_plugin.pyc",
                "plugin_name": "example_plugin",
                "version": "1.2.3",
                "minimum_client_version": "1.0.0",
                "python_tag": "cp310",
                "python_magic": "00000000",
                "size": 6,
                "sha256": "0" * 64,
                "company": "Example Bank",
                "statement_suffix": ".pdf",
                "statement_type": "Example Statement",
            }
        ],
    }
    manifest_bytes = json.dumps(manifest, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    (release_dir / plugins.PLUGIN_MANIFEST).write_bytes(manifest_bytes)
    (release_dir / plugins.PLUGIN_SIGNATURE).write_bytes(b"s" * 64)
    (plugin_root / plugins.CURRENT_RELEASE).write_text(
        json.dumps({"schema_version": 1, "release_sequence": release_sequence}),
        encoding="utf-8",
    )
    return manifest_bytes


def test_serves_exact_active_manifest_and_signature(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_bytes = _write_release(tmp_path)
    monkeypatch.setattr(plugins, "PLUGINS_DIR", tmp_path)

    manifest_response = client.get(f"{settings.API_V1_STR}/plugins/manifest")
    signature_response = client.get(f"{settings.API_V1_STR}/plugins/manifest-signature")

    assert manifest_response.status_code == 200
    assert manifest_response.content == manifest_bytes
    assert signature_response.status_code == 200
    assert signature_response.content == b"s" * 64
    assert manifest_response.headers["cache-control"] == ("no-cache, no-store, must-revalidate")


def test_legacy_catalog_is_derived_from_active_signed_manifest(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_release(tmp_path)
    monkeypatch.setattr(plugins, "PLUGINS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/plugins/")

    assert response.status_code == 200
    assert response.json() == [
        {
            "FILENAME": "example_plugin.pyc",
            "PLUGIN_NAME": "example_plugin",
            "VERSION": "1.2.3",
            "MIN_CLIENT_VERSION": "1.0.0",
            "COMPANY": "Example Bank",
            "SUFFIX": ".pdf",
            "STATEMENT_TYPE": "Example Statement",
        }
    ]


def test_rejects_invalid_release_pointer(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / plugins.CURRENT_RELEASE).write_text(
        '{"schema_version":1,"release_sequence":"../../outside"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(plugins, "PLUGINS_DIR", tmp_path)

    response = client.get(f"{settings.API_V1_STR}/plugins/manifest")

    assert response.status_code == 503
    assert response.json()["detail"] == "Plugin catalog unavailable"
