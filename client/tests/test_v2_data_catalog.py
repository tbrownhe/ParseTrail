"""Signed data definitions are verified as exact bytes before admission."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import (
    CatalogCache,
    CatalogCancelled,
    CatalogError,
    CatalogRollbackError,
    DefinitionIdentity,
    key_id_for_public_key,
    verify_catalog,
)

DEFINITION = b'{"parser_id":"synthetic_cash","revision":"1","suffix":".csv","capabilities":["table_rows_v1"]}'


def signed_catalog(
    *,
    definition: bytes = DEFINITION,
    claimed_hash: str | None = None,
    sequence: int = 3,
    private: Ed25519PrivateKey | None = None,
):
    private = private or Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    envelope = {
        "schema_version": 1,
        "engine_contract": 1,
        "release_sequence": sequence,
        "source_revision": "a" * 40,
        "key_id": key_id,
        "definitions": [
            {
                "parser_id": "synthetic_cash",
                "revision": "1",
                "suffix": ".csv",
                "size": len(definition),
                "sha256": claimed_hash or hashlib.sha256(definition).hexdigest(),
                "content_base64": base64.b64encode(definition).decode(),
            }
        ],
    }
    snapshot = json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    return snapshot, private.sign(snapshot), {key_id: public}


def admit(content: bytes) -> DefinitionIdentity:
    declaration = json.loads(content)
    if set(declaration) != {"parser_id", "revision", "suffix", "capabilities"}:
        raise ValueError("unknown declaration fields")
    if declaration["capabilities"] != ["table_rows_v1"]:
        raise ValueError("unsupported operation")
    return DefinitionIdentity(declaration["parser_id"], declaration["revision"], declaration["suffix"])


def test_exact_signed_snapshot_and_definition_are_admitted() -> None:
    snapshot, signature, keys = signed_catalog()
    release = verify_catalog(snapshot, signature, keys, admit)
    assert release.release_sequence == 3
    assert release.definitions[0].content == DEFINITION
    assert release.definitions[0].identity.parser_id == "synthetic_cash"


def test_tamper_untrusted_key_and_unknown_operation_refuse_before_use() -> None:
    snapshot, signature, keys = signed_catalog()
    calls = 0

    def counted_admit(content: bytes) -> DefinitionIdentity:
        nonlocal calls
        calls += 1
        return admit(content)

    with pytest.raises(CatalogError, match="invalid_signature"):
        verify_catalog(snapshot + b" ", signature, keys, counted_admit)
    assert calls == 0
    with pytest.raises(CatalogError, match="untrusted_key"):
        verify_catalog(snapshot, signature, {}, counted_admit)
    bad_definition = DEFINITION.replace(b"table_rows_v1", b"eval_v1")
    bad_snapshot, bad_signature, bad_keys = signed_catalog(definition=bad_definition)
    with pytest.raises(CatalogError, match="definition_rejected"):
        verify_catalog(bad_snapshot, bad_signature, bad_keys, admit)


def test_signed_but_changed_definition_hash_refuses() -> None:
    snapshot, signature, keys = signed_catalog(claimed_hash="0" * 64)
    with pytest.raises(CatalogError, match="definition_hash_mismatch"):
        verify_catalog(snapshot, signature, keys, admit)


def test_offline_cache_activation_rollback_and_cancellation(tmp_path: Path) -> None:
    private = Ed25519PrivateKey.generate()
    first, first_signature, keys = signed_catalog(private=private)
    cache = CatalogCache(tmp_path / "catalog", keys, admit)
    assert cache.load_current() is None
    assert cache.activate(first, first_signature).release_sequence == 3
    assert cache.load_current().snapshot == first
    second, second_signature, _ = signed_catalog(private=private, sequence=4)
    assert cache.activate(second, second_signature).release_sequence == 4
    assert cache.load_current().release_sequence == 4
    with pytest.raises(CatalogRollbackError, match="catalog_rollback"):
        cache.activate(first, first_signature)

    checks = 0

    def cancel_before_pointer() -> bool:
        nonlocal checks
        checks += 1
        return checks == 2

    third, third_signature, _ = signed_catalog(private=private, sequence=5)
    with pytest.raises(CatalogCancelled, match="cancelled"):
        cache.activate(third, third_signature, cancelled=cancel_before_pointer)
    assert cache.load_current().release_sequence == 4
    assert cache.activate(first, first_signature, allow_rollback=True).release_sequence == 3
    assert cache.load_current().release_sequence == 3


def test_offline_cache_tamper_refuses_without_fallback(tmp_path: Path) -> None:
    snapshot, signature, keys = signed_catalog()
    cache = CatalogCache(tmp_path / "catalog", keys, admit)
    cache.activate(snapshot, signature)
    release_dir = next((cache.root / "releases").iterdir())
    (release_dir / "catalog.json").write_bytes(snapshot + b" ")
    with pytest.raises(CatalogError, match="catalog_cache_hash"):
        cache.load_current()
