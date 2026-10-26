"""Generate a synthetic source-runtime baseline for the fixed frozen diagnostic.

This writes a new inline manifest, never signing/releasing a production catalog.
Its private key exists only in memory. Public fixture inputs are checked in under
devtools/parser_engine_pilot; none are bundled into the application by this tool.
"""

from __future__ import annotations

import base64
import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key, verify_catalog
from parsetrail.core.v2_fixture_verification import (
    MAX_MANIFEST_BYTES,
    FixtureVerificationError,
    isolated_fixture_environment,
    publish_new_json,
    validate_manifest,
)
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import import_catalog_source


def build_fixture_manifest() -> bytes:
    """Use actual source workers; expected hashes are a baseline, not a new oracle."""
    if getattr(sys, "frozen", False):
        raise FixtureVerificationError("baseline_requires_source_runtime")
    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

    root = Path(__file__).resolve().parents[2] / "devtools" / "parser_engine_pilot"
    cases = family_sources()
    paths = sorted(root.glob("*definition.json"))
    if len(cases) != 23 or {case.definition_name for case in cases} != {path.name for path in paths}:
        raise FixtureVerificationError("fixture_matrix_mismatch")
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    entries = []
    for path in paths:
        definition = path.read_bytes()
        identity = admit_pilot_definition(definition)
        entries.append(
            {
                "parser_id": identity.parser_id,
                "revision": identity.revision,
                "suffix": identity.suffix,
                "size": len(definition),
                "sha256": hashlib.sha256(definition).hexdigest(),
                "content_base64": base64.b64encode(definition).decode("ascii"),
            }
        )
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": "0" * 40,
            "key_id": key_id,
            "definitions": sorted(entries, key=lambda entry: entry["parser_id"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    signature = key.sign(snapshot)
    catalog = verify_catalog(snapshot, signature, {key_id: public}, admit_pilot_definition)
    fixtures = []
    with tempfile.TemporaryDirectory(prefix="parsetrail-fixture-baseline-") as temporary:
        directory = Path(temporary)
        with isolated_fixture_environment(directory), V2ProfileStore.create(directory / "baseline.db") as store:
            for case in cases:
                identity = admit_pilot_definition((root / case.definition_name).read_bytes())
                result = import_catalog_source(store, case.source, catalog=catalog, suffix=case.suffix)
                if result.evidence.parser_id != identity.parser_id:
                    raise FixtureVerificationError("baseline_parser_mismatch")
                fixtures.append(
                    {
                        "fixture_id": identity.parser_id,
                        "parser_id": identity.parser_id,
                        "suffix": case.suffix,
                        "source_base64": base64.b64encode(case.source).decode("ascii"),
                        "expected_evidence_sha256": hashlib.sha256(
                            result.evidence.model_dump_json().encode("utf-8")
                        ).hexdigest(),
                    }
                )
            if store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() != (0,):
                raise FixtureVerificationError("baseline_automatic_journal")
    content = (
        json.dumps(
            {
                "schema_version": 1,
                "purpose": "synthetic_fixture_baseline",
                "baseline": {
                    "runtime": "source",
                    "comparison": "synthetic_evidence_hash_equality_only",
                    "source_revision": "fixture_placeholder_not_release",
                    "python_version": platform.python_version(),
                    "platform_system": platform.system(),
                    "platform_machine": platform.machine(),
                },
                "catalog_snapshot_base64": base64.b64encode(snapshot).decode("ascii"),
                "catalog_signature_base64": base64.b64encode(signature).decode("ascii"),
                "public_key_base64": base64.b64encode(public).decode("ascii"),
                "fixtures": fixtures,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    if len(content) > MAX_MANIFEST_BYTES:
        raise FixtureVerificationError("manifest_size")
    validate_manifest(content)
    return content


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) != 2 or argv[0] != "--output" or argv[1].startswith("--"):
            raise FixtureVerificationError("generator_arguments")
        destination = Path(argv[1])
        if destination.exists() or destination.is_symlink():
            raise FixtureVerificationError("destination_exists")
        if not destination.parent.is_dir():
            raise FixtureVerificationError("destination_parent_missing")
        content = build_fixture_manifest()
        publish_new_json(destination, content)
        return 0
    except Exception:
        if sys.stderr is not None:
            sys.stderr.write("fixture_manifest_generation_failed\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
