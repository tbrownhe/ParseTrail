import hashlib
import json
from pathlib import Path

import pytest

from scripts import release_inventory


def test_records_source_tools_and_all_release_checksums(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer = b"installer bytes"
    installer_name = "parsetrail_1.3.0_win64_setup.exe"
    (tmp_path / installer_name).write_bytes(installer)
    manifest = {
        "schema_version": 1,
        "release_sequence": 7,
        "artifacts": [
            {
                "filename": installer_name,
                "size": len(installer),
                "sha256": hashlib.sha256(installer).hexdigest(),
            }
        ],
    }
    (tmp_path / "client-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "client-manifest.sig").write_bytes(b"s" * 64)
    monkeypatch.setattr(release_inventory, "_command_version", lambda command: f"{command[0]} test")

    inventory = release_inventory.create_inventory(
        release_dir=tmp_path,
        source_commit="b" * 40,
        source_tag="client-v1.3.0",
        release_kind="client",
        target_platform="win64",
        version="1.3.0",
        packager="nsis",
    )

    assert inventory["source_commit"] == "b" * 40
    assert inventory["tools"]["uv"] == "uv test"
    assert inventory["tools"]["packager"] == "makensis.exe test"
    assert {item["filename"] for item in inventory["files"]} == {
        installer_name,
        "client-manifest.json",
        "client-manifest.sig",
    }
    assert (tmp_path / "release-inventory.json").is_file()


def test_plugin_inventory_requires_signed_source_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"plugin"
    (tmp_path / "parser.pyc").write_bytes(payload)
    (tmp_path / "plugin-manifest.sig").write_bytes(b"s" * 64)
    (tmp_path / "plugin-manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "release_sequence": 8,
                "source_commit": "a" * 40,
                "artifacts": [
                    {
                        "filename": "parser.pyc",
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(release_inventory, "_command_version", lambda _command: "test")

    with pytest.raises(ValueError, match="source commit"):
        release_inventory.create_inventory(
            release_dir=tmp_path,
            source_commit="b" * 40,
            source_tag="plugins-2026.08.29",
            release_kind="plugins",
            target_platform="python-3.13.15",
            version=None,
            packager="none",
        )
