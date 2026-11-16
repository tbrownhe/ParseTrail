"""Unmatched postings are exact money; matching is an independent reviewed link."""

import pytest
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore

from .test_v2_loan_payments import PREFERENCES, _profile


def test_lender_only_post_then_bank_attachment_and_link_withdrawal(tmp_path):
    path = tmp_path / "loan.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        basis = store.loan_review_snapshot(PREFERENCES).basis_sha256
        preview = store.loan_payment_preview(None, rows, preferences=PREFERENCES, expected_basis_sha256=basis)
        assert len(preview.entries) == 1 and preview.manifest.bank is None
        event = store.post_reviewed_loan_payment(
            None,
            rows,
            preferences=PREFERENCES,
            expected_basis_sha256=basis,
            reason="Initial Review",
            reference="Printed lender payment",
        )
        assert len(store._active_journal_entries()) == 1
        assert store._active_consumed() == {rows[0]: -22000}
        state = store.resolution_snapshot(preferences=PREFERENCES)
        by_id = {item.id: item for item in state.items}
        assert by_id[event.event_id].date_provenance == "assumed"
        assert by_id[event.event_id].source_dates == (("2026-01-15", "assumed"),)
        assert by_id["row:" + bank].date_provenance == "observed"
        assert by_id["row:" + bank].source_dates == (("2026-01-14", "observed"),)
        candidate = next(c for c in state.candidates if c.incoming_id == event.event_id)
        assert candidate.outgoing_id == "row:" + bank and not candidate.automatic
        link = store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Confirmed owned bank side",
        )
        assert (
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Confirmed owned bank side",
            )
            == link
        )
        assert len(store._active_journal_entries()) == 2
        assert store._active_consumed() == {bank: -22000, rows[0]: -22000}
        assert (
            sum(
                p.amount_minor
                for e in store._active_journal_entries()
                for p in e.postings
                if p.account_id == "builtin:loan-interest"
            )
            == 2000
        )
        assert all(
            i.status == "matched"
            for i in store.resolution_snapshot(preferences=PREFERENCES).items
            if i.kind != "source"
        )
        with pytest.raises(ProfileFormatError, match="unlink_before_correction"):
            store.withdraw_reviewed_loan(
                event.event_id, expected_event_version=event.version, reason="Correct lender review"
            )
        store.withdraw_transfer_resolution(
            link.link_id, expected_version=link.version, reason="Different bank evidence needed"
        )
        with pytest.raises(ProfileFormatError, match="link_retired"):
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Confirmed owned bank side",
            )
        assert len(store._active_journal_entries()) == 2
        assert (
            len([i for i in store.resolution_snapshot(preferences=PREFERENCES).items if i.status == "unmatched"]) == 2
        )
    with V2ProfileStore.open(path) as store:
        assert len(store._active_journal_entries()) == 2
        assert store.loan_history()[0].manifest.bank is None


def test_both_sides_posted_resolution_is_link_only_and_retries_exact(tmp_path):
    path = tmp_path / "both.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        first = store.post_unresolved_transfer(
            bank,
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Owned payment",
        )
        event = store.post_reviewed_loan_payment(
            None,
            rows,
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Initial Review",
            reference="Printed split",
        )
        state = store.resolution_snapshot(preferences=PREFERENCES)
        assert len([i for i in state.items if i.status == "unmatched"]) == 2
        from datetime import date

        positions = store.account_positions(as_of=date(2026, 1, 31))
        assert positions.transfer_clearing_debit_minor == 0 and positions.unresolved_transfer_count == 2
        before = store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall()
        link = store.resolve_transfer(
            first.id,
            event.event_id,
            preferences=PREFERENCES,
            expected_basis_sha256=state.basis_sha256,
            reason="Matched owned payment",
        )
        assert (
            store.resolve_transfer(
                first.id,
                event.event_id,
                preferences=PREFERENCES,
                expected_basis_sha256=state.basis_sha256,
                reason="Matched owned payment",
            )
            == link
        )
        assert store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall() == before
        assert store.account_positions(as_of=date(2026, 1, 31)).unresolved_transfer_count == 0
        with pytest.raises(ProfileFormatError, match="unlink_before_correction"):
            store.withdraw_unresolved_transfer(first.id, expected_version=first.version, reason="Wrong intent")


def test_unresolved_transfer_withdrawal_does_not_revive_retry(tmp_path):
    path = tmp_path / "withdraw.db"
    bank, _rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        basis = store.loan_review_snapshot(PREFERENCES).basis_sha256
        item = store.post_unresolved_transfer(
            bank, preferences=PREFERENCES, expected_basis_sha256=basis, reason="Owned payment"
        )
        store.withdraw_unresolved_transfer(item.id, expected_version=item.version, reason="Incorrect transfer")
        assert store._active_journal_entries() == ()
        with pytest.raises(ProfileFormatError, match="leg_retired"):
            store.post_unresolved_transfer(
                bank, preferences=PREFERENCES, expected_basis_sha256=basis, reason="Owned payment"
            )


def test_selected_longer_match_window_and_row_request_survive_backup_retry(tmp_path):
    path = tmp_path / "window.db"
    bank, rows = _profile(path, bank_day="01/01/2026")
    with V2ProfileStore.open(path) as store:
        event = store.post_reviewed_loan_payment(
            None,
            rows,
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Initial Review",
            reference="Printed split",
        )
        frame = store.resolution_snapshot(preferences=PREFERENCES, max_day_gap=31)
        candidate = next(c for c in frame.candidates if c.incoming_id == event.event_id)
        link = store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            max_day_gap=frame.max_day_gap,
            expected_basis_sha256=frame.basis_sha256,
            reason="Confirmed owned payment",
        )
    backup = tmp_path / "backup.db"
    V2ProfileStore.snapshot_to(path, backup)
    with V2ProfileStore.open(backup) as store:
        assert (
            store.resolve_transfer(
                candidate.outgoing_id,
                candidate.incoming_id,
                preferences=PREFERENCES,
                max_day_gap=31,
                expected_basis_sha256=frame.basis_sha256,
                reason="Confirmed owned payment",
            )
            == link
        )
        assert len(store._active_journal_entries()) == 2


def test_resolution_journal_export_retains_link_history_without_duplicate_money(tmp_path):
    from datetime import date

    from openpyxl import load_workbook
    from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

    path = tmp_path / "export.db"
    bank, rows = _profile(path)
    with V2ProfileStore.open(path) as store:
        event = store.post_reviewed_loan_payment(
            None,
            rows,
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Initial Review",
            reference="Printed split",
        )
        frame = store.resolution_snapshot(preferences=PREFERENCES)
        store.resolve_transfer(
            "row:" + bank,
            event.event_id,
            preferences=PREFERENCES,
            expected_basis_sha256=frame.basis_sha256,
            reason="Confirmed owned bank side",
        )
        report = store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert len(report.resolution_items) == 2 and report.resolution_links[0].status == "active"
        output = write_reviewed_journal_workbook(report, tmp_path / "report.xlsx")
    workbook = load_workbook(output, read_only=True)
    assert "Resolution Legs" in workbook.sheetnames and "Resolution Links" in workbook.sheetnames
    rows = list(workbook["Resolution Legs"].values)
    provenance_column = rows[0].index("Accounting date provenance")
    dates_column = rows[0].index("All component accounting dates / provenance")
    assert {row[provenance_column] for row in rows[1:]} == {"observed", "assumed"}
    assert any("2026-01-15 (assumed)" in row[dates_column] for row in rows[1:])
    workbook.close()


@pytest.mark.parametrize("reverse_printed_order", [False, True])
def test_multidate_wells_resolution_preserves_all_qualified_dates_and_bounds_every_leg(tmp_path, reverse_printed_order):
    from datetime import date

    from devtools.parser_engine_pilot import test_wells_loan_lines as wells

    interest = "01/25/26 INTEREST PAYMENT $1.00"
    principal = "01/15/26 PRINCIPAL PAYMENT $20.00"
    changes = {4: principal, 5: interest} if reverse_printed_order else {4: interest, 5: principal}
    path = tmp_path / "wells.db"
    bank, rows = _profile(
        path, amount=2100, evidence=wells.parse(changes), definition=wells.DEFINITION, raw=b"%PDF-synthetic-loan"
    )
    with V2ProfileStore.open(path) as store:
        event = store.post_reviewed_loan_payment(
            None,
            rows,
            preferences=PREFERENCES,
            expected_basis_sha256=store.loan_review_snapshot(PREFERENCES).basis_sha256,
            reason="Initial Review",
            reference="Both printed dated components",
        )
        frame = store.resolution_snapshot(preferences=PREFERENCES, max_day_gap=7)
        item = next(item for item in frame.items if item.id == event.event_id)
        expected_dates = (("2026-01-15", "assumed"), ("2026-01-25", "assumed"))
        assert item.posting_date == "2026-01-15" and item.date_provenance == "assumed"
        assert item.source_dates == expected_dates
        late_period = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 20), end=date(2026, 2, 1))
        assert late_period.total_minor == 100 and late_period.unresolved_transfer_count == 1
        empty_gap = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 16), end=date(2026, 1, 20))
        assert empty_gap.total_minor == 0 and empty_gap.unresolved_transfer_count == 0
        assert store.account_positions(as_of=date(2026, 1, 14)).unresolved_transfer_count == 0
        assert store.account_positions(as_of=date(2026, 1, 15)).unresolved_transfer_count == 1
        assert {entry.posting_date for entry in store._active_journal_entries()} == {
            date(2026, 1, 15),
            date(2026, 1, 25),
        }
        assert not frame.candidates
        with pytest.raises(ProfileFormatError, match="candidate_unavailable"):
            store.resolve_transfer(
                "row:" + bank,
                event.event_id,
                preferences=PREFERENCES,
                expected_basis_sha256=frame.basis_sha256,
                reason="Both dates must fit",
                max_day_gap=7,
            )
        wider = store.resolution_snapshot(preferences=PREFERENCES, max_day_gap=14)
        candidate = next(candidate for candidate in wider.candidates if candidate.incoming_id == event.event_id)
        assert candidate.day_gap == 11
        store.resolve_transfer(
            candidate.outgoing_id,
            candidate.incoming_id,
            preferences=PREFERENCES,
            expected_basis_sha256=wider.basis_sha256,
            reason="Reviewed both dated components",
            max_day_gap=14,
        )
        resolved = next(
            item for item in store.resolution_snapshot(preferences=PREFERENCES).items if item.id == event.event_id
        )
        assert resolved.status == "matched" and resolved.source_dates == expected_dates
        matched_period = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 20), end=date(2026, 2, 1))
        assert matched_period.total_minor == 100 and matched_period.unresolved_transfer_count == 0
