"""Finite printed loan-component proofs; raw source use is not principal allocation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from parsetrail.core.ledger import AccountKind, Allocation, JournalEntry, LedgerAccount, Posting
from parsetrail.core.source_evidence import ObservationEvidence
from parsetrail.core.v2_settlements import TransferMovement, validate_movement

LOAN_RULE = "v2-loan-payment-1"
CLEARING = "internal:transfer-clearing:USD"
INTEREST = "builtin:loan-interest"
LOAN_PARSERS = frozenset(
    {"pdf_capitaloneauto_202402", "mohela_account_history_export", "mohela_detailed_export", "pdf_wfloanper_202306"}
)
MAX_LOAN_PAYLOAD = 2 * 1024 * 1024


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class LoanComponentProof:
    row_id: str
    source_sha256: str
    parser_id: str
    account_id: str
    account_name: str
    activity_date: str
    effective_date: str
    raw_amount_minor: int
    raw_principal_minor: int | None
    raw_interest_minor: int | None
    raw_fee_minor: int | None
    row_evidence: str
    tracking_scope: str = "principal_component"
    date_provenance: str = "assumed"
    account_kind: str = "liability"

    @property
    def sign_factor(self) -> int:
        return 1 if self.parser_id == "pdf_wfloanper_202306" else -1

    @property
    def principal_minor(self) -> int:
        return (self.raw_principal_minor or 0) * self.sign_factor

    @property
    def interest_minor(self) -> int:
        return (self.raw_interest_minor or 0) * self.sign_factor

    @property
    def gross_minor(self) -> int:
        return self.raw_amount_minor * self.sign_factor


def validate_component(proof: LoanComponentProof) -> ObservationEvidence:
    if type(proof) is not LoanComponentProof or any(
        type(v) is not str or not v
        for v in (
            proof.row_id,
            proof.source_sha256,
            proof.parser_id,
            proof.account_id,
            proof.account_name,
            proof.activity_date,
            proof.effective_date,
            proof.row_evidence,
        )
    ):
        raise ValueError("loan_component_invalid")
    if (
        proof.parser_id not in LOAN_PARSERS
        or proof.account_kind != "liability"
        or proof.tracking_scope != "principal_component"
        or proof.date_provenance != "assumed"
        or len(proof.row_evidence) > 128 * 1024
        or len(proof.account_id) > 80
        or len(proof.account_name) > 200
        or len(proof.source_sha256) != 64
        or any(c not in "0123456789abcdef" for c in proof.source_sha256)
    ):
        raise ValueError("loan_component_invalid")
    if (
        date.fromisoformat(proof.activity_date).isoformat() != proof.activity_date
        or proof.effective_date != proof.activity_date
    ):
        raise ValueError("loan_component_date_invalid")
    row = ObservationEvidence.model_validate_json(proof.row_evidence)
    parts = {part.role: part.amount.minor for part in row.components}
    if (
        row.row_id != proof.row_id
        or row.row_role != "activity"
        or row.date_role != "activity_date"
        or row.date.provenance != "observed"
        or row.date.iso != proof.activity_date
        or row.amount.provenance != "observed"
        or row.amount.minor != proof.raw_amount_minor
        or any(part.amount.provenance != "observed" for part in row.components)
        or parts
        != {
            k: v
            for k, v in (
                ("principal", proof.raw_principal_minor),
                ("interest", proof.raw_interest_minor),
                ("fee", proof.raw_fee_minor),
            )
            if v is not None
        }
    ):
        raise ValueError("loan_component_evidence_mismatch")
    if (
        any(
            v is not None and (type(v) is not int or not -(2**63) < v < 2**63)
            for v in (proof.raw_principal_minor, proof.raw_interest_minor, proof.raw_fee_minor)
        )
        or type(proof.raw_amount_minor) is not int
        or not 0 < proof.gross_minor < 2**63
    ):
        raise ValueError("loan_component_amount_invalid")
    if proof.parser_id == "pdf_wfloanper_202306":
        if set(parts) not in ({"principal"}, {"interest"}) or row.description.text != (
            "PRINCIPAL PAYMENT" if "principal" in parts else "INTEREST PAYMENT"
        ):
            raise ValueError("loan_component_unsupported")
    elif proof.parser_id == "pdf_capitaloneauto_202402":
        if set(parts) != {"principal", "interest"} or (row.description.text or "").casefold() != "payment received":
            raise ValueError("loan_component_unsupported")
    elif set(parts) != {"principal", "interest", "fee"} or (row.description.text or "").casefold() != "payment":
        raise ValueError("loan_component_unsupported")
    if (
        proof.raw_fee_minor not in {None, 0}
        or proof.principal_minor < 0
        or proof.interest_minor < 0
        or proof.principal_minor + proof.interest_minor != proof.gross_minor
    ):
        raise ValueError("loan_component_unsupported")
    return row


def component_proof(
    row: ObservationEvidence, *, source_sha256: str, parser_id: str, account_id: str, account_name: str
) -> LoanComponentProof:
    parts = {part.role: part.amount.minor for part in row.components}
    proof = LoanComponentProof(
        row.row_id,
        source_sha256,
        parser_id,
        account_id,
        account_name,
        row.date.iso,
        row.date.iso,
        row.amount.minor,
        parts.get("principal"),
        parts.get("interest"),
        parts.get("fee"),
        row.model_dump_json(),
    )
    validate_component(proof)
    return proof


def principal_id(event_id: str, row_id: str) -> str:
    return "loan-principal:" + digest((event_id, row_id))


def component_entry(proof: LoanComponentProof, event_id: str, reason: str) -> JournalEntry:
    validate_component(proof)
    postings = ()
    if proof.principal_minor:
        postings += (
            Posting(
                proof.account_id,
                proof.principal_minor,
                (Allocation(principal_id(event_id, proof.row_id), proof.principal_minor),),
            ),
        )
    if proof.interest_minor:
        postings += (Posting(INTEREST, proof.interest_minor),)
    postings += (Posting(CLEARING, -proof.gross_minor),)
    return JournalEntry(
        event_id + ":loan:" + proof.row_id,
        event_id,
        date.fromisoformat(proof.effective_date),
        "Reviewed loan payment components",
        postings,
        reviewed=True,
        reason=reason,
    )


def validate_component_postings(
    proof: LoanComponentProof, entry: JournalEntry, accounts: dict[str, LedgerAccount]
) -> None:
    validate_component(proof)
    if entry != component_entry(proof, entry.event_id, entry.reason) or not entry.reason.strip():
        raise ValueError("loan_component_entry_mismatch")
    loan = accounts.get(proof.account_id)
    clearing = accounts.get(CLEARING)
    interest = accounts.get(INTEREST)
    if (
        loan is None
        or loan.kind != AccountKind.LIABILITY
        or loan.source_account_id is None
        or clearing is None
        or clearing.kind != AccountKind.ASSET
        or clearing.purpose != "clearing"
        or clearing.source_account_id is not None
        or (
            proof.interest_minor
            and (interest is None or interest.kind != AccountKind.EXPENSE or interest.source_account_id is not None)
        )
    ):
        raise ValueError("loan_component_account_invalid")


@dataclass(frozen=True)
class LoanPaymentManifest:
    bank: TransferMovement
    components: tuple[LoanComponentProof, ...]

    @property
    def row_ids(self) -> tuple[str, ...]:
        return (self.bank.row_id, *(p.row_id for p in self.components))

    @property
    def principal_minor(self) -> int:
        return sum(p.principal_minor for p in self.components)

    @property
    def interest_minor(self) -> int:
        return sum(p.interest_minor for p in self.components)


def validate_manifest(manifest: LoanPaymentManifest) -> None:
    if (
        type(manifest) is not LoanPaymentManifest
        or type(manifest.components) is not tuple
        or not 1 <= len(manifest.components) <= 32
    ):
        raise ValueError("loan_manifest_invalid")
    validate_movement(manifest.bank)
    for proof in manifest.components:
        validate_component(proof)
    if (
        manifest.bank.account_kind != "asset"
        or manifest.bank.amount_minor >= 0
        or manifest.bank.tracking_scope not in {"account_total", "cash_component"}
        or len(set(manifest.row_ids)) != len(manifest.row_ids)
        or tuple(sorted(manifest.components, key=lambda p: p.row_id)) != manifest.components
        or len({(p.account_id, p.source_sha256, p.parser_id) for p in manifest.components}) != 1
        or manifest.bank.account_id == manifest.components[0].account_id
        or sum(p.gross_minor for p in manifest.components) != -manifest.bank.amount_minor
    ):
        raise ValueError("loan_manifest_invalid")
    if len(manifest.components) > 1 and manifest.components[0].parser_id != "pdf_wfloanper_202306":
        raise ValueError("loan_manifest_requires_one_payment")


def manifest_payload(manifest: LoanPaymentManifest) -> str:
    validate_manifest(manifest)
    payload = json.dumps({"rule": LOAN_RULE, **asdict(manifest)}, sort_keys=True, separators=(",", ":"))
    if len(payload) > MAX_LOAN_PAYLOAD:
        raise ValueError("loan_manifest_invalid")
    return payload


def decode_manifest(payload: str) -> LoanPaymentManifest:
    if type(payload) is not str or not 0 < len(payload) <= MAX_LOAN_PAYLOAD:
        raise ValueError("loan_manifest_invalid")
    try:
        data = json.loads(payload)
        if (
            type(data) is not dict
            or set(data) != {"rule", "bank", "components"}
            or data["rule"] != LOAN_RULE
            or type(data["components"]) is not list
            or not 1 <= len(data["components"]) <= 32
        ):
            raise ValueError
        result = LoanPaymentManifest(
            TransferMovement(**data["bank"]), tuple(LoanComponentProof(**p) for p in data["components"])
        )
        validate_manifest(result)
        return result
    except (TypeError, KeyError, RecursionError):
        raise ValueError("loan_manifest_invalid") from None


def payment_entries(manifest: LoanPaymentManifest, event_id: str, reason: str) -> tuple[JournalEntry, ...]:
    validate_manifest(manifest)
    bank = manifest.bank
    return (
        JournalEntry(
            event_id + ":bank",
            event_id,
            date.fromisoformat(bank.posting_date),
            "Reviewed loan payment cash outflow",
            (
                Posting(bank.account_id, bank.amount_minor, (Allocation(bank.row_id, bank.amount_minor),)),
                Posting(CLEARING, -bank.amount_minor),
            ),
            reviewed=True,
            reason=reason,
        ),
        *(component_entry(p, event_id, reason) for p in manifest.components),
    )


@dataclass(frozen=True)
class LoanComponentReviewRow:
    row_id: str
    source_sha256: str
    description: str | None
    amount_minor: int
    proof: LoanComponentProof | None
    eligible: bool
    blockers: tuple[str, ...]
    activity_date: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    tracking_scope: str | None = None
    row_evidence: str = ""


@dataclass(frozen=True)
class LoanEvent:
    event_id: str
    manifest: LoanPaymentManifest
    entry_keys: tuple[str, ...]
    reference: str
    reason: str
    created_at: str
    version: str
    status: Literal["active", "cancelled", "replaced"] = "active"
    replacement_event_id: str | None = None


@dataclass(frozen=True)
class LoanEventAction:
    action_id: int
    event_id: str
    expected_event_version: str
    reason: str
    replacement_event_id: str | None
    created_at: str


@dataclass(frozen=True)
class LoanPaymentPreview:
    manifest: LoanPaymentManifest
    entries: tuple[JournalEntry, ...]
    basis_sha256: str


@dataclass(frozen=True)
class LoanReviewSnapshot:
    bank_movements: tuple[TransferMovement, ...]
    components: tuple[LoanComponentReviewRow, ...]
    history: tuple[LoanEvent, ...]
    basis_sha256: str
    actions: tuple[LoanEventAction, ...] = ()
    accounts: tuple = ()


@dataclass(frozen=True)
class LoanSourceLink:
    event_id: str
    entry_key: str
    row_id: str
    source_sha256: str
    account_id: str
    activity_date: str
    effective_date: str
    date_provenance: str
    raw_amount_minor: int
    derived_observation_id: str | None
    principal_minor: int
    interest_minor: int
    active: bool
    proof: LoanComponentProof
