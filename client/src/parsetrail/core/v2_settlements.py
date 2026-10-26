"""Finite reviewed transfer manifests and exact source-dated journal shapes."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from parsetrail.core.ledger import Allocation, JournalEntry, Posting

MAX_SETTLEMENT_PAYLOAD = 2 * 1024 * 1024


@dataclass(frozen=True)
class TransferMovement:
    row_id: str
    source_sha256: str
    account_id: str
    account_name: str
    account_kind: Literal["asset", "liability"]
    posting_date: str
    date_provenance: str
    date_allowed: bool
    amount_minor: int
    description: str
    tracking_scope: str = "account_total"
    source_description_known: bool = True


@dataclass(frozen=True)
class ExpectedOwnedDestination:
    account_id: str
    reference: str
    ownership_confirmed: bool
    account_name: str = ""
    account_kind: Literal["asset", "liability"] | None = None
    tracking_scope: str | None = None

    @property
    def request_key(self) -> tuple:
        return self.account_id, self.reference, self.ownership_confirmed


@dataclass(frozen=True)
class SettlementFee:
    source_row_id: str
    category_id: str
    amount_minor: int
    reference: str
    reason: str


@dataclass(frozen=True)
class TransferSettlement:
    outgoing: TransferMovement
    incoming: tuple[TransferMovement, ...]
    fees: tuple[SettlementFee, ...] = ()
    expected_destination: ExpectedOwnedDestination | None = None

    @property
    def movements(self) -> tuple[TransferMovement, ...]:
        return (self.outgoing, *self.incoming)

    @property
    def row_ids(self) -> tuple[str, ...]:
        return tuple(m.row_id for m in self.movements)

    def fees_for(self, row_id: str) -> tuple[SettlementFee, ...]:
        return tuple(fee for fee in self.fees if fee.source_row_id == row_id)

    @property
    def outgoing_fee_minor(self) -> int:
        return sum(f.amount_minor for f in self.fees_for(self.outgoing.row_id))

    @property
    def sent_principal_minor(self) -> int:
        return -self.outgoing.amount_minor - self.outgoing_fee_minor

    @property
    def received_gross_minor(self) -> int:
        return sum(m.amount_minor + sum(f.amount_minor for f in self.fees_for(m.row_id)) for m in self.incoming)

    @property
    def residual_minor(self) -> int:
        return self.sent_principal_minor - self.received_gross_minor

    @property
    def kind(self) -> str:
        if not self.incoming:
            return "owned outflow awaiting receipt"
        kinds = {m.account_kind for m in self.incoming}
        return (
            "card payment" if kinds == {"liability"} else "asset transfer" if kinds == {"asset"} else "mixed settlement"
        )


@dataclass(frozen=True)
class SettlementPreview:
    settlement: TransferSettlement
    entries: tuple[JournalEntry, ...]


def validate_movement(movement: TransferMovement) -> None:
    if not isinstance(movement, TransferMovement) or (
        any(
            type(value) is not str or not value
            for value in (
                movement.row_id,
                movement.source_sha256,
                movement.account_id,
                movement.account_name,
                movement.posting_date,
                movement.description,
            )
        )
        or re.fullmatch(r"[0-9a-f]{64}", movement.source_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", movement.row_id) is None
        or len(movement.account_id) > 80
        or len(movement.account_name) > 200
        or len(movement.description) > 4096
        or movement.account_kind not in {"asset", "liability"}
        or type(movement.amount_minor) is not int
        or not -(2**63) < movement.amount_minor < 2**63
        or movement.amount_minor == 0
        or movement.date_provenance not in {"observed", "derived", "assumed"}
        or type(movement.date_allowed) is not bool
        or (not movement.date_allowed and movement.date_provenance != "assumed")
        or movement.tracking_scope not in {"account_total", "cash_component", "principal_component"}
        or type(movement.source_description_known) is not bool
    ):
        raise ValueError("settlement_movement_invalid")
    if date.fromisoformat(movement.posting_date).isoformat() != movement.posting_date:
        raise ValueError("settlement_movement_invalid")


def fee_order(fee: SettlementFee) -> tuple:
    return (fee.source_row_id, fee.category_id, fee.amount_minor, fee.reference, fee.reason)


def validate_settlement(settlement: TransferSettlement) -> None:
    if (
        not isinstance(settlement, TransferSettlement)
        or type(settlement.incoming) is not tuple
        or type(settlement.fees) is not tuple
    ):
        raise ValueError("settlement_manifest_invalid")
    if not 0 <= len(settlement.incoming) <= 32 or len(settlement.fees) > 64:
        raise ValueError("settlement_manifest_limits")
    for movement in settlement.movements:
        validate_movement(movement)
    destination = settlement.expected_destination
    if not settlement.incoming:
        if not isinstance(destination, ExpectedOwnedDestination) or (
            type(destination.account_id) is not str
            or not 0 < len(destination.account_id) <= 80
            or destination.account_id == settlement.outgoing.account_id
            or type(destination.reference) is not str
            or not 0 < len(destination.reference.strip()) <= 500
            or destination.reference != destination.reference.strip()
            or destination.ownership_confirmed is not True
            or type(destination.account_name) is not str
            or not 0 < len(destination.account_name) <= 200
            or destination.account_kind not in {"asset", "liability"}
            or destination.tracking_scope not in {"account_total", "cash_component", "principal_component"}
            or (destination.tracking_scope == "cash_component" and destination.account_kind != "asset")
            or (destination.tracking_scope == "principal_component" and destination.account_kind != "liability")
        ):
            raise ValueError("settlement_expected_destination_required")
    elif destination is not None:
        raise ValueError("settlement_expected_destination_requires_missing_receipts")
    if (
        settlement.outgoing.account_kind != "asset"
        or settlement.outgoing.amount_minor >= 0
        or any(m.amount_minor <= 0 or m.account_id == settlement.outgoing.account_id for m in settlement.incoming)
        or len(set(settlement.row_ids)) != len(settlement.row_ids)
        or tuple(sorted(settlement.incoming, key=lambda m: m.row_id)) != settlement.incoming
    ):
        raise ValueError("settlement_manifest_invalid")
    for fee in settlement.fees:
        if not isinstance(fee, SettlementFee) or (
            fee.source_row_id not in settlement.row_ids
            or type(fee.category_id) is not str
            or not 0 < len(fee.category_id) <= 80
            or type(fee.amount_minor) is not int
            or not 0 < fee.amount_minor < 2**63
            or type(fee.reference) is not str
            or not 0 < len(fee.reference.strip()) <= 500
            or type(fee.reason) is not str
            or not 0 < len(fee.reason.strip()) <= 500
            or fee.reference != fee.reference.strip()
            or fee.reason != fee.reason.strip()
        ):
            raise ValueError("settlement_fee_invalid")
    if tuple(sorted(settlement.fees, key=fee_order)) != settlement.fees or len(set(settlement.fees)) != len(
        settlement.fees
    ):
        raise ValueError("settlement_fee_invalid")
    if not 0 < settlement.sent_principal_minor < 2**63 or not 0 <= settlement.residual_minor < 2**63:
        raise ValueError("settlement_overallocated")


def settlement_payload(settlement: TransferSettlement) -> str:
    validate_settlement(settlement)
    return json.dumps({"format": "settlement-2", **asdict(settlement)}, sort_keys=True, separators=(",", ":"))


def decode_settlement(payload: str) -> TransferSettlement:
    if type(payload) is not str or len(payload) > MAX_SETTLEMENT_PAYLOAD:
        raise ValueError("settlement_manifest_limits")
    try:
        data = json.loads(payload)
    except RecursionError:
        raise ValueError("settlement_manifest_invalid") from None
    if (
        type(data) is not dict
        or set(data) != {"format", "outgoing", "incoming", "fees", "expected_destination"}
        or data["format"] != "settlement-2"
    ):
        raise ValueError("settlement_manifest_invalid")
    if (
        type(data["incoming"]) is not list
        or type(data["fees"]) is not list
        or not 0 <= len(data["incoming"]) <= 32
        or len(data["fees"]) > 64
    ):
        raise ValueError("settlement_manifest_invalid")
    settlement = TransferSettlement(
        TransferMovement(**data["outgoing"]),
        tuple(TransferMovement(**m) for m in data["incoming"]),
        tuple(SettlementFee(**f) for f in data["fees"]),
        ExpectedOwnedDestination(**data["expected_destination"]) if data["expected_destination"] is not None else None,
    )
    validate_settlement(settlement)
    return settlement


def settlement_entries(settlement: TransferSettlement, event_id: str, reason: str) -> tuple[JournalEntry, ...]:
    validate_settlement(settlement)
    clearing = "internal:transfer-clearing:USD"
    entries = []
    for index, movement in enumerate(settlement.movements):
        outgoing = index == 0
        fee_postings = tuple(Posting(f.category_id, f.amount_minor) for f in settlement.fees_for(movement.row_id))
        clearing_amount = (
            settlement.sent_principal_minor
            if outgoing
            else -(movement.amount_minor + sum(p.amount_minor for p in fee_postings))
        )
        entries.append(
            JournalEntry(
                event_id + (":out" if outgoing else f":in:{index}"),
                event_id,
                date.fromisoformat(movement.posting_date),
                "Transfer settlement sent" if outgoing else "Transfer settlement received",
                (
                    Posting(
                        movement.account_id,
                        movement.amount_minor,
                        (Allocation(movement.row_id, movement.amount_minor),),
                    ),
                    *fee_postings,
                    Posting(clearing, clearing_amount),
                ),
                reviewed=True,
                reason=reason,
            )
        )
    return tuple(entries)
