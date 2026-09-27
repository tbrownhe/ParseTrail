from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.client_manifest import ClientArtifactError
from parsetrail.core.plugin_manifest import key_id_for_public_key
from scripts.client_release import sign_release, verify_release
from scripts.immutable_publish import PublishError

from scripts import client_candidate, desktop_release, release_inventory
from tests.test_immutable_publish import FakeTransport
from tests.test_publish_existing import _git


@pytest.fixture
def pair(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    (repo / "client").mkdir(parents=True)
    (repo / "client/.python-version").write_text("3.13.15\n", encoding="utf-8")
    _git(repo, "init")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "synthetic")
    _git(repo, "tag", "client-v1.4.3")
    commit = _git(repo, "rev-parse", "HEAD")
    key = Ed25519PrivateKey.generate()
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    trust = tmp_path / "trust.json"
    trust.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": key_id_for_public_key(raw),
                        "public_key": base64.b64encode(raw).decode(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    private = tmp_path / "key.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"test-only"),
        )
    )
    source = tmp_path / "input"
    unsigned = tmp_path / "unsigned"
    source.mkdir()
    unsigned.mkdir()
    monkeypatch.setattr(release_inventory, "_command_version", lambda *_args, **_kwargs: "native test tool")
    monkeypatch.setattr(release_inventory.platform, "python_version", lambda: "3.13.15")
    evidence = {"schema_version": 1, "source_tag": "client-v1.4.3", "source_commit": commit, "targets": {}}
    for target in client_candidate.TARGETS:
        directory = source / target
        directory.mkdir()
        suffix = "exe" if target.startswith("windows") else "dmg"
        installer = directory / f"parsetrail_1.4.3_{target}_setup.{suffix}"
        installer.write_bytes(f"synthetic {target}".encode())
        meta = tmp_path / f"{target}-metadata.json"
        meta.write_text(
            json.dumps(
                {
                    "source_commit": commit,
                    "source_tag": "client-v1.4.3",
                    "client_version": "1.4.3",
                    "target_platform": target,
                    "architecture": "x86_64",
                }
            ),
            encoding="utf-8",
        )
        native = None
        if target.startswith("macos"):
            native = tmp_path / "native.json"
            native.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "build_inputs": {"target_platform": target, "architecture": "x86_64", "openssl_static": True},
                        "library_audit": {"architecture": "x86_64", "cryptography_extensions": 1},
                        "frozen_smoke": {"passed": True},
                    }
                ),
                encoding="utf-8",
            )
        client_candidate.record_candidate(
            installer, meta, packager="nsis" if suffix == "exe" else "create-dmg", native_report=native
        )
        shutil.copytree(directory, unsigned / target)
        sign_release(installer, target, "1.4.3", private, trust, b"test-only", release_sequence=2)
        release_inventory.create_inventory(
            release_dir=directory,
            source_commit=commit,
            source_tag="client-v1.4.3",
            release_kind="client",
            target_platform=target,
            version="1.4.3",
            packager="none",
        )
        evidence["targets"][target] = {"inventory_sha256": release_inventory.inventory_digest(directory)}
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    settings = {
        "staging": {
            "public_api_base_url": "https://staging.example.invalid/api/v1",
            "remote": {"user": "operator", "host": "server", "clients_dir": "/clients", "plugins_dir": "/plugins"},
        }
    }
    return SimpleNamespace(
        repo=repo,
        source=source,
        unsigned=unsigned,
        trust=trust,
        private=private,
        evidence=evidence_path,
        output=tmp_path / "accepted",
        settings=settings,
    )


def adopted(pair) -> Path:
    return desktop_release.adopt(pair.source, pair.evidence, pair.output, repository=pair.repo, trust_store=pair.trust)


def test_adopt_preserves_signed_bytes_without_signing(pair, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("Existing accepted releases must not be re-signed")

    monkeypatch.setattr(desktop_release, "sign_release", forbidden)
    record_path = adopted(pair)
    record = desktop_release.read_json(record_path)
    for target in client_candidate.TARGETS:
        assert record["targets"][target]["release_sequence"] == 2
        for path in (pair.output / target).iterdir():
            assert path.read_bytes() == (pair.source / target / path.name).read_bytes()


def test_adopt_rejects_modified_inventory_and_leaves_no_completed_release(pair):
    path = pair.source / "macos-x86_64/release-inventory.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(PublishError, match="inventory differs"):
        adopted(pair)
    assert not pair.output.exists()


def test_prepare_signs_both_ci_targets_with_one_passphrase_prompt(pair, monkeypatch):
    def download(_run, destination):
        for target in client_candidate.TARGETS:
            shutil.copytree(pair.unsigned / target, destination / target)
        return {"run_id": 42}

    prompts = []
    monkeypatch.setattr(desktop_release, "download_run", download)
    monkeypatch.setattr(desktop_release.getpass, "getpass", lambda prompt: prompts.append(prompt) or "test-only")
    record_path = desktop_release.prepare(
        42, "client-v1.4.3", pair.output, pair.private, repository=pair.repo, trust_store=pair.trust
    )
    assert len(prompts) == 1
    assert desktop_release.read_json(record_path)["origin"]["run_id"] == 42
    for target in client_candidate.TARGETS:
        manifest = verify_release(pair.output / target, pair.trust)
        assert manifest.artifacts[0].platform == target
        record = desktop_release.read_json(pair.output / target / "release-inventory.json")
        builder = desktop_release.read_json(pair.unsigned / target / "build-record.json")
        assert record["tools"] == builder["tools"]


def test_prepare_checks_both_targets_before_requesting_signing_key(pair, monkeypatch):
    def download(_run, destination):
        shutil.copytree(pair.unsigned / "windows-x86_64", destination / "windows-x86_64")
        shutil.copytree(pair.unsigned / "windows-x86_64", destination / "macos-x86_64")
        return {"run_id": 42}

    def forbidden(*_args, **_kwargs):
        pytest.fail("Invalid target pair must fail before requesting the key")

    monkeypatch.setattr(desktop_release, "download_run", download)
    monkeypatch.setattr(desktop_release.getpass, "getpass", forbidden)
    with pytest.raises(ValueError, match="target/Python"):
        desktop_release.prepare(
            42, "client-v1.4.3", pair.output, pair.private, repository=pair.repo, trust_store=pair.trust
        )
    assert not pair.output.exists()


def test_publish_rejects_changed_second_installer_before_uploading_first(pair, monkeypatch):
    path = adopted(pair)
    manifest = verify_release(pair.output / "macos-x86_64", pair.trust)
    (pair.output / "macos-x86_64" / manifest.artifacts[0].filename).write_bytes(b"tampered")
    transport = FakeTransport()
    monkeypatch.setattr("builtins.input", lambda _prompt: pytest.fail("Invalid pair cannot reach confirmation"))
    with pytest.raises(ClientArtifactError):
        desktop_release.publish(
            path,
            pair.settings,
            "staging",
            activate=True,
            repository=pair.repo,
            trust_store=pair.trust,
            transport=transport,
        )
    assert transport.upload_count == 0


def test_interrupted_second_upload_resumes_exact_bytes_without_republishing_first(pair, monkeypatch):
    path = adopted(pair)
    transport = FakeTransport()
    transport.fail_upload_at = 7  # First target is complete; second signature upload fails.
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt: prompts.append(prompt) or "publish 1.4.3 staging")
    monkeypatch.setattr(desktop_release, "smoke_release", lambda **_kwargs: None)
    with pytest.raises(PublishError, match="upload failure"):
        desktop_release.publish(
            path,
            pair.settings,
            "staging",
            activate=True,
            repository=pair.repo,
            trust_store=pair.trust,
            transport=transport,
        )
    state = desktop_release.read_json(path)["publication"]["staging"]["targets"]
    assert state["windows-x86_64"] == "verified"
    assert state["macos-x86_64"] == "unknown; reconcile on retry"
    original_windows = {k: v for k, v in transport.files.items() if "/windows-x86_64/" in k}
    desktop_release.publish(
        path, pair.settings, "staging", activate=True, repository=pair.repo, trust_store=pair.trust, transport=transport
    )
    assert len(prompts) == 2  # One confirmation for the pair on each attempt.
    assert transport.upload_count == 11
    assert {k: v for k, v in transport.files.items() if "/windows-x86_64/" in k} == original_windows
    assert set(desktop_release.read_json(path)["publication"]["staging"]["targets"].values()) == {"verified"}


def test_production_activation_requires_verified_staging_pair(pair):
    path = adopted(pair)
    pair.settings["production"] = {
        "public_api_base_url": "https://production.example.invalid/api/v1",
        "remote": {
            "user": "operator",
            "host": "server",
            "clients_dir": "/production-clients",
            "plugins_dir": "/production-plugins",
        },
    }
    with pytest.raises(ValueError, match="both targets on staging"):
        desktop_release.publish(
            path, pair.settings, "production", activate=True, repository=pair.repo, trust_store=pair.trust
        )


def test_resume_refuses_a_changed_partial_file_without_overwriting_it(pair, monkeypatch):
    path = adopted(pair)
    transport = FakeTransport()
    transport.fail_upload_at = 7
    monkeypatch.setattr("builtins.input", lambda _prompt: "publish 1.4.3 staging")
    monkeypatch.setattr(desktop_release, "smoke_release", lambda **_kwargs: None)
    args = {"activate": True, "repository": pair.repo, "trust_store": pair.trust, "transport": transport}
    with pytest.raises(PublishError, match="upload failure"):
        desktop_release.publish(path, pair.settings, "staging", **args)
    partial = "/clients/macos-x86_64/releases/2/client-manifest.json"
    transport.files[partial] = b"changed partial upload"
    uploads_before = transport.upload_count
    with pytest.raises(PublishError, match="size mismatch"):
        desktop_release.publish(path, pair.settings, "staging", **args)
    assert transport.files[partial] == b"changed partial upload"
    assert transport.upload_count == uploads_before
    assert "/clients/macos-x86_64/current-release.json" not in transport.files
