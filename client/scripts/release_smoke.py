"""Verify that an activated artifact release is observable through the public API."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

MAX_METADATA_BYTES = 1024 * 1024


class ReleaseSmokeError(RuntimeError):
    """The public API does not expose the release that was just activated."""


def _read_bounded(response: Any, maximum_bytes: int) -> bytes:
    payload = response.read(maximum_bytes + 1)
    if len(payload) > maximum_bytes:
        raise ReleaseSmokeError("Public release metadata exceeded its size limit")
    return payload


def _request_bytes(
    url: str,
    *,
    maximum_bytes: int,
    headers: dict[str, str] | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ParseTrail-release-smoke/1", **(headers or {})},
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with opener(request, timeout=15) as response:
                return _read_bounded(response, maximum_bytes)
        except (OSError, urllib.error.URLError, ReleaseSmokeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(attempt + 1)
    raise ReleaseSmokeError(f"Public release request failed: {url}") from last_error


def _require_exact_remote_file(
    local_path: Path,
    url: str,
    *,
    maximum_bytes: int,
    opener: Callable[..., Any],
) -> None:
    local = local_path.read_bytes()
    remote = _request_bytes(
        url,
        maximum_bytes=maximum_bytes,
        opener=opener,
    )
    if remote != local:
        raise ReleaseSmokeError(f"Public bytes do not match {local_path.name}")


def smoke_release(
    *,
    release_dir: Path,
    release_kind: str,
    api_base_url: str,
    platform: str | None = None,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    """Compare local release evidence with public routes after activation."""
    release_dir = release_dir.expanduser().resolve()
    api_base_url = api_base_url.rstrip("/")
    if release_kind == "plugins":
        route = f"{api_base_url}/plugins"
        manifest_name = "plugin-manifest.json"
        signature_name = "plugin-manifest.sig"
    elif release_kind == "client" and platform in {"macos", "win64"}:
        route = f"{api_base_url}/clients/{platform}"
        manifest_name = "client-manifest.json"
        signature_name = "client-manifest.sig"
    else:
        raise ValueError("A client smoke test requires platform macos or win64")

    manifest_path = release_dir / manifest_name
    signature_path = release_dir / signature_name
    _require_exact_remote_file(
        manifest_path,
        f"{route}/manifest",
        maximum_bytes=MAX_METADATA_BYTES,
        opener=opener,
    )
    _require_exact_remote_file(
        signature_path,
        f"{route}/manifest-signature",
        maximum_bytes=64,
        opener=opener,
    )

    manifest = json.loads(manifest_path.read_bytes())
    if not isinstance(manifest, dict):
        raise ReleaseSmokeError("Local release manifest is not an object")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts or not all(isinstance(item, dict) for item in artifacts):
        raise ReleaseSmokeError("Local release manifest contains no artifacts")

    if release_kind == "plugins":
        listing = json.loads(
            _request_bytes(
                f"{route}/",
                maximum_bytes=MAX_METADATA_BYTES,
                opener=opener,
            )
        )
        expected_names = {artifact.get("plugin_name") for artifact in artifacts}
        if None in expected_names:
            raise ReleaseSmokeError("Local plugin manifest is missing a plugin name")
        if (
            not isinstance(listing, list)
            or not all(isinstance(item, dict) for item in listing)
            or {item.get("PLUGIN_NAME") for item in listing} != expected_names
        ):
            raise ReleaseSmokeError("Public plugin listing does not match the activated manifest")
        return

    if len(artifacts) != 1:
        raise ReleaseSmokeError("Client release manifest must contain exactly one installer")
    artifact = artifacts[0]
    filename = artifact.get("filename")
    version = artifact.get("version")
    if not isinstance(filename, str) or not isinstance(version, str):
        raise ReleaseSmokeError("Client release manifest is missing installer metadata")
    artifact_path = release_dir / filename
    with artifact_path.open("rb") as installer:
        expected_first_byte = installer.read(1)
    remote_first_byte = _request_bytes(
        f"{route}/{quote(version, safe='-._~+')}",
        maximum_bytes=1,
        headers={"Range": "bytes=0-0"},
        opener=opener,
    )
    if remote_first_byte != expected_first_byte:
        raise ReleaseSmokeError("Public installer range response does not match the activated artifact")
