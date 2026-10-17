"""Local 2.0 catalog artifacts are complete, reproducible and independently verified."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import verify_catalog
from scripts.v2_catalog_release import REPOSITORY_ROOT, load_offline_key, write_release

DEFINITIONS = Path(__file__).parents[2] / "devtools" / "parser_engine_pilot"


def test_all_current_definitions_build_reproducible_verified_artifacts(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first = write_release(DEFINITIONS, private, first_dir, release_sequence=7, source_revision="a" * 40)
    second = write_release(DEFINITIONS, private, second_dir, release_sequence=7, source_revision="a" * 40)
    assert len(first.definitions) == len(second.definitions) == 23
    assert first_dir.joinpath("catalog.json").read_bytes() == second_dir.joinpath("catalog.json").read_bytes()
    assert first_dir.joinpath("catalog.sig").read_bytes() == second_dir.joinpath("catalog.sig").read_bytes()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    reopened = verify_catalog(
        first_dir.joinpath("catalog.json").read_bytes(),
        first_dir.joinpath("catalog.sig").read_bytes(),
        {first.key_id: public},
        admit_pilot_definition,
    )
    assert reopened == first
    with pytest.raises(FileExistsError, match="catalog_output_exists"):
        write_release(DEFINITIONS, private, first_dir, release_sequence=8, source_revision="b" * 40)
    assert first_dir.joinpath("catalog.json").read_bytes() == first.snapshot


def test_rejected_definition_or_key_leaves_no_release(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "broken-definition.json").write_bytes(b'{"operation":"python_eval"}')
    output = tmp_path / "release"
    with pytest.raises(ValueError, match="unsupported_definition_operation"):
        write_release(definitions, private, output, release_sequence=1, source_revision="a" * 40)
    assert not output.exists()

    key_path = tmp_path / "encrypted.pem"
    key_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(b"temporary-test-passphrase"),
        )
    )
    assert load_offline_key(key_path, b"temporary-test-passphrase").public_key() == private.public_key()
    key_path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    with pytest.raises(ValueError, match="unencrypted_signing_key"):
        load_offline_key(key_path, b"temporary-test-passphrase")
    with pytest.raises(ValueError, match="signing_key_inside_repository"):
        load_offline_key(REPOSITORY_ROOT / "private-key.pem", b"temporary-test-passphrase")
