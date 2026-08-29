from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from parsetrail.core.api import ApiClient
from parsetrail.core.auth import AuthError
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
