"""Local 2.0 catalog artifacts are complete, reproducible and independently verified."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.plugin_manifest import key_id_for_public_key as plugin_key_id
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import (
    CatalogError,
    key_id_for_public_key,
    load_trusted_catalog_keys,
    verify_catalog,
)
from scripts.v2_catalog_release import REPOSITORY_ROOT, load_offline_key, require_shipped_plugin_key, write_release

DEFINITIONS = Path(__file__).parents[2] / "devtools" / "parser_engine_pilot"


def test_catalog_reuses_plugin_release_public_trust(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    trust_store = tmp_path / "plugin-release-keys.json"
    trust_store.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "keys": [
                    {
                        "key_id": plugin_key_id(raw),
                        "public_key": base64.b64encode(raw).decode("ascii"),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert load_trusted_catalog_keys(trust_store) == {key_id_for_public_key(raw): raw}
    require_shipped_plugin_key(private, trust_store)
    with pytest.raises(ValueError, match="signing_key_not_shipped_plugin_key"):
        require_shipped_plugin_key(Ed25519PrivateKey.generate(), trust_store)


def test_all_current_definitions_build_reproducible_verified_artifacts(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first = write_release(DEFINITIONS, private, first_dir, release_sequence=7, source_revision="a" * 40)
    second = write_release(DEFINITIONS, private, second_dir, release_sequence=7, source_revision="a" * 40)
    assert len(first.definitions) == len(second.definitions) == 23
    assert all(item.account_context is not None for item in first.definitions)
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
    changed = json.loads(first.snapshot)
    changed["definitions"][0]["account_context"]["kind"] = (
        "liability" if changed["definitions"][0]["account_context"]["kind"] == "asset" else "asset"
    )
    with pytest.raises(CatalogError, match="invalid_signature"):
        verify_catalog(json.dumps(changed).encode(), first.signature, {first.key_id: public}, admit_pilot_definition)
    with pytest.raises(FileExistsError, match="catalog_output_exists"):
        write_release(DEFINITIONS, private, first_dir, release_sequence=8, source_revision="b" * 40)
    assert first_dir.joinpath("catalog.json").read_bytes() == first.snapshot


def test_account_context_manifest_rejects_unknown_and_duplicate_keys(tmp_path: Path) -> None:
    from scripts.v2_catalog_release import signed_catalog_bytes

    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = DEFINITIONS / "synchrony-table-pilot-definition.json"
    (definitions / source.name).write_bytes(source.read_bytes())
    manifest = definitions / "account-contexts.json"
    manifest.write_text('{"missing_parser":{"institution_key":"citi","kind":"liability"}}')
    with pytest.raises(ValueError, match="unknown_account_context_parser"):
        signed_catalog_bytes(definitions, Ed25519PrivateKey.generate(), release_sequence=1, source_revision="a" * 40)
    manifest.write_text('{"synchrony_amazon_store_card":null}')
    with pytest.raises(ValueError):
        signed_catalog_bytes(definitions, Ed25519PrivateKey.generate(), release_sequence=1, source_revision="a" * 40)
    manifest.write_text('{"synchrony_amazon_store_card":{},"synchrony_amazon_store_card":{}}')
    with pytest.raises(ValueError, match="account_context_manifest_shape"):
        signed_catalog_bytes(definitions, Ed25519PrivateKey.generate(), release_sequence=1, source_revision="a" * 40)


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
