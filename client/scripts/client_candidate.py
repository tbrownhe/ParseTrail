"""Preserve a tested, unsigned installer and its native builder's provenance."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from parsetrail.core.client_manifest import ClientInstallerArtifact

from scripts.release_inventory import _sha256_file, tool_versions

BUILD_RECORD = "build-record.json"
TARGETS = ("windows-x86_64", "macos-x86_64")
CHECKS = {
    "source_suite": True,
    "architecture": True,
    "frozen_runtime": True,
    "offline_modes": ["fresh", "cached", "network-failure"],
}


def verify_candidate(directory: Path, *, source_commit: str, source_tag: str) -> dict:
    path = directory / BUILD_RECORD
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        raise ValueError("Candidate build record must be a bounded regular file")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict) or record.get("schema_version") != 1:
        raise ValueError("Unsupported candidate record")
    if record.get("source_commit") != source_commit or record.get("source_tag") != source_tag:
        raise ValueError("Candidate source/tag does not match the selected release")
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("Candidate source must be a full commit")
    if record.get("checks") != CHECKS:
        raise ValueError("Candidate is missing successful build gates")
    artifact = ClientInstallerArtifact.model_validate(record.get("installer"))
    if (
        artifact.platform not in TARGETS
        or record.get("target_platform") != artifact.platform
        or record.get("version") != artifact.version
        or record.get("architecture") != "x86_64"
        or source_tag != f"client-v{artifact.version}"
    ):
        raise ValueError("Candidate target/version does not match its installer")
    tools = record.get("tools")
    if not isinstance(tools, dict) or any(
        not isinstance(tools.get(key), str) or not tools[key]
        for key in ("operating_system", "python", "python_compiler", "uv", "pyinstaller", "packager")
    ):
        raise ValueError("Candidate native tool versions are missing")
    if artifact.platform == "macos-x86_64":
        native = record.get("native_build", {})
        if (
            not isinstance(native, dict)
            or not all(isinstance(native.get(key), dict) for key in ("build_inputs", "library_audit", "frozen_smoke"))
            or native.get("schema_version") != 1
            or native.get("build_inputs", {}).get("target_platform") != artifact.platform
            or native.get("build_inputs", {}).get("architecture") != "x86_64"
            or native.get("build_inputs", {}).get("openssl_static") is not True
            or native.get("library_audit", {}).get("architecture") != "x86_64"
            or not native.get("library_audit", {}).get("cryptography_extensions")
            or native.get("frozen_smoke", {}).get("passed") is not True
        ):
            raise ValueError("Candidate native Mac evidence is incomplete")
    installer = directory / artifact.filename
    if installer.is_symlink() or not installer.is_file():
        raise ValueError("Candidate installer must be a regular file")
    if installer.stat().st_size != artifact.size or _sha256_file(installer) != artifact.sha256:
        raise ValueError("Candidate installer differs from its build record")
    return record


def record_candidate(
    installer: Path, metadata: Path, *, packager: str, executable: Path | None = None, native_report: Path | None = None
) -> dict:
    build = json.loads(metadata.read_text(encoding="utf-8"))
    artifact = ClientInstallerArtifact(
        filename=installer.name,
        platform=build["target_platform"],
        architecture=build["architecture"],
        version=build["client_version"],
        size=installer.stat().st_size,
        sha256=_sha256_file(installer),
    )
    record = {
        "schema_version": 1,
        "source_commit": build["source_commit"],
        "source_tag": build["source_tag"],
        "target_platform": artifact.platform,
        "architecture": artifact.architecture,
        "version": artifact.version,
        "installer": artifact.model_dump(mode="json"),
        "tools": tool_versions(packager, executable),
        "checks": CHECKS,
    }
    if native_report is not None:
        record["native_build"] = json.loads(native_report.read_text(encoding="utf-8"))
    output = installer.parent / BUILD_RECORD
    with output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
    verify_candidate(installer.parent, source_commit=build["source_commit"], source_tag=build["source_tag"])
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--packager", choices=("nsis", "create-dmg"), required=True)
    parser.add_argument("--packager-executable", type=Path)
    parser.add_argument("--native-report", type=Path)
    args = parser.parse_args()
    record_candidate(
        args.installer,
        args.metadata,
        packager=args.packager,
        executable=args.packager_executable,
        native_report=args.native_report,
    )
    print("Unsigned candidate recorded. Signing and publication are separate local release steps.")


if __name__ == "__main__":
    main()
