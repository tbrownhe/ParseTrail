from __future__ import annotations

import base64
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.client_manifest import ClientInstallerArtifact, ClientManifest, serialize_client_manifest
from parsetrail.core.plugin_manifest import (
    PluginArtifact,
    PluginManifest,
    current_python_magic,
    key_id_for_public_key,
    serialize_manifest,
)
from scripts.immutable_publish import PublishError
from scripts.release_smoke import ReleaseSmokeError

from scripts import publish_existing as publisher
from scripts import release, release_inventory
from tests.test_immutable_publish import FakeTransport


def _git(repository, *arguments):
    return subprocess.run(
        ["git", "-c", "user.name=Release Test", "-c", "user.email=release@example.invalid", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(params=["windows-x86_64", "macos-x86_64", "plugins"])
def output(tmp_path, monkeypatch, request):
    target = request.param
    kind = "plugins" if target == "plugins" else "client"
    tag = "plugins-test-1" if kind == "plugins" else "client-v1.4.0"
    repository = tmp_path / "repository"
    (repository / "client").mkdir(parents=True)
    (repository / "client/.python-version").write_text("3.13.15\n", encoding="utf-8")
    _git(repository, "init")
    _git(repository, "add", ".")
    _git(repository, "commit", "-m", "synthetic release")
    _git(repository, "tag", tag)
    commit = _git(repository, "rev-parse", "HEAD")
    directory = tmp_path / "saved output"
    directory.mkdir()
    key = Ed25519PrivateKey.generate()
    raw_key = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(raw_key)
    trust_store = tmp_path / "public-keys.json"
    trust_store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [{"key_id": key_id, "public_key": base64.b64encode(raw_key).decode()}],
            }
        ),
        encoding="utf-8",
    )
    payload = b"synthetic artifact; never executable"
    shared = {"version": "1.4.0", "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
    common = {"release_sequence": 2, "published_at": datetime.now(timezone.utc), "key_id": key_id}
    if kind == "client":
        suffix = ".exe" if target == "windows-x86_64" else ".dmg"
        artifact = ClientInstallerArtifact(
            filename=f"parsetrail_1.4.0_{target}_setup{suffix}", platform=target, architecture="x86_64", **shared
        )
        manifest = ClientManifest(artifacts=(artifact,), **common)
        manifest_bytes = serialize_client_manifest(manifest)
        prefix = "client"
    else:
        artifact = PluginArtifact(
            filename="example.pyc",
            plugin_name="example",
            minimum_client_version="1.3.0",
            python_tag="cp313",
            python_magic=current_python_magic(),
            company="Synthetic Bank",
            statement_suffix=".pdf",
            statement_type="Synthetic",
            **shared,
        )
        manifest = PluginManifest(artifacts=(artifact,), source_commit=commit, **common)
        manifest_bytes = serialize_manifest(manifest)
        prefix = "plugin"
    (directory / artifact.filename).write_bytes(payload)
    (directory / f"{prefix}-manifest.json").write_bytes(manifest_bytes)
    (directory / f"{prefix}-manifest.sig").write_bytes(key.sign(manifest_bytes))
    monkeypatch.setattr(release_inventory, "_command_version", lambda *args, **kwargs: "synthetic tool")
    monkeypatch.setattr(release_inventory.platform, "python_version", lambda: "3.13.15")
    release_inventory.create_inventory(
        release_dir=directory,
        source_commit=commit,
        source_tag=tag,
        release_kind=kind,
        target_platform="python-3.13.15" if kind == "plugins" else target,
        version=None if kind == "plugins" else "1.4.0",
        packager="none",
    )
    transport = FakeTransport()
    smokes = []

    def smoke(**kwargs):
        smokes.append({path.name: path.read_bytes() for path in kwargs["release_dir"].iterdir()})

    monkeypatch.setattr(publisher, "smoke_release", smoke)
    arguments = {
        "release_dir": directory,
        "kind": kind,
        "tag": tag,
        "target": None if kind == "plugins" else target,
        "inventory_sha256": release_inventory.inventory_digest(directory),
        "remote_spec": "operator@staging.example.invalid",
        "remote_root": "/catalog",
        "api_base_url": "https://staging.example.invalid/api/v1",
        "trust_store": trust_store,
        "repository": repository,
        "transport": transport,
    }
    return SimpleNamespace(
        arguments=arguments,
        directory=directory,
        transport=transport,
        smokes=smokes,
        repository=repository,
        key=key,
        prefix=prefix,
        artifact=artifact,
        manifest=manifest,
    )


def _approve(output, monkeypatch, *, callback=None):
    target = output.arguments["target"] or "python-3.13.15"

    def answer(_prompt):
        if callback:
            callback()
        return f"publish {output.arguments['kind']} {target} 2"

    monkeypatch.setattr("builtins.input", answer)


def test_publishes_reviewed_bytes_without_private_key_or_rebuild(output, monkeypatch):
    from scripts import client_release, plugin_release

    def forbidden(*_args, **_kwargs):
        pytest.fail("publish-existing must not build, sign, create inventory, or request a private key")

    monkeypatch.setattr(release, "_run", forbidden)
    monkeypatch.setattr(client_release, "sign_release", forbidden)
    monkeypatch.setattr(plugin_release, "load_private_key", forbidden)
    monkeypatch.setattr(plugin_release, "sign_release", forbidden)
    monkeypatch.setattr(release_inventory, "create_inventory", forbidden)
    monkeypatch.setattr(release.getpass, "getpass", forbidden)
    before = {path.name: path.read_bytes() for path in output.directory.iterdir()}
    _approve(output, monkeypatch)

    assert publisher.publish_existing(**output.arguments, activate=True) == 2

    assert {path.name: path.read_bytes() for path in output.directory.iterdir()} == before
    assert output.smokes == [before]
    for name, payload in before.items():
        assert output.transport.files[f"/catalog/releases/2/{name}"] == payload


def test_review_is_local_and_declining_activation_never_uploads(output, monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        pytest.fail("review must not contact the remote or prompt for activation")

    monkeypatch.setattr(output.transport, "exists", forbidden)
    monkeypatch.setattr("builtins.input", forbidden)
    assert publisher.publish_existing(**output.arguments) is None
    assert output.arguments["inventory_sha256"] in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", lambda _prompt: "no")
    with pytest.raises(PublishError, match="not approved"):
        publisher.publish_existing(**output.arguments, activate=True)
    assert output.transport.upload_count == 0
    assert output.smokes == []


@pytest.mark.parametrize("changed", ["artifact", "manifest", "signature", "inventory", "missing-inventory"])
def test_changed_or_missing_output_fails_before_remote_access(output, monkeypatch, changed):
    path = {
        "artifact": output.directory / output.artifact.filename,
        "manifest": output.directory / f"{output.prefix}-manifest.json",
        "signature": output.directory / f"{output.prefix}-manifest.sig",
        "inventory": output.directory / "release-inventory.json",
        "missing-inventory": output.directory / "release-inventory.json",
    }[changed]
    if changed == "missing-inventory":
        path.unlink()
    else:
        path.write_bytes(path.read_bytes() + b" ")
    _approve(output, monkeypatch)
    with pytest.raises((RuntimeError, ValueError)):
        publisher.publish_existing(**output.arguments, activate=True)
    assert output.transport.upload_count == 0
    assert output.smokes == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_commit", "b" * 40),
        ("source_tag", "different-tag"),
        ("target_platform", "macos-arm64"),
        ("release_kind", "different-kind"),
        ("release_sequence", 3),
        ("version", "9.9.9"),
    ],
)
def test_rehashed_inventory_with_wrong_identity_is_rejected(output, monkeypatch, field, value):
    path = output.directory / "release-inventory.json"
    inventory = json.loads(path.read_bytes())
    inventory[field] = value
    path.write_text(json.dumps(inventory), encoding="utf-8")
    output.arguments["inventory_sha256"] = release_inventory.inventory_digest(output.directory)
    _approve(output, monkeypatch)
    with pytest.raises((RuntimeError, ValueError)):
        publisher.publish_existing(**output.arguments, activate=True)
    assert output.transport.upload_count == 0


def test_confirmation_uses_verified_snapshot_if_builder_output_changes(output, monkeypatch):
    original = (output.directory / output.artifact.filename).read_bytes()
    _approve(
        output, monkeypatch, callback=lambda: (output.directory / output.artifact.filename).write_bytes(b"later build")
    )
    publisher.publish_existing(**output.arguments, activate=True)
    assert output.transport.files[f"/catalog/releases/2/{output.artifact.filename}"] == original


def test_publication_uses_saved_tag_when_head_is_newer_and_dirty(output, monkeypatch):
    (output.repository / "newer.txt").write_text("newer work", encoding="utf-8")
    _git(output.repository, "add", ".")
    _git(output.repository, "commit", "-m", "later work")
    (output.repository / "dirty.txt").write_text("work in progress", encoding="utf-8")
    _approve(output, monkeypatch)
    assert publisher.publish_existing(**output.arguments, activate=True) == 2


def test_reused_remote_sequence_does_not_change_pointer(output, monkeypatch):
    output.transport.directories.add("/catalog/releases/2")
    before = dict(output.transport.files)
    _approve(output, monkeypatch)
    with pytest.raises(PublishError, match="already exists"):
        publisher.publish_existing(**output.arguments, activate=True)
    assert output.transport.files == before
    assert output.transport.upload_count == 0


def test_activation_drop_is_reconciled_and_publicly_smoked(output, monkeypatch):
    output.transport.activation_mode = "interrupt-after"
    _approve(output, monkeypatch)
    assert publisher.publish_existing(**output.arguments, activate=True) == 2
    assert len(output.smokes) == 1


def test_public_smoke_failure_reports_active_state_without_rewriting(output, monkeypatch):
    def fail(**_kwargs):
        raise ReleaseSmokeError("public API has stale bytes")

    monkeypatch.setattr(publisher, "smoke_release", fail)
    _approve(output, monkeypatch)
    with pytest.raises(PublishError, match="is active, but public smoke failed"):
        publisher.publish_existing(**output.arguments, activate=True)
    assert json.loads(output.transport.files["/catalog/current-release.json"])["release_sequence"] == 2


def test_cli_loads_publication_only_config_without_touching_build_paths(tmp_path, monkeypatch):
    config = tmp_path / "publish.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
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
    calls = []
    monkeypatch.setattr(release, "publish_existing", lambda **kwargs: calls.append(kwargs))
    assert (
        release.main(
            [
                "--config",
                str(config),
                "publish-existing",
                "--kind",
                "client",
                "--platform",
                "macos-x86_64",
                "--tag",
                "client-v1.4.0",
                "--release-dir",
                str(tmp_path),
                "--inventory-sha256",
                "a" * 64,
            ]
        )
        == 0
    )
    assert calls[0]["remote_root"] == "/clients/macos-x86_64"
    assert calls[0]["activate"] is False
