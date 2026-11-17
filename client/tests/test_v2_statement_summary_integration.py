"""Retirement summary review records value without creating cash or journal activity."""

from datetime import date
from pathlib import Path

import pytest
from parsetrail.core import v2_bounded_pdf_text as pdf_text
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

from .v2_institution_helpers import add_test_financial_account


def test_summary_value_reports_and_withdrawal_keep_exact_evidence_and_no_cash_effect(tmp_path, monkeypatch):
    name = "fidelity-401k-summary-pilot-definition.json"
    case = next(item for item in family_sources() if item.definition_name == name)
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / name).read_bytes()
    evidence = pipeline.build_source_evidence(case.source, definition, suffix=case.suffix)
    profile = tmp_path / "retirement.db"
    with V2ProfileStore.create(profile) as store:
        store.import_source(case.source, definition, evidence, suffix=case.suffix)
        add_test_financial_account(
            store, FinancialAccount("retirement", "Retirement plan", "asset", "synthetic", product_type="investment")
        )
        section = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, section.source_identity, section.source_identity_form, "retirement"
        )

    def forbidden(*_args, **_kwargs):
        pytest.fail("A saved retirement summary or valuation read parsed/decoded its source")

    monkeypatch.setattr(pipeline, "build_source_evidence", forbidden)
    monkeypatch.setattr(pipeline, "parse_plan_label_summary", forbidden)
    monkeypatch.setattr(pdf_text, "run_worker", forbidden)
    with V2ProfileStore.open(profile) as store:
        snapshot = store.statement_summary_snapshot(evidence.source_sha256)
        summary = snapshot.sections[0]
        assert summary.status == "pending" and summary.active_value is None
        assert summary.opening.minor == 10000 and summary.closing.minor == 14000
        assert [row.amount.minor for row in summary.rows] == [5000, -1000]
        assert all(row.row_role == "period_summary" for row in summary.rows)
        inventory = store.document_summaries()[0]
        assert inventory.pending_summary_values == 1 and inventory.pending_activity_rows == 0
        candidate = summary.candidate
        value = store.record_reviewed_source_value(
            summary.account_id,
            candidate.candidate_id,
            expected_candidate_sha256=candidate.version,
            expected_basis_sha256=summary.basis_sha256,
            expected_profile_identity=snapshot.profile_identity,
            reference="Retirement statement value",
            reason="Initial Review",
        )
        reviewed = store.statement_summary_snapshot(evidence.source_sha256).sections[0]
        assert reviewed.status == "reviewed" and reviewed.active_value.value_id == value.value_id
        inventory = store.document_summaries()[0]
        assert inventory.pending_summary_values == 0 and inventory.reviewed_summary_values == 1
        assert inventory.pending_activity_rows == 0 and store._active_consumed() == {}
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert not store.resolution_snapshot(preferences=V2Preferences()).items
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        assert (
            store.reviewed_category_summary(kind="income", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
        position = store.account_positions(as_of=date(2026, 1, 31)).accounts[0]
        assert position.value_status == "known" and position.latest_dated_value.amount_minor == 14000
        assert position.recorded_debit_minor == 0 and position.position_debit_minor is None
        assert store.account_positions(as_of=date(2026, 1, 30)).accounts[0].latest_dated_value is None
        frame = store.account_anchor_snapshot("retirement")
        store.withdraw_reviewed_dated_value(
            "retirement",
            value.value_id,
            expected_value_version=value.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Recheck statement value",
        )
        withdrawn = store.statement_summary_snapshot(evidence.source_sha256).sections[0]
        assert withdrawn.status == "pending" and withdrawn.active_value is None
        inventory = store.document_summaries()[0]
        assert inventory.pending_summary_values == 1 and inventory.reviewed_summary_values == 0
        saved = store.load_import(evidence.source_sha256)
        assert saved.source == case.source and saved.definition == definition and saved.evidence == evidence
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
