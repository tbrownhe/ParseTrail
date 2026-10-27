"""Explicit archive account assignment with one verified snapshot and atomic apply.

Printed identities are reused only within exact signed institution/class/scope
context. A confirmed opaque identity remains opaque; no hidden digits or account
display names participate in matching. These choices never post financial entries.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_account_creation import AccountCreationDraft, suggest_account_creation
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_source_account
from parsetrail.core.v2_data_catalog import VerifiedCatalog
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore, _rows

RULE = "explicit-archive-account-assignment-1"


class AccountAssignmentCancelled(ProfileFormatError):
    """Cancellation rolled back every staged account and selected assignment."""


@dataclass(frozen=True)
class SourceAccountTarget:
    source_sha256: str
    source_identity: str | None
    source_identity_form: str | None
    parser_id: str
    document_kind: str
    row_count: int
    start: date | None
    end: date | None
    start_provenance: str
    end_provenance: str


@dataclass(frozen=True)
class AccountAssignmentGroup:
    group_id: str
    institution_key: str | None
    kind: str | None
    tracking_scope: str | None
    source_identity: str | None
    source_identity_form: str | None
    targets: tuple[SourceAccountTarget, ...]
    draft: AccountCreationDraft
    status: Literal["suggested", "choose_account", "ambiguous", "manual"]
    reason: str
    suggested_account_id: str | None
    eligible_account_ids: tuple[str, ...]


@dataclass(frozen=True)
class AccountAssignmentPlan:
    basis_sha256: str
    authority_sha256: str
    groups: tuple[AccountAssignmentGroup, ...]
    accounts: tuple[FinancialAccount, ...]
    profile_sha256: str = ""


@dataclass(frozen=True)
class AccountAssignmentChoice:
    group_id: str
    account_id: str


@dataclass(frozen=True)
class AccountAssignmentResult:
    assigned_sections: int
    created_accounts: int
    already_applied_sections: int = 0


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cancel(cancelled):
    if cancelled is not None and cancelled():
        raise AccountAssignmentCancelled("batch_assignment_cancelled")


def _authority(catalog, preferences) -> str:
    if not isinstance(preferences, V2Preferences):
        raise ProfileFormatError("batch_assignment_preferences_invalid")
    if catalog is not None and not isinstance(catalog, VerifiedCatalog):
        raise ProfileFormatError("batch_assignment_catalog_invalid")
    return _digest(
        [
            RULE,
            hashlib.sha256(catalog.snapshot + catalog.signature).hexdigest() if catalog is not None else None,
            [
                [
                    entry.identity.parser_id,
                    entry.identity.revision,
                    entry.identity.suffix,
                    entry.sha256,
                    entry.account_context.model_dump() if entry.account_context is not None else None,
                ]
                for entry in catalog.definitions
            ]
            if catalog is not None
            else [],
            asdict(preferences),
        ]
    )


def _state_basis(store, authority):
    """Conservative current-state guard without embedding source bytes in a plan."""
    state = [authority]
    for table, columns in (
        ("Sources", "sha256,size,suffix"),
        ("Definitions", "sha256,size"),
        ("EvidenceSnapshots", "source_sha256,definition_sha256,sha256,size"),
        ("Accounts", "*"),
        ("SourceAccountBindings", "*"),
        ("FileAccountAssertions", "*"),
        ("RowAccountAssignments", "*"),
        ("BindingCorrections", "*"),
        ("JournalEntries", "*"),
        ("JournalAllocations", "*"),
        ("LoanSourceUses", "*"),
        ("SourceOverlapReviews", "*"),
        ("TransferPairReviews", "*"),
        ("StatementSourceReviews", "*"),
        ("OpeningDecisions", "*"),
        ("OpeningDecisionRevisions", "*"),
        ("AccountDatedValues", "*"),
        ("DatedValueWithdrawals", "*"),
    ):
        values = store.connection.execute(f"SELECT {columns} FROM {table}").fetchall()
        state.append([table, sorted(values, key=lambda row: json.dumps(row, separators=(",", ":")))])
    return _digest(state)


def _profile_identity(store):
    filename = next(
        (filename for _sequence, name, filename in store.connection.execute("PRAGMA database_list") if name == "main"),
        "",
    )
    if not filename:
        raise ProfileFormatError("batch_assignment_profile_identity_unavailable")
    path = Path(filename).resolve(strict=True)
    stat = path.stat()
    return _digest([os.path.normcase(str(path)), stat.st_dev, stat.st_ino])


def _binding_guards(store, accounts):
    """Prefetch the ordinary-assignment history guards once for the snapshot."""
    corrections = store._read_binding_corrections()
    blocked_rows = {
        row_id
        for (row_id,) in store.connection.execute(
            "SELECT row_id FROM JournalAllocations UNION SELECT row_id FROM LoanSourceUses "
            "UNION SELECT left_row_id FROM SourceOverlapReviews UNION SELECT right_row_id FROM SourceOverlapReviews "
            "UNION SELECT outgoing_row_id FROM TransferPairReviews UNION SELECT incoming_row_id FROM TransferPairReviews"
        )
    }
    source_review_accounts = {}
    for source_id, account_id in store.connection.execute(
        "SELECT source_sha256,account_id FROM StatementSourceReviews"
    ):
        source_review_accounts.setdefault(source_id, set()).add(account_id)
    source_openings = {
        account.id
        for account in accounts
        if (history := store.opening_decision_history(account.id))
        and history[0].origin == "source"
        and history[0].state == "active"
    }
    values = {
        (value.source_proof.source_sha256, value.source_proof.source_identity, value.source_proof.source_identity_form)
        for value in store._read_dated_values()
        if value.state == "active" and value.source_proof is not None
    }
    return corrections, blocked_rows, source_review_accounts, source_openings, values


def _compatible(account, key):
    institution, kind, scope, _identity, _form = key
    return (account.institution_key, account.kind, account.tracking_scope) == (institution, kind, scope)


def account_compatible(group: AccountAssignmentGroup, account: FinancialAccount) -> bool:
    """Whether a staged/existing account has the group's exact trusted scope."""
    return (
        isinstance(group, AccountAssignmentGroup)
        and group.status != "manual"
        and isinstance(account, FinancialAccount)
        and _compatible(
            account,
            (
                group.institution_key,
                group.kind,
                group.tracking_scope,
                group.source_identity,
                group.source_identity_form,
            ),
        )
    )


def _build_plan(store, catalog, preferences, cancelled=None):
    authority = _authority(catalog, preferences)
    accounts = store.financial_accounts()
    account_by_id = {account.id: account for account in accounts}
    corrections, blocked_rows, review_accounts, source_openings, values = _binding_guards(store, accounts)
    assignments = {}
    for source, identity, form, account in store.connection.execute("SELECT * FROM SourceAccountBindings"):
        assignments[source, identity, form] = account
    file_assignments = dict(
        store.connection.execute("SELECT source_sha256,ledger_account_id FROM FileAccountAssertions")
    )
    row_assignments = dict(store.connection.execute("SELECT row_id,ledger_account_id FROM RowAccountAssignments"))
    pending = {}
    seeds = {}
    sections = {}
    for source_id, saved in store._iter_verified_imports():
        _cancel(cancelled)
        evidence = saved.evidence
        payload = evidence.payload
        rows = _rows(evidence)
        identities = (
            tuple((section.source_identity, section.source_identity_form) for section in payload.accounts)
            if isinstance(payload, StatementPayload)
            else tuple(dict.fromkeys((row.source_account, row.source_account_form) for row in rows))
        )
        start = payload.start if isinstance(payload, StatementPayload) else payload.activity_start
        end = payload.end if isinstance(payload, StatementPayload) else payload.activity_end
        for identity, form in identities:
            selected_rows = tuple(
                row for row in rows if (row.source_account, row.source_account_form) == (identity, form)
            )
            draft = suggest_account_creation(evidence, catalog=catalog, source_identity=identity, source_form=form)
            target = SourceAccountTarget(
                source_id,
                identity,
                form,
                evidence.parser_id,
                payload.kind,
                len(selected_rows),
                date.fromisoformat(start.iso) if start.iso else None,
                date.fromisoformat(end.iso) if end.iso else None,
                start.provenance,
                end.provenance,
            )
            key = (draft.institution_key or None, draft.kind, draft.tracking_scope, identity, form)
            assigned = assignments.get((source_id, identity, form))
            sections[source_id, identity, form] = (target, key, assigned)
            trusted = (
                draft.verified_context
                and draft.kind is not None
                and draft.tracking_scope is not None
                and identity is not None
            )
            if assigned is not None:
                if trusted:
                    seeds.setdefault(key, set()).add(assigned)
                continue
            if identity is None:
                if all(row.row_id in row_assignments or source_id in file_assignments for row in selected_rows):
                    continue
            reason = ""
            if identity is None:
                reason = "accountless_export_requires_file_or_row_review"
            elif not draft.verified_context:
                reason = "verified_catalog_context_unavailable"
            elif draft.tracking_scope is None:
                reason = "tracking_scope_unavailable"
            elif (draft.kind == "asset" and draft.tracking_scope == "principal_component") or (
                draft.kind == "liability" and draft.tracking_scope == "cash_component"
            ):
                reason = "source_class_scope_incompatible"
            elif {row.row_id for row in selected_rows}.intersection(blocked_rows):
                reason = "account_binding_has_review_history"
            elif review_accounts.get(source_id, set()).intersection(source_openings):
                reason = "account_binding_source_backed_opening_anchor"
            elif (source_id, identity, form) in values:
                reason = "account_binding_source_backed_dated_value_anchor"
            else:
                for record in corrections:
                    old = record.target
                    if old.source_sha256 != source_id:
                        continue
                    old_rows = (
                        {row.row_id for row in rows}
                        if old.mode == "file"
                        else set(old.row_ids)
                        if old.mode == "rows"
                        else {
                            row.row_id
                            for row in rows
                            if (row.source_account, row.source_account_form)
                            == (old.source_identity, old.source_identity_form)
                        }
                    )
                    if old_rows.intersection(row.row_id for row in selected_rows) or (
                        old.mode == "source" and (old.source_identity, old.source_identity_form) == (identity, form)
                    ):
                        reason = "account_binding_has_correction_history"
                        break
            # Keep locked/manual sections visible without withholding unrelated
            # eligible documents that happen to print the same scoped identity.
            grouping = (*key, source_id if reason or not trusted else None, reason or None)
            group = pending.setdefault(grouping, {"key": key, "draft": draft, "targets": [], "reasons": set()})
            group["targets"].append(target)
            if reason:
                group["reasons"].add(reason)
    groups = []
    for grouping, value in pending.items():
        key, draft = value["key"], value["draft"]
        eligible = tuple(account.id for account in accounts if _compatible(account, key))
        prior = seeds.get(key, set())
        suggested = None
        reason = next(iter(sorted(value["reasons"])), "")
        status = "manual" if reason else "choose_account"
        if not reason and any(
            account_id not in account_by_id or not _compatible(account_by_id[account_id], key) for account_id in prior
        ):
            status, reason = "manual", "prior_assignment_incompatible"
        elif not reason and len(prior) > 1:
            status, reason = "ambiguous", "prior_identity_has_multiple_accounts"
        elif not reason and len(prior) == 1:
            status, reason, suggested = "suggested", "prior_explicit_identity_assignment", next(iter(prior))
        elif not reason:
            match = match_source_account(
                key[3],
                key[4],
                institution_key=key[0],
                kind=key[1],
                candidates=tuple(
                    LedgerAccountCandidate(
                        account.id, account.institution_key, account.kind, account.full_account_number
                    )
                    for account in accounts
                    if account.id in eligible
                ),
                preferences=preferences,
            )
            if match.status == "automatic":
                status, reason, suggested = (
                    "suggested",
                    "opted_in_abbreviated_number_match" if key[4] == "last_four" else "unique_full_number_match",
                    match.ledger_account_id,
                )
            elif match.status == "ambiguous":
                status, reason = "ambiguous", "number_has_multiple_accounts"
            elif match.offer_enable_abbreviated_matching:
                reason = "abbreviated_matching_requires_review"
        groups.append(
            AccountAssignmentGroup(
                _digest([RULE, grouping]),
                key[0],
                key[1],
                key[2],
                key[3],
                key[4],
                tuple(value["targets"]),
                draft,
                status,
                reason,
                suggested,
                eligible,
            )
        )
    groups.sort(key=lambda group: (group.institution_key or "", group.source_identity or "", group.group_id))
    return AccountAssignmentPlan(
        _state_basis(store, authority), authority, tuple(groups), accounts, _profile_identity(store)
    ), sections


def plan_account_assignments(
    store: V2ProfileStore,
    *,
    catalog: VerifiedCatalog | None,
    preferences: V2Preferences,
    cancelled: Callable[[], bool] | None = None,
) -> AccountAssignmentPlan:
    """Read all unassigned sections without changing accounts, bindings or policy."""
    if store.connection.in_transaction:
        raise ProfileFormatError("batch_assignment_requires_committed_snapshot")
    store.connection.execute("BEGIN")
    try:
        plan, _sections = _build_plan(store, catalog, preferences, cancelled)
        _cancel(cancelled)
        return plan
    finally:
        store.connection.execute("ROLLBACK")


def apply_account_assignments(
    store: V2ProfileStore,
    plan: AccountAssignmentPlan,
    choices: tuple[AccountAssignmentChoice, ...],
    *,
    new_accounts: tuple[FinancialAccount, ...] = (),
    catalog_loader: Callable[[], VerifiedCatalog | None],
    preferences_loader: Callable[[], V2Preferences],
    cancelled: Callable[[], bool] | None = None,
) -> AccountAssignmentResult:
    """Save the explicitly selected associations and selected new accounts together.

    Loaders must return freshly verified catalog/current preferences (e.g. the
    workspace cache and preferences methods); they are invoked under the write
    transaction. Cancellation before COMMIT rolls everything back; after COMMIT
    the saved result is returned without reporting an unperformed cancellation.
    """
    store._require_writable()
    if store.connection.in_transaction:
        raise ProfileFormatError("batch_assignment_requires_committed_snapshot")
    if not isinstance(plan, AccountAssignmentPlan) or not isinstance(choices, tuple) or not choices:
        raise ProfileFormatError("batch_assignment_choices_required")
    if any(not isinstance(choice, AccountAssignmentChoice) for choice in choices) or len(
        {choice.group_id for choice in choices}
    ) != len(choices):
        raise ProfileFormatError("batch_assignment_choices_invalid")
    if (
        not isinstance(new_accounts, tuple)
        or any(not isinstance(account, FinancialAccount) for account in new_accounts)
        or len({account.id for account in new_accounts}) != len(new_accounts)
    ):
        raise ProfileFormatError("batch_assignment_new_accounts_invalid")
    for account in new_accounts:
        store._financial_account_values(account)
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        _cancel(cancelled)
        current, sections = _build_plan(store, catalog_loader(), preferences_loader(), cancelled)
        if current.authority_sha256 != plan.authority_sha256 or current.profile_sha256 != plan.profile_sha256:
            raise ProfileFormatError("batch_assignment_plan_stale")
        staged = {account.id: account for account in new_accounts}
        accounts = {account.id: account for account in current.accounts}
        if any(account_id in accounts and accounts[account_id] != account for account_id, account in staged.items()):
            raise ProfileFormatError("batch_assignment_new_account_conflicts")
        supplied_groups = {group.group_id: group for group in plan.groups}
        current_groups = {group.group_id: group for group in current.groups}
        selected_targets = []
        for choice in choices:
            group = supplied_groups.get(choice.group_id)
            if group is None or group.status == "manual":
                raise ProfileFormatError("batch_assignment_group_unavailable")
            account = accounts.get(choice.account_id) or staged.get(choice.account_id)
            key = (
                group.institution_key,
                group.kind,
                group.tracking_scope,
                group.source_identity,
                group.source_identity_form,
            )
            if account is None or not account_compatible(group, account):
                raise ProfileFormatError("batch_assignment_account_incompatible")
            for target in group.targets:
                found = sections.get((target.source_sha256, target.source_identity, target.source_identity_form))
                if found is None or found[0] != target or found[1] != key:
                    raise ProfileFormatError("batch_assignment_plan_stale")
                selected_targets.append((target, choice.account_id, found[2]))
        if current.basis_sha256 != plan.basis_sha256:
            if all(existing == account_id for _target, account_id, existing in selected_targets) and all(
                account_id not in staged or accounts.get(account_id) == staged[account_id]
                for account_id in {choice.account_id for choice in choices}
            ):
                _cancel(cancelled)
                store.connection.execute("COMMIT")
                return AccountAssignmentResult(0, 0, len(selected_targets))
            raise ProfileFormatError("batch_assignment_plan_stale")
        if any(current_groups.get(choice.group_id) != supplied_groups[choice.group_id] for choice in choices):
            raise ProfileFormatError("batch_assignment_plan_stale")
        if any(existing is not None for _target, _account, existing in selected_targets):
            raise ProfileFormatError("batch_assignment_existing_binding")
        created = 0
        for account_id in {choice.account_id for choice in choices}:
            if account_id not in accounts:
                _cancel(cancelled)
                store.add_financial_account(staged[account_id])
                created += 1
        for target, account_id, _existing in selected_targets:
            _cancel(cancelled)
            store.connection.execute(
                "INSERT INTO SourceAccountBindings VALUES (?,?,?,?)",
                (target.source_sha256, target.source_identity, target.source_identity_form, account_id),
            )
        _cancel(cancelled)
        store.connection.execute("COMMIT")
        return AccountAssignmentResult(len(selected_targets), created)
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise
