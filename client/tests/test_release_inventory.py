import hashlib
import json
from pathlib import Path

import pytest

from scripts import release_inventory


def test_records_source_tools_and_all_release_checksums(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packager_executable = tmp_path / "makensis.exe"
    packager_executable.write_bytes(b"test executable")
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
    observed_commands: list[tuple[tuple[str, ...], Path | None]] = []

    def command_version(command: tuple[str, ...], *, executable: Path | None = None) -> str:
        observed_commands.append((command, executable))
        return f"{command[0]} test"

    monkeypatch.setattr(release_inventory, "_command_version", command_version)

    inventory = release_inventory.create_inventory(
        release_dir=tmp_path,
        source_commit="b" * 40,
        source_tag="client-v1.3.0",
        release_kind="client",
        target_platform="win64",
        version="1.3.0",
        packager="nsis",
        packager_executable=packager_executable,
    )

    assert inventory["source_commit"] == "b" * 40
    assert inventory["tools"]["uv"] == "uv test"
    assert inventory["tools"]["packager"] == "makensis.exe test"
    assert observed_commands == [
        (("uv", "--version"), None),
        (("makensis.exe", "/VERSION"), packager_executable),
    ]
    assert {item["filename"] for item in inventory["files"]} == {
        installer_name,
        "client-manifest.json",
        "client-manifest.sig",
    }
    assert (tmp_path / "release-inventory.json").is_file()


def test_explicit_packager_executable_must_exist(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Required release tool was not found"):
        release_inventory._command_version(
            ("makensis.exe", "/VERSION"),
            executable=tmp_path / "missing-makensis.exe",
        )


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


@pytest.mark.parametrize("invalid", [None, "target", "static", "missing_crypto", "failed_smoke", "malformed"])
def test_mac_inventory_preserves_only_complete_native_acceptance(tmp_path, monkeypatch, invalid):
    installer = b"synthetic mac installer"
    filename = "parsetrail_1.3.1_macos_setup.dmg"
    (tmp_path / filename).write_bytes(installer)
    (tmp_path / "client-manifest.sig").write_bytes(b"s" * 64)
    (tmp_path / "client-manifest.json").write_text(
        json.dumps(
            {
                "release_sequence": 9,
                "artifacts": [
                    {"filename": filename, "size": len(installer), "sha256": hashlib.sha256(installer).hexdigest()}
                ],
            }
        ),
        encoding="utf-8",
    )
    evidence = {
        "schema_version": 1,
        "build_inputs": {"target_platform": "macos", "architecture": "x86_64", "openssl_static": True},
        "library_audit": {"architecture": "x86_64", "cryptography_extensions": 1},
        "frozen_smoke": {"passed": True},
    }
    if invalid == "target":
        evidence["build_inputs"]["architecture"] = "arm64"
    elif invalid == "static":
        evidence["build_inputs"]["openssl_static"] = False
    elif invalid == "missing_crypto":
        evidence["library_audit"]["cryptography_extensions"] = 0
    elif invalid == "failed_smoke":
        evidence["frozen_smoke"]["passed"] = False
    elif invalid == "malformed":
        evidence["build_inputs"] = []
    report = tmp_path / "native-report.json"
    report.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(release_inventory, "_command_version", lambda _command: "test")

    def create():
        return release_inventory.create_inventory(
            release_dir=tmp_path,
            source_commit="b" * 40,
            source_tag="client-v1.3.1",
            release_kind="client",
            target_platform="macos",
            version="1.3.1",
            packager="create-dmg",
            native_report=report,
        )

    if invalid:
        with pytest.raises(ValueError, match="evidence"):
            create()
        assert not (tmp_path / "release-inventory.json").exists()
    else:
        assert create()["native_build"] == evidence
        assert json.loads((tmp_path / "release-inventory.json").read_text())["native_build"] == evidence
