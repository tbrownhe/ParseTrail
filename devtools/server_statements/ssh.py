import base64
import subprocess
from pathlib import Path

from settings import settings

_MASTER_KEY_CACHE: bytes | None = None


def _ssh_cmd(base: list[str]) -> list[str]:
    cmd = ["ssh"]
    if settings.SSH_KEY_PATH:
        cmd += ["-i", settings.SSH_KEY_PATH]
    cmd += base
    return cmd


def fetch_remote_env(var_name: str) -> str:
    if not settings.REMOTE_HOST or not settings.REMOTE_USER:
        raise ValueError(
            "REMOTE_HOST and REMOTE_USER are required to fetch MASTER_KEY remotely"
        )
    remote_cmd = f"grep '^{var_name}=' {settings.REMOTE_ENV_PATH}"
    cmd = _ssh_cmd(
        [
            f"{settings.REMOTE_USER}@{settings.REMOTE_HOST}",
            remote_cmd,
        ]
    )
    result = subprocess.run(cmd, capture_output=True, check=True, text=True)
    for line in result.stdout.splitlines():
        if line.startswith(f"{var_name}="):
            return line.split("=", 1)[1].strip()
    raise ValueError(f"{var_name} not found in remote env file")


def fetch_encrypted_file(file_name: str) -> bytes:
    """Read the encrypted file either locally or via SSH."""
    if settings.ENVIRONMENT == "local":
        remote_path = f"{settings.REMOTE_STATEMENTS_DIR.rstrip('/')}/{file_name}"
        remote_cmd = f"cat {remote_path}"
        cmd = _ssh_cmd(
            [
                f"{settings.REMOTE_USER}@{settings.REMOTE_HOST}",
                remote_cmd,
            ]
        )
        result = subprocess.run(cmd, capture_output=True, check=True)
        return result.stdout
    else:
        local_path = Path(settings.REMOTE_STATEMENTS_DIR) / file_name
        if local_path.exists():
            return local_path.read_bytes()


def load_master_key() -> bytes:
    """Retrieve the master key once per session from the remote env."""
    global _MASTER_KEY_CACHE
    if _MASTER_KEY_CACHE is not None:
        return _MASTER_KEY_CACHE

    key_str = fetch_remote_env("MASTER_KEY")
    try:
        key = base64.b64decode(key_str)
    except Exception as e:
        raise ValueError("MASTER_KEY could not be base64-decoded") from e
    if len(key) != 32:
        raise ValueError(
            f"MASTER_KEY must be 32 bytes after base64 decode (got {len(key)})"
        )
    _MASTER_KEY_CACHE = key
    return key
