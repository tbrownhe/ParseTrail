"""Prepare unsigned local catalog bytes for review; no private key or activation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from parsetrail.core.v2_data_catalog import load_trusted_catalog_keys

from scripts.v2_catalog_release import (
    UnsignedCatalog,
    _publish_files,
    unsigned_catalog_bytes,
    validate_prepared_catalog,
)


def prepare_catalog(
    definitions_dir: Path, public_key: bytes, output_dir: Path, *, release_sequence: int, source_revision: str
) -> UnsignedCatalog:
    """Atomically publish exact unsigned input and its human-readable review facts."""
    snapshot = unsigned_catalog_bytes(
        definitions_dir, public_key, release_sequence=release_sequence, source_revision=source_revision
    )
    prepared = validate_prepared_catalog(snapshot)
    envelope = prepared.envelope
    review = {
        "schema_version": 1,
        "unsigned": True,
        "activation": "Unavailable until the exact catalog bytes have a valid detached signature.",
        "catalog_sha256": prepared.sha256,
        "release_sequence": envelope.release_sequence,
        "source_revision": envelope.source_revision,
        "key_id": envelope.key_id,
        "catalog_schema_version": envelope.schema_version,
        "engine_contract": envelope.engine_contract,
        "definition_count": len(envelope.definitions),
        "definitions": [item.model_dump(exclude={"content_base64"}) for item in envelope.definitions],
    }
    _publish_files(
        output_dir,
        {
            "catalog.json": snapshot,
            "catalog.sha256": (prepared.sha256 + "  catalog.json\n").encode("ascii"),
            "review.json": (json.dumps(review, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        },
    )
    return prepared


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definitions-dir", type=Path, required=True)
    parser.add_argument("--key-id", required=True, help="A public catalog key ID shipped with this client")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-sequence", type=int, required=True)
    parser.add_argument("--source-revision", required=True)
    args = parser.parse_args(argv)
    keys = load_trusted_catalog_keys()
    if args.key_id not in keys:
        parser.error("--key-id must identify a shipped public catalog key")
    prepared = prepare_catalog(
        args.definitions_dir,
        keys[args.key_id],
        args.output_dir,
        release_sequence=args.release_sequence,
        source_revision=args.source_revision,
    )
    print(f"Prepared UNSIGNED catalog {prepared.envelope.release_sequence}; SHA-256 {prepared.sha256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
