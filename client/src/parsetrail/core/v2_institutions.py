"""Managed institution identities, independent of supported document formats."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from parsetrail.core.v2_data_catalog import VerifiedCatalog


@dataclass(frozen=True)
class Institution:
    """A stable internal identity and a human-facing name, not a parser claim."""

    id: str
    name: str


BUILTIN_INSTITUTIONS = (
    Institution("capital_one", "Capital One"),
    Institution("chase", "Chase"),
    Institution("citi", "Citi"),
    Institution("fidelity", "Fidelity"),
    Institution("happen", "Happen Bank"),
    Institution("healthequity", "HealthEquity"),
    Institution("lendingclub", "LendingClub"),
    Institution("mohela", "MOHELA"),
    Institution("occu", "Oregon Community Credit Union"),
    Institution("synchrony", "Synchrony"),
    Institution("transamerica", "Transamerica"),
    Institution("usbank", "U.S. Bank"),
    Institution("vanguard", "Vanguard"),
    Institution("wellsfargo", "Wells Fargo"),
    Institution("yamaha", "Yamaha Financial Services"),
)
_BUILTINS = {institution.id: institution for institution in BUILTIN_INSTITUTIONS}
_RESERVED_NAMES = {
    "unknown",
    "not identified",
    "institution not identified",
    "choose an institution…",
    "choose an institution...",
}


def validate_institution(institution: Institution) -> Institution:
    """Validate a deliberate managed record; never invent an unknown identity."""
    if (
        not isinstance(institution, Institution)
        or type(institution.id) is not str
        or re.fullmatch(r"[a-z][a-z0-9_-]{2,79}", institution.id) is None
        or type(institution.name) is not str
        or not 0 < len(institution.name.strip()) <= 200
        or institution.name != institution.name.strip()
        or any(ord(character) < 32 for character in institution.name)
        or " ".join(institution.name.split()).casefold() in _RESERVED_NAMES
    ):
        raise ValueError("institution_invalid")
    builtin = _BUILTINS.get(institution.id)
    if builtin is not None and institution != builtin:
        raise ValueError("institution_identity_conflict")
    return institution


def merge_institutions(*collections: Iterable[Institution]) -> tuple[Institution, ...]:
    """Merge exact records while refusing ambiguous user-facing identities.

    Neither a shared name nor similar spelling merges different stable IDs.
    Whitespace and case differences cannot make two institution choices appear
    distinguishable when they denote different matching identities.
    """
    by_id = {}
    by_name = {}
    for collection in collections:
        for institution in collection:
            validate_institution(institution)
            previous = by_id.get(institution.id)
            if previous is not None and previous != institution:
                raise ValueError("institution_identity_conflict")
            name_key = " ".join(institution.name.split()).casefold()
            named_id = by_name.get(name_key)
            if named_id is not None and named_id != institution.id:
                raise ValueError("institution_name_conflict")
            by_id[institution.id] = institution
            by_name[name_key] = institution.id
    return tuple(sorted(by_id.values(), key=lambda item: (item.name.casefold(), item.id)))


def institution_label(key: str | None, institutions: Iterable[Institution] = ()) -> str:
    """Resolve display names; an unidentified account has no matching key."""
    if key is None:
        return "Institution not identified"
    builtin = _BUILTINS.get(key)
    if builtin is not None:
        return builtin.name
    for institution in institutions:
        if institution.id == key:
            return institution.name
    # Defensive display fallback for a detached read model. Account writes still
    # require the managed profile registry and never admit this fallback as ID.
    return key.replace("_", " ").replace("-", " ").title()


def catalog_institutions(catalog: VerifiedCatalog) -> tuple[Institution, ...]:
    """Expose only contexts of an already authenticated/admitted catalog."""
    if not isinstance(catalog, VerifiedCatalog):
        raise ValueError("institution_catalog_invalid")
    institutions = {}
    for definition in catalog.definitions:
        context = definition.account_context
        keys = {
            profile.institution_key for profile in definition.account_profiles if profile.institution_key is not None
        }
        if context is not None:
            keys.add(context.institution_key)
        for key in keys:
            institution = _BUILTINS.get(key) or Institution(key, institution_label(key))
            validate_institution(institution)
            previous = institutions.get(key)
            if previous is not None and previous != institution:
                raise ValueError("institution_identity_conflict")
            institutions[key] = institution
    # A future catalog institution cannot impersonate another catalog identity
    # or a built-in through a visually identical name.
    merge_institutions(BUILTIN_INSTITUTIONS, institutions.values())
    return merge_institutions(institutions.values())
