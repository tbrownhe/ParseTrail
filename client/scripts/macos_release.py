# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# required-version = ">=0.12.5"
# ///
"""Package-free Intel Mac toolchain, bundled-library, and frozen-runtime gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parents[1]
MACHO_MAGIC = {
    bytes.fromhex(value)
    for value in ("feedface", "cefaedfe", "feedfacf", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca")
}
DYLIB_COMMANDS = {
    "LC_LOAD_DYLIB",
    "LC_LOAD_WEAK_DYLIB",
    "LC_REEXPORT_DYLIB",
    "LC_LOAD_UPWARD_DYLIB",
    "LC_LAZY_LOAD_DYLIB",
}


class MacReleaseError(RuntimeError):
    """An Intel release cannot pass a required native gate."""


def _run(command: list[str], *, env: dict[str, str] | None = None, timeout: int = 30) -> str:
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, env=env, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MacReleaseError(f"{Path(command[0]).name} could not complete: {type(exc).__name__}") from exc
    if result.returncode:
        raise MacReleaseError(
            f"{Path(command[0]).name} failed (exit {result.returncode}). Check the native tool installation."
        )
    return result.stdout.strip()


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise MacReleaseError(
            f"Missing {name}. Install Xcode command line tools and Homebrew openssl@3, rust, pkg-config, create-dmg."
        )
    return path


def _require_intel_mac() -> None:
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise MacReleaseError("This packaging gate requires an Intel macOS host; Apple Silicon is deferred.")


def preflight() -> tuple[dict[str, str], dict[str, object]]:
    """Inspect native build inputs without installing any tools or Python packages."""
    _require_intel_mac()
    tools = {
        name: _require_tool(name)
        for name in ("brew", "rustc", "cargo", "pkg-config", "clang", "xcrun", "lipo", "otool", "create-dmg")
    }
    prefix = Path(_run([tools["brew"], "--prefix", "openssl@3"]))
    if not prefix.is_absolute() or not prefix.is_dir():
        raise MacReleaseError("Homebrew openssl@3 is not installed; run brew install openssl@3.")
    for name in ("lib/libssl.a", "lib/libcrypto.a", "include/openssl/ssl.h", "lib/pkgconfig/openssl.pc", "bin/openssl"):
        if not (prefix / name).is_file():
            raise MacReleaseError(f"Homebrew openssl@3 is missing {name}; reinstall openssl@3.")

    env = os.environ.copy()
    # Target-qualified openssl-sys settings otherwise override the generic ones.
    for name, value in {
        "OPENSSL_DIR": str(prefix),
        "OPENSSL_LIB_DIR": str(prefix / "lib"),
        "OPENSSL_INCLUDE_DIR": str(prefix / "include"),
        "OPENSSL_STATIC": "1",
        "OPENSSL_NO_VENDOR": "1",
        "OPENSSL_LIBS": "ssl:crypto",
    }.items():
        env[name] = value
        env[f"X86_64_APPLE_DARWIN_{name}"] = value
    env.update(
        PKG_CONFIG_PATH=str(prefix / "lib/pkgconfig"),
        PKG_CONFIG_LIBDIR=str(prefix / "lib/pkgconfig"),
        CARGO_BUILD_TARGET="x86_64-apple-darwin",
    )
    rust = _run([tools["rustc"], "-vV"])
    version = re.search(r"^release: (\d+)\.(\d+)\.(\d+)$", rust, re.MULTILINE)
    if version is None or tuple(map(int, version.groups())) < (1, 83, 0):
        raise MacReleaseError("cryptography source builds require stable Rust >= 1.83.0; update Rust.")
    if "host: x86_64-apple-darwin" not in rust.splitlines():
        raise MacReleaseError("Rust must target the Intel macOS host.")
    openssl_version = _run([str(prefix / "bin/openssl"), "version"])
    if not openssl_version.startswith("OpenSSL 3."):
        raise MacReleaseError("The openssl@3 prefix did not supply OpenSSL 3.")
    pkg_version = _run([tools["pkg-config"], "--modversion", "openssl"], env=env)
    if not pkg_version.startswith("3."):
        raise MacReleaseError("pkg-config did not resolve OpenSSL 3 from the selected prefix.")
    archives = {}
    for name in ("libssl.a", "libcrypto.a"):
        archive = prefix / "lib" / name
        if "x86_64" not in _run([tools["lipo"], "-archs", str(archive)]).split():
            raise MacReleaseError(f"openssl@3 {name} has no Intel x86_64 slice.")
        archives[name] = hashlib.sha256(archive.read_bytes()).hexdigest()
    inputs: dict[str, object] = {
        "target_platform": "macos",
        "architecture": "x86_64",
        "openssl_formula": "openssl@3",
        "openssl_version": openssl_version,
        "openssl_static": True,
        "openssl_archives_sha256": archives,
        "rust": version.group(0).removeprefix("release: "),
        "cargo": _run([tools["cargo"], "--version"]),
        "clang": _run([tools["clang"], "--version"]).splitlines()[0],
        "macos_sdk": _run([tools["xcrun"], "--sdk", "macosx", "--show-sdk-version"]),
        "pkg_config": _run([tools["pkg-config"], "--version"]),
        "pkg_config_openssl": pkg_version,
        "create_dmg": _run([tools["create-dmg"], "--version"]),
    }
    return env, inputs


def sync_dependencies(*, fresh_cryptography: bool, output: Path | None) -> None:
    env, inputs = preflight()
    command = [
        _require_tool("uv"),
        "sync",
        "--extra",
        "dev",
        "--frozen",
        "--python",
        sys.executable,
        "--no-python-downloads",
    ]
    if fresh_cryptography:
        # A wheel cached from an earlier dynamic source build must not be reused.
        command += ["--no-cache", "--reinstall-package", "cryptography"]
    try:
        result = subprocess.run(command, cwd=CLIENT_ROOT, env=env, check=False, timeout=1800)
    except subprocess.TimeoutExpired as exc:
        raise MacReleaseError("Locked Mac dependency sync exceeded 1800 seconds.") from exc
    if result.returncode:
        raise MacReleaseError(f"Locked Mac dependency sync failed (exit {result.returncode}).")
    if output is not None:
        _write_json(output, {"schema_version": 1, "build_inputs": inputs})


def _is_macho(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(4) in MACHO_MAGIC


def _load_commands(output: str) -> tuple[list[str], list[str]]:
    dependencies, rpaths = [], []
    for block in re.split(r"(?m)^Load command \d+\s*$", output)[1:]:
        command = re.search(r"(?m)^\s*cmd (LC_\w+)\s*$", block)
        if command is None:
            raise MacReleaseError("Unrecognized otool load-command output.")
        kind = command.group(1)
        if kind not in DYLIB_COMMANDS | {"LC_RPATH"}:
            continue  # LC_ID_DYLIB is the image's identity, not a dependency.
        field = "path" if kind == "LC_RPATH" else "name"
        value = re.search(rf"(?m)^\s*{field} (.+) \(offset \d+\)\s*$", block)
        if value is None:
            raise MacReleaseError(f"Missing {field} in {kind} output.")
        (rpaths if kind == "LC_RPATH" else dependencies).append(value.group(1))
    if "Load command " not in output:
        raise MacReleaseError("otool returned no Mach-O load commands.")
    return dependencies, rpaths


def _is_system(path: str) -> bool:
    normalized = posixpath.normpath(path)
    return normalized.startswith(("/usr/lib/", "/System/Library/"))


def _expand(path: str, *, loader: Path, executable: Path, root: Path) -> Path:
    for marker, base in (("@loader_path", loader.parent), ("@executable_path", executable.parent)):
        if path == marker or path.startswith(marker + "/"):
            resolved = (base / path[len(marker) :].lstrip("/")).resolve()
            if not resolved.is_relative_to(root):
                raise MacReleaseError(f"Bundled path escapes the app: {path}")
            return resolved
    raise MacReleaseError(f"Non-relocatable library path: {path}")


def audit_bundle(app: Path) -> dict[str, object]:
    """Fail closed on workstation paths, missing bundled libraries, or dynamic crypto."""
    _require_intel_mac()
    otool = _require_tool("otool")
    root = app.resolve(strict=True)
    executable = root / "Contents/MacOS/ParseTrail"
    if not executable.is_file() or not _is_macho(executable):
        raise MacReleaseError("The app is missing its Mach-O ParseTrail executable.")
    binaries = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() and (not path.exists() or not path.resolve().is_relative_to(root)):
            raise MacReleaseError(f"Broken or external bundle symlink: {path.relative_to(root)}")
        if path.is_file() and not path.is_symlink() and _is_macho(path):
            binaries.append(path)
    commands = {path: _load_commands(_run([otool, "-arch", "x86_64", "-l", str(path)])) for path in binaries}
    main_rpaths = [
        _expand(value, loader=executable, executable=executable, root=root) for value in commands[executable][1]
    ]
    records = []
    crypto_count = 0
    for binary, (dependencies, rpaths) in commands.items():
        relative = binary.relative_to(root).as_posix()
        is_crypto = "/cryptography/" in f"/{relative}" and binary.name.startswith("_rust")
        crypto_count += int(is_crypto)
        search_paths = [
            _expand(value, loader=binary, executable=executable, root=root) for value in rpaths
        ] + main_rpaths
        resolved_dependencies = []
        for dependency in dependencies:
            if is_crypto and re.match(r"lib(?:ssl|crypto)(?:\.|$)", posixpath.basename(dependency)):
                raise MacReleaseError(f"cryptography must link OpenSSL statically: {relative}: {dependency}")
            if _is_system(dependency):
                resolved_dependencies.append(posixpath.normpath(dependency))
                continue
            if dependency.startswith("@rpath/"):
                candidates = [(base / dependency.removeprefix("@rpath/")).resolve() for base in search_paths]
            else:
                candidates = [_expand(dependency, loader=binary, executable=executable, root=root)]
            if any(not path.is_relative_to(root) for path in candidates):
                raise MacReleaseError(f"Library resolution escapes the app: {relative}: {dependency}")
            resolved = next((path for path in candidates if path.is_file()), None)
            if resolved is None or not _is_macho(resolved):
                raise MacReleaseError(f"Unresolved bundled library: {relative}: {dependency}")
            resolved_dependencies.append(resolved.relative_to(root).as_posix())
        records.append({"binary": relative, "dependencies": resolved_dependencies})
    if not crypto_count:
        raise MacReleaseError("The app is missing the cryptography Rust extension; static OpenSSL cannot be verified.")
    return {
        "architecture": "x86_64",
        "macho_files": len(records),
        "cryptography_extensions": crypto_count,
        "libraries": records,
    }


def smoke_test(app: Path, *, timeout: int = 30) -> dict[str, object]:
    executable = app.resolve(strict=True) / "Contents/MacOS/ParseTrail"
    if not executable.is_file():
        raise MacReleaseError("Frozen executable not found.")
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DYLD_", "PYTHON", "OPENSSL", "X86_64_APPLE_DARWIN_OPENSSL", "PARSETRAIL_"))
    }
    env["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    with tempfile.TemporaryDirectory(prefix="parsetrail-frozen-smoke-") as profile:
        env.update(HOME=profile, XDG_CONFIG_HOME=profile, XDG_DATA_HOME=profile, XDG_CACHE_HOME=profile)
        _run([str(executable), "--runtime-smoke-test"], env=env, timeout=timeout)
    return {"passed": True, "timeout_seconds": timeout, "profile": "temporary", "path": "system-tools-only"}


def _write_json(path: Path, document: dict[str, object]) -> None:
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight", help="check tools only; do not install packages, build, or sign")
    sync = commands.add_parser("sync", help="preflight before syncing locked dependencies with static OpenSSL inputs")
    sync.add_argument("--fresh-cryptography", action="store_true")
    sync.add_argument("--output", type=Path)
    audit = commands.add_parser("audit", help="audit native libraries and run the bounded frozen smoke")
    audit.add_argument("--app", type=Path, required=True)
    audit.add_argument("--build-inputs", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            _env, inputs = preflight()
            print(json.dumps(inputs, indent=2, sort_keys=True))
        elif args.command == "sync":
            sync_dependencies(fresh_cryptography=args.fresh_cryptography, output=args.output)
        else:
            report = json.loads(args.build_inputs.read_text(encoding="utf-8"))
            report["library_audit"] = audit_bundle(args.app)
            report["frozen_smoke"] = smoke_test(args.app)
            _write_json(args.output, report)
            print(f"Audited {report['library_audit']['macho_files']} native files; frozen runtime smoke passed.")
        return 0
    except (MacReleaseError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
