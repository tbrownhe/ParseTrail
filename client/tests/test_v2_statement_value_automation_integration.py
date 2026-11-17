"""Automatic value recording preserves prepared evidence and nonposting semantics."""

from datetime import date

import pytest
from parsetrail.core import v2_bounded_pdf_text as pdf_text
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_statement_value_automation import AUTOMATIC_REASON

from .test_v2_statement_value_automation import choose_summary, statement_workspace


def test_new_account_auto_value_then_reports_withdrawal_and_retry_do_not_parse(tmp_path, monkeypatch):
    workspace, path = statement_workspace(tmp_path, existing_account=False)
    source = path.read_bytes()
    workspace.set_auto_record_statement_values(True)
    workspace.set_auto_post_loan_payments(True)
    assert not workspace.preferences().allow_assumed_posting_dates
    parsed = []
    parse = pipeline.parse_plan_label_summary

    def count_parse(*args, **kwargs):
        parsed.append(True)
        return parse(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Automatic value recording or saved-evidence reads parsed/decoded after confirmation")

    def confirm(source_path, review):
        assert len(parsed) == 1
        plan = choose_summary(source_path, review)
        monkeypatch.setattr(pipeline, "parse_plan_label_summary", forbidden)
        monkeypatch.setattr(pdf_text, "run_worker", forbidden)
        return plan

    monkeypatch.setattr(pipeline, "parse_plan_label_summary", count_parse)
    result = workspace.import_file(path, review_import=confirm)
    outcome = result.statement_value_automation
    assert result.status == "imported" and outcome.status == "recorded"
    assert result.loan_automation is None
    assert (outcome.amount_minor, outcome.value_date) == (14000, date(2026, 1, 31))
    assert len(parsed) == 1
    with V2ProfileStore.open(workspace.profile_path) as store:
        saved = store.load_import(result.source_sha256)
        assert saved.source == source and saved.evidence == result.evidence
        snapshot = store.statement_summary_snapshot(result.source_sha256)
        section = snapshot.sections[0]
        value = section.active_value
        assert snapshot.complete and value.value_id == outcome.value_id and value.reason == AUTOMATIC_REASON
        assert value.source_proof.closing == result.evidence.payload.accounts[0].closing
        inventory = store.document_summaries()[0]
        assert inventory.pending_summary_values == 0 and inventory.reviewed_summary_values == 1
        position = store.account_positions(as_of=outcome.value_date).accounts[0]
        assert position.latest_dated_value.value_id == value.value_id
        assert position.position_debit_minor is None and position.recorded_debit_minor == 0
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert not store.resolution_snapshot(preferences=workspace.preferences()).items
        for kind in ("expense", "income"):
            assert (
                store.reviewed_category_summary(kind=kind, start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
                == 0
            )
        frame = store.account_anchor_snapshot(section.account_id)
        store.withdraw_reviewed_dated_value(
            section.account_id,
            value.value_id,
            expected_value_version=value.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Recheck automatic statement value",
        )
        assert not store.statement_summary_snapshot(result.source_sha256).complete
        assert store.document_summaries()[0].pending_summary_values == 1
    retry = workspace.import_file(path, review_import=forbidden)
    assert retry.status == "already_imported" and retry.statement_value_automation is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.statement_summary_snapshot(result.source_sha256).complete
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (1,)
        assert store.load_import(result.source_sha256).evidence == result.evidence
