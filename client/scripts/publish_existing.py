"""Review and publish preserved release output using public keys only."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

from parsetrail.core.client_manifest import verify_client_manifest, verify_installer_file
from parsetrail.core.client_targets import INSTALLER_SUFFIXES
from parsetrail.core.plugin_manifest import load_trusted_plugin_keys, verify_artifact_file, verify_manifest

from scripts.immutable_publish import (
    MAX_INVENTORY_BYTES,
    REMOTE_ROOT_PATTERN,
    SHA256_PATTERN,
    PublishError,
    RemoteTransport,
    SshTransport,
    _load_release,
    _safe_filename,
    publish_release,
)
from scripts.release_smoke import ReleaseSmokeError, smoke_release
from scripts.release_source import REPOSITORY_ROOT, _git, resolve_release_tag

INVENTORY_FILENAME = "release-inventory.json"
DEFAULT_TRUST_STORE = Path(__file__).resolve().parents[1] / "src/parsetrail/assets/plugin-release-keys.json"


def _read_local(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PublishError(f"Release file must be a regular file: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if not data or len(data) > limit:
        raise PublishError(f"Release file is empty or too large: {path.name}")
    return data


def _snapshot(release_dir: Path, snapshot: Path, *, kind: str, inventory_sha256: str) -> dict[str, object]:
    if not SHA256_PATTERN.fullmatch(inventory_sha256):
        raise PublishError("inventory-sha256 must be the recorded lowercase SHA-256 digest")
    inventory_bytes = _read_local(release_dir / INVENTORY_FILENAME, MAX_INVENTORY_BYTES)
    if hashlib.sha256(inventory_bytes).hexdigest() != inventory_sha256:
        raise PublishError("Release inventory differs from the reviewed SHA-256 digest")
    inventory = json.loads(inventory_bytes)
    if not isinstance(inventory, dict) or not isinstance(inventory.get("files"), list):
        raise PublishError("Release inventory is invalid")
    prefix = "plugin" if kind == "plugins" else "client"
    manifest_name = f"{prefix}-manifest.json"
    signature_name = manifest_name.removesuffix(".json") + ".sig"
    manifest_bytes = _read_local(release_dir / manifest_name, MAX_INVENTORY_BYTES)
    signature_bytes = _read_local(release_dir / signature_name, 64)
    (snapshot / INVENTORY_FILENAME).write_bytes(inventory_bytes)
    (snapshot / manifest_name).write_bytes(manifest_bytes)
    (snapshot / signature_name).write_bytes(signature_bytes)
    # Copy only recorded regular files. The private snapshot preserves the
    # verified bytes even if the builder output changes during confirmation.
    seen = set()
    for record in inventory["files"]:
        if not isinstance(record, dict):
            raise PublishError("Release inventory contains invalid file metadata")
        name = _safe_filename(record.get("filename"))
        if name in seen or name == INVENTORY_FILENAME:
            raise PublishError("Release inventory filenames must be unique")
        seen.add(name)
        if name in {manifest_name, signature_name}:
            continue
        if not name.endswith(".pyc" if kind == "plugins" else (".exe", ".dmg")):
            raise PublishError("Inventory contains an unexpected release filename")
        path = release_dir / name
        if path.is_symlink() or not path.is_file():
            raise PublishError(f"Release file must be a regular file: {name}")
        shutil.copyfile(path, snapshot / name)
    return inventory


def _verify_output(
    snapshot: Path,
    inventory: dict[str, object],
    *,
    kind: str,
    tag: str,
    target: str | None,
    trust_store: Path,
    repository: Path,
) -> tuple[str, str, int]:
    keys = load_trusted_plugin_keys(trust_store)
    prefix = "plugin" if kind == "plugins" else "client"
    manifest_name, signature_name = f"{prefix}-manifest.json", f"{prefix}-manifest.sig"
    manifest_bytes = (snapshot / manifest_name).read_bytes()
    signature_bytes = (snapshot / signature_name).read_bytes()
    if kind == "client":
        manifest = verify_client_manifest(manifest_bytes, signature_bytes, keys).manifest
        if target not in INSTALLER_SUFFIXES or len(manifest.artifacts) != 1:
            raise PublishError("Client publication requires one installer and an explicit supported target")
        artifact = manifest.artifacts[0]
        if (
            artifact.platform != target
            or inventory.get("target_platform") != target
            or inventory.get("architecture") != artifact.architecture
            or inventory.get("manifest_schema_version") != manifest.schema_version
            or inventory.get("version") != artifact.version
            or tag != f"client-v{artifact.version}"
        ):
            raise PublishError("Client target/version/tag disagrees with the signed manifest or inventory")
        verify_installer_file(snapshot / artifact.filename, artifact)
    else:
        if target is not None:
            raise PublishError("Plugin publication does not accept an installer target")
        manifest = verify_manifest(manifest_bytes, signature_bytes, keys).manifest
        if inventory.get("source_commit") != manifest.source_commit or manifest.source_commit is None:
            raise PublishError("Plugin inventory disagrees with the signed source commit")
        if inventory.get("version") is not None:
            raise PublishError("Plugin inventory must not specify an installer version")
        for artifact in manifest.artifacts:
            verify_artifact_file(snapshot / artifact.filename, artifact)

    source = resolve_release_tag(expected_tag=tag, repository=repository)
    if inventory.get("source_commit") != source.source_commit or inventory.get("source_tag") != source.source_tag:
        raise PublishError("Release inventory does not match the source tag's commit")
    python_version = _git(repository, "show", f"{source.source_commit}:client/.python-version")
    tools = inventory.get("tools")
    if (
        inventory.get("release_kind") != kind
        or type(inventory.get("schema_version")) is not int
        or inventory["schema_version"] != 1
        or not isinstance(tools, dict)
        or tools.get("python") != python_version
        or not re.fullmatch(r"3\.\d+\.\d+", python_version)
    ):
        raise PublishError("Release inventory kind/schema/Python disagrees with the tagged build")
    if kind == "plugins":
        expected_python_tag = "cp" + "".join(python_version.split(".")[:2])
        if inventory.get("target_platform") != f"python-{python_version}" or any(
            artifact.python_tag != expected_python_tag for artifact in manifest.artifacts
        ):
            raise PublishError("Plugin target disagrees with the tagged Python version")
    sequence, _files = _load_release(snapshot, manifest_name, signature_name, INVENTORY_FILENAME)
    return manifest_name, signature_name, sequence


def publish_existing(
    *,
    release_dir: Path,
    kind: str,
    tag: str,
    target: str | None,
    inventory_sha256: str,
    remote_spec: str,
    remote_root: str,
    api_base_url: str,
    activate: bool = False,
    trust_store: Path = DEFAULT_TRUST_STORE,
    repository: Path = REPOSITORY_ROOT,
    transport: RemoteTransport | None = None,
) -> int | None:
    """Verify locally, show exact evidence, and optionally confirm activation."""
    if kind not in {"client", "plugins"}:
        raise PublishError("Release kind must be client or plugins")
    if not REMOTE_ROOT_PATTERN.fullmatch(remote_root) or ".." in remote_root.split("/") or remote_root == "/":
        raise PublishError("Remote root must be an absolute safe release directory")
    transport = transport if transport is not None else SshTransport(remote_spec)
    release_dir = release_dir.expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="parsetrail-publish-") as temporary:
        snapshot = Path(temporary)
        inventory = _snapshot(release_dir, snapshot, kind=kind, inventory_sha256=inventory_sha256)
        manifest_name, signature_name, sequence = _verify_output(
            snapshot, inventory, kind=kind, tag=tag, target=target, trust_store=trust_store, repository=repository
        )
        print(
            json.dumps(
                {
                    "release_kind": kind,
                    "release_sequence": sequence,
                    "target_platform": inventory["target_platform"],
                    "source_tag": tag,
                    "source_commit": inventory["source_commit"],
                    "inventory_sha256": inventory_sha256,
                    "destination": f"{remote_spec}:{remote_root}",
                    "public_api_base_url": api_base_url,
                    "files": inventory["files"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        if not activate:
            print("Review complete; no remote connection was made. Add --activate to confirm publication.")
            return None
        expected = f"publish {kind} {inventory['target_platform']} {sequence}"
        if input(f"Type {expected!r} to activate these exact bytes: ") != expected:
            raise PublishError("Publication was not approved")
        publish_release(
            release_dir=snapshot,
            manifest_name=manifest_name,
            signature_name=signature_name,
            inventory_name=INVENTORY_FILENAME,
            remote_root=remote_root,
            transport=transport,
        )
        try:
            smoke_release(release_dir=snapshot, release_kind=kind, api_base_url=api_base_url, platform=target)
        except (OSError, ValueError, ReleaseSmokeError) as exc:
            raise PublishError(
                f"Release {sequence} is active, but public smoke failed. Preserve it and investigate the API; "
                "do not rebuild or retry activation. See docs/artifact-rollback.md."
            ) from exc
        print(f"Release {sequence} activated; public manifest/signature and artifact listing/range verified.")
        return sequence
