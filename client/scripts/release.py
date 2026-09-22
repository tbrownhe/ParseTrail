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

from scripts.publish_existing import DEFAULT_TRUST_STORE, publish_existing
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


@dataclass(frozen=True)
class PublicationConfig:
    public_api_base_url: str
    remote: RemoteConfig


def _existing_path(value: object, *, name: str, directory: bool) -> Path:
    if not isinstance(value, str) or not value:
        raise ReleaseConfigError(f"{name} must be a non-empty path")
    path = Path(value).expanduser().resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        kind = "directory" if directory else "file"
        raise ReleaseConfigError(f"{name} does not name an existing {kind}: {path}")
    return path


def load_config(path: Path, *, publication_only: bool = False) -> ReleaseConfig | PublicationConfig:
    try:
        payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseConfigError(f"Could not read release config: {path}") from exc
    public_fields = {"schema_version", "public_api_base_url", "remote"}
    build_fields = {"clients_dir", "plugins_dir", "signing_key"}
    allowed = [public_fields, public_fields | build_fields] if publication_only else [public_fields | build_fields]
    if not isinstance(payload, dict) or set(payload) not in allowed:
        raise ReleaseConfigError("Release config has unknown or missing fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
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

    if publication_only:
        if remote is None:
            raise ReleaseConfigError("Remote configuration is required to review a publication")
        return PublicationConfig(public_api_base_url=public_api_base_url.rstrip("/"), remote=remote)
    return ReleaseConfig(
        clients_dir=_existing_path(payload["clients_dir"], name="clients_dir", directory=True),
        plugins_dir=_existing_path(payload["plugins_dir"], name="plugins_dir", directory=True),
        signing_key=_existing_path(payload["signing_key"], name="signing_key", directory=False),
        public_api_base_url=public_api_base_url.rstrip("/"),
        remote=remote,
    )


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=False)
    if completed.returncode:
        raise RuntimeError(f"Release command failed with exit code {completed.returncode}: {command[0]}")


def _client_command(config: ReleaseConfig, platform_name: str) -> list[str]:
    if platform_name not in {"windows-x86_64", "macos-x86_64"}:
        raise ReleaseConfigError("Client releases require an explicit supported installer target")
    client_root = Path(__file__).resolve().parents[1]
    if platform_name == "windows-x86_64":
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
    return command


def release_plugins(config: ReleaseConfig, source_tag: str) -> None:
    from parsetrail.build_plugins import compile_plugins

    from scripts.plugin_release import sign_release, verify_release
    from scripts.release_inventory import create_inventory, inventory_digest

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
    print(f"Inventory SHA-256: {inventory_digest(config.plugins_dir)}")
    print("Dry run complete; preserve this output and use publish-existing after review.")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    client = subparsers.add_parser("client")
    client.add_argument("--platform", choices=("macos-x86_64", "windows-x86_64"), required=True)

    plugins = subparsers.add_parser("plugins")
    plugins.add_argument("--tag", required=True)
    existing = subparsers.add_parser("publish-existing", help="verify saved output; optionally confirm activation")
    existing.add_argument("--kind", choices=("client", "plugins"), required=True)
    existing.add_argument("--release-dir", type=Path, required=True)
    existing.add_argument("--tag", required=True)
    existing.add_argument("--platform", choices=("macos-x86_64", "windows-x86_64"))
    existing.add_argument("--inventory-sha256", required=True)
    existing.add_argument("--trust-store", type=Path, default=DEFAULT_TRUST_STORE)
    existing.add_argument("--activate", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "publish-existing":
            config = load_config(args.config, publication_only=True)
            remote_root = config.remote.plugins_dir
            if args.kind == "client":
                if args.platform is None:
                    raise ReleaseConfigError("Client publication requires --platform")
                remote_root = f"{config.remote.clients_dir.rstrip('/')}/{args.platform}"
            publish_existing(
                release_dir=args.release_dir,
                kind=args.kind,
                tag=args.tag,
                target=args.platform,
                inventory_sha256=args.inventory_sha256,
                remote_spec=f"{config.remote.user}@{config.remote.host}",
                remote_root=remote_root,
                api_base_url=config.public_api_base_url,
                trust_store=args.trust_store,
                activate=args.activate,
            )
        else:
            config = load_config(args.config)
            if args.command == "client":
                _run(_client_command(config, args.platform))
            else:
                release_plugins(config, args.tag)
    except (OSError, ValueError, RuntimeError, EOFError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
