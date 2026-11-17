"""Statement-value review preserves exact source proof without posting period totals."""

import sqlite3
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_single_column_summary import parse_plan_label_summary

from devtools.parser_engine_pilot import test_plan_label_summary as fidelity

from .v2_institution_helpers import add_test_financial_account


def summary_source(store, *, number=0, bound=True, changes=None, transform=None):
    raw = f"%PDF-public-summary-{number}".encode()
    text = "\n".join(line.raw for line in fidelity.lines(changes=changes).lines)
    evidence = parse_plan_label_summary(
        fidelity.DEFINITION, page_lines(raw, [text], extraction_library="public-synthetic-summary-1")
    )
    if transform is not None:
        evidence = transform(evidence)
    store.import_source(raw, fidelity.DEFINITION, evidence, suffix=".pdf")
    if bound:
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "plan")
    return evidence


def prepared(path, *, bound=True, transform=None):
    with V2ProfileStore.create(path) as store:
        add_test_financial_account(
            store, FinancialAccount("plan", "Retirement plan", "asset", "fidelity", product_type="investment")
        )
        return summary_source(store, bound=bound, transform=transform)


def record(store, source, *, snapshot=None, reason="Initial Review"):
    snapshot = snapshot or store.statement_summary_snapshot(source)
    section = snapshot.sections[0]
    return store.record_reviewed_source_value(
        section.account_id,
        section.candidate.candidate_id,
        expected_candidate_sha256=section.candidate.version,
        expected_basis_sha256=section.basis_sha256,
        expected_profile_identity=snapshot.profile_identity,
        reference=f"Retirement statement {source}",
        reason=reason,
    )


def manual(store, amount, *, day=date(2026, 1, 31), corrects=None, allow_conflict=False):
    frame = store.account_anchor_snapshot("plan")
    return store.record_reviewed_dated_value(
        "plan",
        amount_minor=amount,
        value_date=day,
        tracking_scope="account_total",
        reference="Separate authored estimate",
        reason="Separate value review",
        expected_basis_sha256=frame.basis_sha256,
        corrects_value_id=corrects,
        allow_conflict=allow_conflict,
    )


def withdraw(store, value):
    store.withdraw_reviewed_dated_value(
        "plan",
        value.value_id,
        expected_value_version=value.version,
        expected_basis_sha256=store.account_anchor_snapshot("plan").basis_sha256,
        reason="Withdraw unsupported value",
    )


def counts(store, source):
    return next(row for row in store.document_summaries() if row.source_sha256 == source)


def test_summary_review_records_only_exact_closing_and_separate_completion(tmp_path):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        view = store.statement_summary_snapshot(evidence.source_sha256)
        section = view.sections[0]
        assert not view.complete and section.status == "pending"
        assert section.account_id == "plan" and section.account_name == "Retirement plan"
        assert (section.opening.minor, section.closing.minor) == (10000, 14000)
        assert [row.amount.minor for row in section.rows] == [5000, -1000]
        assert all(row.row_role == "period_summary" and row.date_role == "statement_period_end" for row in section.rows)
        assert not view.capture_verified and view.independent_balance_verified
        summary = counts(store, evidence.source_sha256)
        assert (summary.pending_summary_values, summary.reviewed_summary_values) == (1, 0)
        assert summary.pending_activity_rows == summary.unassigned_activity_rows == 0
    assert path.read_bytes() == before
    with V2ProfileStore.open(path) as store:
        value = record(store, evidence.source_sha256, snapshot=view)
        assert record(store, evidence.source_sha256, snapshot=view) == value
        saved = store.statement_summary_snapshot(evidence.source_sha256)
        assert saved.complete and saved.sections[0].active_value == value
        assert saved.sections[0].history == (value,)
        summary = counts(store, evidence.source_sha256)
        assert (summary.pending_summary_values, summary.reviewed_summary_values) == (0, 1)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (1,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store._active_consumed() == {}
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.account_positions(as_of=date(2026, 1, 31)).accounts[0].position_debit_minor is None


@pytest.mark.parametrize("case", ["manual_equal", "other_source", "withdrawn", "corrected_away", "changed_assessment"])
def test_equal_money_or_historical_proof_does_not_complete_current_source(tmp_path, case):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        if case == "manual_equal":
            manual(store, 14000)
        elif case == "other_source":
            other = summary_source(store, number=1)
            record(store, other.source_sha256)
        else:
            value = record(store, evidence.source_sha256)
            if case == "withdrawn":
                withdraw(store, value)
            elif case == "corrected_away":
                manual(store, 14000, corrects=value.value_id)
            else:
                store.record_statement_source_review(
                    "plan",
                    evidence.source_sha256,
                    expected_revision_id=None,
                    opening_origin="unestablished",
                    closing_origin="unestablished",
                    timing_confirmed=False,
                    posting_dates="unverified",
                    source_reference="New source assessment",
                )
        snapshot = store.statement_summary_snapshot(evidence.source_sha256)
        assert not snapshot.complete and snapshot.sections[0].status == "pending"
        assert snapshot.sections[0].active_value is None
        assert counts(store, evidence.source_sha256).pending_summary_values == 1


def test_conflict_is_not_completion_and_other_dates_do_not_conflict(tmp_path):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        value = record(store, evidence.source_sha256)
        manual(store, 80000, day=date(2026, 2, 28))
        assert store.statement_summary_snapshot(evidence.source_sha256).complete
        contrary = manual(store, 14100, allow_conflict=True)
        view = store.statement_summary_snapshot(evidence.source_sha256)
        assert not view.complete and view.sections[0].status == "conflict"
        assert view.sections[0].active_value == value
        assert {point.amount_minor for point in view.sections[0].conflicting_values} == {14000, 14100}
        assert (
            counts(store, evidence.source_sha256).pending_summary_values,
            counts(store, evidence.source_sha256).reviewed_summary_values,
        ) == (1, 0)
        withdraw(store, contrary)
        assert store.statement_summary_snapshot(evidence.source_sha256).complete


def test_manual_contrary_point_blocks_new_source_value_without_inventing_resolution(tmp_path):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        manual(store, 90000)
        view = store.statement_summary_snapshot(evidence.source_sha256)
        assert view.sections[0].status == "conflict" and not view.complete
        assert view.sections[0].candidate is None and view.sections[0].active_value is None
        assert "statement_summary_value_conflict" in view.sections[0].blockers


def test_missing_section_binding_and_unsupported_row_shape_stay_blocked(tmp_path):
    for name, bound, transform in (
        ("unbound", False, None),
        (
            "shape",
            True,
            lambda evidence: evidence.model_copy(
                update={
                    "payload": evidence.payload.model_copy(
                        update={
                            "accounts": (
                                evidence.payload.accounts[0].model_copy(
                                    update={
                                        "rows": (
                                            evidence.payload.accounts[0]
                                            .rows[0]
                                            .model_copy(update={"row_role": "activity", "date_role": "posting_date"}),
                                            evidence.payload.accounts[0].rows[1],
                                        )
                                    }
                                ),
                            )
                        }
                    )
                }
            ),
        ),
    ):
        path = tmp_path / f"{name}.db"
        evidence = prepared(path, bound=bound, transform=transform)
        with V2ProfileStore.open(path, read_only=True) as store:
            view = store.statement_summary_snapshot(evidence.source_sha256)
            assert not view.complete and view.sections[0].status == "blocked"
            assert view.sections[0].candidate is None
            assert counts(store, evidence.source_sha256).pending_summary_values == 1


def test_physical_profile_and_stale_basis_refuse_before_writes(tmp_path):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        original = store.statement_summary_snapshot(evidence.source_sha256)
    clone = V2ProfileStore.snapshot_to(path, tmp_path / "clone.db")
    with V2ProfileStore.open(clone) as store:
        with pytest.raises(ProfileFormatError, match="statement_summary_profile_changed"):
            record(store, evidence.source_sha256, snapshot=original)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
    with V2ProfileStore.open(path) as store:
        store.update_financial_account(replace(store.financial_accounts()[0], name="Changed account name"))
        with pytest.raises(ProfileFormatError, match="account_anchor_changed_since_selection"):
            record(store, evidence.source_sha256, snapshot=original)
        assert not store.statement_summary_snapshot(evidence.source_sha256).complete


def test_failed_write_and_retired_retry_never_leave_a_partial_or_revived_value(tmp_path, monkeypatch):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        original = store._append_dated_value

        def fail(*args, **kwargs):
            original(*args, **kwargs)
            raise sqlite3.IntegrityError("Synthetic failure after value insertion")

        monkeypatch.setattr(store, "_append_dated_value", fail)
        with pytest.raises(sqlite3.IntegrityError):
            record(store, evidence.source_sha256)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
        monkeypatch.setattr(store, "_append_dated_value", original)
        view = store.statement_summary_snapshot(evidence.source_sha256)
        value = record(store, evidence.source_sha256, snapshot=view)
        withdraw(store, value)
        assert record(store, evidence.source_sha256, snapshot=view).state == "withdrawn"
        assert not store.statement_summary_snapshot(evidence.source_sha256).complete


def test_inventory_reuses_proof_sources_once_per_snapshot_and_revalidates_next_read(tmp_path, monkeypatch):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        sources = [evidence]
        for number in range(1, 4):
            sources.append(summary_source(store, number=number))
        for source in sources:
            record(store, source.source_sha256)
        parsed = []
        original = store._verified_saved_import

        def count(source, *args, **kwargs):
            assert store._source_read_evidence is None
            parsed.append(source)
            return original(source, *args, **kwargs)

        monkeypatch.setattr(store, "_verified_saved_import", count)
        assert all(summary.reviewed_summary_values == 1 for summary in store.document_summaries())
        assert sorted(parsed) == sorted(source.source_sha256 for source in sources)
        parsed.clear()
        assert all(summary.reviewed_summary_values == 1 for summary in store.document_summaries())
        assert sorted(parsed) == sorted(source.source_sha256 for source in sources)
        assert store._source_read_evidence is None
        assert store._deferred_dated_proofs is None


@pytest.mark.parametrize("method", ["document_summaries", "statement_summary_snapshot"])
def test_deferred_proof_failure_never_escapes_as_reviewed_and_releases_context(tmp_path, monkeypatch, method):
    path = tmp_path / "summary.db"
    evidence = prepared(path)
    with V2ProfileStore.open(path) as store:
        record(store, evidence.source_sha256)

        def refuse(*_args, **_kwargs):
            raise ProfileFormatError("account_dated_value_source_proof_invalid")

        monkeypatch.setattr(store, "_validate_dated_source_proof_evidence", refuse)
        with pytest.raises(ProfileFormatError, match="account_dated_value_history_integrity"):
            if method == "document_summaries":
                store.document_summaries()
            else:
                store.statement_summary_snapshot(evidence.source_sha256)
        assert store._deferred_dated_proofs is None and store._source_read_evidence is None
        assert not store.connection.in_transaction


def test_selected_summary_retains_only_its_source_not_other_proof_pdfs(tmp_path, monkeypatch):
    path = tmp_path / "summary.db"
    first = prepared(path)
    with V2ProfileStore.open(path) as store:
        for number in range(4):
            source = first if number == 0 else summary_source(store, number=number)
            record(store, source.source_sha256)
        parsed = []
        original = store._verified_saved_import

        def count(source, *args, **kwargs):
            assert set(store._source_read_evidence or ()) <= {first.source_sha256}
            parsed.append(source)
            return original(source, *args, **kwargs)

        monkeypatch.setattr(store, "_verified_saved_import", count)
        assert store.statement_summary_snapshot(first.source_sha256).complete
        assert parsed.count(first.source_sha256) == 1
        assert len(parsed) == 4
        assert store._source_read_evidence is None and store._deferred_dated_proofs is None


def test_profile_change_during_summary_read_refuses_stale_snapshot(tmp_path, monkeypatch):
    from parsetrail.core import v2_import_accounts

    path = tmp_path / "summary.db"
    evidence = prepared(path)
    identity = v2_import_accounts._profile_identity
    calls = []

    def changed(store):
        calls.append(True)
        return identity(store) if len(calls) == 1 else "f" * 64

    monkeypatch.setattr(v2_import_accounts, "_profile_identity", changed)
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="statement_summary_profile_changed"):
            store.statement_summary_snapshot(evidence.source_sha256)
        assert store._source_read_evidence is None and store._deferred_dated_proofs is None
        assert not store.connection.in_transaction
