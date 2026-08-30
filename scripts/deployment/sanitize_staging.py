"""Remove production identities and ciphertext from a restored staging database."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STAGING_PROJECT = "parsetrail-staging"
STAGING_EMAIL_SUFFIX = "@staging.parsetrail.com"
DISABLED_PASSWORD_HASH = "!parsetrail-staging-restored-user-disabled!"
CONTAINER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._+-]+@staging\.parsetrail\.com", re.IGNORECASE)


class SanitizationError(RuntimeError):
    """A staging-restoration safety check failed."""


def run(command: list[str]) -> str:
    try:
        completed = subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SanitizationError(f"Required command was not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "command failed").strip()
        raise SanitizationError(f"{command[0]} failed: {detail}") from exc
    return completed.stdout.strip()


def repository_root() -> Path:
    script = Path(__file__).resolve()
    for parent in script.parents:
        if (parent / ".git").exists() and (parent / "docker-compose.yml").is_file():
            return parent
    raise SanitizationError("Could not locate the ParseTrail Git repository")


def require_external_output(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(repository_root())
    except ValueError:
        pass
    else:
        raise SanitizationError("Sanitization evidence must be stored outside the Git repository")
    if resolved.exists():
        raise SanitizationError(f"Refusing to overwrite existing evidence: {resolved}")
    resolved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    return resolved


def validate_inputs(container: str, keep_email: str, confirmation: str) -> str:
    if confirmation != "YES":
        raise SanitizationError("Pass --confirm-sanitize-staging-users YES after reviewing the target")
    if not CONTAINER_PATTERN.fullmatch(container):
        raise SanitizationError("The Docker container name is invalid")
    normalized_email = keep_email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized_email):
        raise SanitizationError(f"The preserved account must end in {STAGING_EMAIL_SUFFIX}")
    return normalized_email


def inspect_staging_database(container: str) -> dict[str, Any]:
    raw = run(["docker", "inspect", "--type", "container", container])
    try:
        documents = json.loads(raw)
        inspection = documents[0]
        labels = inspection["Config"]["Labels"]
        running = inspection["State"]["Running"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SanitizationError("Docker returned an invalid container inspection") from exc
    if running is not True:
        raise SanitizationError("The target database container is not running")
    if labels.get("com.docker.compose.project") != STAGING_PROJECT:
        raise SanitizationError(f"The target must belong to the {STAGING_PROJECT} Compose project")
    if labels.get("com.docker.compose.service") != "db":
        raise SanitizationError("The target must be the Compose database service")
    return inspection


def container_setting(container: str, name: str) -> str:
    value = run(["docker", "exec", container, "printenv", name])
    if not value or "\n" in value:
        raise SanitizationError(f"The database container has an invalid {name}")
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


def parse_counts(output: str, *, fields: int) -> tuple[int, ...]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SanitizationError("The staging database returned an unexpected result")
    parts = lines[0].split("|")
    if len(parts) != fields:
        raise SanitizationError("The staging database returned an unexpected count shape")
    try:
        return tuple(int(part) for part in parts)
    except ValueError as exc:
        raise SanitizationError("The staging database returned a non-numeric count") from exc


def sanitization_sql(keep_email: str) -> str:
    # validate_inputs restricts keep_email to a deliberately small character set.
    return f"""
BEGIN;
LOCK TABLE public.\"user\" IN SHARE ROW EXCLUSIVE MODE;
LOCK TABLE public.statement_uploads IN SHARE ROW EXCLUSIVE MODE;
DO $sanitize$
DECLARE
    keep_count integer;
    conflicting_staging_count integer;
BEGIN
    SELECT count(*) INTO keep_count
      FROM public.\"user\"
     WHERE lower(email) = '{keep_email}'
       AND is_active = true
       AND is_superuser = true;
    IF keep_count <> 1 THEN
        RAISE EXCEPTION 'expected exactly one active staging superuser to preserve, found %', keep_count;
    END IF;

    SELECT count(*) INTO conflicting_staging_count
      FROM public.\"user\"
     WHERE lower(email) <> '{keep_email}'
       AND lower(email) LIKE '%{STAGING_EMAIL_SUFFIX}';
    IF conflicting_staging_count <> 0 THEN
        RAISE EXCEPTION 'found % additional staging-domain account(s); refusing a repeat or late scrub',
            conflicting_staging_count;
    END IF;
END
$sanitize$;

WITH sanitized AS (
    UPDATE public.\"user\"
       SET email = 'scrubbed+' || replace(id::text, '-', '') || '{STAGING_EMAIL_SUFFIX}',
           hashed_password = '{DISABLED_PASSWORD_HASH}',
           is_active = false,
           is_superuser = false,
           full_name = NULL,
           pending_email = NULL,
           session_version = session_version + 1,
           password_reset_version = password_reset_version + 1,
           email_verification_version = email_verification_version + 1
     WHERE lower(email) <> '{keep_email}'
     RETURNING 1
), removed_uploads AS (
    DELETE FROM public.statement_uploads
    RETURNING 1
)
SELECT (SELECT count(*) FROM sanitized), (SELECT count(*) FROM removed_uploads);
COMMIT;
"""


def verify_sql(keep_email: str) -> str:
    return f"""
SELECT
    count(*),
    count(*) FILTER (
        WHERE lower(email) = '{keep_email}'
          AND is_active = true
          AND is_superuser = true
    ),
    count(*) FILTER (
        WHERE lower(email) <> '{keep_email}'
          AND email LIKE 'scrubbed+%{STAGING_EMAIL_SUFFIX}'
          AND hashed_password = '{DISABLED_PASSWORD_HASH}'
          AND is_active = false
          AND is_superuser = false
          AND full_name IS NULL
          AND pending_email IS NULL
    ),
    (SELECT count(*) FROM public.statement_uploads)
FROM public.\"user\";
"""


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


def sanitize(container: str, keep_email: str, evidence_path: Path, confirmation: str) -> dict[str, Any]:
    normalized_email = validate_inputs(container, keep_email, confirmation)
    output = require_external_output(evidence_path)
    inspection = inspect_staging_database(container)
    user = container_setting(container, "POSTGRES_USER")
    database = container_setting(container, "POSTGRES_DB")
    version = psql(container, user, database, "SHOW server_version_num;")
    if not version.startswith("17"):
        raise SanitizationError(f"Expected a PostgreSQL 17 staging target; server_version_num is {version}")

    schema_revision = psql(container, user, database, "SELECT version_num FROM public.alembic_version;")
    if not schema_revision or "\n" in schema_revision:
        raise SanitizationError("The staging database does not have one Alembic revision")

    changed_output = psql(container, user, database, sanitization_sql(normalized_email))
    sanitized_users, removed_uploads = parse_counts(changed_output, fields=2)
    verification = parse_counts(
        psql(container, user, database, verify_sql(normalized_email)),
        fields=4,
    )
    total_users, kept_users, verified_sanitized_users, remaining_uploads = verification
    if kept_users != 1 or verified_sanitized_users != sanitized_users or total_users != sanitized_users + 1:
        raise SanitizationError("The staging user sanitization did not satisfy its postconditions")
    if remaining_uploads != 0:
        raise SanitizationError("Copied statement submissions remain in staging")

    evidence = {
        "schema_version": 1,
        "sanitized_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "compose_project": STAGING_PROJECT,
        "database_container_id": str(inspection.get("Id", "")),
        "database_server_version_num": version,
        "alembic_revision": schema_revision,
        "preserved_account": normalized_email,
        "total_users": total_users,
        "sanitized_users": sanitized_users,
        "removed_statement_uploads": removed_uploads,
    }
    atomic_json(output, evidence)
    return evidence


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--container", required=True, help="Running parsetrail-staging database container")
    result.add_argument("--keep-email", required=True, help="One staging-domain bootstrap account to preserve")
    result.add_argument("--evidence", type=Path, required=True, help="New evidence JSON path outside the repository")
    result.add_argument("--confirm-sanitize-staging-users", required=True, metavar="YES")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        evidence = sanitize(
            args.container,
            args.keep_email,
            args.evidence,
            args.confirm_sanitize_staging_users,
        )
    except SanitizationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "Sanitized the restored staging database: "
        f"{evidence['sanitized_users']} copied user(s), "
        f"{evidence['removed_statement_uploads']} copied submission(s)."
    )
    print(f"Evidence: {args.evidence.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
