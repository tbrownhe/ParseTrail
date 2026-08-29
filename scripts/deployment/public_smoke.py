#!/usr/bin/env python3
"""Authenticated public-route smoke checks for a completed deployment."""

from __future__ import annotations

import json
import mimetypes
import os
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 1024 * 1024


class SmokeFailure(RuntimeError):
    """A public smoke check did not meet its explicit contract."""


@dataclass(frozen=True)
class SmokeConfig:
    api_base_url: str
    dashboard_url: str
    website_url: str
    username: str
    password: str
    timeout_seconds: float = 15.0

    @classmethod
    def from_file(cls, path: Path) -> SmokeConfig:
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise SmokeFailure(f"Smoke credential file must have mode 600: {path}")
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SmokeFailure(f"Cannot read smoke configuration: {path}") from exc
        if set(raw) - {
            "api_base_url",
            "dashboard_url",
            "website_url",
            "username",
            "password",
            "timeout_seconds",
        }:
            raise SmokeFailure("Smoke configuration contains unknown fields")
        try:
            config = cls(**raw)
        except TypeError as exc:
            raise SmokeFailure("Smoke configuration is missing required fields") from exc
        for name in ("api_base_url", "dashboard_url", "website_url"):
            value = getattr(config, name)
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise SmokeFailure(f"{name} must be an absolute HTTP(S) URL")
        if not config.username or not config.password:
            raise SmokeFailure("Smoke credentials must not be empty")
        if not 1 <= config.timeout_seconds <= 60:
            raise SmokeFailure("timeout_seconds must be between 1 and 60")
        return config


def _bounded_read(response: Any, limit: int = MAX_RESPONSE_BYTES) -> bytes:
    data = response.read(limit + 1)
    if len(data) > limit:
        raise SmokeFailure("Public response exceeded the smoke-test read limit")
    return data


def _request(
    url: str,
    *,
    timeout: float,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: bytes | None = None,
    expected: set[int] = frozenset({200}),
    read_limit: int = MAX_RESPONSE_BYTES,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.status
            body = _bounded_read(response, read_limit)
            response_headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read(min(read_limit, 4096))
        response_headers = {key.lower(): value for key, value in exc.headers.items()}
    except (OSError, urllib.error.URLError) as exc:
        raise SmokeFailure(f"Request failed for {url}: {type(exc).__name__}") from exc
    if status not in expected:
        raise SmokeFailure(f"Unexpected HTTP {status} from {url}; expected {sorted(expected)}")
    return status, response_headers, body


def _join(base: str, suffix: str) -> str:
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def _multipart(fields: dict[str, str], file_bytes: bytes) -> tuple[str, bytes]:
    boundary = f"parsetrail-smoke-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode(),
                b"\r\n",
            ]
        )
    content_type = mimetypes.guess_type("smoke.pdf")[0] or "application/octet-stream"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="file"; filename="smoke.pdf"\r\n',
            f"Content-Type: {content_type}\r\n\r\n".encode(),
            file_bytes,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return f"multipart/form-data; boundary={boundary}", b"".join(chunks)


def run_public_smoke(config: SmokeConfig) -> list[dict[str, Any]]:
    """Run bounded public checks, returning non-secret evidence for a release record."""
    results: list[dict[str, Any]] = []

    def check(name: str, operation: Any) -> Any:
        started = time.monotonic()
        value = operation()
        results.append(
            {
                "name": name,
                "status": "passed",
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        )
        return value

    timeout = config.timeout_seconds
    api = config.api_base_url.rstrip("/")

    def health() -> None:
        _, _, body = _request(_join(api, "utils/health-check/"), timeout=timeout)
        if body.strip() != b"true":
            raise SmokeFailure("Health endpoint did not return true")

    check("backend-health", health)

    def page(url: str, marker: bytes) -> None:
        _, _, body = _request(url, timeout=timeout)
        if marker.lower() not in body.lower():
            raise SmokeFailure(f"Expected page marker missing from {url}")

    check("dashboard", lambda: page(config.dashboard_url, b'<div id="root">'))
    check("website", lambda: page(config.website_url, b"ParseTrail"))

    def login() -> str:
        form = urllib.parse.urlencode({"username": config.username, "password": config.password}).encode()
        _, _, body = _request(
            _join(api, "login/access-token"),
            timeout=timeout,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data=form,
        )
        try:
            token = json.loads(body)["access_token"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SmokeFailure("Login response did not contain an access token") from exc
        if not isinstance(token, str) or not token:
            raise SmokeFailure("Login returned an invalid access token")
        return token

    token = check("login", login)
    auth = {"Authorization": f"Bearer {token}"}

    def plugins() -> None:
        _, _, manifest_bytes = _request(_join(api, "plugins/manifest"), timeout=timeout)
        _, _, signature = _request(_join(api, "plugins/manifest-signature"), timeout=timeout)
        if len(signature) != 64:
            raise SmokeFailure("Plugin manifest signature is not 64 bytes")
        try:
            manifest = json.loads(manifest_bytes)
            filename = manifest["artifacts"][0]["filename"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SmokeFailure("Plugin manifest has no downloadable artifact") from exc
        _request(
            _join(api, f"plugins/{urllib.parse.quote(filename)}"),
            timeout=timeout,
            headers={**auth, "Range": "bytes=0-0"},
            expected={206},
            read_limit=1,
        )

    check("signed-plugin-catalog-and-range-download", plugins)

    def clients() -> None:
        _, _, listing_bytes = _request(_join(api, "clients/"), timeout=timeout)
        try:
            listing = json.loads(listing_bytes)
            platform = listing[0]["platform"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SmokeFailure("Client listing has no installer") from exc
        _request(_join(api, f"clients/{platform}/manifest"), timeout=timeout)
        _, _, signature = _request(_join(api, f"clients/{platform}/manifest-signature"), timeout=timeout)
        if len(signature) != 64:
            raise SmokeFailure("Client manifest signature is not 64 bytes")
        _request(
            _join(api, f"clients/{platform}/latest"),
            timeout=timeout,
            headers={"Range": "bytes=0-0"},
            expected={206},
            read_limit=1,
        )

    check("signed-client-catalog-and-range-download", clients)

    def rejected_submission() -> None:
        metadata = json.dumps(
            {
                "file_name": "smoke.pdf",
                "institution": "Deployment Smoke Test",
                "frequency": "Other",
                "comments": "Expected invalid-envelope probe",
            },
            separators=(",", ":"),
        )
        content_type, body = _multipart(
            {"metadata": metadata, "encrypted_key": "invalid-smoke-envelope"},
            b"invalid-smoke-ciphertext",
        )
        _, _, response = _request(
            _join(api, "statements/submit-statement"),
            timeout=timeout,
            method="POST",
            headers={**auth, "Content-Type": content_type},
            data=body,
            expected={400},
        )
        try:
            detail = json.loads(response)["detail"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise SmokeFailure("Statement rejection was not a structured API error") from exc
        if detail != "Invalid encrypted key":
            raise SmokeFailure("Statement route returned an unexpected rejection")

    check("authenticated-statement-rejection-no-write", rejected_submission)
    return results


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    results = run_public_smoke(SmokeConfig.from_file(args.config))
    print(json.dumps({"status": "passed", "checks": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
