"""Headless validation, encryption, and upload of statement submissions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from parsetrail.core.api import StatementSubmissionCancelled, api_client
from parsetrail.core.crypto import encrypt_file

MAX_STATEMENT_BYTES = 25 * 1024 * 1024
STATEMENT_FREQUENCIES = ("Daily", "Weekly", "Monthly", "Quarterly", "Annually", "Other")


class StatementSubmissionError(RuntimeError):
    """Base class for expected failures at the submission boundary."""


class StatementSubmissionValidationError(StatementSubmissionError):
    """Raised when a proposed submission is invalid."""


class StatementSubmissionRejectedError(StatementSubmissionError):
    """Raised when the server does not confirm durable encrypted storage."""


class _Response(Protocol):
    def json(self) -> object: ...

    def close(self) -> None: ...


class _Auth(Protocol):
    def login(self, email: str, password: str) -> object: ...


class _ApiClient(Protocol):
    auth: _Auth

    def submit_statement(
        self,
        encrypted_file: bytes,
        encrypted_key: str,
        metadata: dict[str, object],
        *,
        cancelled: Callable[[], bool],
        progress: Callable[[int, int], None],
    ) -> _Response: ...


@dataclass(frozen=True)
class PreparedStatementSubmission:
    source: Path
    metadata: dict[str, object]


class StatementSubmissionService:
    """Keep plaintext local while orchestrating an in-memory encrypted upload."""

    def __init__(
        self,
        *,
        client: _ApiClient = api_client,
        encryptor: Callable[[Path], tuple[bytes, str]] = encrypt_file,
    ) -> None:
        self.client = client
        self.encryptor = encryptor

    def prepare(
        self,
        source: Path,
        *,
        institution: str,
        frequency: str,
        comments: str = "",
    ) -> PreparedStatementSubmission:
        source = Path(source).resolve()
        normalized_institution = institution.strip()
        normalized_comments = comments.strip()
        if not source.is_file():
            raise StatementSubmissionValidationError("Please select an existing statement file.")
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise StatementSubmissionValidationError("The selected statement file cannot be read.") from exc
        if size > MAX_STATEMENT_BYTES:
            raise StatementSubmissionValidationError("Attachments cannot exceed 25 MB.")
        if not normalized_institution:
            raise StatementSubmissionValidationError("Institution name is required.")
        if frequency not in STATEMENT_FREQUENCIES:
            raise StatementSubmissionValidationError("Select a valid statement frequency.")
        if len(normalized_comments) > 256:
            raise StatementSubmissionValidationError("Comments must be 256 characters or less.")

        return PreparedStatementSubmission(
            source=source,
            metadata={
                "file_name": source.name,
                "institution": normalized_institution,
                "frequency": frequency,
                "comments": normalized_comments,
            },
        )

    def submit(
        self,
        submission: PreparedStatementSubmission,
        *,
        credentials: tuple[str, str] | None,
        cancelled: Callable[[], bool],
        progress: Callable[[int, int], None],
        stage_changed: Callable[[str], None],
    ) -> None:
        try:
            if credentials is not None:
                stage_changed("Signing in...")
                self.client.auth.login(*credentials)
            self._raise_if_cancelled(cancelled)

            stage_changed("Encrypting statement in memory...")
            encrypted_file, encrypted_key = self.encryptor(submission.source)
            self._raise_if_cancelled(cancelled)

            stage_changed("Uploading encrypted statement...")
            response = self.client.submit_statement(
                encrypted_file,
                encrypted_key,
                submission.metadata,
                cancelled=cancelled,
                progress=progress,
            )
            try:
                payload = response.json()
                message = payload.get("message") if isinstance(payload, Mapping) else None
            finally:
                response.close()
            if message != "SUCCESS":
                raise StatementSubmissionRejectedError("The server did not confirm encrypted statement storage.")
        except (StatementSubmissionCancelled, StatementSubmissionError):
            raise
        except Exception as exc:
            raise StatementSubmissionError("The encrypted statement could not be submitted.") from exc

    @staticmethod
    def _raise_if_cancelled(cancelled: Callable[[], bool]) -> None:
        if cancelled():
            raise StatementSubmissionCancelled("Statement submission cancelled")
