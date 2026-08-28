"""Atomic provisioning and overlap-safe rotation for submission RSA keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

KEYS_DIR = Path("keys")
ACTIVE_KEY_POINTER = "active-submission-key.json"
KEY_RELEASES_DIR = "submission-keys"
PRIVATE_KEY_FILENAME = "private-key.pem"
PUBLIC_KEY_FILENAME = "public-key.pem"
LEGACY_PRIVATE_KEY_FILENAME = "private_key.pem"
LEGACY_PUBLIC_KEY_FILENAME = "public_key.pem"
MAX_POINTER_BYTES = 1024
MAX_DECRYPTION_KEYS = 8
KEY_ID_PATTERN = re.compile(r"^submission-rsa-[0-9a-f]{32}$")


class SubmissionKeyError(RuntimeError):
    """Submission key storage is missing, corrupt, or inconsistent."""


def _key_id(public_pem: bytes) -> str:
    return f"submission-rsa-{hashlib.sha256(public_pem).hexdigest()[:32]}"


def _serialize_keypair(private_key: rsa.RSAPrivateKey) -> tuple[bytes, bytes]:
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _validate_keypair(private_pem: bytes, public_pem: bytes) -> rsa.RSAPrivateKey:
    try:
        private_key = serialization.load_pem_private_key(private_pem, password=None)
        public_key = serialization.load_pem_public_key(public_pem)
    except (TypeError, ValueError) as exc:
        raise SubmissionKeyError("Submission key files are not valid PEM keys") from exc
    if not isinstance(private_key, rsa.RSAPrivateKey) or not isinstance(public_key, rsa.RSAPublicKey):
        raise SubmissionKeyError("Submission keys must be RSA keys")
    if private_key.key_size < 2048:
        raise SubmissionKeyError("Submission RSA key must be at least 2048 bits")
    if private_key.public_key().public_numbers() != public_key.public_numbers():
        raise SubmissionKeyError("Submission public and private keys do not match")
    return private_key


def _write_durable(path: Path, payload: bytes, mode: int) -> None:
    with path.open("xb") as output_file:
        output_file.write(payload)
        output_file.flush()
        os.fsync(output_file.fileno())
    path.chmod(mode)


def _release_directory(root: Path, key_id: str) -> Path:
    if not KEY_ID_PATTERN.fullmatch(key_id):
        raise SubmissionKeyError("Submission key pointer contains an invalid key identifier")
    releases_root = (root / KEY_RELEASES_DIR).resolve()
    release_dir = (releases_root / key_id).resolve()
    try:
        release_dir.relative_to(releases_root)
    except ValueError as exc:
        raise SubmissionKeyError("Submission key path escapes its root") from exc
    return release_dir


def _install_keypair(root: Path, private_pem: bytes, public_pem: bytes) -> str:
    _validate_keypair(private_pem, public_pem)
    key_id = _key_id(public_pem)
    releases_root = root / KEY_RELEASES_DIR
    releases_root.mkdir(parents=True, exist_ok=True)
    releases_root.chmod(stat.S_IRWXU)
    final_dir = _release_directory(root, key_id)
    if final_dir.exists():
        existing_private = (final_dir / PRIVATE_KEY_FILENAME).read_bytes()
        existing_public = (final_dir / PUBLIC_KEY_FILENAME).read_bytes()
        if existing_private != private_pem or existing_public != public_pem:
            raise SubmissionKeyError(f"A different keypair already uses identifier {key_id}")
        return key_id

    staging_dir = releases_root / f".staging-{uuid.uuid4().hex}"
    staging_dir.mkdir()
    try:
        staging_dir.chmod(stat.S_IRWXU)
        _write_durable(
            staging_dir / PRIVATE_KEY_FILENAME,
            private_pem,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        _write_durable(
            staging_dir / PUBLIC_KEY_FILENAME,
            public_pem,
            stat.S_IRUSR | stat.S_IWUSR,
        )
        staging_dir.replace(final_dir)
    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
    return key_id


def _activate_key(root: Path, key_id: str) -> None:
    _release_directory(root, key_id)
    payload = (
        json.dumps(
            {"active_key_id": key_id, "schema_version": 1},
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )
    pointer_path = root / ACTIVE_KEY_POINTER
    partial_path = root / f".{ACTIVE_KEY_POINTER}.{uuid.uuid4().hex}.part"
    try:
        _write_durable(partial_path, payload, stat.S_IRUSR | stat.S_IWUSR)
        partial_path.replace(pointer_path)
    finally:
        partial_path.unlink(missing_ok=True)


def _read_active_key_id(root: Path) -> str:
    pointer_path = root / ACTIVE_KEY_POINTER
    try:
        if not pointer_path.is_file() or pointer_path.stat().st_size > MAX_POINTER_BYTES:
            raise ValueError
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        if set(pointer) != {"active_key_id", "schema_version"} or pointer["schema_version"] != 1:
            raise ValueError
        key_id = pointer["active_key_id"]
        if not isinstance(key_id, str) or not KEY_ID_PATTERN.fullmatch(key_id):
            raise ValueError
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SubmissionKeyError("Active submission key pointer is unavailable or invalid") from exc
    return key_id


def _read_keypair(root: Path, key_id: str) -> tuple[rsa.RSAPrivateKey, bytes]:
    release_dir = _release_directory(root, key_id)
    try:
        private_pem = (release_dir / PRIVATE_KEY_FILENAME).read_bytes()
        public_pem = (release_dir / PUBLIC_KEY_FILENAME).read_bytes()
    except OSError as exc:
        raise SubmissionKeyError(f"Submission key generation {key_id} is incomplete") from exc
    private_key = _validate_keypair(private_pem, public_pem)
    if _key_id(public_pem) != key_id:
        raise SubmissionKeyError("Submission key identifier does not match its public key")
    return private_key, public_pem


def load_active_public_key(root: Path = KEYS_DIR) -> tuple[str, bytes, float]:
    """Load and validate the atomically selected public key."""
    key_id = _read_active_key_id(root)
    _, public_pem = _read_keypair(root, key_id)
    modified_at = (_release_directory(root, key_id) / PUBLIC_KEY_FILENAME).stat().st_mtime
    return key_id, public_pem, modified_at


def load_submission_private_keys(root: Path = KEYS_DIR) -> tuple[rsa.RSAPrivateKey, ...]:
    """Load the active private key first, followed by retained rotation keys."""
    active_key_id = _read_active_key_id(root)
    active_private_key, _ = _read_keypair(root, active_key_id)
    releases_root = root / KEY_RELEASES_DIR
    if not releases_root.is_dir():
        raise SubmissionKeyError("Submission key release directory is unavailable")
    retained = sorted(
        (
            path
            for path in releases_root.iterdir()
            if path.is_dir() and KEY_ID_PATTERN.fullmatch(path.name) and path.name != active_key_id
        ),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    retained_keys = tuple(_read_keypair(root, path.name)[0] for path in retained[: MAX_DECRYPTION_KEYS - 1])
    return (active_private_key, *retained_keys)


def decrypt_submission_key(encrypted_key: bytes, root: Path = KEYS_DIR) -> bytes:
    """Decrypt against active and retained generations for rotation overlap."""
    for private_key in load_submission_private_keys(root):
        try:
            return private_key.decrypt(
                encrypted_key,
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        except ValueError:
            continue
    raise SubmissionKeyError("Encrypted submission key did not match a retained key generation")


def provision_submission_keys(root: Path = KEYS_DIR) -> str:
    """Provision once or migrate a matching legacy pair; never rotate implicitly."""
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(stat.S_IRWXU)
    pointer_path = root / ACTIVE_KEY_POINTER
    if pointer_path.exists():
        key_id, _, _ = load_active_public_key(root)
        return key_id

    legacy_private_path = root / LEGACY_PRIVATE_KEY_FILENAME
    legacy_public_path = root / LEGACY_PUBLIC_KEY_FILENAME
    if legacy_private_path.exists() or legacy_public_path.exists():
        if not legacy_private_path.is_file() or not legacy_public_path.is_file():
            raise SubmissionKeyError("Both legacy submission key files are required for migration")
        private_pem = legacy_private_path.read_bytes()
        public_pem = legacy_public_path.read_bytes()
    else:
        private_pem, public_pem = _serialize_keypair(rsa.generate_private_key(public_exponent=65537, key_size=2048))

    key_id = _install_keypair(root, private_pem, public_pem)
    _activate_key(root, key_id)
    return key_id


def rotate_submission_keys(root: Path = KEYS_DIR) -> str:
    """Explicitly activate a new generation while retaining all prior keys."""
    provision_submission_keys(root)
    private_pem, public_pem = _serialize_keypair(rsa.generate_private_key(public_exponent=65537, key_size=2048))
    key_id = _install_keypair(root, private_pem, public_pem)
    _activate_key(root, key_id)
    return key_id


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("provision", "rotate", "show-active"))
    parser.add_argument("--keys-dir", type=Path, default=KEYS_DIR)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "provision":
        key_id = provision_submission_keys(args.keys_dir)
    elif args.command == "rotate":
        key_id = rotate_submission_keys(args.keys_dir)
    else:
        key_id, _, _ = load_active_public_key(args.keys_dir)
    print(key_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
