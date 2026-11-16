"""Vehicle financing preserves source principal, authored acquisition and separate bank evidence."""

from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore

from devtools.parser_engine_pilot import test_loan_history_lines as capital

from .test_v2_loan_payments import PREFERENCES, _profile


def origination_profile(path, *, downpayment=500000):
    evidence = parse_loan_history(
        capital.DEFINITION,
        capital.lines(interest=False, changes={1: "Current Payment Due: $300.00 Principal Balance: $10,000.00"}),
    )
    bank, rows = _profile(path, amount=downpayment, evidence=evidence)
    with V2ProfileStore.open(path) as store:
        store.create_tangible_asset(
            FinancialAccount("vehicle", "My vehicle", "asset", None, product_type="vehicle"),
            value_date=date(2026, 1, 16),
            amount_minor=1500000,
            annual_rate_basis_points=1000,
            reason="Owner estimated purchase value",
        )
    return bank, rows[0]


def preview(store, row, bank=None, *, value=1000000):
    state = store.origination_snapshot()
    return store.preview_loan_origination(
        row,
        destination_account_id="vehicle",
        acquisition_value_minor=value,
        acquisition_date=date(2026, 1, 16),
        bank_downpayment_row_id=bank,
        preferences=PREFERENCES,
        expected_basis_sha256=state.basis_sha256,
        reason="Reviewed vehicle acquisition",
    )


def test_origination_exact_financing_posts_distinct_dates_and_unknown_opening_then_withdraws(tmp_path):
    path = tmp_path / "origination.db"
    bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        frame = store.origination_snapshot()
        assert len(frame.rows) == 1 and frame.rows[0].principal_minor == 1000000
        draft = preview(store, row)
        assert len(draft.entries) == 2 and store._active_journal_entries() == ()
        event = store.post_loan_origination(draft)
        assert store.post_loan_origination(draft) == event
        assert store._active_consumed() == {row: 1000000}
        assert [
            (e.posting_date, [(p.account_id, p.amount_minor) for p in e.postings])
            for e in store._active_journal_entries()
        ] == [
            (date(2026, 1, 15), [("loan", -1000000), ("internal:transfer-clearing:USD", 1000000)]),
            (date(2026, 1, 16), [("vehicle", 1000000), ("internal:transfer-clearing:USD", -1000000)]),
        ]
        assert not store.opening_decision_history("loan") and not store.opening_decision_history("vehicle")
        assert next(i for i in store.origination_snapshot().rows if i.row_id == row).event_id == event.event_id
        with pytest.raises(ProfileFormatError, match="preview_invalid"):
            store.post_loan_origination(replace(draft, acquisition_value_minor=1000001))
        store.withdraw_loan_origination(
            event.event_id, expected_version=event.version, reason="Review destination again"
        )
        assert store._active_journal_entries() == () and store._active_consumed().get(row, 0) == 0
        with pytest.raises(ProfileFormatError, match="event_retired"):
            store.post_loan_origination(draft)
        fresh = preview(store, row)
        assert store.post_loan_origination(fresh).event_id != event.event_id
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup) as store:
        assert len(store._active_journal_entries()) == 2 and len(store.origination_snapshot().events) == 2


def test_origination_downpayment_requires_exact_actual_outflow_and_preserves_its_date(tmp_path):
    path = tmp_path / "downpayment.db"
    bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        with pytest.raises(ProfileFormatError, match="downpayment_evidence_required"):
            preview(store, row, value=1500000)
        with pytest.raises(ProfileFormatError, match="downpayment_evidence_required"):
            preview(store, row, bank, value=1499999)
        draft = preview(store, row, bank, value=1500000)
        event = store.post_loan_origination(draft)
        assert len(event.entry_keys) == 3
        assert store._active_consumed() == {row: 1000000, bank: -500000}
        assert (
            sum(
                p.amount_minor for e in store._active_journal_entries() for p in e.postings if p.account_id == "vehicle"
            )
            == 1500000
        )
        assert next(e.posting_date for e in store._active_journal_entries() if e.key.endswith(":downpayment")) == date(
            2026, 1, 14
        )
        assert not any(p.account_id.startswith("builtin:") for e in store._active_journal_entries() for p in e.postings)


def test_asset_value_is_nonposting_estimate_and_same_date_a_b_a_can_be_corrected(tmp_path):
    path = tmp_path / "values.db"
    origination_profile(path)
    with V2ProfileStore.open(path) as store:
        first = store.tangible_asset_values(as_of=date(2026, 1, 16))[0]
        assert first.amount_minor == first.estimated_minor == 1500000
        later = store.tangible_asset_values(as_of=date(2027, 1, 16))[0]
        assert 1349000 < later.estimated_minor < 1351000
        store.set_tangible_asset_value(
            "vehicle", value_date=first.value_date, amount_minor=2000000, reason=first.reason
        )
        restored = store.set_tangible_asset_value(
            "vehicle",
            value_date=first.value_date,
            amount_minor=1500000,
            annual_rate_basis_points=1000,
            reason=first.reason,
        )
        assert restored.amount_minor == 1500000 and restored.revision_id > first.revision_id
        assert store._active_journal_entries() == ()
        with pytest.raises(ProfileFormatError, match="tangible_asset_cannot_bind_statement"):
            source = store.source_ids()[0]
            store.assert_file_account(source, "vehicle")


def test_origination_date_and_vehicle_guards_refuse_without_writes(tmp_path):
    path = tmp_path / "guards.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        basis = store.origination_snapshot().basis_sha256
        with pytest.raises(ProfileFormatError, match="assumed_date_permission"):
            store.preview_loan_origination(
                row,
                destination_account_id="vehicle",
                acquisition_value_minor=1000000,
                acquisition_date=date(2026, 1, 16),
                preferences=V2Preferences(),
                expected_basis_sha256=basis,
                reason="Initial Review",
            )
        with pytest.raises(ProfileFormatError, match="vehicle_destination"):
            store.preview_loan_origination(
                row,
                destination_account_id="bank",
                acquisition_value_minor=1000000,
                acquisition_date=date(2026, 1, 16),
                preferences=PREFERENCES,
                expected_basis_sha256=basis,
                reason="Initial Review",
            )
        assert store._active_journal_entries() == ()


def test_origination_preview_binds_physical_profile_before_retry_or_write(tmp_path):
    path = tmp_path / "original.db"
    _bank, row = origination_profile(path)
    clone = tmp_path / "clone.db"
    V2ProfileStore.snapshot_to(path, clone)
    with V2ProfileStore.open(path) as store:
        draft = preview(store, row)
    with V2ProfileStore.open(clone) as store:
        with pytest.raises(ProfileFormatError, match="profile_changed"):
            store.post_loan_origination(draft)
        assert store._active_journal_entries() == ()
    with V2ProfileStore.open(path) as store:
        event = store.post_loan_origination(draft)
        assert store.post_loan_origination(draft) == event


def test_optional_asset_decline_rate_keeps_future_value_unknown_until_explicitly_supplied(tmp_path):
    path = tmp_path / "unknown-estimate.db"
    with V2ProfileStore.create(path) as store:
        store.create_tangible_asset(
            FinancialAccount("vehicle", "Vehicle", "asset", None, product_type="vehicle"),
            value_date=date(2026, 1, 16),
            amount_minor=1500000,
            reason="Owner entered value; decline unknown",
        )
        initial = store.tangible_asset_values(as_of=date(2026, 1, 16))[0]
        assert initial.amount_minor == initial.estimated_minor == 1500000
        later = store.tangible_asset_values(as_of=date(2027, 1, 16))[0]
        assert (
            later.amount_minor == 1500000 and later.annual_rate_basis_points is None and later.estimated_minor is None
        )
        store.set_tangible_asset_value(
            "vehicle",
            value_date=date(2026, 1, 16),
            amount_minor=1500000,
            annual_rate_basis_points=0,
            reason="Owner explicitly assumes no annual decline",
        )
        explicit_flat = store.tangible_asset_values(as_of=date(2027, 1, 16))[0]
        assert explicit_flat.annual_rate_basis_points == 0 and explicit_flat.estimated_minor == 1500000
        assert store._active_journal_entries() == ()
