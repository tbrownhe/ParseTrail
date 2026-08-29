import asyncio
import json
from collections.abc import Generator
from typing import cast

import pytest
from app.core.request_limits import RequestBodyLimitMiddleware
from app.core.statement_submission import StatementSubmissionMetadata, bounded_log_value
from pydantic import ValidationError
from starlette.types import Message, Receive, Scope, Send


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Request-boundary unit tests do not use database integration."""
    yield


def _run_request(
    *,
    chunks: list[bytes],
    maximum_bytes: int,
    content_length: str | None = None,
) -> tuple[list[Message], bool]:
    called = False

    async def app(_scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal called
        called = True
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    messages: list[Message] = [
        {
            "type": "http.request",
            "body": chunk,
            "more_body": index < len(chunks) - 1,
        }
        for index, chunk in enumerate(chunks)
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return messages.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    headers = [] if content_length is None else [(b"content-length", content_length.encode())]
    middleware = RequestBodyLimitMiddleware(app, maximum_bytes=maximum_bytes)
    asyncio.run(
        middleware(
            cast(Scope, {"type": "http", "method": "POST", "path": "/upload", "headers": headers}),
            receive,
            send,
        )
    )
    return sent, called


def test_rejects_advertised_oversized_body_before_app_or_multipart_parser() -> None:
    sent, called = _run_request(chunks=[], maximum_bytes=10, content_length="11")

    assert called is False
    assert sent[0]["status"] == 413


def test_rejects_chunked_body_when_cumulative_size_exceeds_limit() -> None:
    sent, called = _run_request(chunks=[b"12345", b"678901"], maximum_bytes=10)

    assert called is True
    assert sent[0]["status"] == 413


def test_allows_body_at_exact_limit() -> None:
    sent, called = _run_request(chunks=[b"12345", b"67890"], maximum_bytes=10)

    assert called is True
    assert sent[0]["status"] == 204


def test_statement_metadata_is_strict_and_canonically_serializable() -> None:
    metadata = StatementSubmissionMetadata.model_validate_json(
        json.dumps(
            {
                "file_name": "statement.pdf",
                "institution": " Example Bank ",
                "frequency": "Monthly",
                "comments": "parser failed",
            }
        )
    )

    assert metadata.institution == "Example Bank"
    assert json.loads(metadata.model_dump_json())["file_name"] == "statement.pdf"


@pytest.mark.parametrize(
    "payload",
    [
        {"file_name": "../statement.pdf", "institution": "Bank", "frequency": "Monthly"},
        {"file_name": "statement.pdf", "institution": "", "frequency": "Monthly"},
        {"file_name": "statement.pdf", "institution": "Bank", "frequency": "Sometimes"},
        {
            "file_name": "statement.pdf",
            "institution": "Bank",
            "frequency": "Monthly",
            "unexpected": "field",
        },
    ],
)
def test_statement_metadata_rejects_invalid_or_extra_fields(payload: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        StatementSubmissionMetadata.model_validate(payload)


def test_log_values_are_single_line_and_bounded() -> None:
    assert bounded_log_value("agent\r\nprivate", 8) == "agent  p"
