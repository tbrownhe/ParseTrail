"""Document association describes confirmed rows without inventing source facts."""

from parsetrail.core.v2_batch_account_assignment import plan_account_assignments
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_account_bindings import DEFINITION, SOURCE


def _profile(path, *, summary_row=False):
    evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
    if summary_row:
        first, second = evidence.payload.rows
        second = second.model_copy(update={"row_role": "period_summary", "date_role": "statement_period_end"})
        evidence = evidence.model_copy(
            update={"payload": evidence.payload.model_copy(update={"rows": (first, second)})}
        )
    with V2ProfileStore.create(path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        store.add_financial_account(FinancialAccount("a", "Education loan A", "liability", "mohela"))
        store.add_financial_account(FinancialAccount("b", "Education loan B", "liability", "mohela"))
    return evidence


def test_all_rows_on_one_account_make_document_findable_without_a_file_assertion(tmp_path):
    path = tmp_path / "assigned.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        before_plan = plan_account_assignments(store, catalog=None, preferences=V2Preferences())
        assert len(before_plan.groups) == 1 and before_plan.groups[0].source_identity is None
        before = store.document_summaries()[0]
        assert before.associated_account_ids == () and before.association_kind == "unassigned"
        assert not before.association_complete and before.assigned_row_count == 0
        store.assign_rows_account(evidence.source_sha256, tuple(row.row_id for row in evidence.payload.rows), "a")
        summary = store.document_summaries()[0]
        assert summary.associated_account_ids == ("a",)
        assert summary.bound_account_names == ("Education loan A",)
        assert summary.association_kind == "rows" and summary.association_complete
        assert summary.assigned_row_count == summary.row_count == 2
        assert summary.unassigned_activity_rows == summary.unassigned_source_accounts == 0
        assert summary.source_accounts == () and summary.has_unidentified_rows
        assert store.connection.execute("SELECT count(*) FROM FileAccountAssertions").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (0,)
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert plan_account_assignments(store, catalog=None, preferences=V2Preferences()).groups == ()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    before_bytes = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.document_summaries() == (summary,)
    assert path.read_bytes() == before_bytes


def test_partial_and_multiple_account_row_associations_remain_qualified(tmp_path):
    path = tmp_path / "mixed.db"
    evidence = _profile(path)
    first, second = evidence.payload.rows
    with V2ProfileStore.open(path) as store:
        store.assign_row_account(first.row_id, "a")
        partial = store.document_summaries()[0]
        assert partial.associated_account_ids == ("a",) and partial.bound_account_names == ("Education loan A",)
        assert partial.association_kind == "rows" and not partial.association_complete
        assert partial.assigned_row_count == 1 and partial.unassigned_activity_rows == 1
        assert len(plan_account_assignments(store, catalog=None, preferences=V2Preferences()).groups) == 1
        store.assign_row_account(second.row_id, "b")
        multiple = store.document_summaries()[0]
        assert multiple.associated_account_ids == ("a", "b")
        assert multiple.bound_account_names == ("Education loan A", "Education loan B")
        assert multiple.association_kind == "rows" and multiple.association_complete
        assert multiple.assigned_row_count == 2 and multiple.unassigned_activity_rows == 0
        assert multiple.source_accounts == ()
        assert plan_account_assignments(store, catalog=None, preferences=V2Preferences()).groups == ()


def test_file_assertion_remains_distinct_and_withdrawal_updates_next_summary(tmp_path):
    path = tmp_path / "file.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.assert_file_account(evidence.source_sha256, "a")
        summary = store.document_summaries()[0]
        assert summary.association_kind == "file" and summary.association_complete
        assert summary.associated_account_ids == ("a",) and summary.assigned_row_count == 2
        store.clear_file_account_assertion(evidence.source_sha256)
        cleared = store.document_summaries()[0]
        assert cleared.association_kind == "unassigned" and not cleared.association_complete
        assert cleared.associated_account_ids == () and cleared.bound_account_names == ()
        assert cleared.assigned_row_count == 0 and cleared.unassigned_activity_rows == 2


def test_all_row_coverage_is_distinct_from_activity_only_pending_counts(tmp_path):
    path = tmp_path / "summary-row.db"
    evidence = _profile(path, summary_row=True)
    first, second = evidence.payload.rows
    with V2ProfileStore.open(path) as store:
        store.assign_row_account(first.row_id, "a")
        partial = store.document_summaries()[0]
        assert partial.row_count == 2 and partial.assigned_row_count == 1
        assert partial.unassigned_activity_rows == 0 and not partial.association_complete
        store.assign_row_account(second.row_id, "a")
        assert store.document_summaries()[0].association_complete
