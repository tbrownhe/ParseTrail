#!/usr/bin/env python3
"""Abandon staging submissions and rotate their server-side encryption key."""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from public_smoke import SmokeConfig, SmokeFailure, run_public_smoke
from release import (
    ReleaseError,
    atomic_json,
    compose_command,
    current_commit,
    deployment_context,
    load_json,
    run,
    validate_release,
    validate_staging_artifacts,
    validate_staging_smoke_credentials,
)
from staging_recovery_rehearsal import activate, inspect_service, verify_running_boundaries
from staging_restore_drill import DrillError, psql

STAGING_ROOT = Path("/srv/parsetrail-staging").resolve()
STAGING_STATEMENTS = (STAGING_ROOT / "resources/statements").resolve()


class ResetError(RuntimeError):
    """A staging-reset safety check or postcondition failed."""


def require_child(path: Path, parent: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(parent)
    except ValueError as exc:
        raise ResetError(f"{label} must be below {parent}") from exc
    if resolved == parent:
        raise ResetError(f"{label} must be a child of {parent}")
    return resolved


def replace_dotenv_value(text: str, key: str, value: str) -> str:
    found = False
    output: list[str] = []
    for original in text.splitlines():
        stripped = original.strip()
        candidate = stripped[7:].lstrip() if stripped.startswith("export ") else stripped
        existing_key, separator, _ = candidate.partition("=")
        if separator and existing_key.strip() == key:
            if found:
                raise ResetError(f"Deployment environment defines {key} more than once")
            prefix = "export " if stripped.startswith("export ") else ""
            output.append(f"{prefix}{key}={value}")
            found = True
        else:
            output.append(original)
    if not found:
        raise ResetError(f"Deployment environment does not define {key}")
    return "\n".join(output) + "\n"


def atomic_text(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def statement_inventory(root: Path) -> list[dict[str, Any]]:
    if root.resolve() != STAGING_STATEMENTS or not root.is_dir():
        raise ResetError(f"Statement reset may address only {STAGING_STATEMENTS}")
    inventory: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        if entry.is_symlink() or not entry.is_file():
            raise ResetError(f"Staging statement storage contains an unsupported entry: {entry}")
        inventory.append({"name": entry.name, "size": entry.stat().st_size})
    return inventory


def remove_statement_files(root: Path, inventory: list[dict[str, Any]]) -> None:
    expected = {item["name"] for item in inventory}
    if {item["name"] for item in statement_inventory(root)} != expected:
        raise ResetError("Staging statement storage changed after its writer was stopped")
    for name in expected:
        path = root / name
        if path.parent != root or path.is_symlink() or not path.is_file():
            raise ResetError(f"Refusing to remove an unexpected statement entry: {path}")
        path.unlink()
    if statement_inventory(root):
        raise ResetError("Staging statement files remain after reset")


def database_container(args: argparse.Namespace, values: dict[str, str]) -> str:
    inspection = inspect_service(args, values, "db")
    container = str(inspection.get("Id", ""))
    labels = inspection.get("Config", {}).get("Labels", {})
    if labels.get("com.docker.compose.project") != "parsetrail-staging":
        raise ResetError("Database container does not belong to parsetrail-staging")
    if labels.get("com.docker.compose.service") != "db":
        raise ResetError("Database container is not the staging db service")
    return container


def delete_database_rows(container: str, values: dict[str, str]) -> int:
    try:
        result = psql(
            container,
            values["POSTGRES_USER"],
            values["POSTGRES_DB"],
            "WITH deleted AS (DELETE FROM public.statement_uploads RETURNING 1) SELECT count(*) FROM deleted;",
        )
    except DrillError as exc:
        raise ResetError(str(exc)) from exc
    try:
        deleted = int(result)
    except ValueError as exc:
        raise ResetError("Staging database returned an invalid deleted-row count") from exc
    remaining = psql(
        container,
        values["POSTGRES_USER"],
        values["POSTGRES_DB"],
        "SELECT count(*) FROM public.statement_uploads;",
    )
    if remaining != "0":
        raise ResetError("Staging statement rows remain after reset")
    return deleted


def validate_inputs(args: argparse.Namespace, state_dir: Path) -> Path:
    if args.confirm_abandon_staging_submissions != "YES":
        raise ResetError("Pass --confirm-abandon-staging-submissions YES to authorize destructive staging reset")
    if not 30 <= args.timeout <= 900:
        raise ResetError("--timeout must be between 30 and 900 seconds")
    evidence = require_child(args.evidence, state_dir, "Reset evidence")
    if evidence.exists():
        raise ResetError(f"Reset evidence already exists: {evidence}")
    return evidence


def reset(args: argparse.Namespace) -> dict[str, Any]:
    repository_commit = current_commit(require_clean=True)
    state_dir = args.state_dir.expanduser().resolve()
    evidence_path = validate_inputs(args, state_dir)
    deploy_values, production_values = deployment_context(args, state_dir=state_dir)
    if deploy_values["ENVIRONMENT"] != "staging":
        raise ResetError("Submission reset may target only ENVIRONMENT=staging")
    current_release = validate_release(load_json(state_dir / "current-release.json"))
    validate_staging_artifacts(deploy_values, production_values)
    smoke_config = SmokeConfig.from_file(args.smoke_config)
    validate_staging_smoke_credentials(deploy_values, smoke_config, args.production_smoke_config)
    verify_running_boundaries(args, deploy_values, current_release)

    statements = Path(deploy_values["STATEMENTS_DIR"]).expanduser().resolve()
    inventory = statement_inventory(statements)
    container = database_container(args, deploy_values)
    environment_path = args.deploy_env.expanduser().resolve()
    old_environment = environment_path.read_text(encoding="utf-8")
    new_master_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    new_environment = replace_dotenv_value(old_environment, "MASTER_KEY", new_master_key)

    primary_error: BaseException | None = None
    result: dict[str, Any] = {}
    try:
        run(compose_command(args, deploy_values) + ["stop", "backend"])
        deleted_rows = delete_database_rows(container, deploy_values)
        remove_statement_files(statements, inventory)
        atomic_text(environment_path, new_environment)
        activate(args, deploy_values, current_release)
        verify_running_boundaries(args, deploy_values, current_release)
        smoke = run_public_smoke(smoke_config)
        result = {
            "schema_version": 1,
            "reset_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "repository_commit": repository_commit,
            "release_source_commit": current_release["source_commit"],
            "deleted_database_rows": deleted_rows,
            "deleted_statement_files": len(inventory),
            "deleted_statement_bytes": sum(item["size"] for item in inventory),
            "master_key_rotated": True,
            "smoke": smoke,
        }
    except BaseException as exc:
        primary_error = exc
    finally:
        if primary_error is not None:
            try:
                # Data deletion is intentional and is never rolled back. Use
                # whichever key is now authoritative in the deployment file.
                activate(args, deploy_values, current_release)
                verify_running_boundaries(args, deploy_values, current_release)
            except BaseException as recovery_error:
                raise ResetError("Staging reset failed and the backend could not be restored") from recovery_error
    if primary_error is not None:
        raise primary_error
    atomic_json(evidence_path, result, exclusive=True)
    return result


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--deploy-env", type=Path, required=True)
    result.add_argument("--production-env", type=Path, required=True)
    result.add_argument("--state-dir", type=Path, required=True)
    result.add_argument("--production-state-dir", type=Path, required=True)
    result.add_argument("--compose-file", type=Path, required=True)
    result.add_argument("--smoke-config", type=Path, required=True)
    result.add_argument("--production-smoke-config", type=Path, required=True)
    result.add_argument("--evidence", type=Path, required=True)
    result.add_argument("--timeout", type=int, default=180)
    result.add_argument("--confirm-abandon-staging-submissions", required=True, metavar="YES")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        evidence = reset(args)
    except (DrillError, ReleaseError, ResetError, SmokeFailure) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "Staging submissions abandoned and MASTER_KEY rotated: "
        f"{evidence['deleted_database_rows']} row(s), "
        f"{evidence['deleted_statement_files']} file(s)."
    )
    print(f"Evidence: {args.evidence.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
