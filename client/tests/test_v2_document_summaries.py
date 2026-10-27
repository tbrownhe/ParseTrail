"""Recognizable documents and positions retain one-snapshot evidence checks."""

from datetime import date

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_reconciliation_history import _add_ambiguous_source
from .test_v2_review_read_performance import _tamper
from .test_v2_source_account_bindings import (
    CARD_DEFINITION,
    CARD_SOURCE,
    CASH_DEFINITION,
    CASH_SOURCE,
    card_channels,
    from_synchrony_table,
)
from .test_v2_statement_journal_comparison import _profile
from .test_v2_statement_reconciliation import _review_and_post


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / "documents.db"
    evidence = []
    with V2ProfileStore.create(path) as store:
        for index in range(4):
            raw = CASH_SOURCE.replace(b"Coffee", f"Coffee {index}".encode())
            parsed = build_source_evidence(raw, CASH_DEFINITION, suffix=".csv")
            store.import_source(raw, CASH_DEFINITION, parsed, suffix=".csv")
            evidence.append(parsed)
    return path, evidence


def test_export_labels_dates_and_explicit_assignment_state(archive):
    path, evidence = archive
    with V2ProfileStore.open(path) as store:
        source = evidence[0].source_sha256
        original = store.document_summaries()
        assert tuple(summary.source_sha256 for summary in original) == store.source_ids()
        summary = next(summary for summary in original if summary.source_sha256 == source)
        assert summary.document_kind == "activity_export"
        assert summary.start == date(2026, 10, 1) and summary.end == date(2026, 10, 2)
        assert summary.start_provenance == summary.end_provenance == "derived"
        assert summary.source_accounts == ("Checking A", "Checking B")
        assert summary.bound_account_names == () and summary.institution_key is None
        assert summary.row_count == summary.pending_activity_rows == summary.unassigned_activity_rows == 2
        assert summary.unassigned_source_accounts == 2
        assert not summary.has_unidentified_rows and summary.has_identified_accounts
        store.add_financial_account(FinancialAccount("cash", "Everyday checking", "asset", "synthetic"))
        store.bind_source_account(source, "Checking A", "opaque", "cash")
        assigned = next(summary for summary in store.document_summaries() if summary.source_sha256 == source)
        assert assigned.unassigned_activity_rows == 1 and assigned.pending_activity_rows == 2
        assert assigned.unassigned_source_accounts == 1
        assert assigned.bound_account_names == ("Everyday checking",)
        assert assigned.institution_key == "synthetic"
        assert not store.import_source(
            CASH_SOURCE.replace(b"Coffee", b"Coffee 0"), CASH_DEFINITION, evidence[0], suffix=".csv"
        )
        assert next(summary for summary in store.document_summaries() if summary.source_sha256 == source) == assigned
        assert not store.connection.in_transaction


def test_statement_masks_identity_and_keeps_printed_dates(tmp_path):
    path = tmp_path / "card.db"
    evidence = from_synchrony_table(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.create(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        summary = store.document_summaries()[0]
        assert summary.document_kind == "statement"
        assert summary.source_accounts == ("Ending 1234",)
        assert summary.start.isoformat() == evidence.payload.start.iso
        assert summary.end.isoformat() == evidence.payload.end.iso
        assert summary.start_provenance == evidence.payload.start.provenance
        assert summary.end_provenance == evidence.payload.end.provenance
        assert summary.pending_activity_rows == summary.unassigned_activity_rows == 1
        assert summary.unassigned_source_accounts == 1


def test_empty_statement_still_requires_its_printed_account_confirmation(tmp_path):
    path = tmp_path / "empty-statement.db"
    original = from_synchrony_table(CARD_DEFINITION, *card_channels())
    section = original.payload.accounts[0].model_copy(update={"rows": ()})
    payload = original.payload.model_copy(update={"accounts": (section,), "independent_balance_verified": False})
    evidence = original.model_copy(update={"payload": payload})
    with V2ProfileStore.create(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        pending = store.document_summaries()[0]
        assert pending.row_count == pending.pending_activity_rows == pending.unassigned_activity_rows == 0
        assert pending.unassigned_source_accounts == 1
        assert pending.has_identified_accounts
        assert store.load_import(evidence.source_sha256).evidence.payload.accounts[0].opening is not None
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "synchrony"))
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        assigned = store.document_summaries()[0]
        assert assigned.unassigned_source_accounts == 0
        assert assigned.bound_account_names == ("Card",)


def test_accountless_file_and_row_assignments_do_not_invent_unconfirmed_identities(tmp_path):
    from .test_v2_account_bindings import DEFINITION, SOURCE

    path = tmp_path / "accountless.db"
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    first, second = (row.row_id for row in evidence.payload.rows)
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("loan", "Loan", "liability", "mohela"))
        unassigned = store.document_summaries()[0]
        assert unassigned.unassigned_source_accounts == 0 and unassigned.unassigned_activity_rows == 2
        store.assign_row_account(first, "loan")
        partial = store.document_summaries()[0]
        assert partial.unassigned_source_accounts == 0 and partial.unassigned_activity_rows == 1
        store.assign_row_account(second, "loan")
        assert store.document_summaries()[0].unassigned_activity_rows == 0
        store.clear_row_account_assignment(first)
        store.clear_row_account_assignment(second)
        store.assert_file_account(evidence.source_sha256, "loan")
        assigned = store.document_summaries()[0]
        assert assigned.unassigned_source_accounts == assigned.unassigned_activity_rows == 0


def test_summary_overlap_matches_explicit_account_period_rules(tmp_path):
    import hashlib

    path = tmp_path / "overlap.db"
    original = from_synchrony_table(CARD_DEFINITION, *card_channels())
    account = original.payload.accounts[0].model_copy(update={"rows": ()})
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("a", "Card A", "liability", "synchrony"))
        store.add_financial_account(FinancialAccount("b", "Card B", "liability", "synchrony"))
        sources = []
        for index, (start, end, bound_account) in enumerate(
            [
                ("2026-01-01", "2026-01-31", "a"),
                ("2026-01-15", "2026-02-15", "a"),
                ("2026-02-16", "2026-02-28", "a"),
                ("2026-01-01", "2026-01-31", "b"),
                ("2026-01-01", "2026-01-31", None),
                (None, "2026-01-31", "a"),
            ]
        ):
            source = CARD_SOURCE + str(index).encode()
            payload = original.payload.model_copy(
                update={
                    "start": original.payload.start.model_copy(
                        update={"iso": start, "raw": start, "provenance": "unknown" if start is None else "observed"}
                    ),
                    "end": original.payload.end.model_copy(update={"iso": end, "raw": end}),
                    "accounts": (account,),
                    "independent_balance_verified": False,
                }
            )
            evidence = original.model_copy(
                update={"source_sha256": hashlib.sha256(source).hexdigest(), "payload": payload}
            )
            store.import_source(source, CARD_DEFINITION, evidence, suffix=".pdf")
            if bound_account is not None:
                store.bind_source_account(
                    evidence.source_sha256, account.source_identity, account.source_identity_form, bound_account
                )
            sources.append(evidence.source_sha256)
        for summary in store.document_summaries():
            assert summary.overlapping_source_ids == store.overlapping_statement_sources(summary.source_sha256)
        summaries = {item.source_sha256: item for item in store.document_summaries()}
        assert summaries[sources[0]].overlapping_source_ids == (sources[1],)
        assert summaries[sources[1]].overlapping_source_ids == (sources[0],)
        assert all(not summaries[source].overlapping_source_ids for source in sources[2:])


def test_posted_summary_counts_clear_without_changing_evidence(tmp_path):
    path = tmp_path / "reviewed.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        before = store.document_summaries()[0]
        assert before.pending_activity_rows == 2 and before.unassigned_activity_rows == 0
        _review_and_post(store, evidence)
        after = store.document_summaries()[0]
        assert after.pending_activity_rows == after.unassigned_activity_rows == 0
        assert after.source_accounts == before.source_accounts
        assert store.load_import(evidence.source_sha256).evidence == evidence
    raw = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.document_summaries() == (after,)
    assert path.read_bytes() == raw


def test_empty_bound_sections_keep_their_account_and_unavailable_checks_keep_pending(tmp_path):
    path = tmp_path / "multi-section.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        empty_source = _add_ambiguous_source(store, evidence)
        summary = next(item for item in store.document_summaries() if item.source_sha256 == empty_source.source_sha256)
        assert summary.row_count == summary.pending_activity_rows == summary.unassigned_activity_rows == 0
        assert summary.bound_account_names == ("Savings",)
        assert summary.has_identified_accounts
        positions = store.account_positions(as_of=date(2026, 1, 31))
        assert positions.accounts[0].pending_activity_rows == 2
        assert positions.unbound_activity_rows == 0
        assert "live_reconciliation_unavailable" in positions.accounts[0].coverage_warnings
        assert not store.connection.in_transaction


@pytest.mark.parametrize("operation", ["positions", "summaries"])
def test_unbound_archive_sources_are_verified_once(archive, monkeypatch, operation):
    path, evidence = archive
    verified = []
    original = V2ProfileStore._verified_saved_import

    def record(source, row, observations):
        verified.append(source)
        return original(source, row, observations)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(record))
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        if operation == "positions":
            result = store.account_positions(as_of=date(2026, 10, 31))
            assert result.accounts == () and result.unbound_activity_rows == 8
        else:
            assert len(store.document_summaries()) == 4
        assert not store.connection.in_transaction
    assert sorted(verified) == sorted(item.source_sha256 for item in evidence)
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["positions", "summaries"])
@pytest.mark.parametrize(
    "table,statement,parameters,error",
    [
        (
            "Sources",
            "UPDATE Sources SET content=? WHERE sha256=?",
            lambda source: (b"bad", source),
            "saved_snapshot_integrity",
        ),
        ("Definitions", "UPDATE Definitions SET content=?", lambda _source: (b"bad",), "saved_snapshot_integrity"),
        (
            "EvidenceSnapshots",
            "UPDATE EvidenceSnapshots SET content=? WHERE source_sha256=?",
            lambda source: (b"{}", source),
            "saved_snapshot_integrity",
        ),
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
def test_corrupted_unbound_sources_are_refused(archive, operation, table, statement, parameters, error):
    path, evidence = archive
    _tamper(path, evidence[1].source_sha256, table, statement, parameters)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match=error):
            if operation == "positions":
                store.account_positions(as_of=date(2026, 10, 31))
            else:
                store.document_summaries()
        assert not store.connection.in_transaction
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["positions", "summaries"])
def test_concurrent_assignment_uses_current_snapshot_then_next_read(archive, monkeypatch, operation):
    path, evidence = archive
    selected = evidence[0].source_sha256
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    written = False
    original = V2ProfileStore._iter_verified_imports

    def concurrent_write(store):
        nonlocal written
        if not written:
            written = True
            with V2ProfileStore.open(path) as writer:
                writer.add_financial_account(FinancialAccount("cash", "Cash", "asset", "synthetic"))
                writer.bind_source_account(selected, "Checking A", "opaque", "cash")
        yield from original(store)

    monkeypatch.setattr(V2ProfileStore, "_iter_verified_imports", concurrent_write)
    with V2ProfileStore.open(path, read_only=True) as store:
        if operation == "positions":
            first = store.account_positions(as_of=date(2026, 10, 31))
            second = store.account_positions(as_of=date(2026, 10, 31))
            assert first.accounts == () and first.unbound_activity_rows == 8
            assert len(second.accounts) == 1 and second.unbound_activity_rows == 7
        else:
            first = next(item for item in store.document_summaries() if item.source_sha256 == selected)
            second = next(item for item in store.document_summaries() if item.source_sha256 == selected)
            assert first.unassigned_activity_rows == 2 and first.bound_account_names == ()
            assert second.unassigned_activity_rows == 1 and second.bound_account_names == ("Cash",)
        assert not store.connection.in_transaction


def test_nested_summary_read_refuses_without_rolling_back_callers_transaction(archive):
    path, _evidence = archive
    with V2ProfileStore.open(path) as store:
        store.connection.execute("BEGIN")
        with pytest.raises(ProfileFormatError, match="document_summaries_requires_committed_snapshot"):
            store.document_summaries()
        assert store.connection.in_transaction
        store.connection.execute("ROLLBACK")
