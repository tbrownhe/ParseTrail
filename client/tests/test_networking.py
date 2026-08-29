from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from parsetrail.core import auth as auth_module
from parsetrail.core.api import ApiClient, StatementSubmissionCancelled
from parsetrail.core.auth import AuthError, AuthManager
from parsetrail.core.network import (
    HttpTransport,
    NetworkTimeoutError,
    NetworkUnavailableError,
    RemoteServiceError,
)

RequestHandler = Callable[[BaseHTTPRequestHandler, str], None]


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        del request, client_address


@contextmanager
def _server(handler: RequestHandler) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            handler(self, "GET")

        def do_POST(self) -> None:
            handler(self, "POST")

        def log_message(self, format, *args) -> None:
            del format, args

    server = _QuietServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _FakeAuth:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.clear_count = 0

    def get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer rejected-token"}

    def clear_token(self) -> None:
        self.clear_count += 1


class _MemoryTokenStore:
    def __init__(self) -> None:
        self.token: str | None = None

    def get_token(self) -> str | None:
        return self.token

    def set_token(self, token: str) -> bool:
        self.token = token
        return True

    def delete_token(self) -> None:
        self.token = None


class _BodyConsumingTransport(HttpTransport):
    """Consume a request body synchronously without involving socket scheduling."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.chunks: list[bytes] = []

    def request(self, method: str, url: str, **kwargs):
        self.requests.append((method, url))
        for chunk in kwargs["data"]:
            self.chunks.append(chunk)
        raise AssertionError("cancelled multipart body completed without raising")


def _api(base_url: str, transport: HttpTransport) -> tuple[ApiClient, _FakeAuth]:
    auth = _FakeAuth(base_url)
    client = ApiClient(
        SimpleNamespace(server_url=base_url),
        auth,
        transport=transport,
    )
    return client, auth


def _reply(request: BaseHTTPRequestHandler, status: int, payload: bytes = b"") -> None:
    request.send_response(status)
    request.send_header("Content-Length", str(len(payload)))
    request.end_headers()
    if payload:
        request.wfile.write(payload)


def test_retries_idempotent_get_but_never_post() -> None:
    counts = {"GET": 0, "POST": 0}

    def handler(request: BaseHTTPRequestHandler, method: str) -> None:
        counts[method] += 1
        if method == "GET" and counts[method] == 3:
            _reply(request, 200, b"ok")
        else:
            _reply(request, 503, b"do not expose this body")

    with _server(handler) as base_url:
        client, _ = _api(base_url, HttpTransport(retries=2))
        assert client.get("/retry", auth_required=False).content == b"ok"
        with pytest.raises(RemoteServiceError, match="HTTP 503"):
            client.post("/no-retry", auth_required=False)

    assert counts == {"GET": 3, "POST": 1}


def test_connect_and_read_deadlines_are_translated() -> None:
    def handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        time.sleep(0.15)
        try:
            _reply(request, 200, b"late")
        except (BrokenPipeError, ConnectionResetError):
            pass

    with _server(handler) as base_url:
        client, _ = _api(
            base_url,
            HttpTransport(timeout=(0.05, 0.05), retries=0),
        )
        with pytest.raises(NetworkTimeoutError, match="timed out"):
            client.get("/slow", auth_required=False)


def test_slow_stream_timeout_and_disconnect_are_translated() -> None:
    def slow_handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        request.send_response(200)
        request.send_header("Content-Length", "2")
        request.end_headers()
        request.wfile.write(b"a")
        request.wfile.flush()
        time.sleep(0.15)
        try:
            request.wfile.write(b"b")
        except (BrokenPipeError, ConnectionResetError):
            pass

    with _server(slow_handler) as base_url:
        client, _ = _api(
            base_url,
            HttpTransport(timeout=(0.05, 0.05), retries=0),
        )
        with pytest.raises(NetworkTimeoutError, match="timed out"):
            list(client._download_stream("/slow-stream", auth_required=False, chunk_size=1))

    def disconnect_handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        request.send_response(200)
        request.send_header("Content-Length", "20")
        request.end_headers()
        request.wfile.write(b"partial")
        request.wfile.flush()
        request.connection.shutdown(socket.SHUT_RDWR)
        request.connection.close()

    with _server(disconnect_handler) as base_url:
        client, _ = _api(base_url, HttpTransport(retries=0))
        with pytest.raises(NetworkUnavailableError, match="connection failed"):
            list(client._download_stream("/disconnect", auth_required=False))


def test_error_body_is_redacted_and_401_clears_saved_login() -> None:
    secret = "private statement filename.pdf"

    def handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        status = 401 if request.path == "/auth" else 500
        _reply(request, status, f'{{"detail":"{secret}"}}'.encode())

    with _server(handler) as base_url:
        client, auth = _api(base_url, HttpTransport(retries=0))
        with pytest.raises(RemoteServiceError) as service_error:
            client.get("/error", auth_required=False)
        assert secret not in str(service_error.value)

        with pytest.raises(AuthError) as auth_error:
            client.get("/auth", auth_required=True)
        assert auth.clear_count == 1
        assert secret not in str(auth_error.value)


def test_login_uses_bounded_transport_and_persists_only_in_token_store(monkeypatch) -> None:
    received: dict[str, bytes] = {}

    def handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        length = int(request.headers["Content-Length"])
        received["body"] = request.rfile.read(length)
        _reply(request, 200, b'{"access_token":"server-token","token_type":"bearer"}')

    with _server(handler) as base_url:
        app_settings = SimpleNamespace(
            server_url=base_url,
            access_token="",
            token_expires_at=0,
            email="",
        )
        store = _MemoryTokenStore()
        monkeypatch.setattr(auth_module, "save_settings", lambda _settings: None)
        monkeypatch.setattr(auth_module, "retire_legacy_credential_key", lambda: None)
        manager = AuthManager(
            app_settings,
            transport=HttpTransport(retries=0),
            token_store=store,
        )

        manager.login("user@example.com", "password")

    assert b"username=user%40example.com" in received["body"]
    assert store.token == "server-token"
    assert app_settings.access_token == ""
    assert manager.get_auth_headers() == {"Authorization": "Bearer server-token"}


def test_rejected_login_does_not_expose_server_body(monkeypatch) -> None:
    secret = "account-specific private detail"

    def handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        _reply(request, 401, secret.encode())

    with _server(handler) as base_url:
        app_settings = SimpleNamespace(
            server_url=base_url,
            access_token="",
            token_expires_at=0,
            email="",
        )
        monkeypatch.setattr(auth_module, "retire_legacy_credential_key", lambda: None)
        manager = AuthManager(
            app_settings,
            transport=HttpTransport(retries=0),
            token_store=_MemoryTokenStore(),
        )

        with pytest.raises(AuthError) as error:
            manager.login("user@example.com", "wrong-password")

    assert secret not in str(error.value)


def test_statement_upload_is_length_known_and_reports_true_progress() -> None:
    captured: dict[str, object] = {}

    def handler(request: BaseHTTPRequestHandler, _method: str) -> None:
        length = int(request.headers["Content-Length"])
        captured["content_type"] = request.headers["Content-Type"]
        captured["transfer_encoding"] = request.headers.get("Transfer-Encoding")
        captured["body"] = request.rfile.read(length)
        _reply(request, 200, b'{"message":"SUCCESS"}')

    with _server(handler) as base_url:
        client, _ = _api(base_url, HttpTransport(retries=0))
        updates: list[tuple[int, int]] = []
        response = client.submit_statement(
            b"encrypted-statement",
            "encrypted-key",
            {"institution": "Example Bank"},
            progress=lambda sent, total: updates.append((sent, total)),
        )
        response.close()

    body = captured["body"]
    assert isinstance(body, bytes)
    assert b"encrypted-statement" in body
    assert b'name="metadata"' in body
    assert b"Example Bank" in body
    assert captured["transfer_encoding"] is None
    assert str(captured["content_type"]).startswith("multipart/form-data; boundary=ParseTrail-")
    assert updates[0][0] == 0
    assert updates[-1] == (len(body), len(body))


def test_statement_upload_can_cancel_before_sending_body() -> None:
    transport = _BodyConsumingTransport()
    client, _ = _api("https://example.invalid", transport)
    updates: list[tuple[int, int]] = []

    with pytest.raises(StatementSubmissionCancelled, match="cancelled"):
        client.submit_statement(
            b"encrypted-statement",
            "encrypted-key",
            {"institution": "Example Bank"},
            cancelled=lambda: True,
            progress=lambda sent, total: updates.append((sent, total)),
        )

    assert transport.requests == [
        ("POST", "https://example.invalid/statements/submit-statement")
    ]
    assert transport.chunks == []
    assert len(updates) == 1
    assert updates[0][0] == 0
    assert updates[0][1] > 0
