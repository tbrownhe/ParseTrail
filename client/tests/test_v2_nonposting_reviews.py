"""Zero rows and PDF-created identity retain review history without fabricating money."""

from dataclasses import replace

import pytest
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore

from .test_v2_loan_payments import _profile


def test_mixed_category_transfer_and_zero_batch_is_atomic_and_exactly_retryable(tmp_path):
    from datetime import date

    from parsetrail.core.v2_ordinary_batch import OrdinaryCategorySelection, OrdinaryTransferSelection
    from parsetrail.core.v2_profile_store import FinancialAccount
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from .test_v2_ordinary_batch import DEFINITION
    from .v2_institution_helpers import add_test_financial_account

    raw = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"10/01/2026,Checking A,Coffee,-$4.01,Unavailable\n"
        b"10/03/2026,Checking A,Owned payment,-$20.00,Unavailable\n"
        b"10/05/2026,Checking A,Fee,$0.00,Unavailable\n"
    )
    evidence = build_source_evidence(raw, DEFINITION, suffix=".csv")
    path = tmp_path / "mixed.db"
    with V2ProfileStore.create(path) as store:
        store.import_source(raw, DEFINITION, evidence, suffix=".csv")
        add_test_financial_account(store, FinancialAccount("cash", "Checking", "asset", "synthetic"))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")
        store.add_category_account("fees", "Fees", "expense")
        rows = evidence.payload.rows
        selections = (
            OrdinaryCategorySelection(rows[0].row_id, "fees", "expense"),
            OrdinaryTransferSelection(rows[1].row_id),
            OrdinaryCategorySelection(rows[2].row_id, "fees", "expense"),
        )
        frame = store.source_interpretation_snapshot(evidence.source_sha256, kind="cash")
        draft = store.preview_reviewed_ordinary_batch(
            evidence.source_sha256,
            kind="cash",
            selections=selections,
            reason="Initial Review",
            expected_basis_sha256=frame.basis_sha256,
        )
        assert len(draft.entries) == len(draft.transfer_entries) == len(draft.zero_reviews) == 1
        result = store.post_reviewed_ordinary_batch(draft)
        assert len(store._active_journal_entries()) == 2 and len(result.resolution_event_ids) == 1
        assert len(result.zero_review_revision_ids) == 1 and not result.already_posted
        retry = store.post_reviewed_ordinary_batch(draft)
        assert retry.already_posted and retry.entry_keys == result.entry_keys
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)).total_minor
            == 401
        )
        assert (
            next(
                summary for summary in store.document_summaries() if summary.source_sha256 == evidence.source_sha256
            ).pending_activity_rows
            == 0
        )
        assert (
            store.source_interpretation_snapshot(evidence.source_sha256, kind="cash").owners[0].owner_kind
            == "resolution"
        )


def test_zero_review_correction_withdrawal_preserves_no_money_and_pending_counts(tmp_path):
    path = tmp_path / "zero.db"
    bank, _rows = _profile(path, amount=0)
    with V2ProfileStore.open(path) as store:
        store.add_category_account("fees", "Fees", "expense")
        store.add_category_account("other", "Other", "expense")
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceObservations WHERE row_id=?", (bank,)
        ).fetchone()[0]
        state = store.source_interpretation_snapshot(source, kind="cash")
        assert state.rows[0].status == "Ready for purpose review"
        decision = store.review_zero_amount(
            bank, "fees", "expense", reason="Initial Review", expected_basis_sha256=state.basis_sha256
        )
        assert store._active_journal_entries() == () and store._active_consumed() == {}
        current = store.source_interpretation_snapshot(source, kind="cash")
        assert current.rows[0].status == "Reviewed zero amount" and current.rows[0].category_id == "fees"
        assert (
            next(
                summary for summary in store.document_summaries() if summary.source_sha256 == source
            ).pending_activity_rows
            == 0
        )
        with pytest.raises(ProfileFormatError, match="reason_required"):
            store.review_zero_amount(
                bank,
                "other",
                "expense",
                reason="",
                expected_basis_sha256=current.basis_sha256,
                expected_revision_id=decision.revision_id,
            )
        corrected = store.review_zero_amount(
            bank,
            "other",
            "expense",
            reason="Correct category",
            expected_basis_sha256=current.basis_sha256,
            expected_revision_id=decision.revision_id,
        )
        assert corrected.prior_revision_id == decision.revision_id
        store.withdraw_zero_amount_review(
            bank,
            reason="Review again",
            expected_revision_id=corrected.revision_id,
            expected_basis_sha256=store.source_interpretation_snapshot(source, kind="cash").basis_sha256,
        )
        assert store.source_interpretation_snapshot(source, kind="cash").rows[0].status == "Ready for purpose review"
        assert store._active_journal_entries() == ()


def test_pdf_import_identity_lock_blocks_product_institution_but_allows_name(tmp_path):
    path = tmp_path / "identity.db"
    _profile(path)
    with V2ProfileStore.open(path) as store:
        source = store.connection.execute(
            "SELECT source_sha256 FROM SourceAccountBindings WHERE ledger_account_id='loan'"
        ).fetchone()[0]
        lock = store.lock_pdf_import_account("loan", source)
        account = next(a for a in store.financial_accounts() if a.id == "loan")
        store.update_financial_account(replace(account, name="My vehicle loan"))
        assert store.account_identity_lock("loan") == lock
        with pytest.raises(ProfileFormatError, match="identity_locked"):
            store.update_financial_account(replace(account, institution_key=None))
        with pytest.raises(ProfileFormatError, match="identity_locked"):
            store.update_financial_account(replace(account, product_type="loan"))
    with V2ProfileStore.open(path) as store:
        assert store.account_identity_lock("loan").source_sha256 == source
