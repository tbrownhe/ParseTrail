"""Read immutable source metadata embedded by the release builder."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from parsetrail.core.utils import resource_path
from parsetrail.core.versioning import validate_semver

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
BUILD_METADATA_PATH = "parsetrail/build-metadata.json"


@dataclass(frozen=True)
class BuildMetadata:
    client_version: str
    source_commit: str
    source_tag: str
    target_platform: str
    built_at: str


def read_build_metadata() -> BuildMetadata | None:
    path = resource_path(BUILD_METADATA_PATH)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError
        client_version = validate_semver(payload["client_version"])
        source_commit = payload["source_commit"]
        source_tag = payload["source_tag"]
        target_platform = payload["target_platform"]
        built_at = payload["built_at"]
        if not isinstance(source_commit, str) or not COMMIT_PATTERN.fullmatch(source_commit):
            raise ValueError
        if source_tag != f"client-v{client_version}":
            raise ValueError
        if target_platform not in {"macos", "win64"}:
            raise ValueError
        if not isinstance(built_at, str) or not built_at:
            raise ValueError
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return BuildMetadata(
        client_version=client_version,
        source_commit=source_commit,
        source_tag=source_tag,
        target_platform=target_platform,
        built_at=built_at,
    )


def build_provenance_label() -> str:
    metadata = read_build_metadata()
    if metadata is None:
        return "development source"
    return f"{metadata.source_tag} ({metadata.source_commit[:12]})"
