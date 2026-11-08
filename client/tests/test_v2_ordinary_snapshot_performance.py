"""Selected reads retain integrity while avoiding repeated evidence/JSON work."""

import hashlib
import json

import pytest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_overlap import OVERLAP_RULE
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_ordinary_batch import DEFINITION, SOURCE, _counts, _profile
from .test_v2_transfers import _profile as _transfer_profile


def test_cash_read_model_preserves_derived_date_origin(tmp_path):
    from parsetrail.core.v2_profile_store import FinancialAccount
    from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

    from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION as BANK_DEFINITION
    from devtools.parser_engine_pilot.test_table_bank_source_output import SOURCE as BANK_SOURCE
    from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels

    evidence = from_anchored_bank(BANK_DEFINITION, *bank_channels())
    account = evidence.payload.accounts[0]
    path = tmp_path / "derived-dates.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(BANK_SOURCE, BANK_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("cash", "Synthetic bank", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        assert {row.row_id: row.date_provenance for row in frame.rows} == {
            row.row_id: row.date.provenance for row in account.rows
        }
        assert any(row.date_provenance == "derived" for row in frame.rows)


def test_every_import_decodes_once_and_only_requested_evidence_is_retained(tmp_path, monkeypatch):
    path = tmp_path / "streamed.db"
    selected = _profile(path)
    with V2ProfileStore.open(path) as store:
        for number in range(24):
            raw = SOURCE.replace(b"Coffee", f"Unbound source {number}".encode())
            parsed = build_source_evidence(raw, DEFINITION, suffix=".csv")
            store.import_source(raw, DEFINITION, parsed, suffix=".csv")
    original = V2ProfileStore._verified_saved_import
    decoded = []

    def verified(source, row, actual):
        decoded.append(source)
        return original(source, row, actual)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(verified))
    with V2ProfileStore.open(path, read_only=True) as store:
        iterator = store._iter_verified_imports

        def streamed():
            for item in iterator():
                assert len(store._source_read_evidence) <= 1
                yield item

        monkeypatch.setattr(store, "_iter_verified_imports", streamed)
        frame = store.source_interpretation_snapshot(selected.source_sha256, kind="cash")
        assert len(frame.rows) == 3 and len(decoded) == 25 and len(set(decoded)) == 25
        assert store._source_read_evidence is None and store._transfer_history_cache is None
        assert not store.connection.in_transaction
        store.source_interpretation_snapshot(selected.source_sha256, kind="cash")
        assert len(decoded) == 50


def test_basis_preserves_previous_exact_digest_encoding(tmp_path):
    path = tmp_path / "basis.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        store.add_category_account("expense:unicode", "Caf\u00e9 \u2615", "expense")
        actual = store._source_overlap_basis()
        digest = hashlib.sha256(OVERLAP_RULE.encode())
        for table in (
            "LoanEvents",
            "LoanEventActions",
            "LoanSourceUses",
            "DerivedFinancialObservations",
            "JournalDerivedAllocations",
            "EvidenceSnapshots",
            "SourceObservations",
            "Accounts",
            "SourceAccountBindings",
            "FileAccountAssertions",
            "RowAccountAssignments",
            "JournalEntries",
            "JournalAllocations",
            "JournalCorrections",
            "JournalRetirements",
            "OpeningDecisionRevisions",
            "OpeningDecisions",
            "AccountDatedValues",
            "DatedValueWithdrawals",
            "AccountLifecycleDecisions",
            "TransferEvents",
            "TransferEventActions",
            "TransferPairReviews",
            "SourceInterpretationActions",
            "PostedRepeatRepairs",
            "SourceOverlapReviews",
            "BindingCorrections",
        ):
            digest.update(table.encode())
            columns = "source_sha256,definition_sha256,size,sha256" if table == "EvidenceSnapshots" else "*"
            for row in sorted(
                store.connection.execute(f"SELECT {columns} FROM {table}"),
                key=lambda value: json.dumps(value, separators=(",", ":")),
            ):
                digest.update(json.dumps(row, separators=(",", ":")).encode())
        assert digest.hexdigest() == actual


def test_guard_index_keeps_all_neighbors_and_durable_repeat_rules(tmp_path):
    path = tmp_path / "index.db"
    evidence = _profile(path)
    raw = SOURCE.replace(b"Coffee", b"Another source")
    other = build_source_evidence(raw, DEFINITION, suffix=".csv")
    with V2ProfileStore.open(path) as store:
        store.import_source(raw, DEFINITION, other, suffix=".csv")
        store.bind_source_account(other.source_sha256, "Checking A", "opaque", "cash")
        left, right = evidence.payload.rows[0].row_id, other.payload.rows[0].row_id
        pair = store.source_overlap_pair(left, right)
        store.record_source_overlap_review(
            left,
            right,
            decision="repeat",
            retained_row_id=left,
            reason="Explicit repeated export",
            expected_basis_sha256=pair.basis_sha256,
        )
        full = store._source_overlap_index()
        light = store._source_overlap_index(_posting_only=True)
        assert full[2:] == light[2:]
        assert set(full[0]) == set(light[0])
        assert all(full[1].neighbors(row_id) == light[1].neighbors(row_id) for row_id in full[0])
        assert store._source_overlap_posting_blocks(tuple(full[0]), _verified_index=full) == (
            store._source_overlap_posting_blocks(tuple(light[0]), _verified_index=light)
        )
        assert full[0][left].locations and not light[0][left].locations


def test_requested_source_cache_refuses_own_write_and_savepoint_rollback(tmp_path):
    path = tmp_path / "epochs.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("BEGIN IMMEDIATE")
        try:
            with store._verified_source_operation():
                saved = store.load_import(evidence.source_sha256)
                assert store.load_import(evidence.source_sha256) is saved
                trigger = store.connection.execute(
                    "SELECT sql FROM sqlite_master WHERE name='immutable_Sources_update'"
                ).fetchone()[0]
                store.connection.execute("SAVEPOINT transient")
                store.connection.execute("DROP TRIGGER immutable_Sources_update")
                store.connection.execute("UPDATE Sources SET content=x'00' WHERE sha256=?", (evidence.source_sha256,))
                store.connection.execute(trigger)
                with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
                    store.load_import(evidence.source_sha256)
                store.connection.execute("ROLLBACK TO transient")
                restored = store.load_import(evidence.source_sha256)
                assert restored == saved and restored is not saved
        finally:
            store.connection.execute("ROLLBACK")
        assert store._source_read_evidence is None


def test_transfer_ownership_routes_whole_event_without_second_expense(tmp_path):
    path = tmp_path / "owner.db"
    cash_id, card_id = _transfer_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        event = store.post_reviewed_transfer(cash_id, card_id, preferences=V2Preferences(), reason="Reviewed repayment")
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (cash_id,)
        ).fetchone()[0]
        frame = store.source_interpretation_snapshot(source, kind="cash")
        assert frame.rows[0].entry_key is None and frame.rows[0].allowed_purposes == ()
        assert [(o.row_id, o.owner_kind, o.event_id) for o in frame.owners] == [(cash_id, "transfer", event)]
        assert frame.entries == () and _counts(store)[:2] == (2, 2)


def test_loan_ownership_keeps_principal_interest_and_distinct_dates(tmp_path):
    from .test_v2_loan_payments import _post
    from .test_v2_loan_payments import _profile as _loan_profile

    path = tmp_path / "loan-owner.db"
    bank, rows = _loan_profile(path)
    with V2ProfileStore.open(path) as store:
        event = _post(store, bank, rows)
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (bank,)
        ).fetchone()[0]
        frame = store.source_interpretation_snapshot(source, kind="cash")
        assert frame.owners[0].row_id == bank and frame.owners[0].owner_kind == "loan"
        assert frame.owners[0].event_id == event.event_id and frame.owners[0].label == "Reviewed loan payment"
        assert frame.entries == () and frame.rows[0].entry_key is None
        assert event.manifest.bank.posting_date == "2026-01-14"
        assert event.manifest.components[0].effective_date == "2026-01-15"
        assert event.manifest.principal_minor == 20000 and event.manifest.interest_minor == 2000


def test_cancelled_snapshot_clears_read_scope_and_transaction(tmp_path):
    path = tmp_path / "cancelled.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="cancelled"):
            store.source_interpretation_snapshot(evidence.source_sha256, kind="cash", cancelled=lambda: True)
        assert store._source_read_evidence is None and not store.connection.in_transaction


def test_statement_period_warnings_reuse_verified_dates_without_retaining_archive_models(tmp_path, monkeypatch):
    from parsetrail.core.v2_card_lines import parse_card_lines
    from parsetrail.core.v2_card_source_output import from_card
    from parsetrail.core.v2_pdf_lines import page_lines
    from parsetrail.core.v2_profile_store import FinancialAccount

    from devtools.parser_engine_pilot.test_card_lines import pages
    from devtools.parser_engine_pilot.test_card_source_output import DEFINITION as CARD_DEFINITION

    path = tmp_path / "statements.db"
    sources = []
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("card", "Synthetic card", "liability", "synthetic"))
        for number in range(4):
            raw = f"%PDF-public-synthetic-{number}".encode()
            lines = page_lines(raw, pages(), extraction_library="synthetic-pdf-1")
            evidence = from_card(parse_card_lines(CARD_DEFINITION, lines), lines)
            store.import_source(raw, CARD_DEFINITION, evidence, suffix=".pdf")
            section = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "card"
            )
            sources.append(evidence.source_sha256)
    original = V2ProfileStore._verified_saved_import
    decoded = []

    def verified(source, row, actual):
        decoded.append(source)
        return original(source, row, actual)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(verified))
    with V2ProfileStore.open(path, read_only=True) as store:
        original_periods = store.overlapping_statement_sources

        def overlaps(source):
            result = original_periods(source)
            assert len(store._source_read_evidence) == 1
            return result

        monkeypatch.setattr(store, "overlapping_statement_sources", overlaps)
        frame = store.source_interpretation_snapshot(sources[0], kind="card", preferences=V2Preferences())
        assert frame.overlapping_source_ids == tuple(sorted(sources[1:]))
        assert len(decoded) == 4 and len(set(decoded)) == 4
        assert store._source_read_periods is None
