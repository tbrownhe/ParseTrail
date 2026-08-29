from pathlib import Path

import pytest
from parsetrail.core.client_manifest import (
    CLIENT_MANIFEST_FILENAME,
    CLIENT_SIGNATURE_FILENAME,
)
from scripts.client_release import sign_release, verify_release
from scripts.plugin_release import generate_key


def _release_key(tmp_path: Path) -> tuple[Path, Path, bytes]:
    private_key_path = tmp_path / "offline" / "release-key.pem"
    trust_store_path = tmp_path / "plugin-release-keys.json"
    passphrase = b"a sufficiently long test passphrase"
    generate_key(private_key_path, trust_store_path, passphrase)
    return private_key_path, trust_store_path, passphrase


def test_signs_and_verifies_installer_release(tmp_path: Path) -> None:
    private_key, trust_store, passphrase = _release_key(tmp_path)
    release_dir = tmp_path / "clients" / "win64"
    release_dir.mkdir(parents=True)
    installer = release_dir / "parsetrail_1.2.3_win64_setup.exe"
    installer.write_bytes(b"installer bytes")

    manifest = sign_release(
        installer,
        "win64",
        "1.2.3",
        private_key,
        trust_store,
        passphrase,
        release_sequence=10,
    )

    assert manifest.release_sequence == 10
    assert (release_dir / CLIENT_MANIFEST_FILENAME).is_file()
    assert (release_dir / CLIENT_SIGNATURE_FILENAME).stat().st_size == 64
    assert verify_release(release_dir, trust_store) == manifest


def test_rejects_mismatched_filename_metadata(tmp_path: Path) -> None:
    private_key, trust_store, passphrase = _release_key(tmp_path)
    installer = tmp_path / "parsetrail_1.2.3_win64_setup.exe"
    installer.write_bytes(b"installer")

    with pytest.raises(ValueError, match="filename must be"):
        sign_release(
            installer,
            "macos",
            "1.2.3",
            private_key,
            trust_store,
            passphrase,
            release_sequence=10,
        )


def test_rejects_release_sequence_reuse(tmp_path: Path) -> None:
    private_key, trust_store, passphrase = _release_key(tmp_path)
    installer = tmp_path / "parsetrail_1.2.3_win64_setup.exe"
    installer.write_bytes(b"installer")
    kwargs = {
        "installer_path": installer,
        "platform": "win64",
        "version": "1.2.3",
        "private_key_path": private_key,
        "trust_store_path": trust_store,
        "passphrase": passphrase,
        "release_sequence": 10,
    }
    sign_release(**kwargs)

    with pytest.raises(ValueError, match="must exceed existing sequence"):
        sign_release(**kwargs)


def test_verification_rejects_tampered_installer(tmp_path: Path) -> None:
    private_key, trust_store, passphrase = _release_key(tmp_path)
    installer = tmp_path / "parsetrail_1.2.3_win64_setup.exe"
    installer.write_bytes(b"installer")
    sign_release(
        installer,
        "win64",
        "1.2.3",
        private_key,
        trust_store,
        passphrase,
        release_sequence=10,
    )
    installer.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="size mismatch|digest mismatch"):
        verify_release(tmp_path, trust_store)
