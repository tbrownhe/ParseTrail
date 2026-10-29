"""Posted histories stay fully validated without repeated event/source scans."""

from dataclasses import asdict

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_transfer_batch import TransferBatchCancelled, plan_unique_transfers

from .test_v2_review_read_performance import _tamper
from .test_v2_transfers import BANK_DEFINITION


def _posted_profile(path, *, posted_pairs=96, source_count=8, pending_pairs=2, extra_rows=0):
    """Public synthetic unique amounts; both same-day and clearing transfers."""
    total = posted_pairs + pending_pairs
    sources = [[] for _ in range(source_count)]
    for index in range(total):
        amount = f"{index + 1}.01"
        outgoing, incoming = ("01/03/2026", "01/05/2026") if index % 2 else ("01/07/2026", "01/07/2026")
        sources[index % source_count].extend(
            (
                f"{outgoing},Checking A,Public sent {index},-${amount},$0.00\n",
                f"{incoming},Savings B,Public received {index},${amount},$0.00\n",
            )
        )
    for index in range(extra_rows):
        sources[index % source_count].append(
            f"01/09/2026,Checking A,Public unpaired {index},-${100000 + index}.05,$0.00\n"
        )
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("a", "Checking", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("b", "Savings", "asset", "synthetic"))
        for rows in sources:
            if not rows:
                continue
            content = ("Date,Account,Description,Amount,ReportedBalance\n" + "".join(rows)).encode()
            evidence = build_source_evidence(content, BANK_DEFINITION, suffix=".csv")
            store.import_source(content, BANK_DEFINITION, evidence, suffix=".csv")
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "a")
            if any(row.source_account == "Savings B" for row in evidence.payload.rows):
                store.bind_source_account(evidence.source_sha256, "Savings B", "opaque", "b")
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        # Batch revalidates the entire candidate graph, so post all then retire
        # the intended pending pairs through the ordinary reviewed history API.
        plan = plan_unique_transfers(snapshot)
        result = store.post_reviewed_transfer_batch(plan, preferences=V2Preferences(), reason="Synthetic history")
        for event_id, pair in zip(result.event_ids, plan.pairs, strict=True):
            if -pair.outgoing.amount_minor > posted_pairs * 100 + 1:
                basis = store.transfer_review_snapshot(preferences=V2Preferences()).basis_sha256
                store.withdraw_reviewed_transfer(event_id, expected_basis_sha256=basis, reason="Leave pending")
    return total


def test_posted_snapshot_validates_history_once_and_bindings_once_per_source(tmp_path, monkeypatch):
    path = tmp_path / "posted.db"
    _posted_profile(path)
    with V2ProfileStore.open(path, read_only=True) as store:
        calls = {"history": 0, "bindings": 0, "verified": 0}
        for name, method in (
            ("history", "_read_transfer_history_uncached"),
            ("bindings", "_account_bindings_for_evidence"),
            ("verified", "_verified_saved_import"),
        ):
            original = getattr(store, method)

            def counted(*args, _name=name, _original=original, **kwargs):
                calls[_name] += 1
                return _original(*args, **kwargs)

            monkeypatch.setattr(store, method, counted)
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        assert len(snapshot.events) == 98 and len(snapshot.candidates) == 2
        assert sum(event.status == "active" for event in snapshot.events) == 96
        assert calls == {"history": 1, "bindings": 16, "verified": 8}
        assert store._transfer_history_cache is None and store._transfer_verified_sources is None
        assert not store.connection.in_transaction
        # A fresh operation must revalidate, rather than retain a process cache.
        again = store.transfer_review_snapshot(preferences=V2Preferences(), max_day_gap=3)
        assert asdict(snapshot) == {**asdict(again), "max_day_gap": 7}
        assert calls == {"history": 2, "bindings": 32, "verified": 16}


def test_history_epoch_invalidates_after_writes_and_savepoint_rollback(tmp_path, monkeypatch):
    path = tmp_path / "epochs.db"
    _posted_profile(path, posted_pairs=8, source_count=2, pending_pairs=0)
    with V2ProfileStore.open(path) as store:
        original = store._read_transfer_history_uncached
        calls = []

        def counted():
            calls.append(store.connection.total_changes)
            return original()

        monkeypatch.setattr(store, "_read_transfer_history_uncached", counted)
        store.connection.execute("BEGIN IMMEDIATE")
        try:
            with store._verified_transfer_operation():
                before = store._read_transfer_history()
                assert store._read_transfer_history() is before
                store.connection.execute("SAVEPOINT test_epoch")
                store.connection.execute("UPDATE Accounts SET name='Temporary label' WHERE id='a'")
                assert store._read_transfer_history() == before
                store.connection.execute("ROLLBACK TO test_epoch")
                # A savepoint rollback does not itself advance total_changes.
                # The operation must not reuse its transient post-write result.
                assert store._read_transfer_history() == before
                assert len(calls) == 3
        finally:
            store.connection.execute("ROLLBACK")
        assert store._transfer_history_cache is None


def test_active_binding_change_cannot_hide_behind_scoped_history_cache(tmp_path):
    path = tmp_path / "binding.db"
    _posted_profile(path, posted_pairs=8, source_count=2, pending_pairs=0)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("BEGIN IMMEDIATE")
        try:
            with store._verified_transfer_operation():
                store._read_transfer_history()
                store.connection.execute(
                    "UPDATE SourceAccountBindings SET ledger_account_id='b' WHERE ledger_account_id='a'"
                )
                with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
                    store._read_transfer_history()
        finally:
            store.connection.execute("ROLLBACK")
        assert len(store.transfer_history()) == 8


@pytest.mark.parametrize("corruption", ["journal", "source", "inventory"])
def test_posted_history_source_and_journal_corruption_still_refuse(tmp_path, corruption):
    path = tmp_path / "corrupt.db"
    _posted_profile(path, posted_pairs=8, source_count=2, pending_pairs=0)
    with V2ProfileStore.open(path) as store:
        assert len(store.transfer_history()) == 8
    table, statement, error = {
        "journal": (
            "JournalEntries",
            "UPDATE JournalEntries SET payload=replace(payload,'Synthetic history','Corrupted history')",
            "transfer_history_integrity",
        ),
        "source": ("Sources", "UPDATE Sources SET content=x'00'", "saved_snapshot_integrity"),
        "inventory": (
            "SourceObservations",
            "UPDATE SourceObservations SET amount_minor=amount_minor+1",
            "observation_inventory_mismatch",
        ),
    }[corruption]
    _tamper(
        path,
        None,
        table,
        statement,
        lambda _source: (),
    )
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match=error):
            store.transfer_review_snapshot(preferences=V2Preferences())
        assert store._transfer_history_cache is None and store._transfer_verified_sources is None
        assert not store.connection.in_transaction


def test_active_usage_index_keeps_every_competing_allocation(tmp_path):
    import json

    path = tmp_path / "extra-use.db"
    _posted_profile(path, posted_pairs=8, source_count=2, pending_pairs=0)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("BEGIN IMMEDIATE")
        try:
            with store._verified_transfer_operation():
                store._read_transfer_history()
                key, payload = store.connection.execute("SELECT key,payload FROM JournalEntries LIMIT 1").fetchone()
                copied = json.loads(payload)
                copied["key"] = copied["event_id"] = "synthetic:additional-use"
                store.connection.execute(
                    "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (copied["key"], json.dumps(copied))
                )
                store.connection.execute(
                    "INSERT INTO JournalAllocations SELECT ?,row_id,amount_minor FROM JournalAllocations WHERE entry_key=?",
                    (copied["key"], key),
                )
                with pytest.raises(ProfileFormatError, match="transfer_history_integrity"):
                    store._read_transfer_history()
        finally:
            store.connection.execute("ROLLBACK")
        assert len(store.transfer_history()) == 8


def test_single_post_revalidates_history_after_dml_instead_of_reusing_initial_result(tmp_path, monkeypatch):
    path = tmp_path / "single.db"
    _posted_profile(path, posted_pairs=16, source_count=4)
    with V2ProfileStore.open(path) as store:
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        selected = snapshot.candidates[0]
        original = store._read_transfer_history_uncached
        calls = []

        def counted():
            result = original()
            calls.append(len(result[0]))
            return result

        monkeypatch.setattr(store, "_read_transfer_history_uncached", counted)
        event_id = store.post_reviewed_transfer(
            selected.outgoing.row_id,
            selected.incoming.row_id,
            preferences=V2Preferences(),
            reason="Confirmed exact remaining pair",
            expected_basis_sha256=snapshot.basis_sha256,
        )
        assert calls == [18, 19]
        assert store._transfer_history_cache is None
        assert (
            store.post_reviewed_transfer(
                selected.outgoing.row_id,
                selected.incoming.row_id,
                preferences=V2Preferences(),
                reason="Confirmed exact remaining pair",
                expected_basis_sha256=snapshot.basis_sha256,
            )
            == event_id
        )
        assert calls == [18, 19, 19]


def test_post_and_cancelled_batch_revalidate_posted_history_without_partial_writes(tmp_path):
    path = tmp_path / "post.db"
    _posted_profile(path, posted_pairs=16, source_count=4)
    with V2ProfileStore.open(path) as store:
        snapshot = store.transfer_review_snapshot(preferences=V2Preferences())
        plan = plan_unique_transfers(snapshot)
        before = path.read_bytes()
        with pytest.raises(TransferBatchCancelled):
            store.post_reviewed_transfer_batch(
                plan,
                preferences=V2Preferences(),
                reason="Confirmed remaining transfers",
                cancelled=lambda: store.connection.execute("SELECT count(*) FROM TransferEvents").fetchone()[0] > 18,
            )
        assert path.read_bytes() == before and store._transfer_history_cache is None
        result = store.post_reviewed_transfer_batch(
            plan, preferences=V2Preferences(), reason="Confirmed remaining transfers"
        )
        assert result.posted_pairs == 2
        history = store.transfer_history()
        assert len(history) == 20 and sum(event.status == "active" for event in history) == 18
        assert (
            store.post_reviewed_transfer_batch(
                plan, preferences=V2Preferences(), reason="Confirmed remaining transfers"
            ).already_posted_pairs
            == 2
        )
