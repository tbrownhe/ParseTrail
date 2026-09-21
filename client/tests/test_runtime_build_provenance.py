"""A frozen release must read the same provenance resource as its About dialog."""

import json
import sys

import pytest
from parsetrail import main
from parsetrail.core import build_metadata, client_targets, runtime_smoke
from parsetrail.core.credentials import credential_store
from parsetrail.version import __version__


@pytest.fixture
def frozen_bundle(tmp_path, monkeypatch):
    resource_dir = tmp_path / "_internal"
    metadata_dir = resource_dir / "parsetrail"
    metadata_dir.mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(resource_dir), raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(client_targets, "native_installer_target", lambda: "windows-x86_64")
    monkeypatch.setattr(credential_store, "available", True)
    monkeypatch.setattr(runtime_smoke, "check_native_operations", lambda: None)
    payload = {
        "schema_version": 2,
        "architecture": "x86_64",
        "client_version": __version__,
        "source_commit": "a" * 40,
        "source_tag": f"client-v{__version__}",
        "target_platform": "windows-x86_64",
        "built_at": "2026-09-20T00:00:00+00:00",
    }
    return metadata_dir, payload


def test_frozen_smoke_and_about_read_the_packaged_resource(frozen_bundle):
    metadata_dir, payload = frozen_bundle
    (metadata_dir / "build-metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    assert main.run_runtime_smoke_test() == 0
    assert build_metadata.build_provenance_label() == f"client-v{__version__} ({'a' * 12})"


@pytest.mark.parametrize("filename", [None, "parsetrail-build-random-id.json"])
def test_frozen_smoke_rejects_missing_or_misnamed_provenance(frozen_bundle, filename, monkeypatch):
    metadata_dir, payload = frozen_bundle
    if filename:
        (metadata_dir / filename).write_text(json.dumps(payload), encoding="utf-8")

    def unexpected_native_operations():
        pytest.fail("Unreadable provenance must fail before native smoke operations")

    monkeypatch.setattr(runtime_smoke, "check_native_operations", unexpected_native_operations)
    with pytest.raises(RuntimeError, match="Frozen build metadata is missing or invalid"):
        main.run_runtime_smoke_test()


@pytest.mark.parametrize("mismatch", ["version", "target", "schema"])
def test_frozen_smoke_rejects_incorrect_packaged_provenance(frozen_bundle, mismatch):
    metadata_dir, payload = frozen_bundle
    if mismatch == "version":
        payload.update(client_version="9.9.9", source_tag="client-v9.9.9")
    elif mismatch == "target":
        payload["target_platform"] = "macos-x86_64"
    else:
        payload["schema_version"] = 1
    (metadata_dir / "build-metadata.json").write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(RuntimeError, match="Frozen build metadata"):
        main.run_runtime_smoke_test()


@pytest.mark.usefixtures("frozen_bundle")
def test_source_runtime_smoke_does_not_require_release_metadata(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False)

    assert main.run_runtime_smoke_test() == 0
