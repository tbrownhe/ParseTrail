"""Explicit synthetic fixture diagnostic, isolated from ordinary runtime trust.

Only the opt-in main entry calls this module. Inline fixtures and their supplied
test public key never enter a user profile, preferences or catalog cache. Matching
an expected evidence hash establishes baseline equality, not independent parity.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import platform
import struct
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FIXTURE_BYTES = 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_REPORT_BYTES = 128 * 1024
MAX_FIXTURES = 64
MAX_RUN_SECONDS = 180
IDENTIFIER = r"^[a-z][a-z0-9_-]{2,79}$"
SHA256 = r"^[0-9a-f]{64}$"


class FixtureVerificationError(ValueError):
    """Fixed redacted error code, never a path, source or exception message."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SourceBaseline(_Strict):
    runtime: Literal["source"]
    comparison: Literal["synthetic_evidence_hash_equality_only"]
    source_revision: Literal["fixture_placeholder_not_release"]
    python_version: str = Field(min_length=1, max_length=40, pattern=r"^[0-9a-zA-Z.+-]+$")
    platform_system: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")
    platform_machine: str = Field(min_length=1, max_length=40, pattern=r"^[a-zA-Z0-9_-]+$")


class FixtureSpec(_Strict):
    fixture_id: str = Field(pattern=IDENTIFIER)
    parser_id: str = Field(pattern=IDENTIFIER)
    suffix: Literal[".csv", ".pdf"]
    source_base64: str = Field(min_length=1, max_length=MAX_FIXTURE_BYTES * 4 // 3 + 4)
    expected_evidence_sha256: str = Field(pattern=SHA256)


class FixtureManifest(_Strict):
    schema_version: Literal[1]
    purpose: Literal["synthetic_fixture_baseline"]
    baseline: SourceBaseline
    catalog_snapshot_base64: str = Field(min_length=1, max_length=1024 * 1024 * 4 // 3 + 4)
    catalog_signature_base64: str = Field(min_length=88, max_length=88)
    public_key_base64: str = Field(min_length=44, max_length=44)
    fixtures: list[FixtureSpec] = Field(min_length=1, max_length=MAX_FIXTURES)


@dataclass(frozen=True)
class ValidatedFixture:
    fixture_id: str
    parser_id: str
    suffix: Literal[".csv", ".pdf"]
    source: bytes
    source_sha256: str
    expected_evidence_sha256: str


@dataclass(frozen=True)
class ValidatedManifest:
    manifest_sha256: str
    snapshot: bytes
    signature: bytes
    public_key: bytes
    catalog: object
    fixtures: tuple[ValidatedFixture, ...]


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise FixtureVerificationError("manifest_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise FixtureVerificationError("manifest_invalid_json")


def _decode(value: str, maximum: int, *, exact: int | None = None) -> bytes:
    try:
        result = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise FixtureVerificationError("manifest_invalid_base64") from None
    if not 0 < len(result) <= maximum or (exact is not None and len(result) != exact):
        raise FixtureVerificationError("manifest_decoded_size")
    if base64.b64encode(result).decode("ascii") != value:
        raise FixtureVerificationError("manifest_noncanonical_base64")
    return result


def validate_manifest(content: bytes) -> ValidatedManifest:
    """Validate every identity, byte limit and signature before processing sources."""
    from parsetrail.core.v2_catalog_admission import admit_pilot_definition
    from parsetrail.core.v2_data_catalog import MAX_CATALOG_BYTES, key_id_for_public_key, verify_catalog

    if type(content) is not bytes or not 0 < len(content) <= MAX_MANIFEST_BYTES:
        raise FixtureVerificationError("manifest_size")
    try:
        raw = json.loads(content, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        if type(raw) is not dict or type(raw.get("schema_version")) is not int:
            raise FixtureVerificationError("manifest_shape")
        manifest = FixtureManifest.model_validate(raw)
    except FixtureVerificationError:
        raise
    except (UnicodeError, ValueError, TypeError, RecursionError, ValidationError):
        raise FixtureVerificationError("manifest_shape") from None
    snapshot = _decode(manifest.catalog_snapshot_base64, MAX_CATALOG_BYTES)
    signature = _decode(manifest.catalog_signature_base64, 64, exact=64)
    public_key = _decode(manifest.public_key_base64, 32, exact=32)
    try:
        catalog = verify_catalog(
            snapshot, signature, {key_id_for_public_key(public_key): public_key}, admit_pilot_definition
        )
        # This diagnostic accepts fixture provenance only, never release identity.
        if catalog.source_revision != "0" * 40:
            raise FixtureVerificationError("catalog_not_fixture_placeholder")
    except FixtureVerificationError:
        raise
    except Exception:
        raise FixtureVerificationError("fixture_catalog_rejected") from None
    fixtures = []
    identities, parser_ids, hashes = set(), set(), set()
    total_bytes = 0
    entries = {entry.identity.parser_id: entry for entry in catalog.definitions}
    if len(entries) != len(catalog.definitions):
        raise FixtureVerificationError("fixture_catalog_duplicate_parser")
    for spec in manifest.fixtures:
        source = _decode(spec.source_base64, MAX_FIXTURE_BYTES)
        source_hash = hashlib.sha256(source).hexdigest()
        if spec.fixture_id in identities or spec.parser_id in parser_ids or source_hash in hashes:
            raise FixtureVerificationError("manifest_duplicate_identity")
        identities.add(spec.fixture_id)
        parser_ids.add(spec.parser_id)
        hashes.add(source_hash)
        total_bytes += len(source)
        if total_bytes > MAX_TOTAL_SOURCE_BYTES:
            raise FixtureVerificationError("manifest_total_source_size")
        if spec.parser_id not in entries or entries[spec.parser_id].identity.suffix != spec.suffix:
            raise FixtureVerificationError("manifest_definition_mismatch")
        fixtures.append(
            ValidatedFixture(
                spec.fixture_id, spec.parser_id, spec.suffix, source, source_hash, spec.expected_evidence_sha256
            )
        )
    if parser_ids != set(entries):
        raise FixtureVerificationError("manifest_definition_coverage")
    return ValidatedManifest(
        hashlib.sha256(content).hexdigest(), snapshot, signature, public_key, catalog, tuple(fixtures)
    )


@contextmanager
def isolated_fixture_environment(directory: Path):
    """No ordinary HOME, profile discovery, preferences or credential backend."""
    values = {
        "HOME": str(directory),
        "USERPROFILE": str(directory),
        "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise FixtureVerificationError(code)


def _no_journals(store) -> None:
    for table in ("JournalEntries", "JournalAllocations"):
        _require(
            store.connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), "automatic_journal_detected"
        )


def _catalog_checks(cache, validated, root: Path) -> dict[str, bool]:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from parsetrail.core.v2_catalog_admission import admit_pilot_definition
    from parsetrail.core.v2_data_catalog import (
        CatalogCache,
        CatalogCancelled,
        CatalogError,
        CatalogRollbackError,
        key_id_for_public_key,
    )

    # Tampered bytes cannot replace the supplied valid fixture release.
    try:
        cache.activate(validated.snapshot + b" ", validated.signature)
    except CatalogError:
        pass
    else:
        raise FixtureVerificationError("catalog_tamper_accepted")
    _require(cache.load_current().snapshot == validated.snapshot, "catalog_tamper_changed_current")
    empty_cache = CatalogCache(root / "cancelled-catalog", cache.trusted_keys, admit_pilot_definition)
    try:
        empty_cache.activate(validated.snapshot, validated.signature, cancelled=lambda: True)
    except CatalogCancelled:
        pass
    else:
        raise FixtureVerificationError("catalog_cancellation_ignored")
    _require(empty_cache.load_current() is None, "catalog_cancelled_current_written")
    # A separate diagnostic key signs fixed sequence copies in memory. There is
    # no supplied private key and neither test trust store persists outside temp.
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    rollback = CatalogCache(root / "rollback-catalog", {key_id: public}, admit_pilot_definition)
    base = json.loads(validated.snapshot)
    base["key_id"] = key_id
    snapshots = []
    for sequence in (1, 2):
        base["release_sequence"] = sequence
        snapshot = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
        snapshots.append((snapshot, key.sign(snapshot)))
    rollback.activate(*snapshots[0])
    rollback.activate(*snapshots[1])
    try:
        rollback.activate(*snapshots[0])
    except CatalogRollbackError:
        pass
    else:
        raise FixtureVerificationError("catalog_downgrade_accepted")
    _require(rollback.load_current().release_sequence == 2, "catalog_downgrade_changed_current")
    base["release_sequence"] = 3
    next_snapshot = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    cancellation_checks = 0

    def cancel_before_pointer():
        nonlocal cancellation_checks
        cancellation_checks += 1
        return cancellation_checks == 2

    try:
        rollback.activate(next_snapshot, key.sign(next_snapshot), cancelled=cancel_before_pointer)
    except CatalogCancelled:
        pass
    else:
        raise FixtureVerificationError("catalog_staged_cancellation_ignored")
    _require(rollback.load_current().release_sequence == 2, "catalog_cancelled_changed_current")
    rollback.activate(*snapshots[0], allow_rollback=True)
    _require(rollback.load_current().release_sequence == 1, "catalog_explicit_rollback_failed")
    return {
        "tamper_refused": True,
        "activation_cancelled": True,
        "staged_activation_cancelled": True,
        "downgrade_refused": True,
        "explicit_rollback": True,
    }


def run_fixture_verification(content: bytes) -> dict:
    """Run the fixed workflow; no paths, commands or operations from the manifest."""
    from parsetrail.core.v2_catalog_admission import admit_pilot_definition
    from parsetrail.core.v2_data_catalog import CatalogCache, key_id_for_public_key
    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.core.v2_source_import import CatalogImportError, ImportCancelled, import_catalog_source
    from parsetrail.core.v2_source_pipeline import SourcePipelineError
    from parsetrail.core.v2_source_recovery import recover_source_original

    validated = validate_manifest(content)
    deadline = time.monotonic() + MAX_RUN_SECONDS

    def cancelled():
        return time.monotonic() >= deadline

    def check_deadline():
        _require(not cancelled(), "diagnostic_deadline")

    results = []
    total_evidence = 0
    total_observations = 0
    check_deadline()
    with tempfile.TemporaryDirectory(prefix="parsetrail-fixture-verification-") as directory:
        root = Path(directory)
        with isolated_fixture_environment(root):
            keys = {key_id_for_public_key(validated.public_key): validated.public_key}
            catalogs = tempfile.TemporaryDirectory(prefix="fixture-catalogs-", dir=root)
            catalog_root = Path(catalogs.name)
            cache = CatalogCache(catalog_root / "supplied-fixture-catalog", keys, admit_pilot_definition)
            catalog = cache.activate(validated.snapshot, validated.signature, cancelled=cancelled)
            checks = _catalog_checks(cache, validated, catalog_root)
            profile = root / "fresh.db"
            with V2ProfileStore.create(profile) as store:
                for fixture in validated.fixtures:
                    check_deadline()
                    result = import_catalog_source(
                        store, fixture.source, catalog=catalog, suffix=fixture.suffix, cancelled=cancelled
                    )
                    _require(
                        result.status == "imported" and result.evidence.parser_id == fixture.parser_id,
                        "fixture_admission_mismatch",
                    )
                    saved = store.load_import(fixture.source_sha256)
                    definition = next(
                        entry.content for entry in catalog.definitions if entry.identity.parser_id == fixture.parser_id
                    )
                    evidence = saved.evidence.model_dump_json().encode("utf-8")
                    total_evidence += len(evidence)
                    _require(total_evidence <= MAX_TOTAL_EVIDENCE_BYTES, "diagnostic_total_evidence_size")
                    evidence_hash = hashlib.sha256(evidence).hexdigest()
                    _require(evidence_hash == fixture.expected_evidence_sha256, "fixture_baseline_mismatch")
                    _require(
                        saved.source == fixture.source
                        and saved.definition == definition
                        and saved.evidence == result.evidence,
                        "retained_snapshot_mismatch",
                    )
                    retry = import_catalog_source(
                        store, fixture.source, catalog=catalog, suffix=fixture.suffix, cancelled=cancelled
                    )
                    _require(
                        retry.status == "already_imported" and retry.evidence == result.evidence,
                        "fixture_retry_mismatch",
                    )
                    _no_journals(store)
                    payload = result.evidence.payload
                    observations = (
                        len(payload.rows)
                        if payload.kind == "activity_export"
                        else sum(len(a.rows) for a in payload.accounts)
                    )
                    total_observations += observations
                    results.append(
                        {
                            "fixture_id": fixture.fixture_id,
                            "parser_id": fixture.parser_id,
                            "suffix": fixture.suffix,
                            "source_sha256": fixture.source_sha256,
                            "definition_sha256": result.evidence.definition_sha256,
                            "evidence_sha256": evidence_hash,
                            "observations": observations,
                            "baseline_equal": True,
                            "retry_exact": True,
                        }
                    )
                _require(
                    store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone()
                    == (total_observations,),
                    "observation_count_mismatch",
                )
            check_deadline()
            with V2ProfileStore.create(root / "refusals.db") as refused:
                try:
                    import_catalog_source(
                        refused,
                        validated.fixtures[0].source,
                        catalog=catalog,
                        suffix=validated.fixtures[0].suffix,
                        cancelled=lambda: True,
                    )
                except ImportCancelled:
                    pass
                else:
                    raise FixtureVerificationError("source_cancellation_ignored")
                try:
                    import_catalog_source(
                        refused,
                        b"invalid synthetic fixture",
                        catalog=catalog,
                        suffix=validated.fixtures[0].suffix,
                        cancelled=cancelled,
                    )
                except (CatalogImportError, SourcePipelineError):
                    pass
                else:
                    raise FixtureVerificationError("invalid_source_accepted")
                _require(refused.source_ids() == (), "refused_source_written")
                _no_journals(refused)
            checks.update({"source_cancelled": True, "invalid_source_refused": True})
            catalogs.cleanup()
            _require(not catalog_root.exists(), "diagnostic_catalog_cleanup_failed")
            before = hashlib.sha256(profile.read_bytes()).hexdigest()
            backup = V2ProfileStore.snapshot_to(profile, root / "backup.dbb")
            restored = V2ProfileStore.snapshot_to(backup, root / "restored.db")
            # Recovery deliberately has no cache, preferences or public key input.
            restored_before = hashlib.sha256(restored.read_bytes()).hexdigest()
            with V2ProfileStore.open(restored, read_only=True) as store:
                _no_journals(store)
                _require(
                    set(store.source_ids()) == {fixture.source_sha256 for fixture in validated.fixtures},
                    "restored_source_inventory_mismatch",
                )
                for fixture in validated.fixtures:
                    check_deadline()
                    saved = store.load_import(fixture.source_sha256)
                    _require(
                        saved.source == fixture.source
                        and hashlib.sha256(saved.evidence.model_dump_json().encode()).hexdigest()
                        == fixture.expected_evidence_sha256,
                        "restored_snapshot_mismatch",
                    )
                    recovered = recover_source_original(
                        restored, fixture.source_sha256, root / f"recovered-{fixture.fixture_id}{fixture.suffix}"
                    )
                    _require(recovered.read_bytes() == fixture.source, "recovered_source_mismatch")
            _require(hashlib.sha256(profile.read_bytes()).hexdigest() == before, "original_profile_changed")
            _require(hashlib.sha256(restored.read_bytes()).hexdigest() == restored_before, "restored_profile_changed")
            checks.update(
                {
                    "reopened_exact": True,
                    "backup_restore_as_new": True,
                    "recovery_without_catalog": True,
                    "zero_automatic_journals": True,
                }
            )
            check_deadline()
    # No report is published until every check and temporary cleanup succeeds.
    report = {
        "schema_version": 1,
        "diagnostic": "v2_synthetic_fixture_verification",
        "status": "passed",
        "runtime": "frozen" if getattr(sys, "frozen", False) else "source",
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "process_bits": struct.calcsize("P") * 8,
        },
        "trust": {
            "supplied_catalog": "manifest_fixture_key_only",
            "rollback_catalog": "internal_ephemeral_fixture_key_only",
            "production_trust_changed": False,
        },
        "comparison": "supplied_source_runtime_evidence_hash_equality_only",
        "release_provenance": "not_attested",
        "owner_acceptance": "not_performed",
        "manifest_sha256": validated.manifest_sha256,
        "catalog_sha256": hashlib.sha256(validated.snapshot).hexdigest(),
        "counts": {
            "fixtures": len(results),
            "pdf": sum(f.suffix == ".pdf" for f in validated.fixtures),
            "csv": sum(f.suffix == ".csv" for f in validated.fixtures),
            "observations": total_observations,
        },
        "limits": {
            "manifest_bytes": MAX_MANIFEST_BYTES,
            "fixture_bytes": MAX_FIXTURE_BYTES,
            "total_source_bytes": MAX_TOTAL_SOURCE_BYTES,
            "total_evidence_bytes": MAX_TOTAL_EVIDENCE_BYTES,
            "fixtures": MAX_FIXTURES,
            "run_seconds": MAX_RUN_SECONDS,
            "deadline_scope": "between_operations_and_decoder_workers",
            "profile_scope": "unbound_fixture_evidence_only",
            "forced_source_cancellation_scope": "before_import",
            "private_source_parity": False,
            "complete_capture": False,
            "accounting_acceptance": False,
            "installed_acceptance": False,
        },
        "checks": checks,
        "fixtures": results,
    }
    _require(len(json.dumps(report).encode()) <= MAX_REPORT_BYTES, "diagnostic_report_size")
    return report


def publish_new_json(destination: Path, content: bytes) -> None:
    """Publish complete bytes without overwriting even a racing destination."""
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FixtureVerificationError("destination_exists")
    if not destination.parent.is_dir():
        raise FixtureVerificationError("destination_parent_missing")
    with tempfile.TemporaryDirectory(prefix=".parsetrail-fixture-output-", dir=destination.parent) as temporary:
        staging = Path(temporary) / "complete.json"
        with staging.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(staging, destination)
        except FileExistsError:
            raise FixtureVerificationError("destination_exists") from None


def main(argv: list[str] | None = None) -> int:
    """Fixed two-path CLI; unknown options never enter normal application startup."""
    argv = sys.argv[1:] if argv is None else argv
    code = "diagnostic_failed"
    try:
        if (
            len(argv) != 4
            or argv[0] != "--v2-verify-fixtures"
            or argv[2] != "--report"
            or argv[1].startswith("--")
            or argv[3].startswith("--")
        ):
            raise FixtureVerificationError("diagnostic_arguments")
        manifest_path, destination = Path(argv[1]), Path(argv[3])
        if destination.exists() or destination.is_symlink():
            raise FixtureVerificationError("destination_exists")
        if not destination.parent.is_dir():
            raise FixtureVerificationError("destination_parent_missing")
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise FixtureVerificationError("manifest_unavailable")
        with manifest_path.open("rb") as stream:
            content = stream.read(MAX_MANIFEST_BYTES + 1)
        report = run_fixture_verification(content)
        publish_new_json(destination, json.dumps(report, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        return 0
    except FixtureVerificationError as error:
        code = str(error)
    except Exception:
        pass
    if sys.stderr is not None:
        try:
            sys.stderr.write(f"fixture_verification_failed:{code}\n")
        except OSError:
            pass
    return 2
