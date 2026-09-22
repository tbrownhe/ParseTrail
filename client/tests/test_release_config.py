import json
from pathlib import Path

import pytest
from scripts.release import ReleaseConfigError, load_config


def test_loads_explicit_release_configuration(tmp_path: Path) -> None:
    clients = tmp_path / "clients"
    plugins = tmp_path / "plugins"
    clients.mkdir()
    plugins.mkdir()
    key = tmp_path / "release-key.pem"
    key.write_text("encrypted key fixture", encoding="utf-8")
    config_path = tmp_path / "release.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "clients_dir": str(clients),
                "plugins_dir": str(plugins),
                "signing_key": str(key),
                "public_api_base_url": "https://api.parsetrail.com/api/v1",
                "remote": None,
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.clients_dir == clients.resolve()
    assert config.plugins_dir == plugins.resolve()
    assert config.signing_key == key.resolve()
    assert config.public_api_base_url == "https://api.parsetrail.com/api/v1"
    assert config.remote is None


def test_rejects_missing_release_directory(tmp_path: Path) -> None:
    key = tmp_path / "key.pem"
    key.write_text("key", encoding="utf-8")
    config_path = tmp_path / "release.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "clients_dir": str(tmp_path / "missing"),
                "plugins_dir": str(tmp_path),
                "signing_key": str(key),
                "public_api_base_url": "https://api.parsetrail.com/api/v1",
                "remote": None,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ReleaseConfigError, match="clients_dir"):
        load_config(config_path)


def test_publication_does_not_resolve_private_key_or_builder_paths(tmp_path, monkeypatch):
    from scripts import release

    config_path = tmp_path / "release.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "clients_dir": "disconnected",
                "plugins_dir": "disconnected",
                "signing_key": "disconnected",
                "public_api_base_url": "https://staging.example.invalid/api/v1",
                "remote": {
                    "user": "operator",
                    "host": "staging.example.invalid",
                    "clients_dir": "/clients",
                    "plugins_dir": "/plugins",
                },
            }
        ),
        encoding="utf-8",
    )

    def forbidden(*_args, **_kwargs):
        pytest.fail("Public verification must not access private/build paths")

    monkeypatch.setattr(release, "_existing_path", forbidden)
    config = load_config(config_path, publication_only=True)
    assert isinstance(config, release.PublicationConfig)
