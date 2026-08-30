#!/usr/bin/env python3
"""Build, gate, deploy, smoke, record, and roll back ParseTrail releases."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from public_smoke import SmokeConfig, SmokeFailure, run_public_smoke

SCHEMA_VERSION = 1
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DIGEST_REF_PATTERN = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_COMPOSE_FILE = Path("docker-compose.yml")
DEFAULT_BUILD_COMPOSE_FILE = Path("docker-compose.build.yml")
SERVICES = ("backend", "frontend", "website")
IMAGE_ENV = {
    "backend": "BACKEND_IMAGE_REF",
    "frontend": "FRONTEND_IMAGE_REF",
    "website": "WEBSITE_IMAGE_REF",
}
REPOSITORY_ENV = {
    "backend": "DOCKER_IMAGE_BACKEND",
    "frontend": "DOCKER_IMAGE_FRONTEND",
    "website": "DOCKER_IMAGE_WEBSITE",
}
DEPLOYMENT_ENVIRONMENTS = frozenset(("staging", "production"))
REQUIRED_TARGET_FIELDS = (
    "STACK_NAME",
    "POSTGRES_VOLUME_NAME",
    "SUBMISSION_KEYS_VOLUME_NAME",
    "CLIENTS_DIR",
    "PLUGINS_DIR",
    "STATEMENTS_DIR",
    "SECRET_KEY",
    "MASTER_KEY",
    "POSTGRES_PASSWORD",
    "FIRST_SUPERUSER_PASSWORD",
    "DOMAIN",
    "BACKEND_HOST",
    "FRONTEND_HOST",
    "TRAEFIK_ALLOWED_IP_RANGES",
)
STAGING_UNIQUE_FIELDS = (
    "STACK_NAME",
    "POSTGRES_VOLUME_NAME",
    "SUBMISSION_KEYS_VOLUME_NAME",
    "SECRET_KEY",
    "MASTER_KEY",
    "POSTGRES_PASSWORD",
    "FIRST_SUPERUSER_PASSWORD",
    "DOMAIN",
    "BACKEND_HOST",
    "FRONTEND_HOST",
)
STAGING_UNIQUE_PATH_FIELDS = ("CLIENTS_DIR", "PLUGINS_DIR", "STATEMENTS_DIR")


class ReleaseError(RuntimeError):
    """A release safety invariant was not met."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def console_text(value: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_root() -> Path:
    result = run(["git", "rev-parse", "--show-toplevel"])
    return Path(result.strip()).resolve()


def require_outside_repository(path: Path, repo_root: Path) -> Path:
    resolved_parent = path.expanduser().resolve().parent
    try:
        resolved_parent.relative_to(repo_root)
    except ValueError:
        return path.expanduser().resolve()
    raise ReleaseError(f"Release state and secrets must stay outside the repository: {path}")


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
    dry_run: bool = False,
) -> str:
    print("+", " ".join(command), flush=True)
    if dry_run:
        return ""
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if completed.stdout:
        print(console_text(completed.stdout), end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode:
        raise ReleaseError(f"Command failed with exit code {completed.returncode}: {command[0]}")
    return completed.stdout


def run_logged(command: list[str], log_path: Path, *, env: dict[str, str]) -> None:
    print("+", " ".join(command), flush=True)
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            env=env,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(console_text(line))
            log.write(line)
        return_code = process.wait()
    if return_code:
        raise ReleaseError(f"Migration failed with exit code {return_code}")


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReleaseError(f"Cannot read deployment environment: {path}") from exc
    for number, original in enumerate(lines, start=1):
        line = original.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ReleaseError(f"Invalid dotenv line {number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ReleaseError(f"Invalid dotenv key on line {number} in {path}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _required_target_values(values: dict[str, str], *, label: str) -> None:
    environment = values.get("ENVIRONMENT", "").strip()
    if environment not in DEPLOYMENT_ENVIRONMENTS:
        raise ReleaseError(f"{label} ENVIRONMENT must be staging or production")
    missing = [name for name in REQUIRED_TARGET_FIELDS if not values.get(name, "").strip()]
    if missing:
        raise ReleaseError(f"{label} environment is missing required deployment fields: {', '.join(missing)}")


def _resolved_config_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def validate_deployment_boundary(
    deploy_values: dict[str, str],
    *,
    state_dir: Path,
    production_values: dict[str, str] | None = None,
    production_state_dir: Path | None = None,
) -> None:
    """Fail closed when staging could address production-owned state."""
    _required_target_values(deploy_values, label="Deployment")
    if deploy_values["ENVIRONMENT"] == "production":
        return

    if production_values is None or production_state_dir is None:
        raise ReleaseError("Staging commands require --production-env and --production-state-dir for isolation checks")
    _required_target_values(production_values, label="Production reference")
    if production_values["ENVIRONMENT"] != "production":
        raise ReleaseError("--production-env must describe ENVIRONMENT=production")

    reused = [name for name in STAGING_UNIQUE_FIELDS if deploy_values[name].strip() == production_values[name].strip()]
    reused.extend(
        name
        for name in STAGING_UNIQUE_PATH_FIELDS
        if _resolved_config_path(deploy_values[name]) == _resolved_config_path(production_values[name])
    )
    if state_dir.resolve() == production_state_dir.expanduser().resolve():
        reused.append("release state directory")
    if reused:
        raise ReleaseError(f"Staging reuses production targets: {', '.join(reused)}")

    staging_smtp = deploy_values.get("SMTP_HOST", "").strip()
    production_smtp = production_values.get("SMTP_HOST", "").strip()
    if not staging_smtp:
        raise ReleaseError("Staging SMTP_HOST must name a LAN-only mail capture service")
    if staging_smtp == production_smtp:
        raise ReleaseError("Staging SMTP_HOST must not reuse the production SMTP target")

    source_ranges = deploy_values["TRAEFIK_ALLOWED_IP_RANGES"].split(",")
    tailscale_range = ipaddress.ip_network("100.64.0.0/10")
    for source_range in source_ranges:
        try:
            network = ipaddress.ip_network(source_range.strip(), strict=False)
        except ValueError as exc:
            raise ReleaseError("Staging TRAEFIK_ALLOWED_IP_RANGES contains an invalid network") from exc
        is_tailscale = network.version == 4 and network.subnet_of(tailscale_range)
        if not (network.is_private or network.is_loopback or network.is_link_local or is_tailscale):
            raise ReleaseError("Staging TRAEFIK_ALLOWED_IP_RANGES must contain only LAN/VPN networks")


def deployment_context(
    args: argparse.Namespace,
    *,
    state_dir: Path,
) -> tuple[dict[str, str], dict[str, str] | None]:
    deploy_values = read_dotenv(args.deploy_env)
    production_env_path = getattr(args, "production_env", None)
    production_state_dir = getattr(args, "production_state_dir", None)
    production_values = read_dotenv(production_env_path) if production_env_path is not None else None
    validate_deployment_boundary(
        deploy_values,
        state_dir=state_dir,
        production_values=production_values,
        production_state_dir=production_state_dir,
    )
    return deploy_values, production_values


def validate_staging_artifacts(
    deploy_values: dict[str, str],
    production_values: dict[str, str] | None,
) -> None:
    if deploy_values["ENVIRONMENT"] != "staging":
        return
    assert production_values is not None
    staging_inventory = artifact_inventory(deploy_values)
    production_inventory = artifact_inventory(production_values)
    if production_inventory["plugins"] is None or not production_inventory["clients"]:
        raise ReleaseError("Production signed artifact inventory is incomplete")
    if staging_inventory != production_inventory:
        raise ReleaseError("Staging signed artifact inventory does not match production")


def validate_staging_smoke_credentials(
    deploy_values: dict[str, str],
    staging_config: SmokeConfig,
    production_config_path: Path | None,
) -> None:
    if deploy_values["ENVIRONMENT"] != "staging":
        return
    if production_config_path is None:
        raise ReleaseError("Staging smoke requires --production-smoke-config for credential isolation")
    production_config = SmokeConfig.from_file(production_config_path)
    if staging_config.username == production_config.username:
        raise ReleaseError("Staging smoke username must differ from production")
    if staging_config.password == production_config.password:
        raise ReleaseError("Staging smoke password must differ from production")
    staging_urls = {
        staging_config.api_base_url.rstrip("/"),
        staging_config.dashboard_url.rstrip("/"),
        staging_config.website_url.rstrip("/"),
    }
    production_urls = {
        production_config.api_base_url.rstrip("/"),
        production_config.dashboard_url.rstrip("/"),
        production_config.website_url.rstrip("/"),
    }
    if staging_urls & production_urls:
        raise ReleaseError("Staging smoke URLs must not address production")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Cannot read JSON document: {path}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"Expected a JSON object: {path}")
    return value


def atomic_json(path: Path, value: dict[str, Any], *, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if exclusive and path.exists():
        raise ReleaseError(f"Refusing to overwrite append-only record: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if exclusive and path.exists():
            raise ReleaseError(f"Refusing to overwrite append-only record: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_release(document: dict[str, Any], *, deployable: bool = True) -> dict[str, Any]:
    expected = {"schema_version", "created_at", "source_commit", "deployable", "images"}
    if set(document) != expected or document.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseError("Release descriptor has an unsupported schema")
    if not COMMIT_PATTERN.fullmatch(str(document.get("source_commit", ""))):
        raise ReleaseError("Release descriptor has an invalid source commit")
    images = document.get("images")
    if not isinstance(images, dict) or set(images) != set(SERVICES):
        raise ReleaseError("Release descriptor must name backend, frontend, and website images")
    if deployable and document.get("deployable") is not True:
        raise ReleaseError("Release descriptor was not produced by a pushed build")
    if deployable:
        for service, reference in images.items():
            if not isinstance(reference, str) or not DIGEST_REF_PATTERN.fullmatch(reference):
                raise ReleaseError(f"{service} image is not an immutable digest reference")
    return document


def current_commit(*, require_clean: bool) -> str:
    commit = run(["git", "rev-parse", "HEAD"]).strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseError("Git did not return a full source commit")
    if require_clean and run(["git", "status", "--porcelain"]).strip():
        raise ReleaseError("Release commands require a clean worktree")
    return commit


def release_environment(release: dict[str, Any]) -> dict[str, str]:
    return {IMAGE_ENV[service]: str(release["images"][service]) for service in SERVICES}


def compose_command(args: argparse.Namespace, deploy_values: dict[str, str]) -> list[str]:
    stack_name = deploy_values.get("STACK_NAME", "").strip()
    if not stack_name:
        raise ReleaseError("Deployment environment must define STACK_NAME")
    return [
        "docker",
        "compose",
        "--env-file",
        str(args.deploy_env.resolve()),
        "--project-name",
        stack_name,
        "--file",
        str(args.compose_file.resolve()),
    ]


def compose_environment(release: dict[str, Any]) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(release_environment(release))
    return environment


def schema_revision(
    args: argparse.Namespace,
    deploy_values: dict[str, str],
    release: dict[str, Any],
) -> str:
    output = run(
        compose_command(args, deploy_values)
        + [
            "exec",
            "--no-TTY",
            "db",
            "sh",
            "-c",
            'exec psql --no-psqlrc -At --username "$POSTGRES_USER" '
            '--dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 '
            "--command 'SELECT version_num FROM alembic_version;'",
        ],
        env=compose_environment(release),
    )
    revision = output.strip().splitlines()[-1] if output.strip() else ""
    if not re.fullmatch(r"[0-9a-f]+", revision):
        raise ReleaseError("Could not read a valid Alembic revision from the running database")
    return revision


def resolve_repo_digest(image: str) -> str:
    raw = run(["docker", "image", "inspect", image, "--format", "{{json .RepoDigests}}"])
    try:
        digests = json.loads(raw.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"Cannot resolve pushed digest for {image}") from exc
    repository = image.rsplit(":", 1)[0]
    matches = [value for value in digests if value.startswith(f"{repository}@sha256:")]
    if len(matches) != 1 or not DIGEST_REF_PATTERN.fullmatch(matches[0]):
        raise ReleaseError(f"Expected one pushed repository digest for {image}")
    return matches[0]


def artifact_inventory(deploy_values: dict[str, str]) -> dict[str, Any]:
    inventory: dict[str, Any] = {"plugins": None, "clients": {}}

    def manifest_record(root: Path, pointer_required: bool) -> dict[str, Any] | None:
        pointer_path = root / "current-release.json"
        release_root = root
        sequence: int | None = None
        if pointer_path.is_file():
            pointer = load_json(pointer_path)
            sequence = pointer.get("release_sequence")
            if not isinstance(sequence, int) or sequence <= 0:
                raise ReleaseError(f"Invalid artifact release pointer: {pointer_path}")
            release_root = root / "releases" / str(sequence)
        elif pointer_required:
            return None
        manifest_candidates = list(release_root.glob("*-manifest.json"))
        signature_candidates = list(release_root.glob("*-manifest.sig"))
        if len(manifest_candidates) != 1 or len(signature_candidates) != 1:
            return None
        manifest_path = manifest_candidates[0]
        signature_path = signature_candidates[0]
        manifest = load_json(manifest_path)
        artifacts = manifest.get("artifacts", [])
        summarized = []
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict):
                    summarized.append(
                        {
                            key: artifact.get(key)
                            for key in ("filename", "version", "platform", "size", "sha256")
                            if key in artifact
                        }
                    )
        return {
            "release_sequence": sequence or manifest.get("release_sequence"),
            "manifest_sha256": sha256_file(manifest_path),
            "signature_sha256": sha256_file(signature_path),
            "artifacts": summarized,
        }

    plugins_dir = deploy_values.get("PLUGINS_DIR")
    if plugins_dir:
        inventory["plugins"] = manifest_record(Path(plugins_dir), pointer_required=False)
    clients_dir = deploy_values.get("CLIENTS_DIR")
    if clients_dir:
        for platform in ("macos", "win64"):
            record = manifest_record(Path(clients_dir) / platform, pointer_required=True)
            if record is not None:
                inventory["clients"][platform] = record
    return inventory


def validate_backup_evidence(path: Path, max_age_hours: float) -> dict[str, Any]:
    evidence = load_json(path)
    expected = {
        "schema_version",
        "verified_at",
        "database_dump",
        "database_dump_sha256",
        "database_restore_id",
        "files_restore_id",
        "submission_keys_restore_id",
    }
    if set(evidence) != expected or evidence.get("schema_version") != SCHEMA_VERSION:
        raise ReleaseError("Backup evidence has an unsupported schema")
    try:
        verified_at = datetime.fromisoformat(str(evidence["verified_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReleaseError("Backup evidence has an invalid verified_at value") from exc
    age_hours = (utc_now() - verified_at.astimezone(UTC)).total_seconds() / 3600
    if age_hours < 0 or age_hours > max_age_hours:
        raise ReleaseError(f"Backup evidence is {age_hours:.1f} hours old")
    dump_path = Path(str(evidence["database_dump"]))
    expected_digest = str(evidence["database_dump_sha256"])
    if not dump_path.is_file() or not SHA256_PATTERN.fullmatch(expected_digest):
        raise ReleaseError("Backup evidence does not reference a readable database dump")
    if sha256_file(dump_path) != expected_digest:
        raise ReleaseError("Database backup digest no longer matches its evidence")
    for field in ("database_restore_id", "files_restore_id", "submission_keys_restore_id"):
        if not isinstance(evidence[field], str) or not evidence[field].strip():
            raise ReleaseError(f"Backup evidence is missing {field}")
    return evidence


def state_directory(path: Path, repo_root: Path) -> Path:
    resolved = require_outside_repository(path / "placeholder", repo_root).parent
    resolved.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        resolved.chmod(0o700)
    return resolved


def deployment_id(commit: str) -> str:
    return f"{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{commit[:12]}"


def pending_path(state_dir: Path, identifier: str) -> Path:
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", identifier):
        raise ReleaseError("Invalid deployment identifier")
    return state_dir / "pending" / f"{identifier}.json"


def command_backup_evidence(args: argparse.Namespace) -> None:
    repo_root = repository_root()
    output = require_outside_repository(args.output, repo_root)
    dump = args.database_dump.expanduser().resolve()
    if not dump.is_file():
        raise ReleaseError(f"Database dump does not exist: {dump}")
    for value in (args.database_restore_id, args.files_restore_id, args.submission_keys_restore_id):
        if not value.strip():
            raise ReleaseError("Restore evidence identifiers must not be empty")
    atomic_json(
        output,
        {
            "schema_version": SCHEMA_VERSION,
            "verified_at": iso_now(),
            "database_dump": str(dump),
            "database_dump_sha256": sha256_file(dump),
            "database_restore_id": args.database_restore_id,
            "files_restore_id": args.files_restore_id,
            "submission_keys_restore_id": args.submission_keys_restore_id,
        },
        exclusive=True,
    )
    print(f"Wrote backup verification evidence: {output}")


def command_build(args: argparse.Namespace) -> None:
    repo_root = repository_root()
    commit = current_commit(require_clean=True)
    build_values = read_dotenv(args.build_env)
    repositories: dict[str, str] = {}
    for service, variable in REPOSITORY_ENV.items():
        repository = build_values.get(variable, "").strip()
        if not repository or "@" in repository or repository.endswith(":latest"):
            raise ReleaseError(f"{variable} must be an untagged registry repository")
        repositories[service] = repository
    tagged = {service: f"{repository}:{commit}" for service, repository in repositories.items()}
    build_release = {
        "schema_version": SCHEMA_VERSION,
        "created_at": iso_now(),
        "source_commit": commit,
        "deployable": False,
        "images": tagged,
    }
    environment = os.environ.copy()
    environment.update(build_values)
    environment.update({IMAGE_ENV[name]: reference for name, reference in tagged.items()})
    base = [
        "docker",
        "compose",
        "--env-file",
        str(args.build_env.resolve()),
        "--file",
        str(args.compose_file.resolve()),
    ]
    run(base + ["build", *SERVICES], env=environment, cwd=repo_root, dry_run=args.dry_run)
    if args.push:
        run(base + ["push", *SERVICES], env=environment, cwd=repo_root, dry_run=args.dry_run)
        if not args.dry_run:
            build_release["images"] = {service: resolve_repo_digest(tagged[service]) for service in SERVICES}
            build_release["deployable"] = True
    if args.dry_run:
        print(json.dumps(build_release, indent=2, sort_keys=True))
        return
    output = require_outside_repository(args.output, repo_root)
    atomic_json(output, build_release, exclusive=True)
    print(f"Wrote release descriptor: {output}")


def command_adopt(args: argparse.Namespace) -> None:
    repo_root = repository_root()
    state_dir = state_directory(args.state_dir, repo_root)
    deploy_values, production_values = deployment_context(args, state_dir=state_dir)
    validate_staging_artifacts(deploy_values, production_values)
    current_path = state_dir / "current-release.json"
    if current_path.exists():
        raise ReleaseError("A current immutable release has already been adopted")
    commit = args.source_commit
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseError("--source-commit must be a full 40-character Git commit")
    base = compose_command(args, deploy_values)
    images: dict[str, str] = {}
    for service in SERVICES:
        container_id = run(base + ["ps", "--quiet", service]).strip().splitlines()
        if len(container_id) != 1:
            raise ReleaseError(f"Expected one running {service} container")
        reference = (
            run(["docker", "inspect", container_id[0], "--format", "{{.Config.Image}}"]).strip().splitlines()[-1]
        )
        if not DIGEST_REF_PATTERN.fullmatch(reference):
            raise ReleaseError(f"Running {service} container is not pinned by digest")
        images[service] = reference
    adopted = validate_release(
        {
            "schema_version": SCHEMA_VERSION,
            "created_at": iso_now(),
            "source_commit": commit,
            "deployable": True,
            "images": images,
        }
    )
    revision = schema_revision(args, deploy_values, adopted)
    record = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": f"adopted-{utc_now().strftime('%Y%m%dT%H%M%SZ')}",
        "status": "adopted",
        "timestamp": iso_now(),
        "operator": getpass.getuser(),
        "host": socket.gethostname(),
        "release": adopted,
        "schema_revision": revision,
        "artifacts": artifact_inventory(deploy_values),
        "rollback_target": None,
    }
    atomic_json(state_dir / "records" / f"{record['deployment_id']}.json", record, exclusive=True)
    atomic_json(current_path, adopted)
    print("Adopted the running immutable release as the rollback baseline.")


def command_preflight(args: argparse.Namespace) -> None:
    repo_root = repository_root()
    release = validate_release(load_json(args.release))
    if current_commit(require_clean=True) != release["source_commit"]:
        raise ReleaseError("Checked-out commit does not match the release descriptor")
    state_dir = state_directory(args.state_dir, repo_root)
    deploy_values, production_values = deployment_context(args, state_dir=state_dir)
    validate_staging_artifacts(deploy_values, production_values)
    current_path = state_dir / "current-release.json"
    if not current_path.is_file():
        raise ReleaseError("Adopt the current immutable deployment before the first gated release")
    rollback_target = validate_release(load_json(current_path))
    evidence = validate_backup_evidence(args.backup_evidence, args.max_backup_age_hours)
    base = compose_command(args, deploy_values)
    environment = compose_environment(release)
    rendered_images = [
        line.strip() for line in run(base + ["config", "--images"], env=environment).splitlines() if line.strip()
    ]
    for reference in release["images"].values():
        if reference not in rendered_images:
            raise ReleaseError(f"Rendered Compose config does not contain release image {reference}")
    database_images = [
        image for image in rendered_images if image.split("@", 1)[0].rsplit("/", 1)[-1].split(":", 1)[0] == "postgres"
    ]
    if len(database_images) != 1 or not DIGEST_REF_PATTERN.fullmatch(database_images[0]):
        raise ReleaseError("Production PostgreSQL image must be pinned by digest")
    run(base + ["config", "--quiet"], env=environment)
    run(base + ["pull", *SERVICES], env=environment)
    identifier = deployment_id(str(release["source_commit"]))
    pending = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": identifier,
        "phase": "preflight",
        "created_at": iso_now(),
        "operator": getpass.getuser(),
        "host": socket.gethostname(),
        "migration_policy": "backward-compatible",
        "release": release,
        "rollback_target": rollback_target,
        "schema_before": schema_revision(args, deploy_values, rollback_target),
        "compose_images": rendered_images,
        "backup_evidence": evidence,
        "artifacts_before": artifact_inventory(deploy_values),
    }
    atomic_json(pending_path(state_dir, identifier), pending, exclusive=True)
    print(f"Preflight passed. Deployment ID: {identifier}")


def load_pending(args: argparse.Namespace) -> tuple[Path, dict[str, Any], dict[str, str], Path]:
    repo_root = repository_root()
    state_dir = state_directory(args.state_dir, repo_root)
    path = pending_path(state_dir, args.deployment_id)
    pending = load_json(path)
    if pending.get("deployment_id") != args.deployment_id:
        raise ReleaseError("Pending deployment identifier mismatch")
    deploy_values, _production_values = deployment_context(args, state_dir=state_dir)
    return path, pending, deploy_values, state_dir


def command_migrate(args: argparse.Namespace) -> None:
    path, pending, deploy_values, state_dir = load_pending(args)
    if pending.get("phase") != "preflight":
        raise ReleaseError("Migration requires a completed preflight phase")
    release = validate_release(pending["release"])
    if current_commit(require_clean=True) != release["source_commit"]:
        raise ReleaseError("Checked-out commit does not match the pending release")
    base = compose_command(args, deploy_values)
    environment = compose_environment(release)
    run(
        base + ["up", "--detach", "--no-build", "--wait", "--wait-timeout", str(args.timeout), "db"],
        env=environment,
    )
    log_path = state_dir / "migration-logs" / f"{args.deployment_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_logged(
            base + ["run", "--rm", "--no-deps", "prestart", "bash", "scripts/migrate.sh"],
            log_path,
            env=environment,
        )
    except Exception:
        pending["phase"] = "migration-failed"
        pending["migration_finished_at"] = iso_now()
        pending["migration_log_sha256"] = sha256_file(log_path)
        atomic_json(path, pending)
        raise
    pending["phase"] = "migrated"
    pending["migration_finished_at"] = iso_now()
    pending["migration_log_sha256"] = sha256_file(log_path)
    pending["schema_after_migration"] = schema_revision(args, deploy_values, release)
    atomic_json(path, pending)
    print("Migration completed and was recorded; application services were not replaced.")


def activate(
    args: argparse.Namespace,
    deploy_values: dict[str, str],
    release: dict[str, Any],
) -> None:
    run(
        compose_command(args, deploy_values)
        + [
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(args.timeout),
            "prestart",
            *SERVICES,
        ],
        env=compose_environment(release),
    )


def final_record_path(state_dir: Path, identifier: str) -> Path:
    return state_dir / "records" / f"{identifier}.json"


def command_deploy(args: argparse.Namespace) -> None:
    path, pending, deploy_values, state_dir = load_pending(args)
    if pending.get("phase") != "migrated":
        raise ReleaseError("Deployment requires a successful recorded migration")
    release = validate_release(pending["release"])
    rollback_target = validate_release(pending["rollback_target"])
    smoke_config = SmokeConfig.from_file(args.smoke_config)
    validate_staging_smoke_credentials(
        deploy_values,
        smoke_config,
        getattr(args, "production_smoke_config", None),
    )
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": args.deployment_id,
        "timestamp": iso_now(),
        "operator": getpass.getuser(),
        "host": socket.gethostname(),
        "source_commit": release["source_commit"],
        "release": release,
        "rollback_target": rollback_target,
        "schema_before": pending["schema_before"],
        "schema_after_migration": pending["schema_after_migration"],
        "migration_policy": pending["migration_policy"],
        "migration_log_sha256": pending["migration_log_sha256"],
        "backup_evidence": pending["backup_evidence"],
    }
    try:
        activate(args, deploy_values, release)
        record["smoke"] = run_public_smoke(smoke_config)
        record["schema_after"] = schema_revision(args, deploy_values, release)
        record["artifacts"] = artifact_inventory(deploy_values)
        record["status"] = "succeeded"
    except Exception as deployment_error:
        record["status"] = "failed-rolling-back"
        record["failure"] = type(deployment_error).__name__
        try:
            activate(args, deploy_values, rollback_target)
            record["rollback_smoke"] = run_public_smoke(smoke_config)
            record["rollback_status"] = "succeeded"
            atomic_json(state_dir / "current-release.json", rollback_target)
        except Exception as rollback_error:
            record["rollback_status"] = "failed"
            record["rollback_failure"] = type(rollback_error).__name__
            atomic_json(final_record_path(state_dir, args.deployment_id), record, exclusive=True)
            pending["phase"] = "rollback-failed"
            atomic_json(path, pending)
            raise ReleaseError(
                "Deployment and automatic rollback both failed; keep traffic in maintenance mode"
            ) from rollback_error
        atomic_json(final_record_path(state_dir, args.deployment_id), record, exclusive=True)
        pending["phase"] = "rolled-back"
        atomic_json(path, pending)
        raise ReleaseError("Deployment smoke failed; previous immutable images were reactivated") from deployment_error

    atomic_json(final_record_path(state_dir, args.deployment_id), record, exclusive=True)
    atomic_json(state_dir / "current-release.json", release)
    pending["phase"] = "complete"
    pending["completed_at"] = iso_now()
    atomic_json(path, pending)
    print(f"Deployment passed all public smoke checks. Record: {final_record_path(state_dir, args.deployment_id)}")


def command_rollback(args: argparse.Namespace) -> None:
    repo_root = repository_root()
    state_dir = state_directory(args.state_dir, repo_root)
    source_record = load_json(final_record_path(state_dir, args.deployment_id))
    if source_record.get("status") != "succeeded":
        raise ReleaseError("Only a successful deployment record can provide a rollback target")
    target = validate_release(source_record["rollback_target"])
    current = validate_release(load_json(state_dir / "current-release.json"))
    deploy_values, production_values = deployment_context(args, state_dir=state_dir)
    validate_staging_artifacts(deploy_values, production_values)
    smoke_config = SmokeConfig.from_file(args.smoke_config)
    validate_staging_smoke_credentials(
        deploy_values,
        smoke_config,
        getattr(args, "production_smoke_config", None),
    )
    identifier = f"rollback-{utc_now().strftime('%Y%m%dT%H%M%SZ')}-{target['source_commit'][:12]}"
    activate(args, deploy_values, target)
    smoke = run_public_smoke(smoke_config)
    record = {
        "schema_version": SCHEMA_VERSION,
        "deployment_id": identifier,
        "timestamp": iso_now(),
        "operator": getpass.getuser(),
        "host": socket.gethostname(),
        "status": "rollback-succeeded",
        "release": target,
        "rollback_target": current,
        "source_deployment_id": args.deployment_id,
        "schema_revision": schema_revision(args, deploy_values, target),
        "artifacts": artifact_inventory(deploy_values),
        "smoke": smoke,
    }
    atomic_json(final_record_path(state_dir, identifier), record, exclusive=True)
    atomic_json(state_dir / "current-release.json", target)
    print(f"Rollback passed all public smoke checks. Record: {final_record_path(state_dir, identifier)}")


def add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deploy-env", type=Path, required=True)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument(
        "--production-env",
        type=Path,
        help="Required for staging; production environment used only for isolation comparison",
    )


def add_state_arguments(parser: argparse.ArgumentParser) -> None:
    add_runtime_arguments(parser)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument(
        "--production-state-dir",
        type=Path,
        help="Required for staging; production release-state path used only for isolation comparison",
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup-evidence", help="Record completed restore-drill evidence")
    backup.add_argument("--database-dump", type=Path, required=True)
    backup.add_argument("--database-restore-id", required=True)
    backup.add_argument("--files-restore-id", required=True)
    backup.add_argument("--submission-keys-restore-id", required=True)
    backup.add_argument("--output", type=Path, required=True)
    backup.set_defaults(handler=command_backup_evidence)

    build = commands.add_parser("build", help="Build commit-tagged images on a clean builder")
    build.add_argument("--build-env", type=Path, required=True)
    build.add_argument("--compose-file", type=Path, default=DEFAULT_BUILD_COMPOSE_FILE)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--push", action="store_true")
    build.add_argument("--dry-run", action="store_true")
    build.set_defaults(handler=command_build)

    adopt = commands.add_parser("adopt", help="Adopt running digest-pinned images as baseline")
    add_state_arguments(adopt)
    adopt.add_argument("--source-commit", required=True)
    adopt.set_defaults(handler=command_adopt)

    preflight = commands.add_parser("preflight", help="Validate release, backup, config, and rollback")
    add_state_arguments(preflight)
    preflight.add_argument("--release", type=Path, required=True)
    preflight.add_argument("--backup-evidence", type=Path, required=True)
    preflight.add_argument("--max-backup-age-hours", type=float, default=48)
    preflight.set_defaults(handler=command_preflight)

    migrate = commands.add_parser("migrate", help="Run and capture the explicit Alembic phase")
    add_state_arguments(migrate)
    migrate.add_argument("deployment_id")
    migrate.add_argument("--timeout", type=int, default=180)
    migrate.set_defaults(handler=command_migrate)

    deploy = commands.add_parser("deploy", help="Replace services, smoke, and automatically roll back")
    add_state_arguments(deploy)
    deploy.add_argument("deployment_id")
    deploy.add_argument("--smoke-config", type=Path, required=True)
    deploy.add_argument(
        "--production-smoke-config",
        type=Path,
        help="Required for staging; production smoke config used only for isolation comparison",
    )
    deploy.add_argument("--timeout", type=int, default=180)
    deploy.set_defaults(handler=command_deploy)

    rollback = commands.add_parser("rollback", help="Reactivate a recorded rollback target")
    add_state_arguments(rollback)
    rollback.add_argument("deployment_id")
    rollback.add_argument("--smoke-config", type=Path, required=True)
    rollback.add_argument(
        "--production-smoke-config",
        type=Path,
        help="Required for staging; production smoke config used only for isolation comparison",
    )
    rollback.add_argument("--timeout", type=int, default=180)
    rollback.set_defaults(handler=command_rollback)
    return root


def main() -> int:
    args = parser().parse_args()
    if hasattr(args, "timeout") and not 30 <= args.timeout <= 900:
        raise ReleaseError("--timeout must be between 30 and 900 seconds")
    if hasattr(args, "max_backup_age_hours") and not 1 <= args.max_backup_age_hours <= 168:
        raise ReleaseError("--max-backup-age-hours must be between 1 and 168")
    args.handler(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReleaseError, SmokeFailure) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
