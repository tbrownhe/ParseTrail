"""Standing loan authorization preserves prepared evidence and separate transfer work."""

import hashlib
from datetime import date

import pytest
from parsetrail.core import v2_bounded_pdf_text as pdf_worker
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_loan_automation import AUTOMATIC_REASON
from parsetrail.core.v2_profile_store import V2ProfileStore

from .test_v2_loan_automation import choose_loan, loan_workspace


def test_automatic_post_reports_and_withdrawal_never_parse_confirmed_source(tmp_path, monkeypatch):
    workspace, path = loan_workspace(tmp_path)
    source = path.read_bytes()
    workspace.set_allow_assumed_posting_dates(True)
    workspace.set_auto_post_loan_payments(True)
    parsed = []
    parse = pipeline.parse_loan_history

    def count_parse(*args, **kwargs):
        parsed.append(True)
        return parse(*args, **kwargs)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Confirmed automatic posting or saved evidence reads parsed/decoded the source")

    def confirm(source_path, review):
        assert len(parsed) == 1
        decision = choose_loan(source_path, review)
        monkeypatch.setattr(pipeline, "parse_loan_history", forbidden)
        monkeypatch.setattr(pdf_worker, "run_worker", forbidden)
        return decision

    monkeypatch.setattr(pipeline, "parse_loan_history", count_parse)
    result = workspace.import_file(path, review_import=confirm)
    assert result.status == "imported" and result.loan_automation.status == "posted"
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert len(parsed) == 1
    with V2ProfileStore.open(workspace.profile_path) as store:
        saved = store.load_import(result.source_sha256)
        assert saved.source == source and saved.evidence == result.evidence
        event = store.loan_history()[0]
        assert event.reason == AUTOMATIC_REASON and event.manifest.bank is None
        assert event.event_id == result.loan_automation.event_id
        principal = event.manifest.principal_minor
        interest = event.manifest.interest_minor
        assert (principal, interest) == (
            result.loan_automation.principal_minor,
            result.loan_automation.interest_minor,
        )
        transfers = store.resolution_snapshot(preferences=workspace.preferences())
        assert len(transfers.items) == 1 and not transfers.links
        assert transfers.items[0].id == event.event_id
        assert transfers.items[0].status == "unmatched"
        assert abs(transfers.items[0].gross_minor) == principal + interest
        spending = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1))
        assert spending.total_minor == interest
        store.withdraw_reviewed_loan(
            event.event_id, expected_event_version=event.version, reason="Correct automatic interpretation"
        )
        assert store.loan_history()[0].status == "cancelled"
        assert all(
            item.status == "withdrawn" for item in store.resolution_snapshot(preferences=workspace.preferences()).items
        )
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1)).total_minor
            == 0
        )
    retry = workspace.import_file(path, review_import=forbidden)
    assert retry.status == "already_imported" and retry.loan_automation is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.loan_history()) == 1 and store.loan_history()[0].status == "cancelled"
        assert store.load_import(result.source_sha256).evidence == result.evidence
