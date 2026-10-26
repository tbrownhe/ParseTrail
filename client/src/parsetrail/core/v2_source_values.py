"""Finite statement-closing interpretations; these facts never post journals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Literal, TypeVar

from pydantic import Field

from parsetrail.core.source_evidence import (
    DateValue,
    EvidenceModel,
    MoneyValue,
    SourceEvidence,
    StatementAccount,
    StatementPayload,
)


@dataclass(frozen=True)
class SourceValueRule:
    financial_kind: Literal["asset", "liability"]
    tracking_scope: Literal["account_total", "principal_component", "cash_component"]
    sign_rule: Literal["debit-signed-1", "positive-owed-negate-1"] = "debit-signed-1"


SOURCE_VALUE_RULES = {
    **{
        parser: SourceValueRule("asset", "account_total")
        for parser in (
            "happen_savings_line_pilot",
            "lendingclub_savings_line_pilot",
            "pdf_lendingclublus_202506",
            "pdf_occubank_201409",
            "pdf_wfbankper_202105",
            "wells_business_table_pilot",
            "pdf_fidelityhsa_202001",
            "pdf_fidelity401k_201810",
            "pdf_vanguard_202210",
            "pdf_transamerica_202104",
        )
    },
    **{
        parser: SourceValueRule("liability", "account_total")
        for parser in (
            "chase_card_line_pilot",
            "pdf_citicc_201505",
            "pdf_citicc_202506",
            "pdf_citicc_202511",
            "pdf_occucc_201904",
            "pdf_usbankreicc_201405",
            "synchrony_amazon_store_card",
            "pdf_yamahafin_202306",
        )
    },
    "hsa_cash_line_pilot": SourceValueRule("asset", "cash_component"),
    "pdf_capitaloneauto_202402": SourceValueRule("liability", "principal_component", "positive-owed-negate-1"),
    "pdf_wfloanper_202306": SourceValueRule("liability", "principal_component"),
}

ValueT = TypeVar("ValueT")


def dated_value_conflicts(
    values: tuple[ValueT, ...], *, value_date: date, amount_minor: int, corrects_value_id: int | None = None
) -> tuple[ValueT, ...]:
    """Find contrary current claims at a selected date; never choose by ID."""
    return tuple(
        item
        for item in values
        if item.state == "active"
        and item.value_id != corrects_value_id
        and item.value_date == value_date
        and item.amount_minor != amount_minor
    )


class SourceValueReviewAnnotation(EvidenceModel):
    revision_id: int = Field(gt=0)
    opening_origin: Literal["reported", "unestablished"]
    closing_origin: Literal["reported", "unestablished"]
    timing_confirmed: bool
    posting_dates: Literal["reported", "estimated", "unverified"]
    source_reference: str = Field(min_length=1, max_length=500)
    note: str = Field(max_length=500)
    source_identity: str = Field(min_length=1, max_length=4096)
    source_identity_form: Literal["full", "last_four", "opaque"]


class SourceValueProof(EvidenceModel):
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str = Field(min_length=1, max_length=80)
    definition_revision: str = Field(min_length=1, max_length=80)
    source_identity: str = Field(min_length=1, max_length=4096)
    source_identity_form: Literal["full", "last_four", "opaque"]
    financial_kind: Literal["asset", "liability"]
    tracking_scope: Literal["account_total", "principal_component", "cash_component"]
    sign_rule: Literal["debit-signed-1", "positive-owed-negate-1"]
    closing: MoneyValue
    value_date: DateValue
    review_annotation: SourceValueReviewAnnotation | None = None

    @property
    def amount_minor(self) -> int:
        return self.closing.minor * (-1 if self.sign_rule == "positive-owed-negate-1" else 1)


def source_value_candidate_id(source_sha256: str, section: StatementAccount) -> str:
    return hashlib.sha256(
        json.dumps(
            (source_sha256, section.source_identity, section.source_identity_form), separators=(",", ":")
        ).encode()
    ).hexdigest()


def make_source_value_proof(
    evidence: SourceEvidence,
    section: StatementAccount,
    *,
    financial_kind: str,
    tracking_scope: str,
    evidence_sha256: str,
    review_annotation: SourceValueReviewAnnotation | None = None,
) -> SourceValueProof:
    rule = SOURCE_VALUE_RULES.get(evidence.parser_id)
    if not isinstance(evidence.payload, StatementPayload) or rule is None:
        raise ValueError("source_value_family_unsupported")
    if (
        section.balance_scope != rule.tracking_scope
        or tracking_scope != rule.tracking_scope
        or financial_kind != rule.financial_kind
    ):
        raise ValueError("source_value_scope_or_kind_mismatch")
    if review_annotation is not None and (
        review_annotation.source_identity,
        review_annotation.source_identity_form,
    ) != (section.source_identity, section.source_identity_form):
        raise ValueError("source_value_review_section_mismatch")
    closing, endpoint = section.closing, evidence.payload.end
    if (
        closing is None
        or closing.minor is None
        or closing.provenance not in {"observed", "derived"}
        or not closing.locations
    ):
        raise ValueError("source_value_closing_unavailable")
    if endpoint.iso is None or endpoint.provenance not in {"observed", "derived"} or not endpoint.locations:
        raise ValueError("source_value_date_unavailable")
    return SourceValueProof(
        source_sha256=evidence.source_sha256,
        evidence_sha256=evidence_sha256,
        definition_sha256=evidence.definition_sha256,
        parser_id=evidence.parser_id,
        definition_revision=evidence.definition_revision,
        source_identity=section.source_identity,
        source_identity_form=section.source_identity_form,
        financial_kind=rule.financial_kind,
        tracking_scope=rule.tracking_scope,
        sign_rule=rule.sign_rule,
        closing=closing,
        value_date=endpoint,
        review_annotation=review_annotation,
    )


def proof_payload(proof: SourceValueProof) -> str:
    return json.dumps(proof.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def decode_source_value_proof(payload: str) -> SourceValueProof:
    if type(payload) is not str or len(payload) > 256 * 1024:
        raise ValueError("source_value_proof_invalid")
    try:
        return SourceValueProof.model_validate_json(payload)
    except RecursionError:
        raise ValueError("source_value_proof_invalid") from None
