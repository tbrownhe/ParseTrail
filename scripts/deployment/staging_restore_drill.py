"""Back up and restore every staging-owned persistent data boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

STAGING_PROJECT = "parsetrail-staging"
STAGING_RESOURCES = Path("/srv/parsetrail-staging/resources").resolve()
STAGING_DRILL_ROOT = Path("/srv/parsetrail-staging/restore-drill").resolve()
PRODUCTION_KEYS_VOLUME = "parsetrail_app-keys-data"
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class DrillError(RuntimeError):
    """A restore-drill safety check or postcondition failed."""


def run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | None = None,
) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            stdin=stdin,
            stdout=stdout if stdout is not None else subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except FileNotFoundError as exc:
        raise DrillError(f"Required command was not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode(errors="backslashreplace").strip()
        raise DrillError(f"{command[0]} failed: {detail or 'command failed'}") from exc
    if stdout is not None:
        return ""
    return completed.stdout.decode(errors="backslashreplace").strip()


def inspect_container(container: str) -> dict[str, Any]:
    try:
        documents = json.loads(run(["docker", "inspect", "--type", "container", container]))
        inspection = documents[0]
    except (IndexError, TypeError, json.JSONDecodeError) as exc:
        raise DrillError("Docker returned an invalid container inspection") from exc
    return inspection


def require_staging_database(container: str) -> dict[str, Any]:
    inspection = inspect_container(container)
    try:
        labels = inspection["Config"]["Labels"]
        running = inspection["State"]["Running"]
        image = inspection["Config"]["Image"]
    except (KeyError, TypeError) as exc:
        raise DrillError("The database container inspection is incomplete") from exc
    if running is not True:
        raise DrillError("The staging database must be running")
    if labels.get("com.docker.compose.project") != STAGING_PROJECT:
        raise DrillError(f"The database must belong to the {STAGING_PROJECT} Compose project")
    if labels.get("com.docker.compose.service") != "db":
        raise DrillError("The source container must be the Compose database service")
    if "@sha256:" not in image:
        raise DrillError("The staging PostgreSQL image must be pinned by digest")
    return inspection


def require_staging_backend() -> tuple[str, str]:
    containers = run(
        [
            "docker",
            "ps",
            "--all",
            "--quiet",
            "--filter",
            f"label=com.docker.compose.project={STAGING_PROJECT}",
            "--filter",
            "label=com.docker.compose.service=backend",
        ]
    )
    container_ids = containers.splitlines()
    if len(container_ids) != 1:
        raise DrillError(f"Expected exactly one {STAGING_PROJECT} backend container")
    container = container_ids[0]
    inspection = inspect_container(container)
    try:
        labels = inspection["Config"]["Labels"]
        image = inspection["Config"]["Image"]
        running = inspection["State"]["Running"]
        health = inspection["State"]["Health"]["Status"]
    except (KeyError, TypeError) as exc:
        raise DrillError("The backend container inspection is incomplete") from exc
    if labels.get("com.docker.compose.project") != STAGING_PROJECT:
        raise DrillError(f"The backend must belong to the {STAGING_PROJECT} Compose project")
    if labels.get("com.docker.compose.service") != "backend":
        raise DrillError("The source container must be the Compose backend service")
    if "@sha256:" not in image:
        raise DrillError("The staging backend image must be pinned by digest")
    if running is not True or health != "healthy":
        raise DrillError("The staging backend must be running and healthy before the drill")
    return container, image


def stop_staging_backend(container: str, image: str) -> None:
    run(["docker", "stop", "--time", "30", container])
    inspection = inspect_container(container)
    if inspection.get("Config", {}).get("Image") != image:
        raise DrillError("The staging backend image changed while stopping it")
    if inspection.get("State", {}).get("Running") is not False:
        raise DrillError("The staging backend did not stop")


def restart_staging_backend(
    container: str,
    image: str,
    timeout_seconds: int = 120,
) -> None:
    run(["docker", "start", container])
    deadline = time.monotonic() + timeout_seconds
    last_health = "unknown"
    while time.monotonic() < deadline:
        inspection = inspect_container(container)
        if inspection.get("Config", {}).get("Image") != image:
            raise DrillError("The staging backend image changed during the drill")
        state = inspection.get("State", {})
        last_health = state.get("Health", {}).get("Status", "missing")
        if state.get("Running") is True and last_health == "healthy":
            return
        time.sleep(1)
    raise DrillError(f"The staging backend did not become healthy; last health was {last_health}")


def container_setting(container: str, name: str) -> str:
    value = run(["docker", "exec", container, "printenv", name])
    if not value or "\n" in value:
        raise DrillError(f"The database container has an invalid {name}")
    return value


def psql(container: str, user: str, database: str, sql: str) -> str:
    return run(
        [
            "docker",
            "exec",
            container,
            "psql",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--quiet",
            "--set=ON_ERROR_STOP=1",
            "--username",
            user,
            "--dbname",
            database,
            "--command",
            sql,
        ]
    )


def table_counts(container: str, user: str, database: str) -> dict[str, int]:
    tables = psql(
        container,
        user,
        database,
        "SELECT schemaname, tablename FROM pg_catalog.pg_tables WHERE schemaname = 'public' ORDER BY 1, 2;",
    )
    counts: dict[str, int] = {}
    for line in tables.splitlines():
        if not line:
            continue
        try:
            schema, table = line.split("|", 1)
        except ValueError as exc:
            raise DrillError("PostgreSQL returned an invalid table inventory") from exc
        quoted_schema = schema.replace('"', '""')
        quoted_table = table.replace('"', '""')
        count = psql(container, user, database, f'SELECT count(*) FROM "{quoted_schema}"."{quoted_table}";')
        try:
            counts[f"{schema}.{table}"] = int(count)
        except ValueError as exc:
            raise DrillError("PostgreSQL returned an invalid row count") from exc
    if not counts:
        raise DrillError("The staging database has no public tables")
    return counts


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_dump(container: str, user: str, database: str, destination: Path) -> str:
    try:
        with destination.open("xb") as stream:
            run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_dump",
                    "--username",
                    user,
                    "--dbname",
                    database,
                    "--format",
                    "custom",
                    "--compress",
                    "9",
                    "--no-owner",
                    "--no-privileges",
                ],
                stdout=stream,
            )
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    if destination.stat().st_size == 0:
        destination.unlink()
        raise DrillError("pg_dump produced an empty backup")
    destination.chmod(0o600)
    return sha256_file(destination)


def docker_volume_exists(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "volume", "inspect", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def docker_container_exists(name: str) -> bool:
    completed = subprocess.run(
        ["docker", "inspect", "--type", "container", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0


def create_database_target(
    *,
    image: str,
    volume: str,
    container: str,
    user: str,
    database: str,
    password: str,
) -> None:
    if docker_volume_exists(volume):
        raise DrillError(f"Target database volume already exists: {volume}")
    if docker_container_exists(container):
        raise DrillError(f"Target database container already exists: {container}")
    run(["docker", "volume", "create", volume])
    environment = os.environ.copy()
    environment["POSTGRES_PASSWORD"] = password
    run(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container,
            "--env",
            f"POSTGRES_USER={user}",
            "--env",
            f"POSTGRES_DB={database}",
            "--env",
            "POSTGRES_PASSWORD",
            "--env",
            "PGDATA=/var/lib/postgresql/data/pgdata",
            "--volume",
            f"{volume}:/var/lib/postgresql/data/pgdata",
            image,
        ],
        env=environment,
    )


def wait_for_database(container: str, user: str, database: str, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        completed = subprocess.run(
            ["docker", "exec", container, "pg_isready", "--username", user, "--dbname", database],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode == 0:
            return
        time.sleep(1)
    raise DrillError("The restore-drill PostgreSQL container did not become ready")


def restore_dump(container: str, user: str, database: str, dump: Path) -> None:
    with dump.open("rb") as stream:
        run(
            [
                "docker",
                "exec",
                "--interactive",
                container,
                "pg_restore",
                "--username",
                user,
                "--dbname",
                database,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
            ],
            stdin=stream,
        )


def file_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise DrillError(f"Resource trees must not contain symbolic links: {path}")
        relative = path.relative_to(root).as_posix()
        mode = path.stat().st_mode & 0o777
        if path.is_dir():
            inventory.append({"path": relative, "type": "directory", "mode": mode})
        elif path.is_file():
            inventory.append(
                {
                    "path": relative,
                    "type": "file",
                    "mode": mode,
                    "size": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            )
        else:
            raise DrillError(f"Unsupported resource-tree entry: {path}")
    return inventory


def apply_inventory_modes(root: Path, inventory: list[dict[str, Any]]) -> None:
    # Python's safe tar filter intentionally normalizes permission bits. Restore
    # only the modes captured from our trusted source tree after extraction.
    entries = sorted(inventory, key=lambda item: item["type"] == "directory")
    for item in entries:
        (root / item["path"]).chmod(item["mode"])


def restore_resources(source: Path, output_root: Path) -> tuple[str, int]:
    source_inventory = file_inventory(source)
    archive = output_root / "resources.tar.gz"
    with tarfile.open(archive, "x:gz") as bundle:
        bundle.add(source, arcname="resources", recursive=True)
    archive.chmod(0o600)
    restored_root = output_root / "restored-files"
    restored_root.mkdir(mode=0o700)
    with tarfile.open(archive, "r:gz") as bundle:
        bundle.extractall(restored_root, filter="data")
    restored_resources = restored_root / "resources"
    apply_inventory_modes(restored_resources, source_inventory)
    if file_inventory(restored_resources) != source_inventory:
        raise DrillError("The restored resource tree does not match its source inventory")
    return sha256_file(archive), sum(item["type"] == "file" for item in source_inventory)


def volume_inventory(image: str, volume: str) -> str:
    return run(
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
        ]
    )


def restore_keys(image: str, source_volume: str, target_volume: str) -> tuple[str, int]:
    if source_volume == PRODUCTION_KEYS_VOLUME:
        raise DrillError("Refusing to use the production submission-key volume")
    if not source_volume.endswith("-staging"):
        raise DrillError("The source submission-key volume must be staging-specific")
    if not docker_volume_exists(source_volume):
        raise DrillError(f"The source submission-key volume does not exist: {source_volume}")
    if docker_volume_exists(target_volume):
        raise DrillError(f"Target submission-key volume already exists: {target_volume}")
    source_inventory = volume_inventory(image, source_volume)
    if not source_inventory:
        raise DrillError("The staging submission-key volume is empty")
    run(["docker", "volume", "create", target_volume])
    run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--volume",
            f"{source_volume}:/source:ro",
            "--volume",
            f"{target_volume}:/target",
            image,
            "-ceu",
            "cp -a /source/. /target/",
        ]
    )
    target_inventory = volume_inventory(image, target_volume)
    if target_inventory != source_inventory:
        raise DrillError("The restored submission-key volume does not match its source inventory")
    digest = hashlib.sha256(source_inventory.encode()).hexdigest()
    return digest, len(source_inventory.splitlines())


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_inputs(args: argparse.Namespace) -> None:
    if args.confirm_staging_downtime != "YES":
        raise DrillError("Pass --confirm-staging-downtime YES to permit managed backend downtime")
    for value in (
        args.database_container,
        args.target_database_container,
        args.target_database_volume,
        args.source_keys_volume,
        args.target_keys_volume,
    ):
        if not NAME_PATTERN.fullmatch(value):
            raise DrillError(f"Invalid Docker name: {value}")
    resources = args.resources.expanduser().resolve()
    if resources != STAGING_RESOURCES:
        raise DrillError(f"The resource source must be exactly {STAGING_RESOURCES}")
    if not resources.is_dir():
        raise DrillError(f"The staging resource source is not a directory: {resources}")
    output = args.output.expanduser().resolve()
    try:
        output.relative_to(STAGING_DRILL_ROOT)
    except ValueError as exc:
        raise DrillError(f"The drill output must be below {STAGING_DRILL_ROOT}") from exc
    if output == STAGING_DRILL_ROOT:
        raise DrillError("The drill output must be a new child of the restore-drill root")
    if output.exists():
        raise DrillError(f"The drill output already exists: {output}")
    for value in (args.target_database_container, args.target_database_volume, args.target_keys_volume):
        if "restore-drill" not in value:
            raise DrillError("Every target Docker name must contain restore-drill")


def restore_boundaries(args: argparse.Namespace) -> dict[str, Any]:
    inspection = require_staging_database(args.database_container)
    image = inspection["Config"]["Image"]
    user = container_setting(args.database_container, "POSTGRES_USER")
    database = container_setting(args.database_container, "POSTGRES_DB")
    password = container_setting(args.database_container, "POSTGRES_PASSWORD")
    version = psql(args.database_container, user, database, "SHOW server_version_num;")
    if not version.startswith("17"):
        raise DrillError(f"Expected PostgreSQL 17 staging source; server_version_num is {version}")

    output = args.output.expanduser().resolve()
    output.mkdir(mode=0o700, parents=True)
    source_counts = table_counts(args.database_container, user, database)
    dump = output / "database.dump"
    dump_sha256 = create_dump(args.database_container, user, database, dump)

    target_started = False
    try:
        create_database_target(
            image=image,
            volume=args.target_database_volume,
            container=args.target_database_container,
            user=user,
            database=database,
            password=password,
        )
        target_started = True
        wait_for_database(args.target_database_container, user, database)
        target_version = psql(args.target_database_container, user, database, "SHOW server_version_num;")
        if not target_version.startswith("17"):
            raise DrillError(f"Expected PostgreSQL 17 restore target; server_version_num is {target_version}")
        restore_dump(args.target_database_container, user, database, dump)
        if table_counts(args.target_database_container, user, database) != source_counts:
            raise DrillError("The restored database table counts do not match the source")
    finally:
        if target_started:
            subprocess.run(
                ["docker", "rm", "--force", args.target_database_container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

    resources_sha256, resource_file_count = restore_resources(args.resources.resolve(), output)
    keys_sha256, key_file_count = restore_keys(image, args.source_keys_volume, args.target_keys_volume)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence = {
        "schema_version": 1,
        "verified_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "database_dump": str(dump),
        "database_dump_sha256": dump_sha256,
        "database_public_table_counts": source_counts,
        "database_restore_id": f"staging-pg17-restore-{timestamp}",
        "database_target_volume": args.target_database_volume,
        "files_archive_sha256": resources_sha256,
        "files_restored_count": resource_file_count,
        "files_restore_id": f"staging-files-restore-{timestamp}",
        "submission_keys_inventory_sha256": keys_sha256,
        "submission_keys_restored_count": key_file_count,
        "submission_keys_restore_id": f"staging-keys-restore-{timestamp}",
        "submission_keys_target_volume": args.target_keys_volume,
    }
    return evidence


def drill(args: argparse.Namespace) -> dict[str, Any]:
    validate_inputs(args)
    backend_container, backend_image = require_staging_backend()
    try:
        stop_staging_backend(backend_container, backend_image)
        evidence = restore_boundaries(args)
    finally:
        restart_staging_backend(backend_container, backend_image)
    evidence["backend_image"] = backend_image
    evidence["backend_restart_verified"] = True
    atomic_json(args.output.expanduser().resolve() / "restore-evidence.json", evidence)
    return evidence


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--database-container", required=True)
    result.add_argument("--target-database-container", required=True)
    result.add_argument("--target-database-volume", required=True)
    result.add_argument("--source-keys-volume", required=True)
    result.add_argument("--target-keys-volume", required=True)
    result.add_argument("--resources", type=Path, required=True)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--confirm-staging-downtime", required=True, metavar="YES")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        evidence = drill(args)
    except DrillError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print("Staging backup/restore drill passed all database, file, and submission-key comparisons.")
    print(f"Database restore: {evidence['database_restore_id']}")
    print(f"File restore: {evidence['files_restore_id']}")
    print(f"Submission-key restore: {evidence['submission_keys_restore_id']}")
    print(f"Evidence: {args.output.expanduser().resolve() / 'restore-evidence.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
