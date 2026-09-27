"""Prepare or adopt both desktop installers, then review/promote the same bytes."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from scripts.client_candidate import BUILD_RECORD, TARGETS, verify_candidate
from scripts.client_release import sign_release, verify_release
from scripts.github_candidate import download_run
from scripts.immutable_publish import (
    PublishError,
    SshTransport,
    _load_release,
    _pointer_sequence,
    _verify_remote,
    publish_release,
)
from scripts.publish_existing import DEFAULT_TRUST_STORE, _snapshot, _verify_output
from scripts.release import load_config
from scripts.release_inventory import create_inventory, inventory_digest
from scripts.release_smoke import smoke_release
from scripts.release_source import REPOSITORY_ROOT, _git, resolve_release_tag

RECORD = "desktop-release.json"


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Release metadata must be a bounded regular file")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Release metadata must be an object")
    return value


def save(path: Path, value: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".desktop-state-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def tag_source(tag: str, repository: Path) -> str:
    if not re.fullmatch(r"client-v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Use an existing client-vX.Y.Z tag")
    return resolve_release_tag(expected_tag=tag, repository=repository).source_commit


def verify_pair(source_root: Path, evidence: dict, destination: Path, *, repository: Path, trust_store: Path) -> dict:
    if evidence.get("schema_version") != 1 or set(evidence.get("targets", {})) != set(TARGETS):
        raise ValueError("A release must contain exactly Windows x64 and Intel macOS")
    tag = evidence["source_tag"]
    commit = tag_source(tag, repository)
    if evidence.get("source_commit") != commit:
        raise ValueError("Release source differs from the selected tag")
    targets = {}
    for target in TARGETS:
        folder = destination / target
        folder.mkdir()
        digest = evidence["targets"][target]["inventory_sha256"]
        inventory = _snapshot(source_root / target, folder, kind="client", inventory_sha256=digest)
        _, _, sequence = _verify_output(
            folder, inventory, kind="client", tag=tag, target=target, trust_store=trust_store, repository=repository
        )
        targets[target] = {"inventory_sha256": digest, "release_sequence": sequence}
    return {
        "schema_version": 1,
        "source_tag": tag,
        "source_commit": commit,
        "version": tag.removeprefix("client-v"),
        "targets": targets,
        "publication": {},
        "prepared_at": datetime.now(timezone.utc).isoformat(),
    }


def adopt(
    source_root: Path,
    evidence_path: Path,
    output: Path,
    *,
    repository: Path = REPOSITORY_ROOT,
    trust_store: Path = DEFAULT_TRUST_STORE,
) -> Path:
    """Copy only anchored, signed artifacts; never rewrite or re-sign accepted output."""
    evidence = read_json(evidence_path)
    if output.exists():
        raise ValueError("Release destination already exists; use status/publish for the preserved release")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".desktop-adopt-", dir=output.parent) as temporary:
        staged = Path(temporary) / "release"
        staged.mkdir()
        record = verify_pair(source_root, evidence, staged, repository=repository, trust_store=trust_store)
        record["origin"] = {"kind": "adopted-signed-output"}
        save(staged / RECORD, record)
        staged.rename(output)
    return output / RECORD


def prepare(
    run_id: int,
    tag: str,
    output: Path,
    signing_key: Path,
    *,
    repository: Path = REPOSITORY_ROOT,
    trust_store: Path = DEFAULT_TRUST_STORE,
) -> Path:
    commit = tag_source(tag, repository)
    if output.exists():
        raise ValueError("Release destination already exists; use status/publish without rebuilding or re-signing")
    python_version = _git(repository, "show", f"{commit}:client/.python-version")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Keep a failed signing/download attempt for diagnosis rather than signing a
    # partially overwritten release on retry. Successful output is moved once.
    staged = Path(tempfile.mkdtemp(prefix=".desktop-prepare-", dir=output.parent))
    origin = download_run(run_id, staged)
    candidates = {}
    for target in TARGETS:
        candidate = verify_candidate(staged / target, source_commit=commit, source_tag=tag)
        if candidate["target_platform"] != target or candidate["tools"]["python"] != python_version:
            raise ValueError("CI candidate target/Python differs from the selected source")
        candidates[target] = candidate
    print(f"Verified both CI installers for {tag} ({commit[:12]}), run {run_id}.")
    passphrase = getpass.getpass("Release signing-key passphrase (both installers): ").encode("utf-8")
    evidence = {"schema_version": 1, "source_tag": tag, "source_commit": commit, "targets": {}}
    for target, candidate in candidates.items():
        directory = staged / target
        sign_release(
            directory / candidate["installer"]["filename"],
            target,
            candidate["version"],
            signing_key,
            trust_store,
            passphrase,
        )
        verify_release(directory, trust_store)
        create_inventory(
            release_dir=directory,
            source_commit=commit,
            source_tag=tag,
            release_kind="client",
            target_platform=target,
            version=candidate["version"],
            packager="none",
            build_record=directory / BUILD_RECORD,
        )
        evidence["targets"][target] = {"inventory_sha256": inventory_digest(directory)}
    adopted = staged / "complete"
    adopted.mkdir()
    record = verify_pair(staged, evidence, adopted, repository=repository, trust_store=trust_store)
    record["origin"] = {"kind": "github-actions", **origin}
    for target in TARGETS:
        shutil.copyfile(staged / target / BUILD_RECORD, adopted / target / BUILD_RECORD)
    save(adopted / RECORD, record)
    adopted.rename(output)
    print(f"Prepared {output / RECORD}. Both original build records remain in {staged}.")
    return output / RECORD


def publication_config(settings: dict, environment: str):
    if environment not in {"staging", "production"}:
        raise ValueError("Select staging or production")
    payload = settings.get(environment)
    if not isinstance(payload, dict):
        raise ValueError(f"Configure the {environment} destination once in desktop-release-config.json")
    with tempfile.TemporaryDirectory(prefix="desktop-config-") as temporary:
        path = Path(temporary) / "publish.json"
        path.write_text(json.dumps({"schema_version": 1, **payload}), encoding="utf-8")
        config = load_config(path, publication_only=True)
    # A mistaken staging target must not address the configured production channel.
    other = settings.get("production" if environment == "staging" else "staging")
    if isinstance(other, dict):
        remote = payload.get("remote", {})
        other_remote = other.get("remote", {})
        if payload.get("public_api_base_url") == other.get("public_api_base_url") or (
            remote.get("host"),
            remote.get("clients_dir"),
        ) == (other_remote.get("host"), other_remote.get("clients_dir")):
            raise ValueError("Staging and production must use separate API URLs and artifact roots")
    return config


def publish(
    record_path: Path,
    settings: dict,
    environment: str,
    *,
    activate: bool = False,
    repository: Path = REPOSITORY_ROOT,
    trust_store: Path = DEFAULT_TRUST_STORE,
    transport=None,
) -> None:
    record = read_json(record_path)
    config = publication_config(settings, environment)
    remote = f"{config.remote.user}@{config.remote.host}"
    destination = {"remote": remote, "clients_dir": config.remote.clients_dir, "api": config.public_api_base_url}
    previous = record.get("publication", {}).get(environment, {})
    if previous and previous.get("destination") != destination:
        raise ValueError("This release already records a different destination for that environment")
    if activate and environment == "production":
        accepted = record.get("publication", {}).get("staging", {}).get("targets", {})
        if any(accepted.get(target) != "verified" for target in TARGETS):
            raise ValueError("Verify both targets on staging before production promotion")
    with tempfile.TemporaryDirectory(prefix="desktop-publish-") as temporary:
        root = Path(temporary)
        verified = verify_pair(record_path.parent, record, root, repository=repository, trust_store=trust_store)
        print(
            f"{verified['source_tag']} ({verified['source_commit'][:12]}) -> {environment}: {remote}:{config.remote.clients_dir}"
        )
        for target in TARGETS:
            manifest = verify_release(root / target, trust_store)
            artifact = manifest.artifacts[0]
            print(f"  {target}: {artifact.filename}, {artifact.size} bytes, SHA-256 {artifact.sha256}")
        if not activate:
            print("Review passed. No server connection made. Use --activate after native acceptance.")
            return
        phrase = f"publish {verified['version']} {environment}"
        if (
            input(f"Native installer checks must be accepted. Type '{phrase}' to publish both reviewed targets: ")
            != phrase
        ):
            raise PublishError("Publication canceled")
        transport = transport or SshTransport(remote)
        progress = record.setdefault("publication", {}).setdefault(
            environment, {"destination": destination, "targets": {}}
        )
        for target in TARGETS:
            folder = root / target
            remote_root = f"{config.remote.clients_dir.rstrip('/')}/{target}"
            sequence, files = _load_release(
                folder, "client-manifest.json", "client-manifest.sig", "release-inventory.json"
            )
            try:
                current = _pointer_sequence(transport.read(f"{remote_root}/current-release.json", 4096))
                if current == sequence:
                    # Retry after interruption/smoke failure: prove this exact
                    # release is active before skipping its upload/activation.
                    for artifact in files:
                        _verify_remote(transport, artifact, f"{remote_root}/releases/{sequence}/{artifact.filename}")
                else:
                    publish_release(
                        release_dir=folder,
                        manifest_name="client-manifest.json",
                        signature_name="client-manifest.sig",
                        inventory_name="release-inventory.json",
                        remote_root=remote_root,
                        transport=transport,
                        resume_inventory_sha256=verified["targets"][target]["inventory_sha256"],
                    )
                progress["targets"][target] = "active; smoke pending"
                save(record_path, record)
                smoke_release(
                    release_dir=folder, release_kind="client", api_base_url=config.public_api_base_url, platform=target
                )
                progress["targets"][target] = "verified"
                save(record_path, record)
                print(f"{target}: active bytes and public download verified.")
            except Exception:
                # Preserve prior successful targets and the last known state.
                # A retry always reconciles the authoritative pointer first.
                progress["targets"].setdefault(target, "unknown; reconcile on retry")
                save(record_path, record)
                raise
        print(f"Both targets verified on {environment}. Release record: {record_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("desktop-release-config.json"))
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare", help="download a successful CI run and sign both installers once")
    build.add_argument("--run", type=int, required=True)
    build.add_argument("--tag", required=True)
    existing = commands.add_parser("adopt", help="preserve and verify an existing signed pair without signing")
    existing.add_argument("--from-dir", type=Path, required=True)
    existing.add_argument("--evidence", type=Path, required=True)
    for name in ("status", "publish"):
        command = commands.add_parser(name)
        command.add_argument("version")
        if name == "publish":
            command.add_argument("--environment", choices=("staging", "production"), required=True)
            command.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    try:
        settings = read_json(args.config)
        if settings.get("schema_version") != 1:
            raise ValueError("Unsupported desktop release configuration")
        releases = Path(settings["releases_dir"]).expanduser().resolve()
        if args.command == "prepare":
            tag_source(args.tag, REPOSITORY_ROOT)
            path = prepare(
                args.run,
                args.tag,
                releases / args.tag.removeprefix("client-v"),
                Path(settings["signing_key"]).expanduser().resolve(),
            )
            print(f"Release ready for native checks: {path}")
        elif args.command == "adopt":
            evidence = read_json(args.evidence)
            tag_source(evidence["source_tag"], REPOSITORY_ROOT)
            path = adopt(args.from_dir, args.evidence, releases / evidence["source_tag"].removeprefix("client-v"))
            print(f"Accepted signed artifacts adopted unchanged: {path}")
        else:
            if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.version):
                raise ValueError("Version must be X.Y.Z")
            record = releases / args.version / RECORD
            if args.command == "status":
                value = read_json(record)
                with tempfile.TemporaryDirectory(prefix="desktop-status-") as temporary:
                    verify_pair(
                        record.parent,
                        value,
                        Path(temporary),
                        repository=REPOSITORY_ROOT,
                        trust_store=DEFAULT_TRUST_STORE,
                    )
                print(
                    json.dumps(
                        {
                            "tag": value["source_tag"],
                            "verified_targets": list(TARGETS),
                            "publication": value["publication"],
                        },
                        indent=2,
                    )
                )
            else:
                publish(record, settings, args.environment, activate=args.activate)
    except (OSError, ValueError, RuntimeError, EOFError) as error:
        print(f"Release stopped: {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
