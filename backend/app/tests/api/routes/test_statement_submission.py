import asyncio
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException, Request, UploadFile

from app.api.routes import statements
from app.models import User


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Handler failure injection uses an isolated fake engine."""
    yield


class _Connection:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.parameters: list[dict[str, Any]] = []

    def execute(self, _query: object, parameters: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("injected database failure with private metadata")
        self.parameters.append(parameters)


class _Engine:
    def __init__(self, *, fail_registration: bool = False) -> None:
        self.connection = _Connection(fail=fail_registration)
        self.begin_count = 0

    @contextmanager
    def connect(self) -> Generator[_Connection, None, None]:
        yield self.connection

    @contextmanager
    def begin(self) -> Generator[_Connection, None, None]:
        self.begin_count += 1
        yield self.connection


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "https",
            "path": "/api/v1/statements/submit-statement",
            "raw_path": b"/api/v1/statements/submit-statement",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"user-agent", b"test-agent")],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 443),
        }
    )


def _user() -> User:
    return User(
        id=uuid.uuid4(),
        email="submitter@example.com",
        hashed_password="not-used",
    )


def _metadata() -> str:
    return json.dumps(
        {
            "file_name": "statement.pdf",
            "institution": "Example Bank",
            "frequency": "Monthly",
            "comments": "parser failed",
        }
    )


def _upload() -> UploadFile:
    return UploadFile(file=BytesIO(b"client ciphertext"), filename="ignored-name.pdf")


def _install_crypto_fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(statements, "decrypt_client_key", lambda _encrypted: b"symmetric-key")
    monkeypatch.setattr(statements, "decrypt_client_data", lambda _key, _data: b"plaintext-in-memory")
    monkeypatch.setattr(
        statements,
        "aes_encrypt_data",
        lambda _data: (b"i" * 16, b"server ciphertext", b"t" * 16),
    )
    monkeypatch.setattr(statements, "enforce_statement_quota", lambda *_args, **_kwargs: None)


def _submit() -> dict[str, str]:
    return asyncio.run(
        statements.upload_statement(
            file=_upload(),
            request=_request(),
            metadata=_metadata(),
            encrypted_key=b"ZW5jcnlwdGVkLWtleQ==",
            current_user=_user(),
        )
    )


def test_success_publishes_one_ciphertext_and_registers_canonical_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    _install_crypto_fakes(monkeypatch)
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path)
    monkeypatch.setattr(statements, "engine", engine)

    assert _submit() == {"message": "SUCCESS"}

    stored_files = list(tmp_path.glob("*.enc"))
    assert len(stored_files) == 1
    assert stored_files[0].read_bytes() == b"server ciphertext"
    assert not list(tmp_path.glob("*.tmp"))
    registered_metadata = json.loads(engine.connection.parameters[-1]["metadata"])
    assert registered_metadata["file_name"] == "statement.pdf"
    assert engine.connection.parameters[-1]["plugin_status"] == "pending"


def test_database_failure_after_file_creation_removes_ciphertext(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_crypto_fakes(monkeypatch)
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path)
    monkeypatch.setattr(statements, "engine", _Engine(fail_registration=True))

    with pytest.raises(HTTPException) as failure:
        _submit()

    assert failure.value.status_code == 500
    assert failure.value.detail == "Statement registration failed"
    assert not list(tmp_path.iterdir())


def test_filesystem_failure_never_starts_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    _install_crypto_fakes(monkeypatch)
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path / "missing-directory")
    monkeypatch.setattr(statements, "engine", engine)

    with pytest.raises(HTTPException) as failure:
        _submit()

    assert failure.value.status_code == 500
    assert failure.value.detail == "Statement storage failed"
    assert engine.begin_count == 0


def test_malformed_encrypted_key_is_rejected_before_file_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path)
    monkeypatch.setattr(statements, "engine", engine)
    monkeypatch.setattr(statements, "enforce_statement_quota", lambda *_args, **_kwargs: None)

    with pytest.raises(HTTPException) as failure:
        asyncio.run(
            statements.upload_statement(
                file=_upload(),
                request=_request(),
                metadata=_metadata(),
                encrypted_key=b"not-valid-base64***",
                current_user=_user(),
            )
        )

    assert failure.value.status_code == 400
    assert failure.value.detail == "Invalid encrypted key"
    assert not list(tmp_path.iterdir())
    assert engine.begin_count == 0


def test_corrupted_client_ciphertext_is_rejected_without_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = _Engine()
    monkeypatch.setattr(statements, "STATEMENTS_DIR", tmp_path)
    monkeypatch.setattr(statements, "engine", engine)
    monkeypatch.setattr(statements, "enforce_statement_quota", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(statements, "decrypt_client_key", lambda _encrypted: b"symmetric-key")
    monkeypatch.setattr(
        statements,
        "decrypt_client_data",
        lambda _key, _data: (_ for _ in ()).throw(ValueError("corrupt authentication tag")),
    )

    with pytest.raises(HTTPException) as failure:
        _submit()

    assert failure.value.status_code == 400
    assert failure.value.detail == "Invalid encrypted statement"
    assert not list(tmp_path.iterdir())
    assert engine.begin_count == 0
