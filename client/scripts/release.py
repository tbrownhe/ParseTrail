"""Run one guarded ParseTrail client or plugin release from local builders."""

from __future__ import annotations

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from parsetrail.build_plugins import compile_plugins
from parsetrail.version import __version__

from scripts.immutable_publish import SshTransport, publish_release
from scripts.plugin_release import DEFAULT_TRUST_STORE, sign_release, verify_release
from scripts.release_inventory import create_inventory
from scripts.release_smoke import smoke_release
from scripts.release_source import REPOSITORY_ROOT, validate_release_source


class ReleaseConfigError(RuntimeError):
    """The explicit local release configuration is incomplete or invalid."""


@dataclass(frozen=True)
class RemoteConfig:
    user: str
    host: str
    clients_dir: str
    plugins_dir: str


@dataclass(frozen=True)
class ReleaseConfig:
    clients_dir: Path
    plugins_dir: Path
    signing_key: Path
    public_api_base_url: str
    remote: RemoteConfig | None


def _existing_path(value: object, *, name: str, directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ReleaseConfigError(f"{name} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        kind = "directory" if directory else "file"
        raise ReleaseConfigError(f"{name} does not name an existing {kind}: {path}")
    return path


def load_config(path: Path) -> ReleaseConfig:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseConfigError(f"Could not read release config: {path}") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "clients_dir",
        "plugins_dir",
        "signing_key",
        "public_api_base_url",
        "remote",
    }:
        raise ReleaseConfigError("Release config has unknown or missing fields")
    if payload["schema_version"] != 1:
        raise ReleaseConfigError("Unsupported release config schema")

    remote_payload = payload["remote"]
    remote = None
    if remote_payload is not None:
        if not isinstance(remote_payload, dict) or set(remote_payload) != {
            "user",
            "host",
            "clients_dir",
            "plugins_dir",
        }:
            raise ReleaseConfigError("Remote release config has unknown or missing fields")
        if not all(isinstance(value, str) and value for value in remote_payload.values()):
            raise ReleaseConfigError("Remote release values must be non-empty strings")
        remote = RemoteConfig(**remote_payload)

    public_api_base_url = payload["public_api_base_url"]
    if not isinstance(public_api_base_url, str):
        raise ReleaseConfigError("public_api_base_url must be an HTTPS URL")
    public_url = urlsplit(public_api_base_url)
    if (
        public_url.scheme != "https"
        or not public_url.hostname
        or public_url.username is not None
        or public_url.password is not None
        or public_url.query
        or public_url.fragment
    ):
        raise ReleaseConfigError("public_api_base_url must be an HTTPS URL without credentials, query, or fragment")

    return ReleaseConfig(
        clients_dir=_existing_path(payload["clients_dir"], name="clients_dir", directory=True),
        plugins_dir=_existing_path(payload["plugins_dir"], name="plugins_dir", directory=True),
        signing_key=_existing_path(payload["signing_key"], name="signing_key", directory=False),
        public_api_base_url=public_api_base_url.rstrip("/"),
        remote=remote,
    )


def _confirm_publish(kind: str) -> None:
    expected = f"publish {kind}"
    answer = input(f"Type {expected!r} to activate this public release: ")
    if answer != expected:
        raise ReleaseConfigError("Publication was not approved")


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=False)
    if completed.returncode:
        raise RuntimeError(f"Release command failed with exit code {completed.returncode}: {command[0]}")


def _client_command(config: ReleaseConfig, platform_name: str, *, publish: bool) -> list[str]:
    client_root = Path(__file__).resolve().parents[1]
    if platform_name == "win64":
        shell = shutil.which("pwsh") or shutil.which("powershell.exe")
        if shell is None:
            raise ReleaseConfigError("PowerShell was not found for the Windows release")
        command = [
            shell,
            "-NoProfile",
            "-File",
            str(client_root / "build_client_win64.ps1"),
            "-ClientsDir",
            str(config.clients_dir),
            "-SigningKey",
            str(config.signing_key),
        ]
    else:
        shell = shutil.which("bash")
        if shell is None:
            raise ReleaseConfigError("bash was not found for the macOS release")
        command = [
            shell,
            str(client_root / "build_client_macos.sh"),
            "--clients-dir",
            str(config.clients_dir),
            "--signing-key",
            str(config.signing_key),
        ]
    if publish:
        if config.remote is None:
            raise ReleaseConfigError("Remote configuration is required for publication")
        command.extend(
            [
                "-Publish" if platform_name == "win64" else "--publish",
                "-RemoteUser" if platform_name == "win64" else "--remote-user",
                config.remote.user,
                "-RemoteHost" if platform_name == "win64" else "--remote-host",
                config.remote.host,
                "-RemoteClientsDir" if platform_name == "win64" else "--remote-clients-dir",
                config.remote.clients_dir,
            ]
        )
    return command


def release_plugins(config: ReleaseConfig, source_tag: str, *, publish: bool) -> None:
    source = validate_release_source(repository=REPOSITORY_ROOT, expected_tag=source_tag)
    _run([sys.executable, "-m", "pytest", "-q"])
    compile_plugins(config.plugins_dir)
    passphrase = getpass.getpass("Plugin signing-key passphrase: ").encode("utf-8")
    manifest = sign_release(
        config.plugins_dir,
        config.signing_key,
        DEFAULT_TRUST_STORE,
        passphrase,
        source_commit=source.source_commit,
    )
    verify_release(config.plugins_dir, DEFAULT_TRUST_STORE)
    create_inventory(
        release_dir=config.plugins_dir,
        source_commit=source.source_commit,
        source_tag=source.source_tag,
        release_kind="plugins",
        target_platform=f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        version=None,
        packager="none",
    )
    print(f"Signed and verified plugin release {manifest.release_sequence} from {source.source_commit[:12]}.")
    if not publish:
        print("Dry run complete; public artifact directories were not changed.")
        return
    if config.remote is None:
        raise ReleaseConfigError("Remote configuration is required for publication")
    _confirm_publish("plugins")
    publish_release(
        release_dir=config.plugins_dir,
        manifest_name="plugin-manifest.json",
        signature_name="plugin-manifest.sig",
        inventory_name="release-inventory.json",
        remote_root=config.remote.plugins_dir,
        transport=SshTransport(f"{config.remote.user}@{config.remote.host}"),
    )
    smoke_release(
        release_dir=config.plugins_dir,
        release_kind="plugins",
        api_base_url=config.public_api_base_url,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    client = subparsers.add_parser("client")
    client.add_argument("--platform", choices=("macos", "win64"), required=True)
    client.add_argument("--publish", action="store_true")

    plugins = subparsers.add_parser("plugins")
    plugins.add_argument("--tag", required=True)
    plugins.add_argument("--publish", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        config = load_config(args.config)
        if args.command == "client":
            if args.publish:
                _confirm_publish(f"client {__version__} {args.platform}")
            _run(_client_command(config, args.platform, publish=args.publish))
            if args.publish:
                smoke_release(
                    release_dir=config.clients_dir / args.platform,
                    release_kind="client",
                    api_base_url=config.public_api_base_url,
                    platform=args.platform,
                )
        else:
            release_plugins(config, args.tag, publish=args.publish)
    except (OSError, ValueError, RuntimeError, ReleaseConfigError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
