"""Borrowing is exact even when receipt, purchase cost and valuation are unknown."""

import hashlib
import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_ordinary_batch import OrdinaryTransferSelection
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_table_card_source_output import from_anchored_card

from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

from .test_v2_loan_payments import PREFERENCES
from .test_v2_origination import origination_profile
from .test_v2_transfers import BANK_DEFINITION


def funding(store, row, **kwargs):
    return store.preview_loan_funding(
        row,
        preferences=PREFERENCES,
        expected_basis_sha256=store.origination_snapshot().basis_sha256,
        reason="Initial Review",
        **kwargs,
    )


def deposit(store, *, account="bank", amount=1000000, day="01/16/2026"):
    raw = (
        f"Date,Account,Description,Amount,ReportedBalance\n"
        f"{day},Receipt,Loan proceeds,${amount // 100}.{amount % 100:02d},Unavailable\n"
    ).encode()
    evidence = build_source_evidence(raw, BANK_DEFINITION, suffix=".csv")
    store.import_source(raw, BANK_DEFINITION, evidence, suffix=".csv")
    store.bind_source_account(evidence.source_sha256, "Receipt", "opaque", account)
    return evidence.payload.rows[0].row_id


@pytest.mark.parametrize("expected_destination", [None, "bank"])
def test_exact_borrowing_unresolved_then_actual_receipt_only_adds_cash_once(tmp_path, expected_destination):
    path = tmp_path / "funding.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        draft = funding(store, row, destination_account_id=expected_destination)
        assert draft.mode == "funding" and draft.acquisition_value_minor is None
        assert len(draft.entries) == 1 and store._active_journal_entries() == ()
        event = store.post_loan_origination(draft)
        assert store.post_loan_origination(draft) == event
        assert event.total_acquisition_cost_minor is None and event.tangible_allocation_date is None
        assert event.effective_date == date(2026, 1, 15) and event.date_provenance == "assumed"
        assert [(p.account_id, p.amount_minor) for p in draft.entries[0].postings] == [
            ("loan", -1000000),
            ("internal:transfer-clearing:USD", 1000000),
        ]
        assert store.account_positions(as_of=date(2026, 1, 15)).unresolved_transfer_count == 1
        assert store.resolution_snapshot(preferences=PREFERENCES).items[0].direction == "outgoing"
        receipt = deposit(store)
        state = store.resolution_snapshot(preferences=PREFERENCES)
        candidate = next(c for c in state.candidates if c.outgoing_id == event.event_id)
        assert candidate.incoming_id == "row:" + receipt
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_link BEFORE INSERT ON TransferResolutionLinks "
            "BEGIN SELECT RAISE(ABORT,'synthetic link failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic link failure"):
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Confirmed owned receipt",
            )
        assert len(store._active_journal_entries()) == 1 and store._active_consumed() == {row: 1000000}
        assert store.resolution_snapshot(preferences=PREFERENCES).basis_sha256 == state.basis_sha256
        store.connection.execute("DROP TRIGGER fail_link")
        link = store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Confirmed owned receipt",
        )
        assert (
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Confirmed owned receipt",
            )
            == link
        )
        entries = store._active_journal_entries()
        assert len(entries) == 2 and entries[0].posting_date != entries[1].posting_date
        assert store._active_consumed() == {row: 1000000, receipt: 1000000}
        assert sum(p.amount_minor for e in entries for p in e.postings if p.account_id == "loan") == -1000000
        assert sum(p.amount_minor for e in entries for p in e.postings if p.account_id == "bank") == 1000000
        assert store.account_positions(as_of=date(2026, 1, 16)).unresolved_transfer_count == 0
        with pytest.raises(ProfileFormatError, match="unlink_before_correction"):
            store.withdraw_loan_origination(event.event_id, expected_version=event.version, reason="Correct borrowing")
        store.withdraw_transfer_resolution(link.link_id, expected_version=link.version, reason="Recheck receipt")
        assert store.account_positions(as_of=date(2026, 1, 16)).unresolved_transfer_count == 2
        assert sum(p.amount_minor for e in entries for p in e.postings if p.account_id.endswith("clearing:USD")) == 0
        store.withdraw_loan_origination(event.event_id, expected_version=event.version, reason="Correct borrowing")
        assert len(store._active_journal_entries()) == 1
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.origination_snapshot().events[0].status == "withdrawn"
        assert len(store._active_journal_entries()) == 1


def test_confirmed_tangible_allocation_is_exact_financed_portion_with_unknown_cost(tmp_path):
    path = tmp_path / "asset.db"
    _bank, row = origination_profile(path, principal=1530941)
    with V2ProfileStore.open(path) as store:
        store.set_tangible_asset_value(
            "vehicle",
            value_date=date(2026, 1, 15),
            amount_minor=2000000,
            annual_rate_basis_points=-1400,
            reason="Independent estimated value",
        )
        with pytest.raises(ProfileFormatError, match="confirmation_required"):
            funding(store, row, destination_account_id="vehicle")
        draft = funding(
            store,
            row,
            destination_account_id="vehicle",
            confirm_tangible_allocation=True,
            tangible_allocation_date=date(2026, 1, 16),
        )
        event = store.post_loan_origination(draft)
        assert event.total_acquisition_cost_minor is None and event.acquisition_value_minor is None
        assert event.tangible_allocation_date == date(2026, 1, 16)
        assert len(event.entry_keys) == 2 and store._active_consumed() == {row: 1530941}
        assert sum(p.amount_minor for e in draft.entries for p in e.postings if p.account_id == "vehicle") == 1530941
        assert not any(abs(p.amount_minor) == 469059 for e in draft.entries for p in e.postings)
        assert not any(item.kind == "origination" for item in store.resolution_snapshot(preferences=PREFERENCES).items)
        assert store.account_positions(as_of=date(2026, 1, 16)).unresolved_transfer_count == 0
        assert not store.opening_decision_history("loan") and not store.opening_decision_history("vehicle")
        assert store.tangible_asset_values(as_of=date(2026, 1, 15))[0].amount_minor == 2000000
        with pytest.raises(ProfileFormatError, match="preview_invalid"):
            store.post_loan_origination(replace(draft, acquisition_value_minor=2000000))


def signed_card_profile(path):
    # Two explicitly assigned accounts: a credit on the old card, new debt on the other.
    channels = card_channels({0: ("01/05", "01/05", "Payment", "-$10.00")})
    table, lines = channels
    # Keep the public synthetic statement equation exact: -100 +10 -10 = -100.
    from parsetrail.core.v2_pdf_lines import page_lines

    lines = page_lines(
        CARD_SOURCE,
        [
            "Account number ending in: 1234\nPrevious balance $100.00\nNew balance $100.00",
            "Account number ending in 1234",
        ],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )
    card = from_anchored_card(CARD_DEFINITION, table, lines)
    second_raw = b"%PDF-second-synthetic-card"
    second_table = replace(table, source_sha256=hashlib.sha256(second_raw).hexdigest())
    second_lines = page_lines(
        second_raw,
        [
            "Account number ending in: 1234\nPrevious balance $100.00\nNew balance $100.00",
            "Account number ending in 1234",
        ],
        extraction_library="pdfplumber-bounded-layout-default-v1",
    )
    second_card = from_anchored_card(CARD_DEFINITION, second_table, second_lines)
    with V2ProfileStore.create(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, card, suffix=".pdf")
        store.import_source(second_raw, CARD_DEFINITION, second_card, suffix=".pdf")
        store.add_financial_account(FinancialAccount("old", "Old card", "liability", "citi"))
        store.add_financial_account(FinancialAccount("new", "New card", "liability", "citi"))
        section = card.payload.accounts[0]
        store.bind_source_account(card.source_sha256, section.source_identity, section.source_identity_form, "old")
        store.bind_source_account(
            second_card.source_sha256, section.source_identity, section.source_identity_form, "new"
        )
    return card, second_card


def test_negative_card_transfer_mixed_batch_and_debt_to_debt_link_no_expense(tmp_path):
    path = tmp_path / "cards.db"
    incoming_evidence, evidence = signed_card_profile(path)
    incoming = incoming_evidence.payload.accounts[0].rows[0].row_id
    outgoing = evidence.payload.accounts[0].rows[1].row_id
    with V2ProfileStore.open(path) as store:
        state = store.source_interpretation_snapshot(evidence.source_sha256, kind="card", preferences=PREFERENCES)
        assert outgoing in state.transfer_eligible_row_ids
        draft = store.preview_reviewed_ordinary_batch(
            evidence.source_sha256,
            kind="card",
            selections=(OrdinaryTransferSelection(outgoing),),
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Initial Review",
        )
        posted = store.post_reviewed_ordinary_batch(draft)
        assert store.post_reviewed_ordinary_batch(draft).already_posted
        state = store.resolution_snapshot(preferences=PREFERENCES)
        candidate = next(
            c
            for c in state.candidates
            if c.outgoing_id == posted.resolution_event_ids[0] and c.incoming_id == "row:" + incoming
        )
        store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Owned balance transfer",
        )
        assert store._active_consumed() == {outgoing: -1000, incoming: 1000}
        assert len(store._active_journal_entries()) == 2
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        assert store.transfer_candidates(preferences=PREFERENCES) == ()
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_fresh_builtin_and_signed_estimates_are_nonposting_and_read_only(tmp_path):
    path = tmp_path / "values.db"
    with V2ProfileStore.create(path) as store:
        assert [(c.id, c.name) for c in store.category_accounts()] == [("builtin:loan-interest", "Loan interest")]
        store.add_financial_account(
            FinancialAccount("asset", "Precious metals", "asset", None, product_type="tangible_asset")
        )
        assert not store.tangible_asset_values()
        for rate in (-10000, -1400, 0, 500, 100000, None):
            point = store.set_tangible_asset_value(
                "asset",
                value_date=date(2026, 1, 1),
                amount_minor=2000000,
                annual_rate_basis_points=rate,
                reason="Owner estimate",
            )
            estimate = store.tangible_asset_values(as_of=date(2027, 1, 1))[0].estimated_minor
            assert point.amount_minor == 2000000
            if rate is None:
                assert estimate is None
            elif rate == -10000:
                assert estimate == 0
            elif rate < 0:
                assert 0 < estimate < 2000000
            elif rate == 0:
                assert estimate == 2000000
            else:
                assert estimate > 2000000
        assert store._active_journal_entries() == ()
        with pytest.raises(ProfileFormatError, match="value_invalid"):
            store.set_tangible_asset_value(
                "asset", value_date=date(2026, 1, 1), amount_minor=1, annual_rate_basis_points=-10001, reason="Invalid"
            )
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert len(store.category_accounts()) == 1
        assert store.tangible_asset_values(as_of=date(2027, 1, 1))[0].estimated_minor is None
    assert path.read_bytes() == before
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA user_version=26")
    with pytest.raises(ProfileFormatError):
        V2ProfileStore.open(path)


def test_borrowing_can_refinance_another_loan_using_its_separate_evidenced_payment(tmp_path):
    from devtools.parser_engine_pilot import test_wells_loan_lines as wells

    path = tmp_path / "refinance.db"
    _bank, row = origination_profile(path)
    old = wells.parse(
        {
            3: "Prior Principal Balance $10,000.00",
            4: "01/15/26 INTEREST PAYMENT $1.00",
            5: "01/15/26 PRINCIPAL PAYMENT $9,999.00",
            6: "01/31/26 Ending Principal Balance $1.00*",
        }
    )
    with V2ProfileStore.open(path) as store:
        store.import_source(b"%PDF-synthetic-loan", wells.DEFINITION, old, suffix=".pdf")
        store.add_financial_account(
            FinancialAccount("old-loan", "Old loan", "liability", "synthetic", tracking_scope="principal_component")
        )
        section = old.payload.accounts[0]
        store.bind_source_account(old.source_sha256, section.source_identity, section.source_identity_form, "old-loan")
        borrowing = store.post_loan_origination(funding(store, row, destination_account_id="old-loan"))
        payment = store.post_reviewed_loan_payment(
            None,
            tuple(r.row_id for r in section.rows),
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Printed repayment",
            reference="Printed principal and interest",
        )
        state = store.resolution_snapshot(preferences=PREFERENCES)
        assert (borrowing.event_id, payment.event_id) in {(c.outgoing_id, c.incoming_id) for c in state.candidates}
        store.resolve_transfer(
            borrowing.event_id,
            payment.event_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Confirmed direct refinance",
        )
        assert len(store._active_journal_entries()) == 3
        amounts = {}
        for entry in store._active_journal_entries():
            for posting in entry.postings:
                amounts[posting.account_id] = amounts.get(posting.account_id, 0) + posting.amount_minor
        assert amounts == {
            "loan": -1000000,
            "old-loan": 999900,
            "builtin:loan-interest": 100,
            "internal:transfer-clearing:USD": 0,
        }
        assert store.account_positions(as_of=date(2026, 1, 16)).unresolved_transfer_count == 0
        assert not store.opening_decision_history("old-loan")


def test_negative_card_can_fund_cash_without_old_settlement_policy_expansion(tmp_path):
    path = tmp_path / "cash-advance.db"
    _incoming, card = signed_card_profile(path)
    outgoing = card.payload.accounts[0].rows[1].row_id
    with V2ProfileStore.open(path) as store:
        store.add_financial_account(FinancialAccount("cash", "Cash", "asset", None, product_type="cash"))
        receipt = deposit(store, account="cash", amount=1000, day="01/10/2026")
        event = store.post_unresolved_transfer(
            outgoing,
            preferences=PREFERENCES,
            expected_basis_sha256=store.resolution_snapshot(preferences=PREFERENCES).basis_sha256,
            reason="Owned cash advance",
        )
        assert all(m.row_id != outgoing for m in store._transfer_movements(PREFERENCES))
        state = store.resolution_snapshot(preferences=PREFERENCES)
        store.resolve_transfer(
            event.id,
            "row:" + receipt,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Actual cash receipt",
        )
        assert store._active_consumed() == {outgoing: -1000, receipt: 1000}
        assert len(store._active_journal_entries()) == 2
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )


def test_funding_stale_profile_and_failed_atomic_write_never_partially_post(tmp_path):
    path = tmp_path / "atomic.db"
    _bank, row = origination_profile(path)
    clone = tmp_path / "clone.db"
    with V2ProfileStore.open(path) as store:
        draft = funding(
            store,
            row,
            destination_account_id="vehicle",
            confirm_tangible_allocation=True,
            tangible_allocation_date=date(2026, 1, 16),
        )
        before = tuple(store.connection.execute("SELECT * FROM Accounts"))
        store.connection.execute(
            "CREATE TRIGGER test_fail_asset BEFORE INSERT ON JournalEntries "
            "WHEN new.key LIKE '%:asset' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            store.post_loan_origination(draft)
        assert tuple(store.connection.execute("SELECT * FROM Accounts")) == before
        assert store._active_journal_entries() == () and store._active_consumed() == {}
        assert not store.connection.execute("SELECT * FROM LoanOriginationEvents").fetchall()
        store.connection.execute("DROP TRIGGER test_fail_asset")
    V2ProfileStore.snapshot_to(path, clone)
    with V2ProfileStore.open(clone) as store:
        with pytest.raises(ProfileFormatError, match="profile_changed"):
            store.post_loan_origination(draft)
    with V2ProfileStore.open(path) as store:
        store.add_category_account("custom", "New category", "expense")
        with pytest.raises(ProfileFormatError, match="changed"):
            store.post_loan_origination(draft)
        assert store._active_journal_entries() == ()


def test_export_distinguishes_unknown_acquisition_cost_and_signed_annual_value_change(tmp_path):
    from openpyxl import load_workbook
    from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

    path = tmp_path / "export.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        store.set_tangible_asset_value(
            "vehicle",
            value_date=date(2026, 1, 17),
            amount_minor=2000000,
            annual_rate_basis_points=500,
            reason="Appreciation estimate",
        )
        store.post_loan_origination(funding(store, row))
        report = store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1))
        output = write_reviewed_journal_workbook(report, tmp_path / "funding.xlsx")
    workbook = load_workbook(output, read_only=True)
    try:
        values = list(workbook["Asset Value History"].values)
        rate_column = values[0].index("Annual value change basis points")
        assert {r[rate_column] for r in values[1:]} == {-1000, 500}
        origins = list(workbook["Loan Originations"].values)
        assert origins[1][origins[0].index("Known total acquisition cost minor units")] is None
        assert origins[1][origins[0].index("Borrowing date provenance")] == "assumed"
        assert origins[1][origins[0].index("Mode")] == "funding"
    finally:
        workbook.close()


def test_corrupt_funding_manifest_refuses_common_reads_and_verified_backup(tmp_path):
    from .test_v2_loan_payments import _tamper

    path = tmp_path / "corrupt.db"
    _bank, row = origination_profile(path)
    with V2ProfileStore.open(path) as store:
        store.post_loan_origination(funding(store, row))
        _tamper(store, "LoanOriginationEvents", "UPDATE LoanOriginationEvents SET manifest=?", ('{"mode":"funding"}',))
        with pytest.raises(ProfileFormatError, match="origination_history_integrity"):
            store.account_positions(as_of=date(2026, 1, 16))
    backup = tmp_path / "refused.db"
    with pytest.raises(ProfileFormatError, match="origination_history_integrity"):
        V2ProfileStore.snapshot_to(path, backup)
    assert not backup.exists()
