"""Archive review reads stream validated evidence without repeated global scans."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("streamed-review") / "template.db"
    evidence = []
    with V2ProfileStore.create(path) as store:
        for index in range(6):
            raw = (
                "Date,Account,Description,Amount,ReportedBalance\n"
                f"10/01/2026,Checking A,Source {index},-$4.00,$996.00\n"
            ).encode()
            parsed = build_source_evidence(raw, DEFINITION, suffix=".csv")
            if index == 5:
                parsed = parsed.model_copy(update={"payload": parsed.payload.model_copy(update={"rows": ()})})
            store.import_source(raw, DEFINITION, parsed, suffix=".csv")
            evidence.append(parsed)
    return path, tuple(evidence)


@pytest.fixture
def populated(tmp_path, template):
    original, evidence = template
    path = V2ProfileStore.snapshot_to(original, tmp_path / "profile.db")
    return path, evidence


def test_bulk_and_single_reads_match_including_unbound_and_empty_sources(populated):
    path, evidence = populated
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        single = {source: store.load_import(source) for source in store.source_ids()}
        streamed = dict(store._iter_verified_imports())
        assert streamed == single
        assert {saved.evidence.source_sha256 for saved in streamed.values()} == {
            item.source_sha256 for item in evidence
        }
        assert not streamed[evidence[-1].source_sha256].evidence.payload.rows
        assert store.source_overlap_inventory().candidates == ()
        assert not store.financial_accounts()
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["cash", "reconciliation"])
def test_unrelated_sources_are_verified_once_per_archive_review(populated, monkeypatch, operation):
    path, evidence = populated
    selected = evidence[0].source_sha256
    verified = []
    original = V2ProfileStore._verified_saved_import

    def record(source, row, observations):
        verified.append(source)
        return original(source, row, observations)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(record))
    with V2ProfileStore.open(path, read_only=True) as store:
        if operation == "cash":
            snapshot = store.source_interpretation_snapshot(selected, kind="cash")
            assert len(snapshot.rows) == 1 and snapshot.rows[0].financial_account is None
        else:
            assert store.reconciliation_snapshot().checks == ()
    for item in evidence:
        if item.source_sha256 != selected or operation == "reconciliation":
            assert verified.count(item.source_sha256) == 1


def _tamper(path, source, table, statement, parameters):
    with sqlite3.connect(path) as connection:
        action = "delete" if statement.startswith("DELETE") else "update"
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_{action}",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_{action}")
        connection.execute(statement, parameters(source))
        connection.execute(trigger)


@pytest.mark.parametrize("operation", ["cash", "reconciliation", "overlap"])
@pytest.mark.parametrize(
    "table,statement,parameters,error",
    [
        (
            "Sources",
            "UPDATE Sources SET content=? WHERE sha256=?",
            lambda source: (b"changed", source),
            "saved_snapshot_integrity",
        ),
        (
            "EvidenceSnapshots",
            "UPDATE EvidenceSnapshots SET content=? WHERE source_sha256=?",
            lambda source: (b"{}", source),
            "saved_snapshot_integrity",
        ),
        ("Definitions", "UPDATE Definitions SET content=?", lambda _source: (b"changed",), "saved_snapshot_integrity"),
        (
            "SourceObservations",
            "UPDATE SourceObservations SET amount_minor=amount_minor+1 WHERE source_sha256=?",
            lambda source: (source,),
            "observation_inventory_mismatch",
        ),
        (
            "EvidenceSnapshots",
            "DELETE FROM EvidenceSnapshots WHERE source_sha256=?",
            lambda source: (source,),
            "source_missing",
        ),
    ],
)
def test_archive_checks_still_refuse_corrupt_unbound_sources(populated, operation, table, statement, parameters, error):
    path, evidence = populated
    _tamper(path, evidence[1].source_sha256, table, statement, parameters)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match=error):
            if operation == "cash":
                store.source_interpretation_snapshot(evidence[0].source_sha256, kind="cash")
            elif operation == "reconciliation":
                store.reconciliation_snapshot()
            else:
                store.source_overlap_inventory()
        assert not store.connection.in_transaction
    assert path.read_bytes() == before


def test_archive_snapshot_keeps_external_writes_out_then_observes_next_read(populated, monkeypatch):
    path, evidence = populated
    selected = evidence[0].source_sha256
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    with V2ProfileStore.open(path, read_only=True) as reader:
        baseline = reader.source_interpretation_snapshot(selected, kind="cash")
        original = V2ProfileStore._iter_verified_imports
        written = False

        def concurrent_write(store):
            nonlocal written
            if not written:
                written = True
                with V2ProfileStore.open(path) as writer:
                    writer.add_financial_account(FinancialAccount("cash", "Cash", "asset", "synthetic"))
                    writer.bind_source_account(selected, "Checking A", "opaque", "cash")
            yield from original(store)

        monkeypatch.setattr(V2ProfileStore, "_iter_verified_imports", concurrent_write)
        same_snapshot = reader.source_interpretation_snapshot(selected, kind="cash")
        assert same_snapshot == baseline
        next_snapshot = reader.source_interpretation_snapshot(selected, kind="cash")
        assert next_snapshot.rows[0].financial_account == "Cash"
        assert next_snapshot.basis_sha256 != baseline.basis_sha256
        assert not reader.connection.in_transaction


def test_bulk_read_sees_own_later_write_without_retaining_an_index(populated):
    path, evidence = populated
    selected = evidence[0].source_sha256
    with V2ProfileStore.open(path) as store:
        old = store.source_interpretation_snapshot(selected, kind="cash")
        store.add_financial_account(FinancialAccount("cash", "Cash", "asset", "synthetic"))
        store.bind_source_account(selected, "Checking A", "opaque", "cash")
        current = store.source_interpretation_snapshot(selected, kind="cash")
        assert old.rows[0].financial_account is None and current.rows[0].financial_account == "Cash"
        assert old.basis_sha256 != current.basis_sha256
        assert hashlib.sha256(store.load_import(selected).source).hexdigest() == selected
