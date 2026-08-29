from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from public_smoke import SmokeConfig, run_public_smoke


class _SmokeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    visited: list[str] = []

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self.visited.append(self.path)
        if self.path == "/api/v1/utils/health-check/":
            self._reply(200, b"true")
        elif self.path == "/dashboard":
            self._reply(200, b'<html><div id="root"></div></html>', "text/html")
        elif self.path == "/website":
            self._reply(200, b"<html>ParseTrail</html>", "text/html")
        elif self.path == "/api/v1/plugins/manifest":
            self._reply(200, json.dumps({"artifacts": [{"filename": "test.pyc"}]}).encode())
        elif self.path == "/api/v1/plugins/manifest-signature":
            self._reply(200, b"s" * 64, "application/octet-stream")
        elif self.path == "/api/v1/plugins/test.pyc":
            self.assert_header("Authorization", "Bearer smoke-token")
            self.assert_header("Range", "bytes=0-0")
            self._reply(206, b"p", "application/octet-stream")
        elif self.path == "/api/v1/clients/":
            self._reply(200, json.dumps([{"platform": "win64"}]).encode())
        elif self.path == "/api/v1/clients/win64/manifest":
            self._reply(200, b"{}")
        elif self.path == "/api/v1/clients/win64/manifest-signature":
            self._reply(200, b"c" * 64, "application/octet-stream")
        elif self.path == "/api/v1/clients/win64/latest":
            self.assert_header("Range", "bytes=0-0")
            self._reply(206, b"i", "application/octet-stream")
        else:
            self._reply(404, b"{}")

    def do_POST(self) -> None:  # noqa: N802
        self.visited.append(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        if self.path == "/api/v1/login/access-token":
            if b"username=smoke%40example.com" not in body or b"password=smoke-password" not in body:
                raise AssertionError("Login form did not contain the smoke credentials")
            self._reply(200, b'{"access_token":"smoke-token","token_type":"bearer"}')
        elif self.path == "/api/v1/statements/submit-statement":
            self.assert_header("Authorization", "Bearer smoke-token")
            if b"invalid-smoke-envelope" not in body:
                raise AssertionError("Statement probe did not contain its invalid envelope")
            self._reply(400, b'{"detail":"Invalid encrypted key"}')
        else:
            self._reply(404, b"{}")

    def assert_header(self, name: str, expected: str) -> None:
        actual = self.headers.get(name)
        if actual != expected:
            raise AssertionError(f"{name} was {actual!r}, expected {expected!r}")


class PublicSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        _SmokeHandler.visited = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _SmokeHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def test_complete_public_smoke_contract(self) -> None:
        root = f"http://127.0.0.1:{self.server.server_port}"
        config = SmokeConfig(
            api_base_url=f"{root}/api/v1",
            dashboard_url=f"{root}/dashboard",
            website_url=f"{root}/website",
            username="smoke@example.com",
            password="smoke-password",
            timeout_seconds=5,
        )

        results = run_public_smoke(config)

        self.assertEqual(len(results), 7)
        self.assertTrue(all(result["status"] == "passed" for result in results))
        self.assertIn("/api/v1/plugins/test.pyc", _SmokeHandler.visited)
        self.assertIn("/api/v1/clients/win64/latest", _SmokeHandler.visited)
        self.assertIn("/api/v1/statements/submit-statement", _SmokeHandler.visited)


if __name__ == "__main__":
    unittest.main()
