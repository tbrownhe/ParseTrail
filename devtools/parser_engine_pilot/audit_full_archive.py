"""Read-only archive replay through the signed 2.0 evidence path.

Only aggregate counts appear on stdout. Optional source-level failures must be
written outside the repository. No database or source file is opened for write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from collections import Counter
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_pdf_routing import PDFRoutingError, select_pdf_definition
from parsetrail.core.v2_source_pipeline import MAX_SOURCE_BYTES, SourcePipelineError, build_source_evidence

from client.scripts.v2_catalog_release import signed_catalog_bytes

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEFINITIONS = Path(__file__).parent


def _test_signed_catalog(definitions_dir: Path):
    """Authenticate the checked-in declarations without a production key."""
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    with tempfile.TemporaryDirectory(prefix="v2-archive-catalog-") as temporary:
        staging = Path(temporary)
        for path in sorted(definitions_dir.glob("*definition.json")):
            (staging / path.name).write_bytes(path.read_bytes())
        context_manifest = definitions_dir / "account-contexts.json"
        if context_manifest.is_file():
            (staging / context_manifest.name).write_bytes(context_manifest.read_bytes())
        snapshot, signature, verified = signed_catalog_bytes(
            staging, private, release_sequence=1, source_revision="a" * 40
        )
        assert verified.key_id == key_id_for_public_key(public)
        assert verified.snapshot == snapshot and verified.signature == signature
        return verified


def audit(
    archives: tuple[Path, ...], definitions_dir: Path = DEFAULT_DEFINITIONS, *, suffix: str = ".pdf"
) -> tuple[dict, list[dict]]:
    catalog = _test_signed_catalog(definitions_dir)
    definitions = {item.identity.parser_id: item for item in catalog.definitions}
    files = tuple(sorted(path for archive in archives for path in archive.rglob("*") if path.suffix.lower() == suffix))
    if not files:
        raise ValueError("no_archive_sources")
    route_counts: Counter[str] = Counter()
    parsed_counts: Counter[str] = Counter()
    rows: Counter[str] = Counter()
    failures: list[dict] = []
    for index, path in enumerate(files, 1):
        route = None
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("source_unavailable")
            before = path.stat()
            if not 0 < before.st_size <= MAX_SOURCE_BYTES:
                raise ValueError("source_size")
            with path.open("rb") as stream:
                source = stream.read(MAX_SOURCE_BYTES + 1)
            if len(source) != before.st_size:
                raise ValueError("source_changed")
            if suffix == ".pdf":
                route = select_pdf_definition(source, catalog)
                definition = definitions[route]
                evidence = build_source_evidence(source, definition.content, suffix=".pdf")
            else:
                matches = []
                for definition in catalog.definitions:
                    if definition.identity.suffix != ".csv":
                        continue
                    try:
                        candidate = build_source_evidence(source, definition.content, suffix=".csv")
                    except SourcePipelineError:
                        continue
                    matches.append((definition, candidate))
                if len(matches) != 1:
                    raise ValueError("catalog_ambiguous_match" if matches else "catalog_no_match")
                definition, evidence = matches[0]
                route = definition.identity.parser_id
            route_counts[route] += 1
            after = path.stat()
            if after.st_size != before.st_size or after.st_mtime_ns != before.st_mtime_ns:
                raise ValueError("source_changed")
            if (
                evidence.parser_id != route
                or evidence.definition_sha256 != definition.sha256
                or evidence.source_sha256 != hashlib.sha256(source).hexdigest()
            ):
                raise ValueError("evidence_definition_mismatch")
            parsed_counts[route] += 1
            rows[route] += (
                sum(len(account.rows) for account in evidence.payload.accounts)
                if evidence.payload.kind == "statement"
                else len(evidence.payload.rows)
            )
        except Exception as exc:
            reason = (
                str(exc)
                if isinstance(exc, (PDFRoutingError, SourcePipelineError))
                or (
                    type(exc) is ValueError
                    and str(exc)
                    in {
                        "source_unavailable",
                        "source_size",
                        "source_changed",
                        "evidence_definition_mismatch",
                        "catalog_no_match",
                        "catalog_ambiguous_match",
                    }
                )
                else type(exc).__name__
            )
            failures.append(
                {
                    "path": str(path),
                    "route": route,
                    "reason": reason,
                }
            )
        if index % 100 == 0:
            print(f"checked {index} of {len(files)} {suffix} sources", flush=True)
    return (
        {
            "source_count": len(files),
            "source_suffix": suffix,
            "catalog_definition_count": len(catalog.definitions),
            "route_counts": dict(sorted(route_counts.items())),
            "parsed_counts": dict(sorted(parsed_counts.items())),
            "observation_counts": dict(sorted(rows.items())),
            "failure_count": len(failures),
            "failure_reasons": dict(sorted(Counter(item["reason"] for item in failures).items())),
        },
        failures,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", action="append", type=Path, required=True)
    parser.add_argument("--definitions", type=Path, default=DEFAULT_DEFINITIONS)
    parser.add_argument("--suffix", choices=(".pdf", ".csv"), default=".pdf")
    parser.add_argument("--private-report", type=Path)
    args = parser.parse_args(argv)
    archives = tuple(path.resolve(strict=True) for path in args.archive)
    if any(not path.is_dir() for path in archives):
        parser.error("every archive must be a directory")
    report = (
        args.private_report.expanduser().parent.resolve(strict=True) / args.private_report.name
        if args.private_report is not None
        else None
    )
    if report is not None and report.is_relative_to(REPOSITORY_ROOT):
        parser.error("private report must be outside the repository")
    summary, failures = audit(archives, args.definitions, suffix=args.suffix)
    print(json.dumps(summary, sort_keys=True))
    if report is not None:
        with report.open("x", encoding="utf-8") as output:
            json.dump(failures, output, indent=2)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
