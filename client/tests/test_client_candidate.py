from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import client_candidate, release_inventory


@pytest.fixture
def candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    installer = tmp_path / "parsetrail_1.4.3_windows-x86_64_setup.exe"
    installer.write_bytes(b"synthetic installer, not executable")
    metadata = tmp_path / "metadata.json"
    metadata.write_text(
        json.dumps(
            {
                "source_commit": "a" * 40,
                "source_tag": "client-v1.4.3",
                "target_platform": "windows-x86_64",
                "architecture": "x86_64",
                "client_version": "1.4.3",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        client_candidate,
        "tool_versions",
        lambda *args: {
            "operating_system": "native-builder",
            "python": "3.13.15",
            "python_compiler": "native compiler",
            "uv": "uv 0.12.5",
            "pyinstaller": "6.21.0",
            "packager": "NSIS",
        },
    )
    client_candidate.record_candidate(installer, metadata, packager="nsis")
    return tmp_path


def test_unsigned_candidate_detects_installer_tampering(candidate: Path) -> None:
    args = {"source_commit": "a" * 40, "source_tag": "client-v1.4.3"}
    record = client_candidate.verify_candidate(candidate, **args)
    (candidate / record["installer"]["filename"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="differs"):
        client_candidate.verify_candidate(candidate, **args)


@pytest.mark.parametrize("change", ["source", "target", "gates", "native"])
def test_unsigned_candidate_rejects_incomplete_or_wrong_build(candidate: Path, change: str) -> None:
    path = candidate / client_candidate.BUILD_RECORD
    record = json.loads(path.read_text(encoding="utf-8"))
    if change == "source":
        record["source_commit"] = "b" * 40
    elif change == "target":
        record["target_platform"] = "macos-x86_64"
    elif change == "gates":
        record["checks"]["source_suite"] = False
    else:
        record["target_platform"] = "macos-x86_64"
        record["installer"]["platform"] = "macos-x86_64"
        record["installer"]["filename"] = "parsetrail_1.4.3_macos-x86_64_setup.dmg"
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError):
        client_candidate.verify_candidate(candidate, source_commit="a" * 40, source_tag="client-v1.4.3")


def test_signing_inventory_preserves_native_builder_versions(candidate: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from datetime import datetime, timezone

    from parsetrail.core.client_manifest import ClientInstallerArtifact, ClientManifest, serialize_client_manifest

    record = client_candidate.verify_candidate(candidate, source_commit="a" * 40, source_tag="client-v1.4.3")
    manifest = ClientManifest(
        release_sequence=123,
        published_at=datetime.now(timezone.utc),
        key_id="plugin-ed25519-" + "a" * 32,
        artifacts=(ClientInstallerArtifact.model_validate(record["installer"]),),
    )
    (candidate / "client-manifest.json").write_bytes(serialize_client_manifest(manifest))
    (candidate / "client-manifest.sig").write_bytes(b"s" * 64)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Signing another host's installer must not collect this host's build tools")

    monkeypatch.setattr(release_inventory, "tool_versions", forbidden)
    inventory = release_inventory.create_inventory(
        release_dir=candidate,
        source_commit="a" * 40,
        source_tag="client-v1.4.3",
        release_kind="client",
        target_platform="windows-x86_64",
        version="1.4.3",
        packager="none",
        build_record=candidate / client_candidate.BUILD_RECORD,
    )
    assert inventory["tools"] == record["tools"]
