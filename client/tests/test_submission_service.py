from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core.api import StatementSubmissionCancelled
from parsetrail.core.submission import (
    MAX_STATEMENT_BYTES,
    StatementSubmissionError,
    StatementSubmissionRejectedError,
    StatementSubmissionService,
    StatementSubmissionValidationError,
)


class _Response:
    def __init__(self, payload: object):
        self.payload = payload
        self.closed = False

    def json(self) -> object:
        return self.payload

    def close(self) -> None:
        self.closed = True


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.logins = []
        self.submissions = []
        self.auth = SimpleNamespace(login=lambda email, password: self.logins.append((email, password)))

    def submit_statement(self, encrypted_file, encrypted_key, metadata, **callbacks):
        self.submissions.append((encrypted_file, encrypted_key, metadata, callbacks))
        return self.response


def test_submission_service_module_is_headless() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by submission service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.submission
print("headless submission service ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "headless submission service ok" in result.stdout


def test_prepare_validates_and_excludes_the_local_path_from_metadata(tmp_path: Path) -> None:
    statement = tmp_path / "private-name.pdf"
    statement.write_bytes(b"statement")
    service = StatementSubmissionService()

    prepared = service.prepare(
        statement,
        institution=" Example Bank ",
        frequency="Monthly",
        comments=" Parser changed ",
    )

    assert prepared.source == statement.resolve()
    assert prepared.metadata == {
        "file_name": "private-name.pdf",
        "institution": "Example Bank",
        "frequency": "Monthly",
        "comments": "Parser changed",
    }
    assert "file_path" not in prepared.metadata

    with pytest.raises(StatementSubmissionValidationError, match="existing"):
        service.prepare(tmp_path / "missing.pdf", institution="Bank", frequency="Monthly")
    with pytest.raises(StatementSubmissionValidationError, match="Institution"):
        service.prepare(statement, institution=" ", frequency="Monthly")
    with pytest.raises(StatementSubmissionValidationError, match="frequency"):
        service.prepare(statement, institution="Bank", frequency="Sometimes")
    with pytest.raises(StatementSubmissionValidationError, match="256"):
        service.prepare(statement, institution="Bank", frequency="Monthly", comments="x" * 257)


def test_prepare_rejects_files_over_25_mib(tmp_path: Path) -> None:
    statement = tmp_path / "large.pdf"
    with statement.open("wb") as output:
        output.truncate(MAX_STATEMENT_BYTES + 1)

    with pytest.raises(StatementSubmissionValidationError, match="25 MB"):
        StatementSubmissionService().prepare(statement, institution="Bank", frequency="Monthly")


def test_submit_logs_in_encrypts_in_memory_uploads_and_closes_response(tmp_path: Path) -> None:
    statement = tmp_path / "statement.pdf"
    statement.write_bytes(b"plaintext")
    response = _Response({"message": "SUCCESS"})
    client = _Client(response)
    encrypted_sources = []
    stages = []
    progress = []
    service = StatementSubmissionService(
        client=client,
        encryptor=lambda source: encrypted_sources.append(source) or (b"encrypted-blob", "encrypted-key"),
    )
    prepared = service.prepare(statement, institution="Bank", frequency="Monthly")

    service.submit(
        prepared,
        credentials=("person@example.com", "password"),
        cancelled=lambda: False,
        progress=lambda sent, total: progress.append((sent, total)),
        stage_changed=stages.append,
    )

    assert client.logins == [("person@example.com", "password")]
    assert encrypted_sources == [statement.resolve()]
    assert stages == ["Signing in...", "Encrypting statement in memory...", "Uploading encrypted statement..."]
    encrypted_file, encrypted_key, metadata, callbacks = client.submissions[0]
    assert (encrypted_file, encrypted_key) == (b"encrypted-blob", "encrypted-key")
    assert metadata == prepared.metadata
    assert callbacks["progress"] is not None
    assert callbacks["cancelled"] is not None
    assert response.closed is True


def test_submit_cancellation_never_uploads(tmp_path: Path) -> None:
    statement = tmp_path / "statement.pdf"
    statement.write_bytes(b"plaintext")
    client = _Client(_Response({"message": "SUCCESS"}))
    encrypted = []
    service = StatementSubmissionService(
        client=client,
        encryptor=lambda source: encrypted.append(source) or (b"encrypted", "key"),
    )
    prepared = service.prepare(statement, institution="Bank", frequency="Monthly")

    with pytest.raises(StatementSubmissionCancelled):
        service.submit(
            prepared,
            credentials=None,
            cancelled=lambda: True,
            progress=lambda *_args: None,
            stage_changed=lambda _stage: None,
        )

    assert encrypted == []
    assert client.submissions == []


def test_submit_requires_server_confirmation_and_retains_diagnostic_chain(tmp_path: Path) -> None:
    statement = tmp_path / "statement.pdf"
    statement.write_bytes(b"plaintext")
    response = _Response({"message": "NOT_STORED"})
    client = _Client(response)
    prepared = StatementSubmissionService().prepare(statement, institution="Bank", frequency="Monthly")
    service = StatementSubmissionService(client=client, encryptor=lambda _source: (b"encrypted", "key"))

    with pytest.raises(StatementSubmissionRejectedError, match="did not confirm"):
        service.submit(
            prepared,
            credentials=None,
            cancelled=lambda: False,
            progress=lambda *_args: None,
            stage_changed=lambda _stage: None,
        )
    assert response.closed is True

    failure = RuntimeError("injected encryption failure")
    broken = StatementSubmissionService(
        client=client,
        encryptor=lambda _source: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(StatementSubmissionError, match="could not be submitted") as caught:
        broken.submit(
            prepared,
            credentials=None,
            cancelled=lambda: False,
            progress=lambda *_args: None,
            stage_changed=lambda _stage: None,
        )
    assert caught.value.__cause__ is failure
