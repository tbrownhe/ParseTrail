from collections.abc import Generator
from pathlib import Path

import pytest
from app.core.submission_keys import (
    ACTIVE_KEY_POINTER,
    LEGACY_PRIVATE_KEY_FILENAME,
    LEGACY_PUBLIC_KEY_FILENAME,
    SubmissionKeyError,
    decrypt_submission_key,
    load_active_public_key,
    load_submission_private_keys,
    provision_submission_keys,
    rotate_submission_keys,
)
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Submission-key lifecycle tests use isolated filesystem roots."""
    yield


def _encrypt(public_pem: bytes, plaintext: bytes) -> bytes:
    public_key = serialization.load_pem_public_key(public_pem)
    assert isinstance(public_key, rsa.RSAPublicKey)
    return public_key.encrypt(
        plaintext,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


def _new_pair() -> tuple[bytes, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ),
    )


def test_loading_missing_keys_does_not_provision_at_import_or_read_time(tmp_path: Path) -> None:
    key_root = tmp_path / "keys"

    with pytest.raises(SubmissionKeyError):
        load_active_public_key(key_root)

    assert not key_root.exists()


def test_provision_is_stable_and_creates_a_matching_immutable_generation(tmp_path: Path) -> None:
    key_id = provision_submission_keys(tmp_path)
    second_key_id = provision_submission_keys(tmp_path)
    active_key_id, public_pem, _ = load_active_public_key(tmp_path)

    assert key_id == second_key_id == active_key_id
    assert len(load_submission_private_keys(tmp_path)) == 1
    ciphertext = _encrypt(public_pem, b"submission secret")
    assert decrypt_submission_key(ciphertext, tmp_path) == b"submission secret"


def test_rotation_retains_old_generation_for_inflight_uploads(tmp_path: Path) -> None:
    old_key_id = provision_submission_keys(tmp_path)
    _, old_public_pem, _ = load_active_public_key(tmp_path)
    old_ciphertext = _encrypt(old_public_pem, b"encrypted before rotation")

    new_key_id = rotate_submission_keys(tmp_path)
    _, new_public_pem, _ = load_active_public_key(tmp_path)
    new_ciphertext = _encrypt(new_public_pem, b"encrypted after rotation")

    assert new_key_id != old_key_id
    assert decrypt_submission_key(old_ciphertext, tmp_path) == b"encrypted before rotation"
    assert decrypt_submission_key(new_ciphertext, tmp_path) == b"encrypted after rotation"
    assert len(load_submission_private_keys(tmp_path)) == 2


def test_provision_migrates_a_matching_legacy_pair_without_rotating(tmp_path: Path) -> None:
    private_pem, public_pem = _new_pair()
    (tmp_path / LEGACY_PRIVATE_KEY_FILENAME).write_bytes(private_pem)
    (tmp_path / LEGACY_PUBLIC_KEY_FILENAME).write_bytes(public_pem)

    provision_submission_keys(tmp_path)

    _, active_public_pem, _ = load_active_public_key(tmp_path)
    assert active_public_pem == public_pem


def test_rejects_incomplete_legacy_pair_and_corrupt_pointer(tmp_path: Path) -> None:
    private_pem, _ = _new_pair()
    (tmp_path / LEGACY_PRIVATE_KEY_FILENAME).write_bytes(private_pem)

    with pytest.raises(SubmissionKeyError, match="Both legacy"):
        provision_submission_keys(tmp_path)

    (tmp_path / LEGACY_PRIVATE_KEY_FILENAME).unlink()
    (tmp_path / ACTIVE_KEY_POINTER).write_text('{"active_key_id":"../../escape"}', encoding="utf-8")
    with pytest.raises(SubmissionKeyError, match="pointer"):
        provision_submission_keys(tmp_path)
