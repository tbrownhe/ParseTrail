"""Validate and record the immutable source state for a desktop release."""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from parsetrail.core.versioning import validate_semver

CLIENT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = CLIENT_ROOT.parent
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class ReleaseSourceError(RuntimeError):
    """The checked-out source is not suitable for a release build."""


@dataclass(frozen=True)
class ReleaseSource:
    source_commit: str
    source_tag: str


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-c", f"safe.directory={repository.as_posix()}", *arguments],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise ReleaseSourceError(f"git {' '.join(arguments)} failed with exit code {completed.returncode}")
    return completed.stdout.strip()


def validate_release_source(
    *,
    repository: Path = REPOSITORY_ROOT,
    expected_tag: str,
) -> ReleaseSource:
    """Require an exact tag at a clean, non-detached source commit."""
    repository = repository.resolve()
    dirty = _git(repository, "status", "--porcelain=v1", "--untracked-files=all")
    if dirty:
        raise ReleaseSourceError("Release builds require a clean Git worktree")

    commit = _git(repository, "rev-parse", "HEAD").lower()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ReleaseSourceError("Git did not return a full source commit")
    tags = set(_git(repository, "tag", "--points-at", "HEAD").splitlines())
    if expected_tag not in tags:
        found = ", ".join(sorted(tags)) if tags else "none"
        raise ReleaseSourceError(f"Release tag {expected_tag!r} must point at HEAD (found: {found})")
    return ReleaseSource(source_commit=commit, source_tag=expected_tag)


def validate_client_release(
    version: str,
    *,
    repository: Path = REPOSITORY_ROOT,
) -> ReleaseSource:
    version = validate_semver(version)
    return validate_release_source(
        repository=repository,
        expected_tag=f"client-v{version}",
    )


def write_build_metadata(
    output: Path,
    *,
    source: ReleaseSource,
    version: str,
    target_platform: str,
) -> None:
    payload = {
        "schema_version": 1,
        "client_version": validate_semver(version),
        **asdict(source),
        "target_platform": target_platform,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "python_compiler": platform.python_compiler(),
    }
    output = output.expanduser().resolve()
    if not output.parent.is_dir():
        raise ReleaseSourceError(f"Build-metadata parent directory does not exist: {output.parent}")
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    client = subparsers.add_parser("client")
    client.add_argument("--version", required=True)
    client.add_argument("--platform", choices=("macos", "win64"), required=True)
    client.add_argument("--metadata-output", type=Path, required=True)

    plugins = subparsers.add_parser("plugins")
    plugins.add_argument("--tag", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "client":
            source = validate_client_release(args.version)
            write_build_metadata(
                args.metadata_output,
                source=source,
                version=args.version,
                target_platform=args.platform,
            )
        else:
            source = validate_release_source(expected_tag=args.tag)
        print(json.dumps(asdict(source), sort_keys=True))
    except (OSError, ValueError, ReleaseSourceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
