"""Editable account drafts from exact saved evidence; no binding or posting policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence, StatementPayload
from parsetrail.core.v2_data_catalog import VerifiedCatalog
from parsetrail.core.v2_loan_payments import LOAN_PARSERS


@dataclass(frozen=True)
class AccountCreationDraft:
    name: str = ""
    institution_key: str = ""
    kind: Literal["asset", "liability"] | None = None
    tracking_scope: Literal["account_total", "principal_component", "cash_component"] | None = None
    full_account_number: str | None = None
    source_identity: str | None = None
    source_form: str | None = None
    verified_context: bool = False


def suggest_account_creation(
    evidence: SourceEvidence,
    *,
    catalog: VerifiedCatalog | None,
    source_identity: str | None = None,
    source_form: str | None = None,
) -> AccountCreationDraft:
    """Suggest only selected printed facts and exact signed declaration context."""
    payload = evidence.payload
    scope = None
    if source_identity is not None:
        if isinstance(payload, StatementPayload):
            sections = tuple(
                account
                for account in payload.accounts
                if (account.source_identity, account.source_identity_form) == (source_identity, source_form)
            )
            if not sections:
                raise ValueError("selected_source_account_missing")
            scopes = {account.balance_scope for account in sections}
            if len(scopes) == 1:
                scope = next(iter(scopes))
        elif not any(
            (row.source_account, row.source_account_form) == (source_identity, source_form) for row in payload.rows
        ):
            raise ValueError("selected_source_account_missing")
    elif isinstance(payload, StatementPayload) or not any(row.source_account is None for row in payload.rows):
        raise ValueError("account_creation_requires_selected_identity")
    entries = (
        tuple(
            item
            for item in catalog.definitions
            if item.identity.parser_id == evidence.parser_id
            and item.identity.revision == evidence.definition_revision
            and item.sha256 == evidence.definition_sha256
        )
        if catalog is not None
        else ()
    )
    context = entries[0].account_context if len(entries) == 1 else None
    institution = context.institution_key if context is not None else ""
    kind = context.kind if context is not None else None
    if not isinstance(payload, StatementPayload) and context is not None and evidence.parser_id in LOAN_PARSERS:
        if kind == "liability":
            scope = "principal_component"
    full_number = (
        source_identity
        if source_form == "full"
        and source_identity is not None
        and len(source_identity) <= 80
        and re.search(r"[*xX•●#…]", source_identity) is None
        else None
    )
    label = {"mohela": "MOHELA", "capital_one": "Capital One", "healthequity": "HealthEquity"}.get(
        institution, institution.replace("_", " ").title()
    )
    name = f"{label or 'Account'} {source_identity}" if source_identity is not None else label
    return AccountCreationDraft(
        name=name[:200],
        institution_key=institution,
        kind=kind,
        tracking_scope=scope,
        full_account_number=full_number,
        source_identity=source_identity,
        source_form=source_form,
        verified_context=context is not None,
    )
