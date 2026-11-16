"""Finite reviewed vehicle acquisition and separate nonposting asset value estimates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from parsetrail.core.ledger import Allocation, JournalEntry, Observation, Posting, validate_entry
from parsetrail.core.v2_loan_payments import CLEARING, digest
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_resolution import error, now, reason_text
from parsetrail.core.v2_settlements import TransferMovement


@dataclass(frozen=True)
class TangibleAssetValue:
    revision_id: int
    account_id: str
    account_name: str
    value_date: date
    amount_minor: int
    estimated_minor: int | None
    as_of: date
    annual_rate_basis_points: int | None
    reason: str
    version: str


@dataclass(frozen=True)
class OriginationRow:
    row_id: str
    source_sha256: str
    account_id: str | None
    account_name: str | None
    activity_date: str | None
    principal_minor: int | None
    status: str
    blockers: tuple[str, ...]
    event_id: str | None = None


@dataclass(frozen=True)
class OriginationSnapshot:
    rows: tuple[OriginationRow, ...]
    basis_sha256: str
    events: tuple
    bank_movements: tuple = ()


@dataclass(frozen=True)
class OriginationPreview:
    row_id: str
    source_sha256: str
    account_id: str
    destination_account_id: str
    acquisition_value_minor: int
    acquisition_date: date
    bank_downpayment_row_id: str | None
    principal_minor: int
    entries: tuple[JournalEntry, ...]
    reason: str
    basis_sha256: str
    preferences: object
    proof: str
    preview_sha256: str
    profile_sha256: str


@dataclass(frozen=True)
class OriginationEvent:
    event_id: str
    row_id: str
    source_sha256: str
    account_id: str
    destination_account_id: str
    acquisition_value_minor: int
    acquisition_date: date
    principal_minor: int
    entry_keys: tuple[str, ...]
    reason: str
    version: str
    status: str
    bank_downpayment_row_id: str | None = None


def _vehicle(store, account_id):
    account = store.connection.execute(
        "SELECT name,kind,role,tracking_scope,product_type FROM Accounts WHERE id=?", (account_id,)
    ).fetchone()
    if account is None or account[1:] != ("asset", "financial", "account_total", "vehicle"):
        raise error("origination_vehicle_destination_required")
    return account[0]


def _value_request(store, account_id, value_date, amount_minor, annual_rate_basis_points, reason):
    reason = reason_text(reason)
    _vehicle(store, account_id)
    if (
        type(value_date) is not date
        or type(amount_minor) is not int
        or not 0 <= amount_minor < 2**63
        or (
            annual_rate_basis_points is not None
            and (type(annual_rate_basis_points) is not int or not 0 <= annual_rate_basis_points <= 10000)
        )
    ):
        raise error("tangible_asset_value_invalid")
    return reason


def value_history(store):
    result = []
    for saved in store.connection.execute("SELECT * FROM TangibleAssetValues ORDER BY revision_id"):
        number, account, day, amount, rate, reason, checksum, created = saved
        try:
            point_date = date.fromisoformat(day)
            _value_request(store, account, point_date, amount, rate, reason)
            if type(number) is not int or number <= 0 or checksum != digest([*saved[:-2], created]):
                raise ValueError
        except (ValueError, TypeError):
            raise error("tangible_asset_value_integrity") from None
        result.append(saved)
    return tuple(result)


def values(store, *, as_of=None):
    target = date.today() if as_of is None else as_of
    if type(target) is not date:
        raise error("tangible_asset_value_date_invalid")
    latest = {}
    for saved in value_history(store):
        number, account, day, amount, rate, reason, version, created = saved
        if day <= target.isoformat() and (
            account not in latest or (day, number) > (latest[account][2], latest[account][0])
        ):
            latest[account] = saved
    result = []
    for saved in latest.values():
        number, account, day, amount, rate, reason, version, _created = saved
        point_date = date.fromisoformat(day)
        projected = amount if target == point_date or rate is not None else None
        if rate is not None and target > point_date:
            with localcontext() as ctx:
                ctx.prec = 40
                fraction = Decimal(10000 - rate) / Decimal(10000)
                elapsed = Decimal((target - point_date).days) / Decimal("365.2425")
                projected = int((Decimal(amount) * (fraction**elapsed)).quantize(Decimal(1), rounding=ROUND_HALF_UP))
        result.append(
            TangibleAssetValue(
                number, account, _vehicle(store, account), point_date, amount, projected, target, rate, reason, version
            )
        )
    return tuple(sorted(result, key=lambda item: (item.account_name, item.account_id)))


def set_value(
    store, account_id, *, value_date, amount_minor, annual_rate_basis_points=None, reason, expected_basis_sha256=None
):
    reason = _value_request(store, account_id, value_date, amount_minor, annual_rate_basis_points, reason)
    store._require_writable()
    with store._atomic_write("tangible_asset_value"):
        history = value_history(store)
        latest = next((r for r in reversed(history) if r[1:3] == (account_id, value_date.isoformat())), None)
        if latest is None or latest[1:6] != (
            account_id,
            value_date.isoformat(),
            amount_minor,
            annual_rate_basis_points,
            reason,
        ):
            if expected_basis_sha256 is not None:
                store._require_source_interpretation_basis(expected_basis_sha256, required=True)
            number = store.connection.execute(
                "SELECT COALESCE(MAX(revision_id),0)+1 FROM TangibleAssetValues"
            ).fetchone()[0]
            created = now(store)
            record = (number, account_id, value_date.isoformat(), amount_minor, annual_rate_basis_points, reason)
            store.connection.execute(
                "INSERT INTO TangibleAssetValues VALUES (?,?,?,?,?,?,?,?)",
                (*record, digest([*record, created]), created),
            )
        return next(value for value in values(store, as_of=value_date) if value.account_id == account_id)


def create_asset(store, account, *, value_date, amount_minor, annual_rate_basis_points=None, reason):
    store._require_writable()
    if account.product_type != "vehicle" or account.kind != "asset" or account.tracking_scope != "account_total":
        raise error("origination_vehicle_destination_required")
    with store._atomic_write("create_tangible_asset"):
        store.add_financial_account(account)
        return set_value(
            store,
            account.id,
            value_date=value_date,
            amount_minor=amount_minor,
            annual_rate_basis_points=annual_rate_basis_points,
            reason=reason,
        )


def _source_proof(store, row_id, *, account_id=None, active=True):
    from parsetrail.core.v2_profile_store import _rows

    source = store.connection.execute(
        "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
        (row_id,),
    ).fetchone()
    if source is None:
        raise error("origination_source_unavailable")
    saved = store.load_import(source[0])
    row = next((row for row in _rows(saved.evidence) if row.row_id == row_id), None)
    binding = next((b.ledger_account_id for b in store.account_bindings(source[0]) if b.row_id == row_id), None)
    account = binding if account_id is None else account_id
    parts = {} if row is None else {part.role: part.amount for part in row.components}
    if (
        saved.evidence.parser_id != "pdf_capitaloneauto_202402"
        or row is None
        or (row.description.text or "").casefold() != "amount financed"
        or row.row_role != "activity"
        or row.date_role != "activity_date"
        or row.date.provenance != "observed"
        or row.amount.provenance != "observed"
        or type(row.amount.minor) is not int
        or row.amount.minor <= 0
        or set(parts) != {"principal"}
        or parts["principal"].provenance != "observed"
        or parts["principal"].minor != row.amount.minor
        or source[1:] != (row.row_role, row.date_role, row.date.iso, row.amount.minor)
        or store.connection.execute("SELECT kind,role,tracking_scope FROM Accounts WHERE id=?", (account,)).fetchone()
        != ("liability", "financial", "principal_component")
        or (active and binding != account)
    ):
        raise error("origination_source_or_account_unsupported")
    proof = {
        "source_sha256": source[0],
        "parser_id": saved.evidence.parser_id,
        "account_id": account,
        "row_evidence": row.model_dump_json(),
    }
    return proof, row


def _entries(data, event_id, reason):
    from parsetrail.core.source_evidence import ObservationEvidence

    row = ObservationEvidence.model_validate_json(data["proof"]["row_evidence"])
    principal, value = row.amount.minor, data["acquisition_value_minor"]
    result = [
        JournalEntry(
            event_id + ":financing",
            event_id,
            date.fromisoformat(row.date.iso),
            "Reviewed loan origination financing",
            (Posting(data["proof"]["account_id"], -principal), Posting(CLEARING, principal)),
            origin="manual",
            reviewed=True,
            reason=reason,
        ),
        JournalEntry(
            event_id + ":asset",
            event_id,
            date.fromisoformat(data["acquisition_date"]),
            "Reviewed vehicle acquisition",
            (Posting(data["destination_account_id"], value), Posting(CLEARING, -value)),
            origin="manual",
            reviewed=True,
            reason=reason,
        ),
    ]
    if data["bank"] is not None:
        bank = TransferMovement(**data["bank"])
        result.append(
            JournalEntry(
                event_id + ":downpayment",
                event_id,
                date.fromisoformat(bank.posting_date),
                "Reviewed acquisition down payment",
                (
                    Posting(bank.account_id, bank.amount_minor, (Allocation(bank.row_id, bank.amount_minor),)),
                    Posting(CLEARING, -bank.amount_minor),
                ),
                reviewed=True,
                reason=reason,
            )
        )
    return tuple(result)


def history(store):
    from parsetrail.core.v2_profile_store import _INACTIVE_JOURNAL_SQL, _decode_journal, _journal_payload

    actions = {}
    for saved in store.connection.execute("SELECT * FROM LoanOriginationActions ORDER BY action_id"):
        number, event, version, reason, basis, checksum, created = saved
        if (
            number <= 0
            or reason != reason_text(reason)
            or checksum != digest([*saved[:-2], created])
            or event in actions
        ):
            raise error("origination_history_integrity")
        actions[event] = saved
    inactive = {key for (key,) in store.connection.execute(_INACTIVE_JOURNAL_SQL)}
    result, expected_uses, expected_keys, active_rows = [], set(), set(), set()
    for saved in store.connection.execute("SELECT * FROM LoanOriginationEvents ORDER BY created_at,event_id"):
        (
            event_id,
            row_id,
            source,
            account,
            destination,
            bank_row,
            manifest,
            versions,
            reason,
            basis,
            version,
            created,
        ) = saved
        try:
            data = json.loads(manifest)
            if set(data) != {"proof", "destination_account_id", "acquisition_value_minor", "acquisition_date", "bank"}:
                raise ValueError
            active = event_id not in actions
            proof, row = _source_proof(store, row_id, account_id=account, active=active)
            _vehicle(store, destination)
            bank = TransferMovement(**data["bank"]) if data["bank"] is not None else None
            delta = data["acquisition_value_minor"] - row.amount.minor
            if (
                proof != data["proof"]
                or destination != data["destination_account_id"]
                or source != proof["source_sha256"]
                or type(data["acquisition_value_minor"]) is not int
                or delta < 0
                or data["acquisition_value_minor"] >= 2**63
                or (delta == 0 and bank is not None)
                or (delta > 0 and (bank is None or bank.amount_minor != -delta))
                or bank_row != (bank.row_id if bank else None)
                or (
                    bank is not None
                    and (bank.account_kind != "asset" or not bank.date_allowed or bank.account_id == destination)
                )
                or event_id != "review:origination:" + digest([manifest, basis, reason])
                or reason != reason_text(reason)
                or version != digest([*saved[:-2], created])
            ):
                raise ValueError
            if bank:
                store._validate_transfer_movements_source((bank,))
                if (
                    active
                    and next(
                        (
                            b.ledger_account_id
                            for b in store.account_bindings(bank.source_sha256)
                            if b.row_id == bank.row_id
                        ),
                        None,
                    )
                    != bank.account_id
                ):
                    raise ValueError
            entries = _entries(data, event_id, reason)
            actual_versions = json.dumps(
                [[entry.key, digest(_journal_payload(entry))] for entry in entries], separators=(",", ":")
            )
            if versions != actual_versions:
                raise ValueError
            observations = (
                {}
                if bank is None
                else {
                    bank.row_id: Observation(
                        bank.row_id, bank.account_id, bank.amount_minor, date.fromisoformat(bank.posting_date)
                    )
                }
            )
            for entry in entries:
                validate_entry(entry, store._ledger_accounts(), observations, {})
                allocations = [
                    (a.observation_id, a.amount_minor) for posting in entry.postings for a in posting.allocations
                ]
                if (
                    store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (entry.key,)).fetchone()
                    != (_journal_payload(entry),)
                    or store.connection.execute(
                        "SELECT row_id,amount_minor FROM JournalAllocations WHERE entry_key=?", (entry.key,)
                    ).fetchall()
                    != allocations
                    or (entry.key in inactive) == active
                ):
                    raise ValueError
                expected_keys.add(entry.key)
                if not active and store.connection.execute(
                    "SELECT reason FROM JournalRetirements WHERE original_key=?", (entry.key,)
                ).fetchone() != (actions[event_id][3],):
                    raise ValueError
            expected_uses.add((event_id, entries[0].key, row_id, row.amount.minor))
            if active:
                used = {row_id, *((bank.row_id,) if bank else ())}
                if active_rows & used:
                    raise ValueError
                active_rows.update(used)
            elif actions[event_id][2] != version:
                raise ValueError
            result.append(
                OriginationEvent(
                    event_id,
                    row_id,
                    source,
                    account,
                    destination,
                    data["acquisition_value_minor"],
                    date.fromisoformat(data["acquisition_date"]),
                    row.amount.minor,
                    tuple(entry.key for entry in entries),
                    reason,
                    version,
                    "active" if active else "withdrawn",
                    bank_row,
                )
            )
        except (ValueError, TypeError, KeyError):
            raise error("origination_history_integrity") from None
    if expected_uses != set(store.connection.execute("SELECT * FROM LoanOriginationSourceUses")) or set(actions) - {
        item.event_id for item in result
    }:
        raise error("origination_history_integrity")
    for key, payload in store.connection.execute(
        "SELECT key,payload FROM JournalEntries WHERE key LIKE 'review:origination:%'"
    ):
        if key not in expected_keys and _decode_journal(payload).origin != "reversal":
            raise error("origination_history_integrity")
    return tuple(result)


def snapshot(store, source_sha256=None):
    from parsetrail.core.v2_profile_store import _rows

    events = history(store)
    active = {event.row_id: event for event in events if event.status == "active"}
    rows = []
    for source in store.source_ids():
        if source_sha256 is not None and source != source_sha256:
            continue
        evidence = store.load_import(source).evidence
        if evidence.parser_id != "pdf_capitaloneauto_202402":
            continue
        for row in _rows(evidence):
            if (row.description.text or "").casefold() != "amount financed":
                continue
            account_id = next(
                (b.ledger_account_id for b in store.account_bindings(source) if b.row_id == row.row_id), None
            )
            account_name = store.connection.execute("SELECT name FROM Accounts WHERE id=?", (account_id,)).fetchone()
            blockers = []
            try:
                _source_proof(store, row.row_id)
            except Exception as exc:
                from parsetrail.core.v2_profile_store import ProfileFormatError

                if not isinstance(exc, ProfileFormatError):
                    raise
                blockers.append(str(exc))
            event = active.get(row.row_id)
            rows.append(
                OriginationRow(
                    row.row_id,
                    source,
                    account_id,
                    account_name[0] if account_name else None,
                    row.date.iso,
                    row.amount.minor,
                    "Reviewed origination" if event else "Choose destination and acquisition funding",
                    tuple(blockers),
                    event.event_id if event else None,
                )
            )
    bank = tuple(
        m
        for m in store._transfer_movements(V2Preferences(allow_assumed_posting_dates=True))
        if m.account_kind == "asset" and m.amount_minor < 0
    )
    return OriginationSnapshot(tuple(rows), store._source_overlap_basis(), events, bank)


def build_preview(
    store,
    row_id,
    *,
    destination_account_id,
    acquisition_value_minor,
    acquisition_date,
    bank_downpayment_row_id=None,
    preferences,
    expected_basis_sha256,
    reason,
):
    reason = reason_text(reason)
    if type(preferences) is not V2Preferences or not preferences.allow_assumed_posting_dates:
        raise error("origination_assumed_date_permission_required")
    if (
        type(acquisition_value_minor) is not int
        or not 0 < acquisition_value_minor < 2**63
        or type(acquisition_date) is not date
    ):
        raise error("origination_acquisition_value_required")
    store._require_source_interpretation_basis(expected_basis_sha256, required=True)
    _vehicle(store, destination_account_id)
    proof, row = _source_proof(store, row_id)
    if store._active_consumed().get(row_id, 0):
        raise error("origination_source_already_used")
    delta = acquisition_value_minor - row.amount.minor
    bank = (
        next((m for m in store._transfer_movements(preferences) if m.row_id == bank_downpayment_row_id), None)
        if bank_downpayment_row_id is not None
        else None
    )
    if (
        delta < 0
        or (delta == 0 and bank_downpayment_row_id is not None)
        or (
            delta > 0
            and (bank is None or bank.account_kind != "asset" or bank.amount_minor != -delta or not bank.date_allowed)
        )
    ):
        raise error("origination_exact_downpayment_evidence_required")
    store._require_source_overlap_postable((row_id, *((bank.row_id,) if bank else ())))
    data = {
        "proof": proof,
        "destination_account_id": destination_account_id,
        "acquisition_value_minor": acquisition_value_minor,
        "acquisition_date": acquisition_date.isoformat(),
        "bank": asdict(bank) if bank else None,
    }
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"))
    event_id = "review:origination:" + digest([encoded, expected_basis_sha256, reason])
    entries = _entries(data, event_id, reason)
    accounts = store._loan_accounts(interest=False, materialize=False)
    observations = (
        {}
        if bank is None
        else {
            bank.row_id: Observation(
                bank.row_id, bank.account_id, bank.amount_minor, date.fromisoformat(bank.posting_date)
            )
        }
    )
    consumed = store._active_consumed()
    for entry in entries:
        validate_entry(entry, accounts, observations, consumed)
    from parsetrail.core.v2_transfer_batch import profile_identity

    profile = profile_identity(store)
    checksum = digest([encoded, expected_basis_sha256, reason, profile, asdict(preferences)])
    return OriginationPreview(
        row_id,
        proof["source_sha256"],
        proof["account_id"],
        destination_account_id,
        acquisition_value_minor,
        acquisition_date,
        bank_downpayment_row_id,
        row.amount.minor,
        entries,
        reason,
        expected_basis_sha256,
        preferences,
        encoded,
        checksum,
        profile,
    )


def post(store, preview):
    from parsetrail.core.v2_profile_store import _journal_payload

    if type(preview) is not OriginationPreview:
        raise error("origination_preview_invalid")
    from parsetrail.core.v2_transfer_batch import profile_identity

    if preview.profile_sha256 != profile_identity(store):
        raise error("origination_profile_changed")
    try:
        from parsetrail.core.source_evidence import ObservationEvidence

        data = json.loads(preview.proof)
        row = ObservationEvidence.model_validate_json(data["proof"]["row_evidence"])
        identity = "review:origination:" + digest([preview.proof, preview.basis_sha256, preview.reason])
        if (
            preview.preview_sha256
            != digest(
                [
                    preview.proof,
                    preview.basis_sha256,
                    preview.reason,
                    preview.profile_sha256,
                    asdict(preview.preferences),
                ]
            )
            or (preview.row_id, preview.source_sha256, preview.account_id, preview.principal_minor)
            != (row.row_id, data["proof"]["source_sha256"], data["proof"]["account_id"], row.amount.minor)
            or (preview.destination_account_id, preview.acquisition_value_minor, preview.acquisition_date.isoformat())
            != (data["destination_account_id"], data["acquisition_value_minor"], data["acquisition_date"])
            or preview.bank_downpayment_row_id != (data["bank"]["row_id"] if data["bank"] else None)
            or preview.entries != _entries(data, identity, preview.reason)
        ):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        raise error("origination_preview_invalid") from None
    store._require_writable()
    if store.connection.in_transaction:
        raise error("origination_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        for event in history(store):
            record = store.connection.execute(
                "SELECT manifest,request_basis FROM LoanOriginationEvents WHERE event_id=?", (event.event_id,)
            ).fetchone()
            if record == (preview.proof, preview.basis_sha256) and event.reason == preview.reason:
                if event.status != "active":
                    raise error("origination_event_retired")
                store.connection.execute("COMMIT")
                return event
        fresh = build_preview(
            store,
            preview.row_id,
            destination_account_id=preview.destination_account_id,
            acquisition_value_minor=preview.acquisition_value_minor,
            acquisition_date=preview.acquisition_date,
            bank_downpayment_row_id=preview.bank_downpayment_row_id,
            preferences=preview.preferences,
            expected_basis_sha256=preview.basis_sha256,
            reason=preview.reason,
        )
        if fresh != preview:
            raise error("origination_preview_changed")
        store._ensure_transfer_clearing()
        created = now(store)
        for entry in preview.entries:
            store.connection.execute(
                "INSERT INTO JournalEntries(key,payload) VALUES (?,?)", (entry.key, _journal_payload(entry))
            )
            for posting in entry.postings:
                for allocation in posting.allocations:
                    store.connection.execute(
                        "INSERT INTO JournalAllocations VALUES (?,?,?)",
                        (entry.key, allocation.observation_id, allocation.amount_minor),
                    )
        event_id = preview.entries[0].event_id
        versions = json.dumps(
            [[entry.key, digest(_journal_payload(entry))] for entry in preview.entries], separators=(",", ":")
        )
        record = (
            event_id,
            preview.row_id,
            preview.source_sha256,
            preview.account_id,
            preview.destination_account_id,
            preview.bank_downpayment_row_id,
            preview.proof,
            versions,
            preview.reason,
            preview.basis_sha256,
        )
        store.connection.execute(
            "INSERT INTO LoanOriginationEvents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (*record, digest([*record, created]), created),
        )
        store.connection.execute(
            "INSERT INTO LoanOriginationSourceUses VALUES (?,?,?,?)",
            (event_id, preview.entries[0].key, preview.row_id, preview.principal_minor),
        )
        result = next(event for event in history(store) if event.event_id == event_id)
        store.connection.execute("COMMIT")
        return result
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise


def withdraw(store, event_id, *, expected_version, reason):
    from parsetrail.core.v2_profile_store import _decode_journal

    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("origination_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        event = next((item for item in history(store) if item.event_id == event_id), None)
        if event is None or event.version != expected_version:
            raise error("origination_event_changed")
        prior = store.connection.execute(
            "SELECT reason FROM LoanOriginationActions WHERE event_id=?", (event_id,)
        ).fetchone()
        if prior:
            if prior != (reason,):
                raise error("origination_event_changed")
        else:
            basis = store._source_overlap_basis()
            store._origination_mutating = True
            for key in event.entry_keys:
                entry = _decode_journal(
                    store.connection.execute("SELECT payload FROM JournalEntries WHERE key=?", (key,)).fetchone()[0]
                )
                store._retire_journal_entry(entry, reason=reason)
            number = store.connection.execute(
                "SELECT COALESCE(MAX(action_id),0)+1 FROM LoanOriginationActions"
            ).fetchone()[0]
            created = now(store)
            record = (number, event_id, expected_version, reason, basis)
            store.connection.execute(
                "INSERT INTO LoanOriginationActions VALUES (?,?,?,?,?,?,?)",
                (*record, digest([*record, created]), created),
            )
            store._origination_mutating = False
        history(store)
        store.connection.execute("COMMIT")
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise
    finally:
        store._origination_mutating = False
