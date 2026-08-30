#!/usr/bin/env python3
"""Prove staging can recover all persistent boundaries after an incompatible migration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from public_smoke import SmokeConfig, run_public_smoke
from release import (
    DIGEST_REF_PATTERN,
    ReleaseError,
    artifact_inventory,
    atomic_json,
    compose_command,
    compose_environment,
    current_commit,
    deployment_context,
    load_json,
    run,
    sha256_file,
    validate_release,
    validate_staging_artifacts,
    validate_staging_smoke_credentials,
)
from staging_restore_drill import (
    NAME_PATTERN,
    DrillError,
    create_database_target,
    docker_container_exists,
    docker_volume_exists,
    file_inventory,
    psql,
    restore_dump,
    table_counts,
    wait_for_database,
)

STAGING_ROOT = Path("/srv/parsetrail-staging").resolve()
RESTORE_DRILL_ROOT = (STAGING_ROOT / "restore-drill").resolve()
RECOVERY_ROOT = (STAGING_ROOT / "recovery-rehearsal").resolve()
MISSING_REVISION = "restore_drill_missing_revision"
EXPECTED_MIGRATION_ERROR = "Can't locate revision identified by"
BOUNDARY_OVERRIDES = (
    "POSTGRES_VOLUME_NAME",
    "SUBMISSION_KEYS_VOLUME_NAME",
    "CLIENTS_DIR",
    "PLUGINS_DIR",
    "STATEMENTS_DIR",
)


class RecoveryError(RuntimeError):
    """A recovery-rehearsal safety check or postcondition failed."""


def canonical_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def require_child(path: Path, parent: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise RecoveryError(f"{label} must be below {parent}") from exc
    if resolved == parent:
        raise RecoveryError(f"{label} must be a child of {parent}")
    return resolved


def validate_restore_evidence(path: Path) -> dict[str, Any]:
    resolved = require_child(path, RESTORE_DRILL_ROOT, "Restore evidence")
    if resolved.name != "restore-evidence.json" or not resolved.is_file():
        raise RecoveryError("Restore evidence must name an existing restore-evidence.json")
    evidence = load_json(resolved)
    required = {
        "schema_version",
        "database_dump",
        "database_dump_sha256",
        "database_public_table_counts",
        "database_target_volume",
        "files_archive_sha256",
        "files_restored_count",
        "submission_keys_inventory_sha256",
        "submission_keys_target_volume",
        "backend_restart_verified",
    }
    if not required.issubset(evidence) or evidence["schema_version"] != 1:
        raise RecoveryError("Restore evidence has an unsupported schema")
    if evidence["backend_restart_verified"] is not True:
        raise RecoveryError("Restore evidence does not attest a verified backend restart")

    dump = Path(str(evidence["database_dump"])).resolve()
    if dump != resolved.parent / "database.dump" or not dump.is_file():
        raise RecoveryError("Restore evidence does not reference its own readable database dump")
    if sha256_file(dump) != evidence["database_dump_sha256"]:
        raise RecoveryError("The restore-evidence database dump digest no longer matches")
    archive = resolved.parent / "resources.tar.gz"
    if not archive.is_file() or sha256_file(archive) != evidence["files_archive_sha256"]:
        raise RecoveryError("The restore-evidence resource archive digest no longer matches")

    for field in ("database_target_volume", "submission_keys_target_volume"):
        value = evidence[field]
        if not isinstance(value, str) or "restore-drill" not in value or not docker_volume_exists(value):
            raise RecoveryError(f"Restore evidence references an invalid or missing {field}")
    counts = evidence["database_public_table_counts"]
    if (
        not isinstance(counts, dict)
        or not counts
        or not all(isinstance(name, str) and isinstance(count, int) and count >= 0 for name, count in counts.items())
    ):
        raise RecoveryError("Restore evidence has invalid database table counts")
    return evidence


def restore_resource_archive(evidence_path: Path, evidence: dict[str, Any], output: Path) -> Path:
    archive = evidence_path.resolve().parent / "resources.tar.gz"
    destination = output / "recovered-files"
    destination.mkdir(mode=0o700)
    with tarfile.open(archive, "r:gz") as bundle:
        members = bundle.getmembers()
        for member in members:
            if not (member.isdir() or member.isfile()) or member.issym() or member.islnk():
                raise RecoveryError(f"Unsupported resource archive entry: {member.name}")
            if member.name != "resources" and not member.name.startswith("resources/"):
                raise RecoveryError(f"Resource archive entry escapes its expected root: {member.name}")
        bundle.extractall(destination, filter="data")
    # The safe extraction filter normalizes modes. Reapply only permission bits
    # from the already digest-verified archive, with directories last.
    for member in sorted(members, key=lambda item: item.isdir()):
        (destination / member.name).chmod(member.mode & 0o777)
    resources = destination / "resources"
    inventory = file_inventory(resources)
    file_count = sum(item["type"] == "file" for item in inventory)
    if file_count != evidence["files_restored_count"]:
        raise RecoveryError("Recovered resource file count does not match restore evidence")
    return resources


def volume_inventory(image: str, volume: str) -> str:
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--volume",
            f"{volume}:/data:ro",
            image,
            "-ceu",
            'cd /data; test -z "$(find . -type l -print -quit)"; find . -type f -exec sha256sum {} + | sort',
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    if completed.returncode:
        raise RecoveryError("Could not inventory the restored submission-key volume")
    return completed.stdout.strip()


def verify_key_evidence(image: str, evidence: dict[str, Any]) -> None:
    inventory = volume_inventory(image, evidence["submission_keys_target_volume"])
    if not inventory or hashlib.sha256(inventory.encode()).hexdigest() != evidence["submission_keys_inventory_sha256"]:
        raise RecoveryError("The restored submission-key volume no longer matches its evidence")


def prepare_failed_database(
    *,
    image: str,
    volume: str,
    container: str,
    user: str,
    database: str,
    password: str,
    dump: Path,
    expected_counts: dict[str, int],
) -> None:
    started = False
    try:
        create_database_target(
            image=image,
            volume=volume,
            container=container,
            user=user,
            database=database,
            password=password,
        )
        started = True
        wait_for_database(container, user, database)
        restore_dump(container, user, database, dump)
        if table_counts(container, user, database) != expected_counts:
            raise RecoveryError("The simulated-failure database does not match the verified backup")
        psql(container, user, database, f"UPDATE alembic_version SET version_num = '{MISSING_REVISION}';")
        revision = psql(container, user, database, "SELECT version_num FROM alembic_version;")
        if revision != MISSING_REVISION:
            raise RecoveryError("Could not install the intentionally incompatible Alembic revision")
    except DrillError as exc:
        raise RecoveryError(str(exc)) from exc
    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "--force", container],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def compose_env(release: dict[str, Any], overrides: dict[str, str]) -> dict[str, str]:
    environment = compose_environment(release)
    environment.update(overrides)
    return environment


def activate(args: argparse.Namespace, values: dict[str, str], release: dict[str, Any]) -> None:
    environment = compose_env(release, {name: values[name] for name in BOUNDARY_OVERRIDES})
    run(
        compose_command(args, values)
        + [
            "up",
            "--detach",
            "--no-build",
            "--wait",
            "--wait-timeout",
            str(args.timeout),
            "prestart",
            "backend",
            "frontend",
            "website",
        ],
        env=environment,
    )


def inspect_service(args: argparse.Namespace, values: dict[str, str], service: str) -> dict[str, Any]:
    container = run(
        compose_command(args, values) + ["ps", "--all", "--quiet", service],
        env=os.environ | {name: values[name] for name in BOUNDARY_OVERRIDES},
    ).strip()
    if not container or "\n" in container:
        raise RecoveryError(f"Expected exactly one staging {service} container")
    try:
        completed = subprocess.run(
            ["docker", "inspect", "--type", "container", container],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
        )
        if completed.returncode:
            raise RecoveryError(f"Could not inspect the staging {service} container")
        inspections = json.loads(completed.stdout)
        return inspections[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryError(f"Docker returned an invalid {service} inspection") from exc


def mount_for(inspection: dict[str, Any], destination: str) -> dict[str, Any]:
    matches = [mount for mount in inspection.get("Mounts", []) if mount.get("Destination") == destination]
    if len(matches) != 1:
        raise RecoveryError(f"Expected exactly one running mount at {destination}")
    return matches[0]


def verify_running_boundaries(
    args: argparse.Namespace,
    values: dict[str, str],
    release: dict[str, Any],
) -> None:
    database = inspect_service(args, values, "db")
    backend = inspect_service(args, values, "backend")
    if database.get("Config", {}).get("Image") != values["POSTGRES_IMAGE"]:
        raise RecoveryError("The running database image differs from the configured digest")
    if backend.get("Config", {}).get("Image") != release["images"]["backend"]:
        raise RecoveryError("The running backend image differs from the recorded release digest")
    if mount_for(database, "/var/lib/postgresql/data/pgdata").get("Name") != values["POSTGRES_VOLUME_NAME"]:
        raise RecoveryError("The running database does not use the expected volume")
    if mount_for(backend, "/app/keys").get("Name") != values["SUBMISSION_KEYS_VOLUME_NAME"]:
        raise RecoveryError("The running backend does not use the expected submission-key volume")
    bind_targets = {
        "/app/data/clients": Path(values["CLIENTS_DIR"]).resolve(),
        "/app/data/plugins": Path(values["PLUGINS_DIR"]).resolve(),
        "/app/secure/statements": Path(values["STATEMENTS_DIR"]).resolve(),
    }
    for destination, source in bind_targets.items():
        if Path(str(mount_for(backend, destination).get("Source", ""))).resolve() != source:
            raise RecoveryError(f"The running backend does not use the expected {destination} bind mount")


def verify_recovered_database_counts(
    args: argparse.Namespace,
    values: dict[str, str],
    expected: dict[str, int],
) -> None:
    database = inspect_service(args, values, "db")
    container = str(database.get("Id", ""))
    try:
        actual = table_counts(container, values["POSTGRES_USER"], values["POSTGRES_DB"])
    except DrillError as exc:
        raise RecoveryError(str(exc)) from exc
    if actual != expected:
        raise RecoveryError("The running recovered database table counts differ from restore evidence")


def expect_incompatible_migration(
    args: argparse.Namespace,
    values: dict[str, str],
    release: dict[str, Any],
    log_path: Path,
) -> str:
    environment = compose_env(release, {name: values[name] for name in BOUNDARY_OVERRIDES})
    base = compose_command(args, values)
    run(
        base + ["up", "--detach", "--no-build", "--wait", "--wait-timeout", str(args.timeout), "db"],
        env=environment,
    )
    command = base + ["run", "--rm", "--no-deps", "prestart", "bash", "scripts/migrate.sh"]
    print("+", " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        env=environment,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="backslashreplace",
    )
    log_path.write_text(completed.stdout, encoding="utf-8", newline="\n")
    log_path.chmod(0o600)
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.returncode == 0:
        raise RecoveryError("The intentionally incompatible migration unexpectedly succeeded")
    if EXPECTED_MIGRATION_ERROR not in completed.stdout or MISSING_REVISION not in completed.stdout:
        raise RecoveryError("Migration failed for an unexpected reason")
    return sha256_file(log_path)


def boundary_values(base: dict[str, str], **overrides: str) -> dict[str, str]:
    values = dict(base)
    values.update(overrides)
    return values


def validate_inputs(args: argparse.Namespace) -> tuple[Path, Path]:
    if args.confirm_staging_recovery != "YES":
        raise RecoveryError("Pass --confirm-staging-recovery YES to permit managed staging boundary switches")
    evidence = require_child(args.restore_evidence, RESTORE_DRILL_ROOT, "Restore evidence")
    output = require_child(args.output, RECOVERY_ROOT, "Recovery output")
    if output.exists():
        raise RecoveryError(f"Recovery output already exists: {output}")
    if "recovery-rehearsal" not in args.failure_database_volume:
        raise RecoveryError("The failure database volume name must contain recovery-rehearsal")
    if "recovery-rehearsal" not in args.failure_database_container:
        raise RecoveryError("The failure database container name must contain recovery-rehearsal")
    for value in (args.failure_database_container, args.failure_database_volume):
        if not NAME_PATTERN.fullmatch(value):
            raise RecoveryError(f"Invalid Docker name: {value}")
    if docker_volume_exists(args.failure_database_volume):
        raise RecoveryError(f"Failure database volume already exists: {args.failure_database_volume}")
    if docker_container_exists(args.failure_database_container):
        raise RecoveryError(f"Failure database container already exists: {args.failure_database_container}")
    if not 30 <= args.timeout <= 900:
        raise RecoveryError("--timeout must be between 30 and 900 seconds")
    return evidence, output


def rehearsal(args: argparse.Namespace) -> dict[str, Any]:
    evidence_path, output = validate_inputs(args)
    repo_commit = current_commit(require_clean=True)
    state_dir = args.state_dir.expanduser().resolve()
    deploy_values, production_values = deployment_context(args, state_dir=state_dir)
    if deploy_values["ENVIRONMENT"] != "staging":
        raise RecoveryError("Recovery rehearsals may target only ENVIRONMENT=staging")
    assert production_values is not None
    restore_evidence = validate_restore_evidence(evidence_path)
    current_release = validate_release(load_json(state_dir / "current-release.json"))
    validate_staging_artifacts(deploy_values, production_values)
    smoke_config = SmokeConfig.from_file(args.smoke_config)
    validate_staging_smoke_credentials(deploy_values, smoke_config, args.production_smoke_config)
    image = deploy_values["POSTGRES_IMAGE"]
    if not DIGEST_REF_PATTERN.fullmatch(image) or ":17" not in image:
        raise RecoveryError("Staging PostgreSQL must be a digest-pinned major version 17 image")
    verify_running_boundaries(args, deploy_values, current_release)
    verify_key_evidence(image, restore_evidence)

    for name in ("database_target_volume", "submission_keys_target_volume"):
        if restore_evidence[name] in {
            deploy_values["POSTGRES_VOLUME_NAME"],
            deploy_values["SUBMISSION_KEYS_VOLUME_NAME"],
            production_values["POSTGRES_VOLUME_NAME"],
            production_values["SUBMISSION_KEYS_VOLUME_NAME"],
        }:
            raise RecoveryError("Recovery targets must be distinct from staging and production volumes")

    output.mkdir(parents=True, mode=0o700)
    recovered_resources = restore_resource_archive(evidence_path, restore_evidence, output)
    failure_values = boundary_values(deploy_values, POSTGRES_VOLUME_NAME=args.failure_database_volume)
    recovery_values = boundary_values(
        deploy_values,
        POSTGRES_VOLUME_NAME=restore_evidence["database_target_volume"],
        SUBMISSION_KEYS_VOLUME_NAME=restore_evidence["submission_keys_target_volume"],
        CLIENTS_DIR=str(recovered_resources / "clients"),
        PLUGINS_DIR=str(recovered_resources / "plugins"),
        STATEMENTS_DIR=str(recovered_resources / "statements"),
    )
    if artifact_inventory(recovery_values) != artifact_inventory(deploy_values):
        raise RecoveryError("Recovered signed-artifact inventory differs from active staging")

    prepare_failed_database(
        image=image,
        volume=args.failure_database_volume,
        container=args.failure_database_container,
        user=deploy_values["POSTGRES_USER"],
        database=deploy_values["POSTGRES_DB"],
        password=deploy_values["POSTGRES_PASSWORD"],
        dump=Path(restore_evidence["database_dump"]),
        expected_counts=restore_evidence["database_public_table_counts"],
    )

    base = compose_command(args, deploy_values)
    original_smoke: list[dict[str, Any]] | None = None
    primary_error: BaseException | None = None
    evidence: dict[str, Any] = {}
    try:
        run(base + ["stop", "backend"], env=compose_env(current_release, {}))
        migration_log_sha256 = expect_incompatible_migration(
            args,
            failure_values,
            current_release,
            output / "expected-migration-failure.log",
        )
        activate(args, recovery_values, current_release)
        verify_running_boundaries(args, recovery_values, current_release)
        verify_recovered_database_counts(
            args,
            recovery_values,
            restore_evidence["database_public_table_counts"],
        )
        recovery_smoke = run_public_smoke(smoke_config)
        evidence = {
            "schema_version": 1,
            "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "repository_commit": repo_commit,
            "release": current_release,
            "expected_missing_revision": MISSING_REVISION,
            "expected_migration_failure_log_sha256": migration_log_sha256,
            "failure_database_volume": args.failure_database_volume,
            "recovery_database_volume": recovery_values["POSTGRES_VOLUME_NAME"],
            "recovery_submission_keys_volume": recovery_values["SUBMISSION_KEYS_VOLUME_NAME"],
            "recovery_resource_inventory_sha256": canonical_digest(file_inventory(recovered_resources)),
            "recovery_smoke": recovery_smoke,
            "source_restore_evidence": str(evidence_path),
        }
    except BaseException as exc:
        primary_error = exc
    finally:
        try:
            activate(args, deploy_values, current_release)
            verify_running_boundaries(args, deploy_values, current_release)
            original_smoke = run_public_smoke(smoke_config)
        except BaseException as restore_error:
            raise RecoveryError(
                "Could not restore the original staging boundaries; keep staging isolated and investigate"
            ) from restore_error
    if primary_error is not None:
        raise primary_error
    assert original_smoke is not None
    evidence["original_boundaries_restored"] = True
    evidence["original_smoke"] = original_smoke
    atomic_json(output / "recovery-evidence.json", evidence, exclusive=True)
    return evidence


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--deploy-env", type=Path, required=True)
    result.add_argument("--production-env", type=Path, required=True)
    result.add_argument("--state-dir", type=Path, required=True)
    result.add_argument("--production-state-dir", type=Path, required=True)
    result.add_argument("--compose-file", type=Path, required=True)
    result.add_argument("--smoke-config", type=Path, required=True)
    result.add_argument("--production-smoke-config", type=Path, required=True)
    result.add_argument("--restore-evidence", type=Path, required=True)
    result.add_argument("--failure-database-container", required=True)
    result.add_argument("--failure-database-volume", required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--timeout", type=int, default=180)
    result.add_argument("--confirm-staging-recovery", required=True, metavar="YES")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        result = rehearsal(args)
    except (DrillError, RecoveryError, ReleaseError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Incompatible migration failed as expected; full-boundary recovery and normal-boundary return passed.")
    print(f"Evidence: {args.output.expanduser().resolve() / 'recovery-evidence.json'}")
    print(f"Restored release: {result['release']['source_commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
