"""Explicit cross-document identity reuse is scoped, atomic and review preserving."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace

import pytest
from parsetrail.core.v2_batch_account_assignment import (
    AccountAssignmentCancelled,
    AccountAssignmentChoice,
    account_compatible,
    apply_account_assignments,
    plan_account_assignments,
)
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_two_date_card_lines import parse_two_date_card

from devtools.parser_engine_pilot import test_two_date_card_lines as yamaha

from .test_v2_inline_account_creation import PDF_SOURCE, _workspace


def _variant(store, original, label, *, empty=False, identity=None, form=None, scope=None):
    source = PDF_SOURCE + label.encode()
    first = original.payload.accounts[0]
    identity = identity or first.source_identity
    form = form or first.source_identity_form
    rows = (
        ()
        if empty
        else tuple(
            row.model_copy(
                update={
                    "row_id": hashlib.sha256(source + row.row_id.encode()).hexdigest(),
                    "source_account": identity,
                    "source_account_form": form,
                }
            )
            for row in first.rows
        )
    )
    section = first.model_copy(
        update={
            "source_identity": identity,
            "source_identity_form": form,
            "balance_scope": scope or first.balance_scope,
            "rows": rows,
        }
    )
    payload = original.payload.model_copy(update={"accounts": (section,), "independent_balance_verified": not empty})
    evidence = original.model_copy(update={"source_sha256": hashlib.sha256(source).hexdigest(), "payload": payload})
    store.import_source(source, yamaha.DEFINITION, evidence, suffix=".pdf")
    return evidence


@pytest.fixture
def archive(tmp_path):
    evidence = parse_two_date_card(yamaha.DEFINITION, yamaha.lines())
    workspace = _workspace(tmp_path, yamaha.DEFINITION, evidence)
    with V2ProfileStore.open(workspace.profile_path) as store:
        additional = tuple(_variant(store, evidence, str(index), empty=index == 2) for index in range(3))
    return workspace, evidence, additional


def _plan(store, workspace, preferences=None):
    return plan_account_assignments(
        store, catalog=workspace.catalog_cache.load_current(), preferences=preferences or V2Preferences()
    )


def _apply(store, workspace, plan, choices, **kwargs):
    return apply_account_assignments(
        store,
        plan,
        choices,
        catalog_loader=workspace.catalog_cache.load_current,
        preferences_loader=V2Preferences,
        **kwargs,
    )


def test_opaque_prior_identity_reuses_one_account_across_all_unassigned_including_empty(archive):
    workspace, original, additional = archive
    section = original.payload.accounts[0]
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(
            FinancialAccount("yamaha", "Owner authored label without a number", "liability", "yamaha")
        )
        store.bind_source_account(
            original.source_sha256, section.source_identity, section.source_identity_form, "yamaha"
        )
        before = workspace.profile_path.read_bytes()
        plan = _plan(store, workspace)
        assert len(plan.groups) == 1
        group = plan.groups[0]
        assert group.status == "suggested" and group.suggested_account_id == "yamaha"
        assert group.source_identity == "123456XXXXXX7890" and group.source_identity_form == "opaque"
        assert group.draft.full_account_number is None
        assert len(group.targets) == 3 and any(target.row_count == 0 for target in group.targets)
        assert all(target.start is not None and target.end is not None for target in group.targets)
        assert workspace.profile_path.read_bytes() == before
        result = _apply(store, workspace, plan, (AccountAssignmentChoice(group.group_id, "yamaha"),))
        assert (result.assigned_sections, result.created_accounts) == (3, 0)
        assert all(
            store.source_account_bindings(item.source_sha256)[0].ledger_account_id == "yamaha" for item in additional
        )
        assert store.source_account_bindings(original.source_sha256)[0].ledger_account_id == "yamaha"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert _plan(store, workspace).groups == ()


def test_staged_account_and_all_sections_save_atomically_with_idempotent_retry(archive):
    workspace, _original, _additional = archive
    staged = FinancialAccount("staged", "Yamaha card", "liability", "yamaha")
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
        group = plan.groups[0]
        assert group.status == "choose_account" and group.suggested_account_id is None
        assert account_compatible(group, staged)
        assert store.financial_accounts() == ()
        choice = (AccountAssignmentChoice(group.group_id, staged.id),)
        result = _apply(store, workspace, plan, choice, new_accounts=(staged,))
        assert (result.assigned_sections, result.created_accounts) == (4, 1)
        before = workspace.profile_path.read_bytes()
        retry = _apply(store, workspace, plan, choice, new_accounts=(staged,))
        assert (retry.assigned_sections, retry.created_accounts, retry.already_applied_sections) == (0, 0, 4)
        assert workspace.profile_path.read_bytes() == before
        assert store.financial_accounts() == (staged,)


@pytest.mark.parametrize(
    "field,value", [("institution_key", "other"), ("kind", "asset"), ("tracking_scope", "principal_component")]
)
def test_incompatible_account_never_receives_bulk_assignment(archive, field, value):
    workspace, _original, _additional = archive
    staged = replace(FinancialAccount("wrong", "Wrong", "liability", "yamaha"), **{field: value})
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
        assert not account_compatible(plan.groups[0], staged)
        before = workspace.profile_path.read_bytes()
        with pytest.raises(ProfileFormatError, match="batch_assignment_account_incompatible"):
            _apply(
                store,
                workspace,
                plan,
                (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),),
                new_accounts=(staged,),
            )
        assert workspace.profile_path.read_bytes() == before
        assert store.financial_accounts() == ()


def test_multiple_prior_accounts_are_ambiguous_and_incompatible_prior_is_manual(archive):
    workspace, original, additional = archive
    identity = original.payload.accounts[0]
    with V2ProfileStore.open(workspace.profile_path) as store:
        for ident in ("one", "two"):
            store.add_financial_account(FinancialAccount(ident, ident, "liability", "yamaha"))
        store.bind_source_account(
            original.source_sha256, identity.source_identity, identity.source_identity_form, "one"
        )
        store.bind_source_account(
            additional[0].source_sha256, identity.source_identity, identity.source_identity_form, "two"
        )
        ambiguous = _plan(store, workspace).groups[0]
        assert ambiguous.status == "ambiguous" and ambiguous.suggested_account_id is None
        store.update_financial_account(FinancialAccount("two", "two", "liability", "other"))
        manual = _plan(store, workspace).groups[0]
        assert manual.status == "manual" and manual.reason == "prior_assignment_incompatible"


def test_locked_section_does_not_block_other_documents_with_same_identity(archive):
    workspace, original, additional = archive
    identity = original.payload.accounts[0]
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("known", "Known", "liability", "yamaha"))
        store.bind_source_account(
            original.source_sha256, identity.source_identity, identity.source_identity_form, "known"
        )
        left, right = sorted((identity.rows[0].row_id, additional[0].payload.accounts[0].rows[0].row_id))
        store.connection.execute(
            "INSERT INTO SourceOverlapReviews(left_row_id,right_row_id,decision,basis_sha256,reason) VALUES (?,?,'pending',?,?)",
            (left, right, "0" * 64, "Synthetic retained source-review history"),
        )
        plan = _plan(store, workspace)
        manual = next(group for group in plan.groups if group.status == "manual")
        eligible = next(group for group in plan.groups if group.status == "suggested")
        assert len(manual.targets) == 1 and manual.targets[0].source_sha256 == additional[0].source_sha256
        assert len(eligible.targets) == 2 and eligible.suggested_account_id == "known"
        result = _apply(store, workspace, plan, (AccountAssignmentChoice(eligible.group_id, "known"),))
        assert result.assigned_sections == 2
        assert store.source_account_bindings(additional[0].source_sha256)[0].ledger_account_id is None


@pytest.mark.parametrize("mismatch", ["missing", "parser", "revision", "digest"])
def test_catalog_authority_must_match_exact_saved_definition(archive, mismatch):
    workspace, _original, _additional = archive
    catalog = workspace.catalog_cache.load_current()
    entry = catalog.definitions[0]
    if mismatch == "missing":
        catalog = None
    elif mismatch == "digest":
        catalog = replace(catalog, definitions=(replace(entry, sha256="f" * 64),))
    else:
        identity = replace(entry.identity, **{"parser_id" if mismatch == "parser" else "revision": "other"})
        catalog = replace(catalog, definitions=(replace(entry, identity=identity),))
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        plan = plan_account_assignments(store, catalog=catalog, preferences=V2Preferences())
        assert len(plan.groups) == 4
        assert all(
            group.status == "manual" and group.reason == "verified_catalog_context_unavailable" for group in plan.groups
        )


def test_full_match_is_exact_and_last_four_obeys_policy_without_changing_it(archive):
    workspace, original, _additional = archive
    with V2ProfileStore.open(workspace.profile_path) as store:
        _variant(store, original, "full", identity="999991234", form="full")
        _variant(store, original, "suffix", identity="1234", form="last_four")
        store.add_financial_account(
            FinancialAccount("numbered", "Not parsed for identity", "liability", "yamaha", "999991234")
        )
        plan = _plan(store, workspace)
        full = next(group for group in plan.groups if group.source_identity_form == "full")
        suffix = next(group for group in plan.groups if group.source_identity_form == "last_four")
        assert full.suggested_account_id == "numbered"
        assert full.reason == "unique_full_number_match"
        assert suffix.suggested_account_id is None and suffix.reason == "abbreviated_matching_requires_review"
        enabled = _plan(store, workspace, V2Preferences(allow_abbreviated_account_matching=True))
        enabled_suffix = next(group for group in enabled.groups if group.source_identity_form == "last_four")
        assert enabled_suffix.suggested_account_id == "numbered"
        assert enabled_suffix.reason == "opted_in_abbreviated_number_match"
        store.add_financial_account(FinancialAccount("other", "Other", "liability", "yamaha", "888881234"))
        ambiguous = _plan(store, workspace, V2Preferences(allow_abbreviated_account_matching=True))
        suffix = next(group for group in ambiguous.groups if group.source_identity_form == "last_four")
        assert suffix.status == "ambiguous" and suffix.suggested_account_id is None
        assert workspace.preferences() == V2Preferences()


def test_accountless_exports_remain_per_document_manual(archive):
    from parsetrail.core.v2_source_pipeline import build_source_evidence

    from .test_v2_account_bindings import DEFINITION, SOURCE

    workspace, _original, _additional = archive
    with V2ProfileStore.open(workspace.profile_path) as store:
        evidence = build_source_evidence(SOURCE, DEFINITION, suffix=".csv")
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".csv")
        plan = _plan(store, workspace)
        group = next(group for group in plan.groups if group.source_identity is None)
        assert len(group.targets) == 1 and group.status == "manual"
        assert group.reason == "accountless_export_requires_file_or_row_review"


@pytest.mark.parametrize("change", ["account", "binding", "source", "policy", "catalog"])
def test_stale_plan_refuses_all_staged_writes(archive, change):
    workspace, original, _additional = archive
    staged = FinancialAccount("staged", "New", "liability", "yamaha")
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
        if change == "account":
            store.add_financial_account(FinancialAccount("other", "Other", "asset", "other"))
        elif change == "binding":
            store.add_financial_account(FinancialAccount("other", "Other", "liability", "yamaha"))
            identity = original.payload.accounts[0]
            store.bind_source_account(
                original.source_sha256, identity.source_identity, identity.source_identity_form, "other"
            )
        elif change == "source":
            _variant(store, original, "later")
        before = workspace.profile_path.read_bytes()
        with pytest.raises(ProfileFormatError, match="batch_assignment_plan_stale"):
            apply_account_assignments(
                store,
                plan,
                (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),),
                new_accounts=(staged,),
                catalog_loader=(lambda: None) if change == "catalog" else workspace.catalog_cache.load_current,
                preferences_loader=(lambda: V2Preferences(allow_abbreviated_account_matching=True))
                if change == "policy"
                else V2Preferences,
            )
        assert workspace.profile_path.read_bytes() == before
        assert not store.connection.in_transaction
        assert all(account.id != staged.id for account in store.financial_accounts())


def test_late_cancel_and_insert_failure_roll_back_all_accounts_and_bindings(archive):
    workspace, _original, _additional = archive
    staged = FinancialAccount("staged", "New", "liability", "yamaha")
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
        choices = (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),)
        before = workspace.profile_path.read_bytes()
        with pytest.raises(AccountAssignmentCancelled):
            _apply(
                store,
                workspace,
                plan,
                choices,
                new_accounts=(staged,),
                cancelled=lambda: (
                    store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone()[0] == 2
                ),
            )
        assert workspace.profile_path.read_bytes() == before
        store.connection.execute(
            "CREATE TEMP TRIGGER refuse_second BEFORE INSERT ON SourceAccountBindings WHEN (SELECT count(*) FROM SourceAccountBindings)=1 BEGIN SELECT RAISE(ABORT,'synthetic failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            _apply(store, workspace, plan, choices, new_accounts=(staged,))
        assert workspace.profile_path.read_bytes() == before
        assert store.financial_accounts() == ()
        assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (0,)


def test_plan_and_apply_verify_each_unbound_source_once(archive, monkeypatch):
    workspace, _original, _additional = archive
    verified = []
    original_verify = V2ProfileStore._verified_saved_import

    def record(source, row, observations):
        verified.append(source)
        return original_verify(source, row, observations)

    monkeypatch.setattr(V2ProfileStore, "_verified_saved_import", staticmethod(record))
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
        assert len(verified) == len(set(verified)) == 4
        verified.clear()
        staged = FinancialAccount("new", "New", "liability", "yamaha")
        _apply(
            store,
            workspace,
            plan,
            (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),),
            new_accounts=(staged,),
        )
        assert len(verified) == len(set(verified)) == 4


def test_identical_profile_copy_cannot_receive_another_profiles_plan(archive, tmp_path):
    workspace, _original, _additional = archive
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
    copied = V2ProfileStore.snapshot_to(workspace.profile_path, tmp_path / "copy.db")
    before = copied.read_bytes()
    with V2ProfileStore.open(copied) as store:
        staged = FinancialAccount("new", "New", "liability", "yamaha")
        with pytest.raises(ProfileFormatError, match="batch_assignment_plan_stale"):
            _apply(
                store,
                workspace,
                plan,
                (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),),
                new_accounts=(staged,),
            )
    assert copied.read_bytes() == before


def test_unrelated_corrupt_snapshot_refuses_plan_and_apply_without_writes(archive):
    from .test_v2_review_read_performance import _tamper

    workspace, _original, additional = archive
    with V2ProfileStore.open(workspace.profile_path) as store:
        plan = _plan(store, workspace)
    _tamper(
        workspace.profile_path,
        additional[1].source_sha256,
        "EvidenceSnapshots",
        "UPDATE EvidenceSnapshots SET content=? WHERE source_sha256=?",
        lambda source: (b"{}", source),
    )
    before = workspace.profile_path.read_bytes()
    with V2ProfileStore.open(workspace.profile_path) as store:
        with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
            _plan(store, workspace)
        staged = FinancialAccount("new", "New", "liability", "yamaha")
        with pytest.raises(ProfileFormatError, match="saved_snapshot_integrity"):
            _apply(
                store,
                workspace,
                plan,
                (AccountAssignmentChoice(plan.groups[0].group_id, staged.id),),
                new_accounts=(staged,),
            )
        assert not store.connection.in_transaction
        assert store.financial_accounts() == ()
    assert workspace.profile_path.read_bytes() == before


def test_plan_uses_one_read_snapshot_and_next_read_sees_concurrent_seed(archive, monkeypatch):
    workspace, original, _additional = archive
    identity = original.payload.accounts[0]
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
    original_iter = V2ProfileStore._iter_verified_imports
    written = False

    def concurrent_seed(store):
        nonlocal written
        if not written:
            written = True
            with V2ProfileStore.open(workspace.profile_path) as writer:
                writer.add_financial_account(FinancialAccount("seed", "Seed", "liability", "yamaha"))
                writer.bind_source_account(
                    original.source_sha256, identity.source_identity, identity.source_identity_form, "seed"
                )
        yield from original_iter(store)

    monkeypatch.setattr(V2ProfileStore, "_iter_verified_imports", concurrent_seed)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        first = _plan(store, workspace)
        second = _plan(store, workspace)
        assert first.groups[0].status == "choose_account" and len(first.groups[0].targets) == 4
        assert second.groups[0].suggested_account_id == "seed" and len(second.groups[0].targets) == 3
        assert first.basis_sha256 != second.basis_sha256
        assert not store.connection.in_transaction
