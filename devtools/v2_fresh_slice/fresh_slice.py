"""Disposable fresh-profile CSV evidence-to-ledger review slice.

This deliberately has no 1.x database reader, migration, aliases or live-profile path.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from datetime import date
from pathlib import Path

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
)
from parsetrail.core.ledger_store import LedgerStore, encoded
from parsetrail.core.v2_parser_engine import (
    MAX_DEFINITION_BYTES,
    MAX_SOURCE_BYTES,
    Evidence,
    load_definition,
    parse_csv,
)
from pydantic import ValidationError

from devtools.v2_fresh_slice.stored_evidence import MAX_EVIDENCE_BYTES, StoredEvidenceV1

PROFILE_VERSION = 1
MANIFEST_KEYS = frozenset({"profile_version", "source_sha256", "definition_sha256", "evidence_sha256", "account_id"})


class FreshSliceError(ValueError):
    """Redacted refusal for an unsupported or changed disposable profile."""


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _evidence(source: bytes, definition: bytes) -> Evidence:
    declared, _ = load_definition(definition)
    if (
        declared.suffix != ".csv"
        or declared.date_role != "posting_date"
        or declared.account_key != "observed"
        or declared.columns.principal is not None
        or declared.columns.interest is not None
        or declared.columns.fees is not None
    ):
        raise FreshSliceError("unsupported_source_contract")
    evidence = parse_csv(definition, source)
    if len(evidence.account_identities) != 1:
        raise FreshSliceError("multiple_source_accounts")
    return evidence


def create_disposable_profile(
    output: Path,
    source: bytes,
    definition: bytes,
    *,
    account_id: str,
    account_name: str,
    expense_categories: tuple[tuple[str, str], ...],
) -> Path:
    """Create one new profile atomically; no existing profile is opened writable."""
    evidence = _evidence(source, definition)
    output = output.resolve()
    if output.exists() or not output.parent.is_dir():
        raise FreshSliceError("profile_target_exists_or_parent_missing")
    account = LedgerAccount(
        account_id, account_name, AccountKind.ASSET, source_account_id=evidence.account_identities[0]
    )
    categories = [LedgerAccount(cid, name, AccountKind.EXPENSE) for cid, name in expense_categories]
    if len({account_id, *(category.id for category in categories)}) != 1 + len(categories):
        raise FreshSliceError("duplicate_account_identity")
    observations = [
        Observation(row.row_id, account_id, row.total.normalized, date.fromisoformat(row.date.normalized))
        for row in evidence.rows
        if row.total.normalized != 0
    ]
    evidence_bytes = encoded(asdict(evidence)).encode()
    manifest = {
        "profile_version": PROFILE_VERSION,
        "source_sha256": _hash(source),
        "definition_sha256": _hash(definition),
        "evidence_sha256": _hash(evidence_bytes),
        "account_id": account_id,
    }
    with tempfile.TemporaryDirectory(prefix="parsetrail-v2-slice-", dir=output.parent) as staging_name:
        staging = Path(staging_name)
        (staging / "source.csv").write_bytes(source)
        (staging / "definition.json").write_bytes(definition)
        (staging / "evidence.json").write_bytes(evidence_bytes)
        with LedgerStore(staging / "ledger.db", create=True) as store:
            store.load_batch([account, *categories], observations, [], [])
        (staging / "manifest.json").write_text(encoded(manifest), encoding="utf-8")
        if output.exists():
            raise FreshSliceError("profile_target_exists_or_parent_missing")
        os.rename(staging, output)
    return output


def _open_verified(profile: Path) -> tuple[dict, StoredEvidenceV1]:
    try:
        profile = profile.resolve(strict=True)
        if (profile / "manifest.json").stat().st_size > 4096:
            raise FreshSliceError("profile_contents")
        manifest = json.loads((profile / "manifest.json").read_text(encoding="utf-8"))
        if (
            (profile / "source.csv").stat().st_size > MAX_SOURCE_BYTES
            or (profile / "definition.json").stat().st_size > MAX_DEFINITION_BYTES
            or (profile / "evidence.json").stat().st_size > MAX_EVIDENCE_BYTES
        ):
            raise FreshSliceError("profile_contents")
        source = (profile / "source.csv").read_bytes()
        definition = (profile / "definition.json").read_bytes()
        saved_evidence = (profile / "evidence.json").read_bytes()
    except (OSError, ValueError):
        raise FreshSliceError("profile_contents") from None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != MANIFEST_KEYS
        or type(manifest["profile_version"]) is not int
        or manifest["profile_version"] != PROFILE_VERSION
        or not isinstance(manifest["account_id"], str)
        or not manifest["account_id"]
    ):
        raise FreshSliceError("unsupported_profile_format")
    if any(
        manifest.get(key) != _hash(content)
        for key, content in (
            ("source_sha256", source),
            ("definition_sha256", definition),
            ("evidence_sha256", saved_evidence),
        )
    ):
        raise FreshSliceError("profile_hash_mismatch")
    try:
        evidence = StoredEvidenceV1.model_validate_json(saved_evidence)
    except ValidationError:
        raise FreshSliceError("invalid_saved_evidence") from None
    if evidence.source_sha256 != _hash(source) or evidence.definition_sha256 != _hash(definition):
        raise FreshSliceError("evidence_source_mismatch")
    return manifest, evidence


def review_items(profile: Path) -> tuple[dict, ...]:
    """List imported rows and their posting state without interpreting them."""
    manifest, evidence = _open_verified(profile)
    with LedgerStore(profile / "ledger.db", read_only=True) as store:
        if store.connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise FreshSliceError("ledger_integrity")
        observations, consumed = store.observations(), store.consumed()
        expected = {row.row_id for row in evidence.rows if row.total.normalized != 0}
        if set(observations) != expected:
            raise FreshSliceError("observation_inventory_changed")
        result = []
        for row in evidence.rows:
            amount = row.total.normalized
            observation = observations.get(row.row_id)
            if amount != 0 and (
                observation.account_id != manifest["account_id"]
                or observation.amount_minor != amount
                or observation.posting_date.isoformat() != row.date.normalized
            ):
                raise FreshSliceError("observation_changed")
            result.append(
                {
                    "row_id": row.row_id,
                    "posting_date": row.date.normalized,
                    "description": row.description.raw,
                    "amount_minor": amount,
                    "source_row": row.date.location.row,
                    "status": "zero_amount_evidence"
                    if amount == 0
                    else "reviewed"
                    if consumed.get(row.row_id) == amount
                    else "pending"
                    if consumed.get(row.row_id, 0) == 0
                    else "partially_allocated",
                }
            )
        return tuple(result)


def accept_expense(profile: Path, row_id: str, category_id: str, *, reason: str) -> str:
    """Post one explicit synthetic expense decision; never infer a category."""
    manifest, evidence = _open_verified(profile)
    rows = {row.row_id: row for row in evidence.rows}
    row = rows.get(row_id)
    if row is None or row.total.normalized >= 0 or not reason.strip():
        raise FreshSliceError("expense_review_requires_negative_row_and_reason")
    with LedgerStore(profile / "ledger.db") as store:
        category = store.accounts().get(category_id)
        if category is None or category.kind != AccountKind.EXPENSE:
            raise FreshSliceError("expense_category_required")
        amount = row.total.normalized
        entry = JournalEntry(
            key="review:" + row_id,
            event_id="event:" + row_id,
            posting_date=date.fromisoformat(row.date.normalized),
            description=row.description.raw,
            postings=(
                Posting(manifest["account_id"], amount, (Allocation(row_id, amount),)),
                Posting(category_id, -amount),
            ),
            reviewed=True,
            reason=reason.strip(),
        )
        try:
            return store.post(entry)
        except LedgerError:
            raise FreshSliceError("expense_review_refused") from None
