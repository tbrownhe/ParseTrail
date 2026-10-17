"""All current pilot definitions pass one strict local catalog admission gate."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key, verify_catalog


def test_every_current_pilot_definition_admits_in_one_signed_local_snapshot() -> None:
    definitions = []
    for path in sorted(Path(__file__).parent.glob("*definition.json")):
        content = path.read_bytes()
        identity = admit_pilot_definition(content)
        definitions.append(
            {
                "parser_id": identity.parser_id,
                "revision": identity.revision,
                "suffix": identity.suffix,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    assert len(definitions) == 23
    assert len({item["parser_id"] for item in definitions}) == 23
    definitions.sort(key=lambda item: item["parser_id"])
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public_key)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": "a" * 40,
            "key_id": key_id,
            "definitions": definitions,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    release = verify_catalog(snapshot, private_key.sign(snapshot), {key_id: public_key}, admit_pilot_definition)
    assert len(release.definitions) == 23


def test_unknown_operation_duplicate_keys_and_executable_fields_refuse() -> None:
    source = Path(__file__).with_name("synchrony-table-pilot-definition.json").read_bytes()
    changed = source.replace(b"anchored_columns_table_v1", b"arbitrary_python_v1")
    with pytest.raises(ValueError, match="unsupported_definition_operation"):
        admit_pilot_definition(changed)
    with pytest.raises(ValueError, match="invalid_definition_json"):
        admit_pilot_definition(source.replace(b'"schema_version": 1,', b'"schema_version": 1, "schema_version": 1,'))
    with pytest.raises(ValueError, match="invalid_definition"):
        admit_pilot_definition(source.replace(b'"schema_version": 1,', b'"schema_version": 1, "python": "exec",'))
    with pytest.raises(ValueError, match="invalid_definition_shape"):
        admit_pilot_definition(b"[]")
