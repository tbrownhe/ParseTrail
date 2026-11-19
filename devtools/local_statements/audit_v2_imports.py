"""Audit V2 recognition and import warnings without importing or opening a profile."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import signal
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from threading import Event

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "client/src"), str(REPOSITORY / "client"), str(REPOSITORY)]

from parsetrail.core.v2_bounded_pdf_text import pdf_decode_operation  # noqa: E402
from parsetrail.core.v2_catalog_admission import admit_pilot_definition  # noqa: E402
from parsetrail.core.v2_data_catalog import (  # noqa: E402
    MAX_CATALOG_BYTES,
    SIGNATURE_BYTES,
    VerifiedCatalog,
    load_trusted_catalog_keys,
    verify_catalog,
)
from parsetrail.core.v2_format_recognition import (  # noqa: E402
    ImportCancelled,
    catalog_digest,
    recognize_catalog_source,
)
from parsetrail.core.v2_parallel_preparation import (  # noqa: E402
    DEFAULT_PREPARATION_WORKERS,
    MAX_PREPARATION_WORKERS,
    OrderedPreparation,
    PreparationCancelled,
    preparation_workers,
)
from parsetrail.core.v2_source_pipeline import MAX_SOURCE_BYTES  # noqa: E402

MAX_FILES = 10_000
MAX_SCANNED_ENTRIES = 100_000
MAX_REPORT_BYTES = 64 * 1024 * 1024
_REPORT_GUIDANCE = {
    "report_exists": "The report already exists. Choose a new filename; reports are never overwritten.",
    "report_parent_unavailable": "The report folder is missing or inaccessible. Choose an existing writable folder.",
    "report_write_failed": "The report could not be written. Check the destination folder's permissions and free space.",
}
_SAFE_ERRORS = {
    "audit_cancelled",
    "audit_directory_unavailable",
    "audit_entry_limit",
    "audit_file_limit",
    "audit_metadata_limit",
    "audit_no_files",
    "audit_pattern_invalid",
    "catalog_ambiguous_match",
    "catalog_no_match",
    "catalog_size",
    "cancelled",
    "invalid_signature",
    "import_preparation_workers_invalid",
    "no_matching_format",
    "source_changed",
    "source_file_unavailable",
    "source_size",
    "trust_keys_shape",
    "untrusted_key",
} | _REPORT_GUIDANCE.keys()


def _linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def _fingerprint(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns


def read_limited(path: Path, limit: int) -> bytes:
    """Refuse links, bound reads, and reject source changes during the read."""
    if _linked(path) or not path.is_file():
        raise ValueError("source_file_unavailable")
    before = path.stat()
    if not 0 < before.st_size <= limit:
        raise ValueError("source_size")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if _linked(path) or _fingerprint(before) != _fingerprint(opened):
            raise ValueError("source_changed")
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if _linked(path) or not (
        _fingerprint(before) == _fingerprint(opened) == _fingerprint(after) == _fingerprint(path.stat())
    ):
        raise ValueError("source_changed")
    if len(data) != before.st_size or not 0 < len(data) <= limit:
        raise ValueError("source_changed")
    return data


def load_catalog(*, release: Path | None = None, trust_keys: Path | None = None, definitions: Path | None = None):
    if definitions is not None:
        if release is not None or trust_keys is not None:
            raise ValueError("development_mode_has_no_release_trust")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from scripts.v2_catalog_release import signed_catalog_bytes

        # Development admission uses an ephemeral key only in memory. Nothing is
        # installed, published or represented as the user's installed catalog.
        private = Ed25519PrivateKey.generate()
        _snapshot, _signature, catalog = signed_catalog_bytes(
            definitions, private, release_sequence=1, source_revision="0" * 40
        )
        del private
        return catalog, "development_definitions_not_installed_catalog"
    if release is None:
        raise ValueError("catalog_release_required")
    if _linked(release) or not release.is_dir():
        raise ValueError("catalog_release_unavailable")
    if trust_keys is None:
        keys = load_trusted_catalog_keys()
    else:
        raw = json.loads(read_limited(trust_keys, 16 * 1024))
        if type(raw) is not dict or not 1 <= len(raw) <= 64:
            raise ValueError("trust_keys_shape")
        try:
            keys = {key: bytes.fromhex(value) for key, value in raw.items()}
        except (TypeError, ValueError):
            raise ValueError("trust_keys_shape") from None
        if any(type(key) is not str or len(value) != 32 for key, value in keys.items()):
            raise ValueError("trust_keys_shape")
    catalog = verify_catalog(
        read_limited(release / "catalog.json", MAX_CATALOG_BYTES),
        read_limited(release / "catalog.sig", SIGNATURE_BYTES),
        keys,
        admit_pilot_definition,
    )
    return catalog, "verified_release"


def selected_paths(directory: Path, *, patterns: tuple[str, ...], recursive: bool, max_files: int):
    if _linked(directory) or not directory.is_dir():
        raise ValueError("audit_directory_unavailable")
    if not 1 <= max_files <= MAX_FILES:
        raise ValueError("audit_file_limit")
    if not patterns or any(
        not pattern or len(pattern) > 200 or "/" in pattern or "\\" in pattern or ":" in pattern for pattern in patterns
    ):
        raise ValueError("audit_pattern_invalid")
    # Exact names need no sibling inventory at all. This also permits
    # tightly scoped diagnosis when only specific originals were authorized.
    exact = tuple(directory / pattern for pattern in patterns)
    if not recursive and all(not any(character in pattern for character in "*?[") for pattern in patterns):
        # A missing/linked explicit file gets a per-file refusal, not a wider scan.
        paths = tuple(
            sorted(
                {path for path in exact if path.suffix.lower() in {".pdf", ".csv"}},
                key=lambda path: path.name.casefold(),
            )
        )
        if len(paths) > max_files:
            raise ValueError("audit_file_limit")
        if not paths:
            raise ValueError("audit_no_files")
        return paths

    def unreadable(_error):
        raise ValueError("audit_directory_unavailable")

    selected, count = [], 0
    for current, directories, filenames in os.walk(directory, followlinks=False, onerror=unreadable):
        count += len(directories) + len(filenames)
        if count > MAX_SCANNED_ENTRIES:
            raise ValueError("audit_entry_limit")
        directories[:] = sorted(name for name in directories if recursive and not _linked(Path(current) / name))
        for name in sorted(filenames):
            path = Path(current) / name
            if (
                path.suffix.lower() in {".pdf", ".csv"}
                and any(fnmatch.fnmatchcase(name.casefold(), pattern.casefold()) for pattern in patterns)
                and not _linked(path)
                and path.is_file()
            ):
                selected.append(path)
                if len(selected) > max_files:
                    raise ValueError("audit_file_limit")
    if not selected:
        raise ValueError("audit_no_files")
    return tuple(sorted(selected, key=lambda path: path.relative_to(directory).as_posix().casefold()))


def _date(value):
    return {
        "iso": value.iso,
        "provenance": value.provenance,
        "locations": [location.model_dump(exclude_none=True) for location in value.locations],
    }


def _candidate(candidate):
    return {
        "parser_id": candidate.parser_id,
        "revision": candidate.revision,
        "definition_sha256": candidate.definition_sha256,
        "engine_version": candidate.engine_version,
        "extractor_version": candidate.extractor_version,
        "row_count": candidate.row_count,
        "source_account_group_count": len(candidate.source_accounts),
        "start": _date(candidate.start),
        "end": _date(candidate.end),
        "requires_review": bool(candidate.attention_codes),
        "warnings": [
            {
                "code": warning.code,
                "classification": warning.classification,
                "occurrence_count": warning.occurrence_count,
                "locations": [location.model_dump(exclude_none=True) for location in warning.locations],
            }
            for warning in candidate.warnings
        ],
    }


def _error(error: Exception) -> str:
    # Exceptions from libraries may contain source text, filenames or PDF metadata.
    # Only explicitly admitted public refusal codes reach the metadata report.
    return str(error) if str(error) in _SAFE_ERRORS else "audit_file_failed"


def _audit_source(item, *, directory, catalog, show_filenames, cancelled):
    """Prepare one metadata result without retaining source bytes or GUI state."""
    index, path = item
    record = {"file": f"fixture-{index + 1:05d}{path.suffix.lower()}"}
    if show_filenames:
        record["file"] = path.relative_to(directory).as_posix()
    source = recognition = None
    try:
        if cancelled():
            raise ImportCancelled("cancelled")
        source = read_limited(path, MAX_SOURCE_BYTES)
        digest = hashlib.sha256(source).hexdigest()
        record["source_sha256"] = digest
        if not show_filenames:
            record["file"] = f"fixture-{index + 1:05d}-{digest[:12]}{path.suffix.lower()}"
        with pdf_decode_operation():
            recognition = recognize_catalog_source(
                source, catalog=catalog, suffix=path.suffix.lower(), cancelled=cancelled
            )
        source = None
        if hashlib.sha256(read_limited(path, MAX_SOURCE_BYTES)).hexdigest() != digest:
            raise ValueError("source_changed")
        candidates = [_candidate(candidate) for candidate in recognition.candidates]
        if not candidates:
            raise ValueError("no_matching_format")
        record.update(
            status="recognized" if len(candidates) == 1 else "ambiguous",
            requires_review=len(candidates) != 1 or any(candidate["requires_review"] for candidate in candidates),
            candidates=candidates,
        )
    except ImportCancelled:
        raise
    except Exception as error:
        if cancelled():
            raise ImportCancelled("cancelled") from None
        record.update(status="failed", error=_error(error))
    finally:
        source = recognition = None
    return record


def audit_directory(
    directory: Path,
    *,
    catalog: VerifiedCatalog,
    mode: str,
    patterns: tuple[str, ...] = ("*.pdf", "*.csv"),
    recursive: bool = False,
    max_files: int = MAX_FILES,
    show_filenames: bool = False,
    cancelled: Callable[[], bool] | None = None,
    workers: int = DEFAULT_PREPARATION_WORKERS,
) -> dict:
    """Prepare bounded metadata concurrently and retain it in selection order."""
    workers = preparation_workers(workers)
    paths = selected_paths(directory, patterns=patterns, recursive=recursive, max_files=max_files)
    stop = cancelled or (lambda: False)
    records, warnings, counts = [], Counter(), Counter()
    metadata_bytes = 0

    def prepare(item, *, cancelled):
        return _audit_source(
            item, directory=directory, catalog=catalog, show_filenames=show_filenames, cancelled=cancelled
        )

    with OrderedPreparation(enumerate(paths), prepare, workers=workers, cancelled=stop) as queue:
        for _path in paths:
            try:
                with queue.take_next() as record:
                    size = len(json.dumps(record, separators=(",", ":")).encode("utf-8"))
                    if metadata_bytes + size > MAX_REPORT_BYTES:
                        counts["metadata_limit_reached"] = 1
                        break
                    metadata_bytes += size
                    records.append(record)
                    counts[record["status"]] += 1
                    counts["requires_review"] += record.get("requires_review", False)
                    for candidate in record.get("candidates", ()):
                        for warning in candidate["warnings"]:
                            warnings[warning["classification"], warning["code"]] += warning["occurrence_count"]
            except (ImportCancelled, PreparationCancelled):
                counts["cancelled"] = 1
                break
    summary = {
        "files_selected": len(paths),
        "files_completed": len(records),
        "files_remaining": len(paths) - len(records),
        **{key: counts[key] for key in ("recognized", "ambiguous", "requires_review", "failed", "cancelled")},
        "metadata_limit_reached": bool(counts["metadata_limit_reached"]),
    }
    return {
        "schema_version": 1,
        "scope": "read_only_recognition_not_account_assignment_posting_or_complete_capture",
        "mode": mode,
        "catalog": {
            "sha256": catalog_digest(catalog),
            "release_sequence": catalog.release_sequence,
            "source_revision": catalog.source_revision,
        },
        "summary": summary,
        "warning_occurrences": [
            {"classification": classification, "code": code, "count": count}
            for (classification, code), count in sorted(warnings.items())
        ],
        "files": records,
    }


def exit_code(report: dict) -> int:
    summary = report["summary"]
    if summary["cancelled"]:
        return 130
    return int(bool(summary["requires_review"] or summary["failed"] or summary["files_remaining"]))


def _validate_report_destination(path: Path) -> None:
    """Reject invalid destinations before spending time reading statements."""
    try:
        if path.exists() or path.is_symlink():
            raise ValueError("report_exists")
        if not path.parent.is_dir():
            raise ValueError("report_parent_unavailable")
    except OSError:
        raise ValueError("report_parent_unavailable") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    catalog_mode = parser.add_mutually_exclusive_group(required=True)
    catalog_mode.add_argument(
        "--catalog-release", type=Path, help="Explicit directory with catalog.json and catalog.sig"
    )
    catalog_mode.add_argument(
        "--development-definitions", type=Path, help="Explicit development declarations, not installed trust"
    )
    parser.add_argument("--trust-keys", type=Path, help="Explicit JSON mapping data-ed25519 key IDs to public key hex")
    parser.add_argument("--pattern", action="append", help="Repeatable basename glob; default *.pdf and *.csv")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--max-files", type=int, default=MAX_FILES)
    parser.add_argument(
        "--workers",
        type=int,
        choices=range(1, MAX_PREPARATION_WORKERS + 1),
        default=DEFAULT_PREPARATION_WORKERS,
        help="Concurrent preparations, 1..4; default available CPUs capped at 4",
    )
    parser.add_argument("--report", type=Path, help="Create a NEW JSON report in an existing folder; never overwrite")
    parser.add_argument(
        "--show-filenames", action="store_true", help="Include relative filenames in the private JSON report"
    )
    args = parser.parse_args(argv)
    if args.trust_keys is not None and args.catalog_release is None:
        parser.error("--trust-keys requires --catalog-release")
    if args.show_filenames and args.report is None:
        parser.error("--show-filenames requires --report")
    stop = Event()
    previous = None
    try:
        if args.report is not None:
            _validate_report_destination(args.report)
        catalog, mode = load_catalog(
            release=args.catalog_release, trust_keys=args.trust_keys, definitions=args.development_definitions
        )
        previous = signal.signal(signal.SIGINT, lambda _signal, _frame: stop.set())
        report = audit_directory(
            args.directory,
            catalog=catalog,
            mode=mode,
            patterns=tuple(args.pattern or ("*.pdf", "*.csv")),
            recursive=args.recursive,
            max_files=args.max_files,
            show_filenames=args.show_filenames,
            cancelled=stop.is_set,
            workers=args.workers,
        )
        if args.report is not None:
            try:
                with args.report.open("x", encoding="utf-8", newline="") as stream:
                    json.dump(report, stream, indent=2, sort_keys=True)
                    stream.write("\n")
            except FileExistsError:
                raise ValueError("report_exists") from None
            except OSError:
                raise ValueError("report_write_failed") from None
        # Console is deliberately aggregate-only, even with --show-filenames.
        print(json.dumps({key: report[key] for key in ("mode", "summary", "warning_occurrences")}, sort_keys=True))
        return exit_code(report)
    except KeyboardInterrupt:
        print(json.dumps({"error": "audit_cancelled"}))
        return 130
    except Exception as error:
        reason = _error(error)
        details = {"error": "audit_setup_failed", "reason": reason}
        if reason in _REPORT_GUIDANCE:
            details["message"] = _REPORT_GUIDANCE[reason]
        print(json.dumps(details))
        return 2
    finally:
        if previous is not None:
            signal.signal(signal.SIGINT, previous)


if __name__ == "__main__":
    raise SystemExit(main())
