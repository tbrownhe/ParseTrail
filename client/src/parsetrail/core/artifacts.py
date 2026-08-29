"""Safe filesystem boundaries and headless generation of client artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from parsetrail.core import query, reports


class InvalidArtifactName(ValueError):
    """Raised when a server-provided artifact name is unsafe."""


def resolve_artifact_destination(root: Path, untrusted_name: str, *, allowed_suffixes: set[str]) -> Path:
    """Resolve an untrusted artifact filename without allowing path traversal."""
    supplied_path = Path(untrusted_name)
    if (
        not untrusted_name
        or "/" in untrusted_name
        or "\\" in untrusted_name
        or supplied_path.name != untrusted_name
        or untrusted_name in {".", ".."}
        or supplied_path.is_absolute()
    ):
        raise InvalidArtifactName("Artifact name must be a plain filename")

    normalized_suffixes = {suffix.lower() for suffix in allowed_suffixes}
    if supplied_path.suffix.lower() not in normalized_suffixes:
        raise InvalidArtifactName("Artifact has an unsupported file type")

    resolved_root = root.resolve()
    destination = (root / supplied_path).resolve()
    try:
        destination.relative_to(resolved_root)
    except ValueError as exc:
        raise InvalidArtifactName("Artifact path escapes its configured root") from exc
    return destination


class ArtifactServiceError(RuntimeError):
    """Base class for expected failures at the artifact boundary."""


class ArtifactPersistenceError(ArtifactServiceError):
    """Raised when artifact source data cannot be queried."""


class ArtifactWriteError(ArtifactServiceError):
    """Raised when an artifact cannot be written completely."""


@dataclass(frozen=True)
class AccountExportResult:
    destination: Path
    account_count: int
    account_number_count: int


class ArtifactService:
    """Own artifact source queries and durable file writes."""

    def __init__(self, SessionFactory: sessionmaker):
        self.SessionFactory = SessionFactory

    def export_accounts(self, destination: Path) -> AccountExportResult:
        destination = Path(destination)
        try:
            with self.SessionFactory() as session:
                accounts = query.accounts_table(session)
                account_numbers = query.account_numbers_table(session)
        except SQLAlchemyError as exc:
            raise ArtifactPersistenceError("Failed to load account configuration data.") from exc

        data = {"Accounts": accounts, "AccountNumbers": account_numbers}
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(data, output, indent=2, default=str)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, destination)
        except OSError as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise ArtifactWriteError(f"Failed to write account configuration to {destination}.") from exc

        return AccountExportResult(
            destination=destination,
            account_count=len(accounts),
            account_number_count=len(account_numbers),
        )

    def generate_report(self, destination: Path, *, months: int | None = None) -> Path:
        destination = Path(destination)
        try:
            with self.SessionFactory() as session:
                data, columns = query.transactions(session, months=months)
        except SQLAlchemyError as exc:
            raise ArtifactPersistenceError("Failed to load report data.") from exc

        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            reports.write_report(data, columns, destination)
        except (OSError, ValueError) as exc:
            raise ArtifactWriteError(f"Failed to write report to {destination}.") from exc
        return destination
