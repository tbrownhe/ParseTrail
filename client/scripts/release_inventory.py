"""Create a checksummed, machine-readable record for one artifact release."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from parsetrail.core.versioning import validate_semver

INVENTORY_FILENAME = "release-inventory.json"
PACKAGER_COMMANDS = {
    "none": None,
    "nsis": ("makensis.exe", "/VERSION"),
    "create-dmg": ("create-dmg", "--version"),
}
SHA256_HEX = frozenset("0123456789abcdef")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_version(
    command: tuple[str, ...],
    *,
    executable: Path | None = None,
) -> str:
    resolved_executable: str | Path | None = executable
    if resolved_executable is None:
        resolved_executable = shutil.which(command[0])
    elif not resolved_executable.expanduser().is_file():
        raise RuntimeError(f"Required release tool was not found: {resolved_executable}")
    if resolved_executable is None:
        raise RuntimeError(f"Required release tool was not found: {command[0]}")
    completed = subprocess.run(
        [str(resolved_executable), *command[1:]],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(f"Could not determine {command[0]} version (exit {completed.returncode})")
    return (completed.stdout or completed.stderr).strip()


def _artifact_records(release_dir: Path, manifest: dict[str, object]) -> list[dict[str, object]]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("Release manifest has no artifacts")
    names = ["plugin-manifest.json", "plugin-manifest.sig"]
    if (release_dir / "client-manifest.json").is_file():
        names = ["client-manifest.json", "client-manifest.sig"]
    expected: dict[str, tuple[int, str]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict) or not isinstance(artifact.get("filename"), str):
            raise ValueError("Release manifest contains invalid artifact metadata")
        filename = artifact["filename"]
        size = artifact.get("size")
        sha256 = artifact.get("sha256")
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(sha256, str)
            or len(sha256) != 64
            or any(character not in SHA256_HEX for character in sha256)
            or filename in expected
        ):
            raise ValueError("Release manifest contains invalid artifact metadata")
        names.append(filename)
        expected[filename] = (size, sha256)

    records = []
    for name in sorted(names):
        if Path(name).name != name:
            raise ValueError("Release filenames must be plain filenames")
        path = release_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Release file is missing: {path}")
        size = path.stat().st_size
        sha256 = _sha256_file(path)
        if name in expected and expected[name] != (size, sha256):
            raise ValueError(f"Release artifact does not match its signed manifest: {name}")
        records.append({"filename": name, "size": size, "sha256": sha256})
    return records


def create_inventory(
    *,
    release_dir: Path,
    source_commit: str,
    source_tag: str,
    release_kind: str,
    target_platform: str,
    version: str | None,
    packager: str,
    packager_executable: Path | None = None,
) -> dict[str, object]:
    release_dir = release_dir.expanduser().resolve()
    if not release_dir.is_dir():
        raise FileNotFoundError(f"Release directory does not exist: {release_dir}")
    if len(source_commit) != 40 or any(character not in SHA256_HEX for character in source_commit):
        raise ValueError("source_commit must be a full lowercase Git commit")
    if release_kind not in {"client", "plugins"}:
        raise ValueError("release_kind must be client or plugins")
    if version is not None:
        version = validate_semver(version)

    manifest_name = "client-manifest.json" if release_kind == "client" else "plugin-manifest.json"
    manifest = json.loads((release_dir / manifest_name).read_text(encoding="utf-8"))
    if release_kind == "plugins" and manifest.get("source_commit") != source_commit:
        raise ValueError("Signed plugin manifest does not match the source commit")

    tools = {
        "operating_system": platform.platform(),
        "python": platform.python_version(),
        "python_compiler": platform.python_compiler(),
        "uv": _command_version(("uv", "--version")),
    }
    try:
        tools["pyinstaller"] = importlib.metadata.version("pyinstaller")
    except importlib.metadata.PackageNotFoundError:
        tools["pyinstaller"] = "not-used"
    packager_command = PACKAGER_COMMANDS[packager]
    if packager_command is None:
        if packager_executable is not None:
            raise ValueError("packager_executable cannot be used when the packager is none")
        tools["packager"] = "not-used"
    elif packager_executable is None:
        tools["packager"] = _command_version(packager_command)
    else:
        tools["packager"] = _command_version(
            packager_command,
            executable=packager_executable,
        )

    inventory: dict[str, object] = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "release_kind": release_kind,
        "target_platform": target_platform,
        "version": version,
        "release_sequence": manifest.get("release_sequence"),
        "source_commit": source_commit,
        "source_tag": source_tag,
        "tools": tools,
        "files": _artifact_records(release_dir, manifest),
    }
    output = release_dir / INVENTORY_FILENAME
    temporary = output.with_suffix(".json.part")
    temporary.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(output)
    return inventory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--source-tag", required=True)
    parser.add_argument("--kind", choices=("client", "plugins"), required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--version")
    parser.add_argument("--packager", choices=tuple(PACKAGER_COMMANDS), default="none")
    parser.add_argument("--packager-executable", type=Path)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        inventory = create_inventory(
            release_dir=args.release_dir,
            source_commit=args.source_commit,
            source_tag=args.source_tag,
            release_kind=args.kind,
            target_platform=args.platform,
            version=args.version,
            packager=args.packager,
            packager_executable=args.packager_executable,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Recorded {len(inventory['files'])} release files in {args.release_dir / INVENTORY_FILENAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
