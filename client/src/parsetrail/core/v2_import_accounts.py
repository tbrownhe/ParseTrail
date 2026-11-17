"""Read-only account-first import proposals and one explicit atomic apply."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from parsetrail.core.v2_account_creation import AccountCreationDraft, suggest_account_creation
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_source_account
from parsetrail.core.v2_format_recognition import (
    FormatCandidate,
    FormatRecognition,
    FormatSelection,
    _recognize_catalog_source,
    candidate_from_evidence,
    selected_definition,
    validate_catalog_evidence,
)
from parsetrail.core.v2_institutions import Institution, catalog_institutions, institution_label, merge_institutions
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, SourceImportResult
from parsetrail.core.v2_source_pipeline import build_source_evidence


@dataclass(frozen=True, slots=True)
class ImportAccountGroup:
    group_id: str
    source_identity: str | None
    source_form: str | None
    source_label: str | None
    row_count: int
    source_scope: str | None
    locations: tuple
    suggested_account_id: str | None = None
    automatic: bool = False
    offer_enable_abbreviated_matching: bool = False
    matching_ambiguous: bool = False


@dataclass(frozen=True, slots=True)
class ImportAccountReview:
    recognition: FormatRecognition
    accounts: tuple[FinancialAccount, ...]
    institutions: tuple[Institution, ...]
    groups: tuple[ImportAccountGroup, ...]
    basis_sha256: str
    profile_sha256: str
    recovery_notice: str = ""
    allow_abbreviated_account_matching: bool = False
    import_preview_mode: str = "always"
    operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ImportAccountChoice:
    group_id: str
    account_id: str


@dataclass(frozen=True, slots=True)
class ImportAccountPlan:
    selection: FormatSelection
    choices: tuple[ImportAccountChoice, ...]
    new_accounts: tuple[FinancialAccount, ...]
    basis_sha256: str
    profile_sha256: str
    candidate: FormatCandidate
    operation_id: str | None = None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _group_id(identity, form):
    return _digest([identity, form])


def _profile_identity(store):
    filename = next(
        (filename for _sequence, name, filename in store.connection.execute("PRAGMA database_list") if name == "main"),
        "",
    )
    if not filename:
        raise ProfileFormatError("import_account_profile_identity_unavailable")
    path = Path(filename).resolve(strict=True)
    stat = path.stat()
    return _digest([os.path.normcase(str(path)), stat.st_dev, stat.st_ino])


def _basis(store):
    values = []
    for table, columns in (
        ("Institutions", "*"),
        ("Accounts", "*"),
        ("Sources", "sha256,size,suffix"),
        ("SourceAccountBindings", "*"),
        ("FileAccountAssertions", "*"),
        ("RowAccountAssignments", "*"),
    ):
        rows = store.connection.execute(f"SELECT {columns} FROM {table}").fetchall()
        values.append([table, sorted(rows, key=lambda row: json.dumps(row, separators=(",", ":")))])
    return _digest(values)


def _remembered_accounts(store, catalog, identity, form, eligible, candidate, section):
    """Reuse explicit associations in exact trusted institution/class/scope context.

    A partial/opaque source identifier remains partial/opaque. Generic CSV account
    text cannot acquire institution authority through a previous authored choice.
    """
    from parsetrail.core.source_evidence import StatementPayload

    account_ids = {account.id for account in eligible}
    expected = (candidate.institution_key, candidate.account_kind, section.source_scope)
    found = set()
    for source, account_id in store.connection.execute(
        "SELECT source_sha256,ledger_account_id FROM SourceAccountBindings WHERE source_identity=? AND source_identity_form=?",
        (identity, form),
    ):
        if account_id not in account_ids or account_id in found:
            continue
        saved = store.load_import(source)
        draft = suggest_account_creation(saved.evidence, catalog=catalog, source_identity=identity, source_form=form)
        if not draft.verified_context or (draft.institution_key, draft.kind, draft.tracking_scope) != expected:
            continue
        payload = saved.evidence.payload
        if isinstance(payload, StatementPayload) and any(
            item.source_identity == identity
            and item.source_identity_form == form
            and item.balance_scope == section.source_scope
            for item in payload.accounts
        ):
            found.add(account_id)
    return tuple(sorted(found))


def build_import_account_review(store, recognition, catalog, preferences=None):
    """Capture current choices without holding a connection during user review."""
    if not isinstance(recognition, FormatRecognition) or not recognition.candidates:
        raise ProfileFormatError("import_account_recognition_invalid")
    if len({_structure(candidate) for candidate in recognition.candidates}) != 1:
        # A column question cannot repair overlapping parser declarations. Do
        # not present an invented union of incompatible source-account groups.
        raise ProfileFormatError("import_account_routing_conflict")
    preferences = preferences or V2Preferences()
    owns = not store.connection.in_transaction
    if owns:
        store.connection.execute("BEGIN")
    try:
        accounts = store.financial_accounts()
        institutions = merge_institutions(store.institutions(), catalog_institutions(catalog))
        grouped = {}
        for candidate in recognition.candidates:
            for section in candidate.source_accounts:
                grouped.setdefault((section.source_identity, section.source_form), []).append((candidate, section))
        groups = []
        for (identity, form), occurrences in grouped.items():
            source_scopes = {section.source_scope for _candidate, section in occurrences}
            suggested, automatic, offer_abbreviated, ambiguous = None, False, False, False
            # Only authenticated PDF source facts can infer an existing account.
            # CSV headers/profile options never establish the user's identity.
            if recognition.suffix == ".pdf" and len(recognition.candidates) == 1:
                candidate, _section = occurrences[0]
                if identity is not None and form in {"full", "last_four", "opaque"} and candidate.institution_key:
                    eligible = tuple(account for account in accounts if _compatible(candidate, _section, account))
                    match = match_source_account(
                        identity,
                        form,
                        institution_key=candidate.institution_key,
                        kind=candidate.account_kind,
                        candidates=tuple(
                            LedgerAccountCandidate(a.id, a.institution_key, a.kind, a.full_account_number)
                            for a in eligible
                        ),
                        preferences=preferences,
                    )
                    suggested = match.ledger_account_id or (
                        match.suggestions[0] if len(match.suggestions) == 1 else None
                    )
                    automatic = match.status == "automatic"
                    offer_abbreviated = match.offer_enable_abbreviated_matching or (
                        form == "last_four" and match.status == "automatic"
                    )
                    remembered = _remembered_accounts(store, catalog, identity, form, eligible, candidate, _section)
                    possibilities = set(match.suggestions) | set(remembered)
                    if len(possibilities) > 1:
                        suggested, automatic, offer_abbreviated, ambiguous = None, False, False, True
                    elif len(possibilities) == 1:
                        suggested = next(iter(possibilities))
                        automatic = match.status == "automatic" or (
                            bool(remembered) and (form != "last_four" or preferences.allow_abbreviated_account_matching)
                        )
                        offer_abbreviated = form == "last_four"
            first = occurrences[0][1]
            groups.append(
                ImportAccountGroup(
                    _group_id(identity, form),
                    identity,
                    form,
                    first.source_label or identity or "Account not identified in document",
                    max(section.row_count for _candidate, section in occurrences),
                    next(iter(source_scopes)) if len(source_scopes) == 1 else None,
                    first.locations,
                    suggested,
                    automatic,
                    offer_abbreviated,
                    ambiguous,
                )
            )
        if not groups:
            raise ProfileFormatError("import_account_source_groups_missing")
        return ImportAccountReview(
            recognition,
            accounts,
            institutions,
            tuple(groups),
            _basis(store),
            _profile_identity(store),
            allow_abbreviated_account_matching=preferences.allow_abbreviated_account_matching,
            import_preview_mode=preferences.import_preview_mode,
        )
    finally:
        if owns:
            store.connection.execute("ROLLBACK")


def _compatible(candidate, section, account):
    if account.product_type == "tangible_asset":
        return False
    return any(
        account.kind == profile.kind
        and account.tracking_scope == profile.tracking_scope
        and (section.source_scope is None or section.source_scope == profile.tracking_scope)
        and (account.product_type is None or account.product_type == profile.product_type)
        and (
            account.institution_key is None
            or profile.institution_key is None
            or account.institution_key == profile.institution_key
        )
        for profile in candidate.account_profiles
    )


def _accounts_by_id(review, new_accounts):
    if len({account.id for account in new_accounts}) != len(new_accounts):
        raise ProfileFormatError("import_account_duplicate_draft")
    accounts = {account.id: account for account in review.accounts}
    for account in new_accounts:
        V2ProfileStore._financial_account_values(account)
        if account.id in accounts:
            raise ProfileFormatError("import_account_duplicate_draft")
        if account.product_type is None:
            raise ProfileFormatError("import_account_product_required")
        if account.institution_key is not None and not any(
            institution.id == account.institution_key for institution in review.institutions
        ):
            raise ProfileFormatError("institution_not_registered")
        accounts[account.id] = account
    return accounts


def matching_import_candidates(review, choices=(), new_accounts=()):
    """Narrow by explicit account choices without inferring physical identity."""
    accounts = _accounts_by_id(review, new_accounts)
    if len({choice.group_id for choice in choices}) != len(choices):
        raise ProfileFormatError("import_account_duplicate_choice")
    result = []
    for candidate in review.recognition.candidates:
        sections = {
            _group_id(section.source_identity, section.source_form): section for section in candidate.source_accounts
        }
        if all(
            choice.group_id in sections
            and choice.account_id in accounts
            and _compatible(candidate, sections[choice.group_id], accounts[choice.account_id])
            for choice in choices
        ):
            result.append(candidate)
    return tuple(result)


def resolve_import_candidate(review, choices=(), new_accounts=()):
    """Resolve declared formats from account metadata, never a column choice."""
    candidates = matching_import_candidates(review, choices, new_accounts)
    if not candidates:
        raise ProfileFormatError("import_account_incompatible")
    if len(candidates) != 1:
        raise ProfileFormatError("import_account_routing_conflict")
    return candidates[0]


def automatic_import_plan(review):
    """Only an explicit opt-in and an entirely routine known-account file can skip UI."""
    if (
        review.import_preview_mode != "when_needed"
        or review.recovery_notice
        or len(review.recognition.candidates) != 1
        or not review.groups
        or any(not group.automatic or group.suggested_account_id is None for group in review.groups)
    ):
        return None
    candidate = review.recognition.candidates[0]
    if candidate.attention_codes:
        return None
    choices = tuple(ImportAccountChoice(group.group_id, group.suggested_account_id) for group in review.groups)
    return prepare_import_accounts(review, choices, candidate.parser_id)


def compatible_import_accounts(review, group_id, parser_id=None, *, new_accounts=()):
    candidates = tuple(
        candidate
        for candidate in review.recognition.candidates
        if parser_id is None or candidate.parser_id == parser_id
    )
    return tuple(
        account
        for account in _accounts_by_id(review, new_accounts).values()
        if any(
            _group_id(section.source_identity, section.source_form) == group_id
            and _compatible(candidate, section, account)
            for candidate in candidates
            for section in candidate.source_accounts
        )
    )


def _structure(candidate):
    return frozenset((section.source_identity, section.source_form) for section in candidate.source_accounts)


def import_account_profiles(review, group_id, choices=(), new_accounts=()):
    profiles = set()
    for candidate in matching_import_candidates(review, choices, new_accounts):
        for section in candidate.source_accounts:
            if _group_id(section.source_identity, section.source_form) != group_id:
                continue
            profiles.update(
                profile
                for profile in candidate.account_profiles
                if section.source_scope is None or section.source_scope == profile.tracking_scope
            )
    return tuple(
        sorted(
            profiles, key=lambda profile: (profile.institution_key or "", profile.product_type, profile.tracking_scope)
        )
    )


def import_account_creation_draft(review, group_id, profile):
    if profile not in import_account_profiles(review, group_id):
        raise ProfileFormatError("import_account_profile_unavailable")
    group = next((group for group in review.groups if group.group_id == group_id), None)
    if group is None:
        raise ProfileFormatError("import_account_group_missing")
    runs = re.findall(r"[0-9]+", group.source_identity or "")
    tail = runs[-1][-4:] if runs else ""
    label = institution_label(profile.institution_key, review.institutions) if profile.institution_key else ""
    full = (
        group.source_identity
        if group.source_form == "full"
        and group.source_identity is not None
        and len(group.source_identity) <= 80
        and re.search(r"[*xX•●#…]", group.source_identity) is None
        else None
    )
    recognized = any(
        candidate.institution_key is not None
        and candidate.institution_key == profile.institution_key
        and candidate.account_kind == profile.kind
        for candidate in review.recognition.candidates
    )
    return AccountCreationDraft(
        name=" ".join(part for part in (label or ("Account" if tail else ""), tail) if part),
        institution_key=profile.institution_key,
        kind=profile.kind,
        tracking_scope=profile.tracking_scope,
        full_account_number=full,
        source_identity=group.source_identity,
        source_form=group.source_form,
        verified_context=recognized,
        source_sha256=review.recognition.source_sha256,
        source_locations=group.locations,
        product_type=profile.product_type,
    )


def prepare_import_accounts(review, choices, parser_id, new_accounts=()):
    """Freeze complete explicit choices for one format's actual source groups."""
    candidate = resolve_import_candidate(review, choices, new_accounts)
    if candidate.parser_id != parser_id:
        raise ProfileFormatError("import_account_incompatible")
    groups = {_group_id(section.source_identity, section.source_form) for section in candidate.source_accounts}
    if {choice.group_id for choice in choices} != groups:
        raise ProfileFormatError("import_account_choices_incomplete")
    if {account.id for account in new_accounts} - {choice.account_id for choice in choices}:
        raise ProfileFormatError("import_account_unused_draft")
    return ImportAccountPlan(
        review.recognition.selection(parser_id),
        tuple(choices),
        tuple(new_accounts),
        review.basis_sha256,
        review.profile_sha256,
        candidate,
        review.operation_id,
    )


def commit_import_accounts(
    store,
    prepared,
    catalog,
    plan,
    cancelled=None,
    *,
    parse=build_source_evidence,
    before_write=None,
    automatic_preferences=None,
):
    """Create accounts, retain source and assign all groups together; post nothing."""
    from parsetrail.core.v2_prepared_import import PreparedImportSession

    try:
        return _commit_import_accounts(
            store,
            prepared,
            catalog,
            plan,
            cancelled,
            parse=parse,
            before_write=before_write,
            automatic_preferences=automatic_preferences,
        )
    finally:
        if type(prepared) is PreparedImportSession:
            prepared.close()


def _commit_import_accounts(
    store,
    prepared,
    catalog,
    plan,
    cancelled,
    *,
    parse,
    before_write,
    automatic_preferences,
):
    from parsetrail.core.v2_prepared_import import PreparedImportSession

    def check_cancelled():
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")

    check_cancelled()
    session = type(prepared) is PreparedImportSession
    submitted_plan = plan
    submitted_catalog = catalog
    recognition = None
    if session:
        recognition, plan, catalog = prepared.claim(catalog, plan)
    if not session and plan.operation_id is not None:
        raise ProfileFormatError("import_preparation_operation_mismatch")
    if _profile_identity(store) != plan.profile_sha256:
        raise ProfileFormatError("import_account_profile_changed")
    entry = selected_definition(prepared.source, catalog=catalog, suffix=prepared.suffix, selection=plan.selection)
    if entry.content != prepared.definition:
        raise ProfileFormatError("import_account_format_changed")
    validate_catalog_evidence(prepared.evidence, plan.selection.source_sha256, entry)
    candidate = candidate_from_evidence(entry, prepared.evidence, catalog)
    if candidate != plan.candidate:
        raise ProfileFormatError("import_account_format_changed")
    # Legacy caller-built DTOs require complete recognition and full selected
    # output equality. A live operation already owns that authenticated proof.
    if not session:

        def check_selected_output(definition, evidence):
            if definition.identity.parser_id == plan.selection.parser_id and evidence != prepared.evidence:
                raise ProfileFormatError("import_account_format_changed")

        recognition = _recognize_catalog_source(
            prepared.source,
            catalog=catalog,
            suffix=prepared.suffix,
            cancelled=cancelled,
            parse=parse,
            collect=check_selected_output,
        )
    if candidate not in recognition.candidates:
        raise ProfileFormatError("import_account_format_changed")
    # Workspace rereads file/catalog immediately before the atomic write.
    if before_write is not None:
        before_write()
    if _profile_identity(store) != plan.profile_sha256:
        raise ProfileFormatError("import_account_profile_changed")
    with store._atomic_write("import_accounts"):
        check_cancelled()
        if session:
            prepared.validate_apply(catalog=submitted_catalog, plan=submitted_plan)
        if _profile_identity(store) != plan.profile_sha256:
            raise ProfileFormatError("import_account_profile_changed")
        if store.source_imported(prepared.source):
            saved = store.load_import(plan.selection.source_sha256)
            return SourceImportResult("already_imported", plan.selection.source_sha256, saved.evidence)
        if _basis(store) != plan.basis_sha256:
            raise ProfileFormatError("import_account_review_stale")
        review = build_import_account_review(
            store,
            recognition,
            catalog,
            preferences=automatic_preferences() if automatic_preferences is not None else None,
        )
        if automatic_preferences is not None:
            routine = automatic_import_plan(review)
            if routine is None or routine.choices != plan.choices or routine.selection != plan.selection:
                raise ProfileFormatError("import_automatic_review_required")
        verified = prepare_import_accounts(review, plan.choices, candidate.parser_id, plan.new_accounts)
        if verified.selection != plan.selection:
            raise ProfileFormatError("import_account_format_changed")
        store.register_catalog_institutions(catalog)
        for account in plan.new_accounts:
            check_cancelled()
            store.add_financial_account(account)
        check_cancelled()
        store.import_source(prepared.source, prepared.definition, prepared.evidence, suffix=prepared.suffix)
        sections = {
            _group_id(section.source_identity, section.source_form): section for section in candidate.source_accounts
        }
        for choice in plan.choices:
            check_cancelled()
            section = sections[choice.group_id]
            if section.source_identity is not None:
                store.bind_source_account(
                    plan.selection.source_sha256, section.source_identity, section.source_form, choice.account_id
                )
            else:
                from parsetrail.core.source_evidence import ActivityExportPayload

                payload = prepared.evidence.payload
                if not isinstance(payload, ActivityExportPayload):
                    raise ProfileFormatError("import_account_unknown_statement_identity")
                row_ids = tuple(row.row_id for row in payload.rows if row.source_account is None)
                if all(row.source_account is None for row in payload.rows):
                    store.assert_file_account(plan.selection.source_sha256, choice.account_id)
                else:
                    store.assign_rows_account(plan.selection.source_sha256, row_ids, choice.account_id)
        if prepared.suffix == ".pdf":
            for account in plan.new_accounts:
                store.lock_pdf_import_account(account.id, plan.selection.source_sha256)
        check_cancelled()
        return SourceImportResult("imported", plan.selection.source_sha256, prepared.evidence)
