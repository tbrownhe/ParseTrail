"""Cached accountless guards agree with authoritative mutations and never query on selection."""

import json
from itertools import combinations

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
)
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_account_bindings import DEFINITION, SOURCE
from .test_v2_accountless_document_summary import _profile
from .test_v2_binding_corrections import change
from .test_v2_review_read_performance import _tamper
from .test_v2_reviewed_openings import _profile as opening_profile
from .test_v2_source_account_bindings import CASH_DEFINITION
from .test_v2_transfers import _profile as transfer_profile


def _cash_definition():
    definition = json.loads(CASH_DEFINITION)
    del definition["columns"]["account"]
    definition["account_key"] = "unknown"
    return json.dumps(definition).encode()


def _cash_profile(path):
    source = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,,Coffee,-$4.00,$996.00\n"
        b"10/02/2026,,Tea,-$3.00,$993.00\n"
    )
    definition = _cash_definition()
    evidence = build_source_evidence(source, definition, suffix=".csv")
    with V2ProfileStore.create(path) as store:
        store.import_source(source, definition, evidence, suffix=".csv")
        for account_id in ("cash", "other"):
            store.add_financial_account(FinancialAccount(account_id, account_id, "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        store.assert_file_account(evidence.source_sha256, "cash")
    return source, definition, evidence


def _ordinary(store, source_id, row_ids=None):
    target = BindingCorrectionTarget(
        source_id, "file" if row_ids is None else "rows", row_ids=() if row_ids is None else tuple(sorted(row_ids))
    )
    try:
        store._require_ordinary_binding_change(target)
    except ProfileFormatError as exc:
        return (str(exc),)
    return ()


def _assert_parity(store, snapshot):
    assert snapshot.file_ordinary_blockers == _ordinary(store, snapshot.evidence.source_sha256)
    for count in range(1, len(snapshot.rows) + 1):
        for selected in combinations((row.row_id for row in snapshot.rows), count):
            assert snapshot.ordinary_blockers_for_rows(selected) == _ordinary(
                store, snapshot.evidence.source_sha256, selected
            )


def test_snapshot_evidence_accounts_bindings_and_pure_selection_are_consistent(tmp_path, monkeypatch):
    path = tmp_path / "cached.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.assign_row_account(evidence.payload.rows[0].row_id, "a")
        snapshot = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert snapshot.evidence == evidence and snapshot.rows == evidence.payload.rows
        assert [binding.ledger_account_id for binding in snapshot.bindings] == ["a", None]
        assert [binding.basis for binding in snapshot.bindings] == ["row", None]
        assert snapshot.file_eligible and not snapshot.posted_row_ids and not snapshot.overlap_row_ids
        _assert_parity(store, snapshot)
        assert not store.connection.in_transaction
    before = path.read_bytes()
    monkeypatch.setattr(
        V2ProfileStore, "open", lambda *_args, **_kwargs: pytest.fail("Selection must not open the store")
    )
    for _index in range(100):
        assert snapshot.ordinary_blockers_for_rows(tuple(row.row_id for row in snapshot.rows)) == ()
        assert snapshot.ordinary_blockers_for_rows(()) == ()
    with pytest.raises(ProfileFormatError, match="binding_correction_target_invalid"):
        snapshot.ordinary_blockers_for_rows(("missing",))
    assert path.read_bytes() == before


def test_reload_verifies_selected_evidence_once_without_per_row_previews(tmp_path, monkeypatch):
    path = tmp_path / "once.db"
    evidence = _profile(path)
    calls = []
    original = V2ProfileStore._verified_saved_import

    def record(source, row, observations):
        calls.append(source)
        return original(source, row, observations)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(record))
    monkeypatch.setattr(
        V2ProfileStore,
        "binding_correction_snapshot",
        lambda *_args, **_kwargs: pytest.fail("No per-row correction previews"),
    )
    with V2ProfileStore.open(path, read_only=True) as store:
        snapshot = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert len(snapshot.rows) == 2 and calls == [evidence.source_sha256]


@pytest.mark.parametrize("amount", [0, 10_000])
@pytest.mark.parametrize("mode", ["file", "rows"])
def test_source_opening_guards_preserve_file_vs_row_scope_including_zero(tmp_path, amount, mode):
    path = tmp_path / "opening.db"
    statement = opening_profile(path, amount_minor=amount)
    accountless = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(SOURCE, DEFINITION, accountless, suffix=".csv")
        if mode == "file":
            store.assert_file_account(accountless.source_sha256, "cash")
        else:
            store.assign_row_account(accountless.payload.rows[0].row_id, "cash")
        store.record_opening_source_review(
            "cash",
            statement.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Synthetic source opening",
        )
        store.post_reviewed_opening("cash")
        snapshot = store.accountless_binding_review_snapshot(accountless.source_sha256)
        _assert_parity(store, snapshot)
        if mode == "file":
            assert snapshot.file_ordinary_blockers == ("account_binding_source_backed_opening_anchor",)
            assert snapshot.ordinary_blockers_for_rows((accountless.payload.rows[0].row_id,)) == ()
        else:
            assert snapshot.ordinary_blockers_for_rows((accountless.payload.rows[0].row_id,)) == (
                "account_binding_source_backed_opening_anchor",
            )
            assert snapshot.ordinary_blockers_for_rows((accountless.payload.rows[1].row_id,)) == ()


def test_correction_history_is_cached_and_stale_mutations_still_recheck(tmp_path):
    path = tmp_path / "correction.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        stale = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert stale.file_ordinary_blockers == ()
        store.assert_file_account(evidence.source_sha256, "a")
        change(store, BindingCorrectionTarget(evidence.source_sha256, "file"), None)
        snapshot = store.accountless_binding_review_snapshot(evidence.source_sha256)
        _assert_parity(store, snapshot)
        assert snapshot.file_ordinary_blockers == ("account_binding_has_correction_history",)
        assert stale.file_ordinary_blockers == ()
        with pytest.raises(ProfileFormatError, match="account_binding_has_correction_history"):
            store.assert_file_account(evidence.source_sha256, "b")
        with pytest.raises(ProfileFormatError, match="account_binding_has_correction_history"):
            store.assign_row_account(evidence.payload.rows[0].row_id, "b")


def test_posting_after_cached_read_still_blocks_stale_account_change(tmp_path):
    path = tmp_path / "posted.db"
    _source, _definition, evidence = _cash_profile(path)
    first, second = evidence.payload.rows
    with V2ProfileStore.open(path) as store:
        stale = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert stale.file_ordinary_blockers == ()
        store.post_reviewed_cash_category(first.row_id, "expense:food", reason="Reviewed synthetic coffee")
        current = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert current.posted_row_ids == frozenset({first.row_id})
        assert current.file_ordinary_blockers == ("account_binding_has_journal_history",)
        assert current.ordinary_blockers_for_rows((second.row_id,)) == ()
        _assert_parity(store, current)
        assert stale.file_ordinary_blockers == ()
        with pytest.raises(ProfileFormatError, match="account_binding_has_journal_history"):
            store.assert_file_account(evidence.source_sha256, "other")


def test_overlap_history_guard_matches_authoritative_for_each_selection(tmp_path):
    path = tmp_path / "overlap.db"
    source, definition, _evidence = _cash_profile(path)
    with V2ProfileStore.open(path) as store:
        revised = build_source_evidence(source + b"\n", definition, suffix=".csv")
        store.import_source(source + b"\n", definition, revised, suffix=".csv")
        store.assert_file_account(revised.source_sha256, "cash")
        pair = store.source_overlap_inventory().candidates[0]
        store.record_source_overlap_review(
            pair.left.row_id,
            pair.right.row_id,
            decision="distinct",
            reason="Synthetic separate purchases",
            expected_basis_sha256=pair.basis_sha256,
        )
        snapshot = store.accountless_binding_review_snapshot(pair.left.source_sha256)
        assert snapshot.overlap_row_ids
        assert snapshot.file_ordinary_blockers == ("account_binding_has_overlap_review_history",)
        _assert_parity(store, snapshot)


def test_transfer_pair_review_guard_matches_authoritative(tmp_path):
    path = tmp_path / "transfer.db"
    outgoing, incoming = transfer_profile(path, bank_date="01/05/2026")
    definition = _cash_definition()
    source = b"Date,Account,Description,Amount,ReportedBalance\n01/05/2026,,Accountless payment,-$20.00,$980.00\n"
    evidence = build_source_evidence(source, definition, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        prior_source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (outgoing,)
        ).fetchone()[0]
        store.clear_source_account_binding(prior_source, "Checking A", "opaque")
        store.import_source(source, definition, evidence, suffix=".csv")
        store.assert_file_account(evidence.source_sha256, "checking")
        frame = store.transfer_review_snapshot(preferences=V2Preferences())
        store.record_transfer_pair_review(
            evidence.payload.rows[0].row_id,
            incoming,
            decision="dismiss",
            expected_basis_sha256=frame.basis_sha256,
            preferences=V2Preferences(),
            reason="Synthetic explicit dismissal",
        )
        snapshot = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert snapshot.file_ordinary_blockers == ("account_binding_has_transfer_review_history",)
        _assert_parity(store, snapshot)


def test_snapshot_pins_binding_context_then_next_read_sees_concurrent_assignment(tmp_path, monkeypatch):
    path = tmp_path / "concurrent.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    original = V2ProfileStore._account_bindings_for_evidence
    written = False

    def concurrent_assignment(store, source_id, selected_evidence, **kwargs):
        nonlocal written
        if not written:
            written = True
            with V2ProfileStore.open(path) as writer:
                writer.assign_row_account(evidence.payload.rows[0].row_id, "a")
        return original(store, source_id, selected_evidence, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "_account_bindings_for_evidence", concurrent_assignment)
    with V2ProfileStore.open(path, read_only=True) as store:
        first = store.accountless_binding_review_snapshot(evidence.source_sha256)
        second = store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert first.bindings[0].ledger_account_id is None
        assert second.bindings[0].ledger_account_id == "a"
        assert not store.connection.in_transaction


def test_bad_source_and_existing_transaction_refuse_without_writes(tmp_path):
    path = tmp_path / "refusal.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="binding_requires_committed_snapshot"):
            store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
    _tamper(
        path,
        evidence.source_sha256,
        "EvidenceSnapshots",
        "UPDATE EvidenceSnapshots SET content=? WHERE source_sha256=?",
        lambda source: (b"{}", source),
    )
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
            store.accountless_binding_review_snapshot(evidence.source_sha256)
        assert not store.connection.in_transaction
    assert path.read_bytes() == before
