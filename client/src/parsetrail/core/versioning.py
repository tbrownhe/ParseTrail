"""Strict semantic-version validation shared by release metadata."""

from __future__ import annotations

import re

SEMVER_PATTERN = re.compile(
    r"^(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)\."
    r"(0|[1-9][0-9]*)"
    r"(?:-(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def validate_semver(value: str) -> str:
    """Return a normalized strict SemVer string or raise ``ValueError``."""
    normalized = value.strip()
    if normalized != value or not SEMVER_PATTERN.fullmatch(normalized):
        raise ValueError("must be a valid semantic version")
    return normalized
