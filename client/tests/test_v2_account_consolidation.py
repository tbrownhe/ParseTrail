"""Continuing-account consolidation preserves exact original financial histories."""

import json
import sqlite3
from datetime import date
from time import perf_counter

import pytest
from parsetrail.core.v2_card_lines import parse_card_lines
from parsetrail.core.v2_card_source_output import from_card
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_report_drilldown import read_reviewed_entry_drilldown
from parsetrail.core.v2_source_import import ImportCancelled

from devtools.parser_engine_pilot.test_card_lines import pages
from devtools.parser_engine_pilot.test_card_source_output import DEFINITION

from .test_v2_settlements import post as post_settlement
from .test_v2_settlements import profile as settlement_profile
from .test_v2_transfers import _profile as payment_profile


def _account(store, identity, *, institution="chase", kind="liability", number=None, product="credit_card"):
    store.add_financial_account(
        FinancialAccount(
            identity, identity.title(), kind, institution, full_account_number=number, product_type=product
        )
    )


def _source(store, identity, index=0, *, post=True, amount=1000):
    source = f"%PDF-public-consolidation-{index}-{identity}".encode()
    text = pages()
    text[0] = text[0].replace("1234", "1234" if identity == "old" else "5678")
    text[1] = text[1].replace("10.00", f"{amount // 100}.{amount % 100:02}")
    lines = page_lines(source, text, extraction_library="synthetic-pdf-1")
    evidence = from_card(parse_card_lines(DEFINITION, lines), lines)
    store.import_source(source, DEFINITION, evidence, suffix=".pdf")
    section = evidence.payload.accounts[0]
    store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, identity)
    if post:
        store.post_reviewed_card_purchase(
            section.rows[0].row_id, "expense:food", reason="Reviewed card spend", preferences=V2Preferences(False, True)
        )
    return evidence


def _profile(path, *, sources=True):
    with V2ProfileStore.create(path) as store:
        _account(store, "old", number="1234567890121234")
        _account(store, "kept", number="1234567890125678")
        store.add_category_account("expense:food", "Food", "expense")
        if sources:
            _source(store, "old")
            _source(store, "kept", 1, amount=2000)


def _confirm(store, preview=None, **kwargs):
    preview = preview or store.account_consolidation_snapshot("kept", "old")
    return store.consolidate_accounts(
        "kept",
        "old",
        expected_basis_sha256=preview.basis_sha256,
        expected_profile_sha256=preview.profile_sha256,
        reason="Same actual continuing card obligation",
        reference="Confirmed replacement card",
        **kwargs,
    )


def test_posted_card_history_groups_without_rewriting_and_backup_recovers(tmp_path):
    path = tmp_path / "cards.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        original = {
            table: store.connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in (
                "Accounts",
                "Sources",
                "EvidenceSnapshots",
                "SourceAccountBindings",
                "JournalEntries",
                "JournalAllocations",
            )
        }
        preview = store.account_consolidation_snapshot("kept", "old")
        assert not preview.blockers
        assert (
            preview.source_count,
            preview.source_binding_count,
            preview.activity_row_count,
            preview.journal_entry_count,
        ) == (2, 2, 4, 2)
        assert preview.retained_source_identities == (("1234", "last_four"), ("5678", "last_four"))
        decision = _confirm(store, preview)
        assert _confirm(store, preview) == decision
        assert [item.id for item in store.active_financial_accounts()] == ["kept"]
        assert set(store.account_members("old")) == {"old", "kept"}
        assert store.account_numbers("kept") == ("1234567890121234", "1234567890125678")
        for table, rows in original.items():
            assert store.connection.execute(f"SELECT * FROM {table}").fetchall() == rows
        positions = store.account_positions(as_of=date(2026, 4, 30))
        assert len(positions.accounts) == 1
        account = positions.accounts[0]
        assert account.recorded_debit_minor == -3000 and account.position_debit_minor is None
        assert account.pending_activity_rows == 2 and account.opening_status == "missing"
        movements = store.financial_journal_summary(start=date(2026, 3, 1), end=date(2026, 5, 1))
        assert [(item.account_id, item.nonopening_change_minor) for item in movements.accounts] == [("kept", -3000)]
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 3, 1), end=date(2026, 5, 1)).total_minor
            == 3000
        )
        store._validate_common_journal_read()
    drilldown = read_reviewed_entry_drilldown(path, "kept", start=date(2026, 3, 1), end=date(2026, 5, 1))
    assert drilldown.total_minor == 3000 and len(drilldown.entries) == 2
    assert sorted(drilldown.effect_minor(entry) for entry in drilldown.entries) == [1000, 2000]
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.canonical_account_id("old") == "kept"
        assert store.account_positions(as_of=date(2026, 4, 30)).accounts[0].recorded_debit_minor == -3000


@pytest.mark.parametrize("moment", ["before", "before_write", "before_commit"])
def test_cancellation_is_atomic(tmp_path, moment):
    path = tmp_path / "cancel.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        cancelled = False

        def cancel():
            nonlocal cancelled
            cancelled = True

        kwargs = {"cancelled": lambda: cancelled}
        if moment == "before":
            cancelled = True
        elif moment == "before_write":
            # Callback sets cancellation immediately before writes; the transaction owns rollback.
            kwargs["before_write"] = cancel
        else:
            kwargs["before_commit"] = cancel
        with pytest.raises(ImportCancelled):
            _confirm(store, **kwargs)
        assert not store.account_consolidation_history()
        assert len(store.active_financial_accounts()) == 2
        assert not store.connection.in_transaction


def test_stale_failure_conflicting_retry_and_physical_clone_refuse(tmp_path):
    path = tmp_path / "stale.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        stale = store.account_consolidation_snapshot("kept", "old")
        store.add_category_account("expense:new", "New", "expense")
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            _confirm(store, stale)
        preview = store.account_consolidation_snapshot("kept", "old")

        def fail():
            raise RuntimeError("synthetic failure")

        with pytest.raises(RuntimeError, match="synthetic failure"):
            _confirm(store, preview, before_commit=fail)
        assert not store.account_consolidation_history()
    clone = tmp_path / "clone.db"
    V2ProfileStore.snapshot_to(path, clone)
    with V2ProfileStore.open(clone) as store:
        with pytest.raises(ProfileFormatError, match="profile_changed"):
            _confirm(store, preview)
    with V2ProfileStore.open(path) as store:
        _confirm(store, preview)
        with pytest.raises(ProfileFormatError, match="conflicts_with_prior"):
            store.consolidate_accounts(
                "kept",
                "old",
                expected_basis_sha256=preview.basis_sha256,
                expected_profile_sha256=preview.profile_sha256,
                reason="Other",
                reference="Other",
            )


@pytest.mark.parametrize(
    "institution,kind,product",
    [("citi", "liability", "credit_card"), ("chase", "asset", "checking"), (None, "liability", "credit_card")],
)
def test_incompatible_or_unknown_account_identity_refuses(tmp_path, institution, kind, product):
    path = tmp_path / "incompatible.db"
    with V2ProfileStore.create(path) as store:
        _account(store, "kept")
        _account(store, "old", institution=institution, kind=kind, product=product)
        preview = store.account_consolidation_snapshot("kept", "old")
        assert preview.blockers
        with pytest.raises(ProfileFormatError, match="consolidation_blocked"):
            _confirm(store, preview)
        assert not store.account_consolidation_history()


def test_pending_old_source_stays_postable_but_new_retired_targets_refuse(tmp_path):
    path = tmp_path / "pending.db"
    _profile(path, sources=False)
    with V2ProfileStore.open(path) as store:
        evidence = _source(store, "old", post=False)
        _confirm(store)
        row = evidence.payload.accounts[0].rows[0]
        key = store.post_reviewed_card_purchase(
            row.row_id, "expense:food", reason="Reviewed after consolidation", preferences=V2Preferences(False, True)
        )
        assert (
            json.loads(
                store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
            )["postings"][0]["account_id"]
            == "old"
        )
        assert store.account_positions(as_of=date(2026, 4, 30)).accounts[0].recorded_debit_minor == -1000
        with pytest.raises(ProfileFormatError, match="choose_continuing_account"):
            store.bind_source_account(evidence.source_sha256, "1234", "last_four", "old")


def test_pending_repeats_become_guarded_and_two_posted_repeats_block(tmp_path):
    path = tmp_path / "repeat.db"
    _profile(path, sources=False)
    with V2ProfileStore.open(path) as store:
        _source(store, "old")
        second = _source(store, "kept", 1, post=False)
        preview = store.account_consolidation_snapshot("kept", "old")
        assert not preview.blockers and preview.warnings
        _confirm(store, preview)
        row = second.payload.accounts[0].rows[0]
        with pytest.raises(ProfileFormatError):
            store.post_reviewed_card_purchase(
                row.row_id, "expense:food", reason="Potential repeat", preferences=V2Preferences(False, True)
            )
    path2 = tmp_path / "posted-repeat.db"
    _profile(path2, sources=False)
    with V2ProfileStore.open(path2) as store:
        _source(store, "old")
        _source(store, "kept", 1)
        assert any("posted on both" in value for value in store.account_consolidation_snapshot("kept", "old").blockers)


def test_card_repayment_keeps_different_dates_and_clearing(tmp_path):
    path = tmp_path / "payments.db"
    outgoing, incoming = payment_profile(path, bank_date="01/03/2026")
    with V2ProfileStore.open(path) as store:
        store.add_financial_account(FinancialAccount("kept", "Continuing card", "liability", "citi"))
        store.post_reviewed_transfer(outgoing, incoming, preferences=V2Preferences(), reason="Confirmed card payment")
        preview = store.account_consolidation_snapshot("kept", "card")
        assert not preview.blockers
        store.consolidate_accounts(
            "kept",
            "card",
            expected_basis_sha256=preview.basis_sha256,
            expected_profile_sha256=preview.profile_sha256,
            reason="Same actual card",
            reference="Replaced card",
        )
        transit = store.account_positions(as_of=date(2026, 1, 3))
        assert transit.transfer_clearing_debit_minor == 2000
        settled = store.account_positions(as_of=date(2026, 1, 5))
        assert settled.transfer_clearing_debit_minor == 0
        assert next(item for item in settled.accounts if item.account_id == "kept").recorded_debit_minor == 2000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )


def test_schema_and_audit_are_strict(tmp_path):
    path = tmp_path / "strict.db"
    _profile(path, sources=False)
    with V2ProfileStore.open(path) as store:
        _confirm(store)
        with pytest.raises(sqlite3.IntegrityError):
            store.connection.execute("DELETE FROM AccountConsolidations")
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=27")
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)


def _opening(store, account, amount=-10000, cutoff=date(2026, 1, 1)):
    frame = store.account_anchor_snapshot(account)
    return store.post_reviewed_manual_opening(
        account,
        amount_minor=amount,
        cutoff_date=cutoff,
        tracking_scope="account_total",
        reference="Known continuing-account opening",
        reason="Reviewed opening",
        expected_decision_version=frame.opening.version if frame.opening else None,
        expected_basis_sha256=frame.basis_sha256,
    )


@pytest.mark.parametrize("opening_amount", [-10000, 0])
def test_one_opening_uses_original_owner_and_two_openings_block_until_withdrawn(tmp_path, opening_amount):
    path = tmp_path / "opening.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        opening = _opening(store, "old", amount=opening_amount)
        second = _opening(store, "kept", amount=0)
        assert any("Both accounts" in item for item in store.account_consolidation_snapshot("kept", "old").blockers)
        store.withdraw_reviewed_opening(
            "kept", expected_decision_version=second.version, reason="Remove duplicate opening"
        )
        _confirm(store)
        position = store.account_positions(as_of=date(2026, 4, 30)).accounts[0]
        assert position.opening_status == "valid" and position.position_debit_minor == opening_amount - 3000
        frame = store.account_anchor_snapshot("kept", as_of=date(2026, 4, 30))
        assert frame.opening.account_id == "old" and frame.position_debit_minor == opening_amount - 3000
        assert store.opening_review_snapshot("kept").decision.account_id == "old"
        corrected = _opening(store, "kept", amount=-11000)
        assert corrected.account_id == "old"
        assert store.account_positions(as_of=date(2026, 4, 30)).accounts[0].position_debit_minor == -14000
        assert store.opening_decision_history("old")[-1].version == opening.version


def test_values_are_latest_points_not_added_and_conflicts_block(tmp_path):
    path = tmp_path / "values.db"
    _profile(path, sources=False)
    with V2ProfileStore.open(path) as store:

        def point(account, day, amount):
            frame = store.account_anchor_snapshot(account)
            return store.record_reviewed_dated_value(
                account,
                amount_minor=amount,
                value_date=day,
                tracking_scope="account_total",
                reference="Reviewed printed balance",
                reason="Point, not movement",
                expected_basis_sha256=frame.basis_sha256,
            )

        old = point("old", date(2026, 1, 31), -10000)
        latest = point("kept", date(2026, 2, 28), -9000)
        conflict = point("kept", date(2026, 1, 31), -9999)
        assert any(
            "dated values disagree" in item for item in store.account_consolidation_snapshot("kept", "old").blockers
        )
        store.withdraw_reviewed_dated_value(
            "kept",
            conflict.value_id,
            reason="Remove conflicting point",
            expected_value_version=conflict.version,
            expected_basis_sha256=store.account_anchor_snapshot("kept").basis_sha256,
        )
        _confirm(store)
        position = store.account_positions(as_of=date(2026, 2, 28)).accounts[0]
        assert position.latest_dated_value.value_id == latest.value_id
        assert position.recorded_debit_minor == 0 and position.position_debit_minor is None
        frame = store.account_anchor_snapshot("kept")
        assert {item.value_id for item in frame.dated_values} == {old.value_id, latest.value_id, conflict.value_id}
        with pytest.raises(ProfileFormatError, match="choose_continuing_account"):
            point("old", date(2026, 3, 31), -8000)
        with pytest.raises(ProfileFormatError, match="conflict_requires_review"):
            point("kept", date(2026, 1, 31), -9999)


def test_existing_different_date_member_settlement_blocks_and_new_self_settlement_refuses(tmp_path):
    path = tmp_path / "existing-self.db"
    _, outgoing, incoming = settlement_profile(path)
    with V2ProfileStore.open(path) as store:
        post_settlement(store, outgoing, incoming)
        assert any(
            "journal moves money" in item
            for item in store.account_consolidation_snapshot("checking", "savings").blockers
        )
    path2 = tmp_path / "new-self.db"
    _, outgoing, incoming = settlement_profile(path2)
    with V2ProfileStore.open(path2) as store:
        preview = store.account_consolidation_snapshot("checking", "savings")
        store.consolidate_accounts(
            "checking",
            "savings",
            expected_basis_sha256=preview.basis_sha256,
            expected_profile_sha256=preview.profile_sha256,
            reason="Same actual cash account",
            reference="Owner confirmed",
        )
        with pytest.raises(ProfileFormatError, match="same_continuing_account"):
            post_settlement(store, outgoing, incoming)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_eighty_bindings_preflight_and_positions_preserve_all_sources(tmp_path, record_property):
    path = tmp_path / "eighty.db"
    _profile(path, sources=False)
    with V2ProfileStore.open(path) as store:
        with store._atomic_write("synthetic_eighty_setup"):
            for index in range(80):
                _source(store, "old" if index < 40 else "kept", index, post=False, amount=1000 + index)
        start = perf_counter()
        preview = store.account_consolidation_snapshot("kept", "old")
        record_property("eighty_preflight_seconds", perf_counter() - start)
        assert not preview.blockers and preview.source_count == preview.source_binding_count == 80
        _confirm(store, preview)
        start = perf_counter()
        report = store.account_positions(as_of=date(2026, 4, 30))
        record_property("eighty_positions_seconds", perf_counter() - start)
        assert len(report.accounts) == 1 and report.accounts[0].pending_activity_rows == 160
        assert report.accounts[0].position_debit_minor is None
        assert len(store.document_summaries()) == 80


def test_expected_destination_on_absorbed_account_resolves_later_kept_receipt(tmp_path):
    from .test_v2_flexible_funding import deposit, funding
    from .test_v2_loan_payments import PREFERENCES
    from .test_v2_origination import origination_profile

    path = tmp_path / "expected-destination.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        store.add_financial_account(FinancialAccount("kept", "Continuing bank", "asset", "synthetic"))
        store.add_financial_account(FinancialAccount("other", "Different bank account", "asset", "synthetic"))
        event = store.post_loan_origination(funding(store, row, destination_account_id="bank"))
        original_event = store.connection.execute("SELECT * FROM LoanOriginationEvents").fetchall()
        original_journals = store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key").fetchall()
        preview = store.account_consolidation_snapshot("kept", "bank")
        assert not preview.blockers
        store.consolidate_accounts(
            "kept",
            "bank",
            expected_basis_sha256=preview.basis_sha256,
            expected_profile_sha256=preview.profile_sha256,
            reason="Same actual continuing bank account",
            reference="Confirmed duplicate bookkeeping records",
        )
        wrong_receipt = deposit(store, account="other", day="01/17/2026")
        wrong_state = store.resolution_snapshot(preferences=PREFERENCES)
        assert not any(item.outgoing_id == event.event_id for item in wrong_state.candidates)
        with pytest.raises(ProfileFormatError, match="resolution_candidate_unavailable"):
            store.resolve_transfer(
                event.event_id,
                "row:" + wrong_receipt,
                preferences=PREFERENCES,
                expected_basis_sha256=wrong_state.basis_sha256,
                reason="Different account is not the expected destination",
            )
        assert (
            store.connection.execute("SELECT key,payload FROM JournalEntries ORDER BY key").fetchall()
            == original_journals
        )
        receipt = deposit(store, account="kept")
        state = store.resolution_snapshot(preferences=PREFERENCES)
        candidate = next(item for item in state.candidates if item.outgoing_id == event.event_id)
        assert candidate.incoming_id == "row:" + receipt
        link = store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Confirmed receipt on continuing account",
        )
        assert (
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Confirmed receipt on continuing account",
            )
            == link
        )
        assert store.connection.execute("SELECT * FROM LoanOriginationEvents").fetchall() == original_event
        for key, payload in original_journals:
            assert store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone() == (
                payload,
            )
        positions = store.account_positions(as_of=date(2026, 1, 16))
        assert positions.transfer_clearing_debit_minor == 0 and positions.unresolved_transfer_count == 0
        assert next(item for item in positions.accounts if item.account_id == "kept").recorded_debit_minor == 1000000
        assert store.account_positions(as_of=date(2026, 1, 15)).transfer_clearing_debit_minor == 1000000
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
    backup = tmp_path / "expected-destination-backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup) as store:
        assert store.resolution_snapshot(preferences=PREFERENCES).links[0] == link
        store.withdraw_transfer_resolution(link.link_id, expected_version=link.version, reason="Recheck receipt")
        assert len(store._active_journal_entries()) == 2
        assert store.account_positions(as_of=date(2026, 1, 16)).unresolved_transfer_count == 2
