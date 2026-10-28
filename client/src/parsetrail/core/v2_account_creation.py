"""Editable account drafts from exact saved evidence; no binding or posting policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from parsetrail.core.source_evidence import (
    DateValue,
    MoneyValue,
    SourceEvidence,
    SourceLocation,
    StatementPayload,
    TextValue,
)
from parsetrail.core.v2_data_catalog import VerifiedCatalog
from parsetrail.core.v2_loan_payments import LOAN_PARSERS


@dataclass(frozen=True)
class AccountCreationDraft:
    """Editable metadata beside immutable document context, never book balances.

    Product labels remain unavailable when the saved evidence omits them.
    Source locations identify the selected section or first matching export row.
    """

    name: str = ""
    institution_key: str = ""
    kind: Literal["asset", "liability"] | None = None
    tracking_scope: Literal["account_total", "principal_component", "cash_component"] | None = None
    full_account_number: str | None = None
    source_identity: str | None = None
    source_form: str | None = None
    verified_context: bool = False
    source_sha256: str | None = None
    source_locations: tuple[SourceLocation, ...] = ()
    product_label: TextValue | None = None
    period_start: DateValue | None = None
    period_end: DateValue | None = None
    opening_balance: MoneyValue | None = None
    closing_balance: MoneyValue | None = None


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
    section = None
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
            if len(sections) == 1:
                section = sections[0]
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
    # This is an editable label, never an identifier or matching key. Do not
    # concatenate digits separated by masking or other source characters.
    visible_runs = re.findall(r"[0-9]+", source_identity or "")
    visible_tail = visible_runs[-1][-4:] if visible_runs else ""
    name = " ".join(part for part in (label or ("Account" if visible_tail else ""), visible_tail) if part)
    if section is not None:
        locations = section.identity_locations
    elif not isinstance(payload, StatementPayload):
        locations = next(
            (
                tuple(fragment.location for fragment in row.fragments)
                for row in payload.rows
                if (row.source_account, row.source_account_form) == (source_identity, source_form)
            ),
            (),
        )
    else:
        locations = ()
    return AccountCreationDraft(
        name=name[:200],
        institution_key=institution,
        kind=kind,
        tracking_scope=scope,
        full_account_number=full_number,
        source_identity=source_identity,
        source_form=source_form,
        verified_context=context is not None,
        source_sha256=evidence.source_sha256,
        source_locations=locations,
        period_start=payload.start if isinstance(payload, StatementPayload) else payload.activity_start,
        period_end=payload.end if isinstance(payload, StatementPayload) else payload.activity_end,
        opening_balance=section.opening if section is not None else None,
        closing_balance=section.closing if section is not None else None,
    )
