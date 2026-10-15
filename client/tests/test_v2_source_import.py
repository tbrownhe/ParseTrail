"""Fresh-profile import retries and failure leave original evidence intact."""

from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, compare_reparse, import_source

from devtools.parser_engine_pilot.source_pipeline import build_source_evidence

DEFINITION = Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"


def parse(source: bytes, definition: bytes):
    return build_source_evidence(source, definition, suffix=".csv")


def test_exact_retry_uses_saved_evidence_and_skips_parser(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "v2.db") as store:
        first = import_source(store, SOURCE, DEFINITION.read_bytes(), suffix=".csv", parse=parse)

        def fail_if_called(_source: bytes, _definition: bytes):
            raise AssertionError("retry must not parse")

        retry = import_source(store, SOURCE, b"changed declaration", suffix=".csv", parse=fail_if_called)
        assert (first.status, retry.status) == ("imported", "already_imported")
        assert retry.evidence == first.evidence
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (1,)
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (1,)


def test_failure_and_cancellation_leave_no_partial_source(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "v2.db") as store:
        with pytest.raises(ValueError):
            import_source(store, SOURCE + b"bad", DEFINITION.read_bytes(), suffix=".csv", parse=parse)
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)
        checks = 0

        def cancel_after_parse() -> bool:
            nonlocal checks
            checks += 1
            return checks == 2

        with pytest.raises(ImportCancelled, match="cancelled"):
            import_source(
                store, SOURCE, DEFINITION.read_bytes(), suffix=".csv", parse=parse, cancelled=cancel_after_parse
            )
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)


def test_revised_source_is_a_second_pending_snapshot(tmp_path: Path) -> None:
    revised = SOURCE.replace(b"-$4.00,$996.00", b"-$5.00,$995.00")
    with V2ProfileStore.create(tmp_path / "v2.db") as store:
        first = import_source(store, SOURCE, DEFINITION.read_bytes(), suffix=".csv", parse=parse)
        second = import_source(store, revised, DEFINITION.read_bytes(), suffix=".csv", parse=parse)
        assert first.source_sha256 != second.source_sha256
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (2,)
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (2,)


def test_reparse_compares_new_definition_without_replacing_saved_evidence(tmp_path: Path) -> None:
    import json

    first_definition = DEFINITION.read_bytes()
    changed = json.loads(first_definition)
    changed["revision"] = "2"
    second_definition = json.dumps(changed).encode()
    profile = tmp_path / "v2.db"
    with V2ProfileStore.create(profile) as store:
        imported = import_source(store, SOURCE, first_definition, suffix=".csv", parse=parse)
        same = compare_reparse(store, imported.source_sha256, first_definition, parse=parse)
        assert same.identical_output
        comparison = compare_reparse(store, imported.source_sha256, second_definition, parse=parse)
        assert not comparison.identical_output
        assert comparison.saved == imported.evidence
        assert comparison.candidate.definition_sha256 != imported.evidence.definition_sha256
        with pytest.raises(ValueError, match="reparse_source_or_definition_mismatch"):
            compare_reparse(store, imported.source_sha256, second_definition, parse=lambda _s, _d: imported.evidence)
        assert store.load_import(imported.source_sha256).evidence == imported.evidence
        assert store.connection.execute("SELECT count(*) FROM EvidenceSnapshots").fetchone() == (1,)
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.load_import(imported.source_sha256).evidence == imported.evidence
