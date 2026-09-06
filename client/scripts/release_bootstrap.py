# /// script
# requires-python = ">=3.10"
# dependencies = []
# [tool.uv]
# required-version = ">=0.12.5"
# ///
"""Validate a native release interpreter before installing project dependencies.

Run with ``uv run --no-env-file --script scripts/release_bootstrap.py``.
Inline script metadata keeps the launcher independent of the client environment.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

CLIENT_ROOT = Path(__file__).resolve().parents[1]
MINIMUM_UV = (0, 12, 5)
TARGET_SYSTEMS = {"win64": "Windows", "macos": "Darwin"}
PYTHON_PROBE = """
import json, platform, struct, sysconfig
print(json.dumps({
    "version": platform.python_version(),
    "implementation": platform.python_implementation(),
    "system": platform.system(),
    "machine": platform.machine(),
    "bits": struct.calcsize("P") * 8,
    "free_threaded": bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
}))
"""


class BootstrapError(RuntimeError):
    """The builder cannot supply the required release environment."""


@dataclass(frozen=True)
class ReleaseRuntime:
    uv: str
    uv_version: str
    python_version: str
    interpreter: str
    target: str


def _run(command: list[str], *, cwd: Path, phase: str, timeout: int = 60) -> str:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BootstrapError(f"{phase} could not complete: {type(exc).__name__}") from exc
    if result.returncode:
        raise BootstrapError(f"{phase} failed (exit {result.returncode}). No release build was started.")
    return result.stdout.strip()


def _validate_uv(output: str) -> str:
    match = re.fullmatch(r"uv (\d+)\.(\d+)\.(\d+)(?: \([^\r\n]+\))?", output)
    if match is None or tuple(map(int, match.groups())) < MINIMUM_UV:
        raise BootstrapError("Release builds require a stable uv version >= 0.12.5; update uv before retrying.")
    return ".".join(match.groups())


def _validate_target(target: str | None) -> str:
    host_system = platform.system()
    selected = target or next((name for name, system in TARGET_SYSTEMS.items() if system == host_system), "")
    if selected not in TARGET_SYSTEMS or TARGET_SYSTEMS[selected] != host_system:
        raise BootstrapError("Release builds require the matching native Windows x64 or Intel macOS host.")
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise BootstrapError("Only Windows x64 and Intel macOS release hosts are supported; arm64 is deferred.")
    return selected


def bootstrap(target: str | None = None, *, client_root: Path = CLIENT_ROOT) -> ReleaseRuntime:
    """Provision and inspect exact managed CPython, without syncing any packages."""
    uv = shutil.which("uv")
    if uv is None:
        raise BootstrapError("uv was not found on PATH. Install uv >= 0.12.5 before releasing.")
    uv_version = _validate_uv(_run([uv, "--version"], cwd=client_root, phase="uv version check"))
    selected = _validate_target(target)
    try:
        version = (client_root / ".python-version").read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BootstrapError("Could not read the client's .python-version file.") from exc
    if not re.fullmatch(r"3\.\d+\.\d+", version):
        raise BootstrapError(".python-version must contain one exact stable Python 3 patch version.")

    request = f"cpython-{version}"
    install = [uv, "python", "install", "--no-config", "--no-bin", request]
    if selected == "win64":
        install.append("--no-registry")
    _run(install, cwd=client_root, phase=f"Provisioning {request} for {selected}", timeout=300)
    interpreter = _run(
        [
            uv,
            "python",
            "find",
            "--no-config",
            "--no-project",
            "--system",
            "--managed-python",
            "--no-python-downloads",
            request,
        ],
        cwd=client_root,
        phase=f"Locating managed {request}",
    )
    if not interpreter or not Path(interpreter).is_file():
        raise BootstrapError(f"uv did not return an existing interpreter for {request}.")
    probe = _run([interpreter, "-I", "-S", "-c", PYTHON_PROBE], cwd=client_root, phase="Release interpreter inspection")
    try:
        runtime = json.loads(probe)
    except json.JSONDecodeError as exc:
        raise BootstrapError("Release interpreter returned invalid inspection data.") from exc
    if not isinstance(runtime, dict) or (
        runtime.get("version") != version
        or runtime.get("implementation") != "CPython"
        or runtime.get("system") != TARGET_SYSTEMS[selected]
        or str(runtime.get("machine", "")).lower() not in {"amd64", "x86_64"}
        or runtime.get("bits") != 64
        or runtime.get("free_threaded") is not False
    ):
        raise BootstrapError(
            f"Expected standard 64-bit CPython {version} for {selected}; interpreter inspection disagreed."
        )
    return ReleaseRuntime(uv, uv_version, version, interpreter, selected)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="provision/verify Python without installing client dependencies")
    check.add_argument("--platform", choices=tuple(TARGET_SYSTEMS), required=True)
    check.add_argument("--print-python", action="store_true", help="print only the verified interpreter path")
    client = commands.add_parser("client", help="bootstrap, then run the guarded client release")
    client.add_argument("--platform", choices=tuple(TARGET_SYSTEMS), required=True)
    client.add_argument("--publish", action="store_true")
    plugins = commands.add_parser("plugins", help="bootstrap, then run the guarded plugin release")
    plugins.add_argument("--tag", required=True)
    plugins.add_argument("--publish", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command != "check" and args.config is None:
        parser.error("--config is required for client/plugins releases")
    try:
        runtime = bootstrap(getattr(args, "platform", None))
        if args.command == "check":
            print(runtime.interpreter if args.print_python else json.dumps(asdict(runtime), sort_keys=True))
            return 0
        # Mac source builds need their native toolchain before the first package operation.
        if runtime.target == "macos" and args.command == "client":
            try:
                native = subprocess.run(
                    [runtime.interpreter, "-I", "-S", str(CLIENT_ROOT / "scripts/macos_release.py"), "sync"],
                    cwd=CLIENT_ROOT,
                    check=False,
                    timeout=1860,
                )
            except subprocess.TimeoutExpired as exc:
                raise BootstrapError("Intel macOS preflight/dependency sync timed out.") from exc
            if native.returncode:
                raise BootstrapError("Intel macOS preflight/dependency sync failed; see the preceding diagnostic.")
        else:
            _run(
                [
                    runtime.uv,
                    "sync",
                    "--extra",
                    "dev",
                    "--frozen",
                    "--python",
                    runtime.interpreter,
                    "--no-python-downloads",
                ],
                cwd=CLIENT_ROOT,
                phase="Locked release dependency sync",
                timeout=1800,
            )
        forwarded = ["--config", str(args.config.expanduser().resolve()), args.command]
        if args.command == "client":
            forwarded.extend(["--platform", args.platform])
        else:
            forwarded.extend(["--tag", args.tag])
        if args.publish:
            forwarded.append("--publish")
        # Inherit the terminal: signing and activation prompts must stay interactive.
        completed = subprocess.run(
            [
                runtime.uv,
                "run",
                "--no-env-file",
                "--no-sync",
                "--python",
                runtime.interpreter,
                "--no-python-downloads",
                "python",
                "-m",
                "scripts.release",
                *forwarded,
            ],
            cwd=CLIENT_ROOT,
            check=False,
        )
        return completed.returncode
    except (BootstrapError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
