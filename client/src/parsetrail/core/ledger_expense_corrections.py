"""Explicit category splits/corrections of posted ordinary cash/card expenses and refunds."""

import json
from dataclasses import asdict, replace

from parsetrail.core.ledger import AccountKind, LedgerAccount, LedgerError, Posting, identifier, minor_units
from parsetrail.core.ledger_opening_review import observation_date_provenance
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import decode_entry, encoded

RULE = "expense-correction-1"


def expense_split(store, accounts, observation, splits, *, kind=AccountKind.EXPENSE):
    """Validate exact category counterparts shared by interpretations and corrections."""
    if kind not in (AccountKind.EXPENSE, AccountKind.INCOME):
        raise LedgerError("Choose an expense or income category scope.")
    c = store.connection
    if not isinstance(splits, (list, tuple)) or not splits:
        raise LedgerError(f"Provide one or more exact {kind.value} category amounts.")
    normalized = []
    for part in splits:
        if not isinstance(part, (list, tuple)) or len(part) != 2 or type(part[0]) is not int:
            raise LedgerError("Each split requires an integer category identity and positive minor units.")
        cid, amount = part
        minor_units(amount)
        if amount < 0:
            raise LedgerError("Split amounts must be positive; the source determines posting signs.")
        normalized.append((cid, amount))
    normalized.sort()
    if len({cid for cid, _ in normalized}) != len(normalized):
        raise LedgerError("Combine repeated categories into one split amount.")
    if sum(amount for _, amount in normalized) != abs(observation.amount_minor):
        raise LedgerError("Split amounts must exactly equal the whole source movement.")
    definitions = {cid: json.loads(payload) for cid, payload in c.execute("SELECT id,payload FROM CategoryDefinitions")}
    mappings, postings = [], []
    for cid, amount in normalized:
        category = definitions.get(cid)
        if not category or category["Type"] != kind.value.title():
            raise LedgerError(
                f"Choose an existing {kind.value} category; other account classes are outside this scope."
            )
        account = LedgerAccount(f"category:{cid}", category["Name"], kind, observation.currency)
        account.validate()
        if account.id in accounts and accounts[account.id] != account:
            raise LedgerError("Category account mapping conflicts with the retained definition.")
        mappings.append(asdict(account))
        postings.append(Posting(account.id, amount if observation.amount_minor < 0 else -amount))
    return normalized, mappings, postings


class ExpenseCorrections:
    """Preserve the whole financial observation; only its expense counterparts change.

    No guessing, partial settlements, income reclassification, financial-account
    changes, or transfer/loan/asset/opening corrections belong in this service.
    """

    category_kind = AccountKind.EXPENSE
    rule = RULE
    key_prefix = "expense-correction:"

    def __init__(self, review):
        self.review, self.store = review, review.store

    def preview(self, original_key, splits, reason):
        """Read-only plan. Splits are distinct (category_id, positive minor units) pairs."""
        c = self.store.connection
        if c.in_transaction:
            raise LedgerError("Preview requires a committed read snapshot.")
        c.execute("BEGIN")
        try:
            return self._build(original_key, splits, reason)
        finally:
            c.execute("ROLLBACK")

    def _build(self, original_key, splits, reason):
        identifier(original_key)
        identifier(reason)
        reason = reason.strip()
        store, c = self.store, self.store.connection
        row = c.execute("SELECT payload FROM LedgerEntries WHERE key=?", (original_key,)).fetchone()
        if row is None:
            raise LedgerError("Original entry does not exist.")
        original = decode_entry(row[0])
        status = store.entry_status(original_key)
        if status["superseded"]:
            raise LedgerError("Original entry was already corrected; select its active replacement.")
        accounts, observations = store.accounts(), store.observations()
        scoped = {a["id"] for a in self.review.plan["accounts"] if a["source_account_id"] is not None}
        movement, counterparts = self._movement(original, accounts, observations, scoped)
        observation = observations[movement.allocations[0].observation_id]
        normalized, mappings, postings = expense_split(store, accounts, observation, splits, kind=self.category_kind)
        if sorted((p.account_id, p.amount_minor) for p in counterparts) == sorted(
            (p.account_id, p.amount_minor) for p in postings
        ):
            raise LedgerError("Category amounts are unchanged; no correction is needed.")
        request = {"rule": self.rule, "original_key": original_key, "splits": normalized, "reason": reason}
        replacement = replace(
            original,
            key=self.key_prefix + key(request),
            postings=(movement, *postings),
            reviewed=True,
            reason=reason,
        )
        plan = {
            **request,
            "splits": [list(part) for part in normalized],
            "candidate_hash": key(self.review.plan),
            "original_payload_hash": key(original.payload()),
            "original_reviewed": status["reviewed"],
            "replacement": replacement.payload(),
            "category_accounts": mappings,
            "financial_movement_unchanged": True,
            f"net_{self.category_kind.value}_change_minor": 0,
        }
        # Canonical JSON types make persisted previews compare identically on reopen.
        plan = json.loads(encoded(plan))
        return {**plan, "preview_hash": key(plan)}

    @classmethod
    def _movement(cls, original, accounts, observations, scoped):
        financial = [p for p in original.postings if accounts[p.account_id].source_account_id is not None]
        if original.origin != "imported" or len(financial) != 1 or financial[0].account_id not in scoped:
            raise LedgerError(f"Only ordinary imported {cls.category_kind.value} entries can be corrected here.")
        movement = financial[0]
        if len(movement.allocations) != 1:
            raise LedgerError("Correction requires one whole source movement.")
        allocation = movement.allocations[0]
        observation = observations[allocation.observation_id]
        if (
            movement.amount_minor != allocation.amount_minor
            or movement.amount_minor != observation.amount_minor
            or movement.account_id != observation.account_id
            or original.posting_date != observation.posting_date
        ):
            raise LedgerError("Correction requires the unchanged whole source amount, account and date.")
        counterparts = [p for p in original.postings if p is not movement]
        if not counterparts or any(
            accounts[p.account_id].kind != cls.category_kind
            or accounts[p.account_id].purpose != "normal"
            or p.allocations
            or (p.amount_minor > 0) == (movement.amount_minor > 0)
            for p in counterparts
        ):
            raise LedgerError(
                "Other account classes and mixed-sign counterparts require a different correction workflow."
            )
        if sum(p.amount_minor for p in counterparts) != -movement.amount_minor:
            raise LedgerError("Original category counterparts do not match the source amount.")
        return movement, counterparts

    def entries(self):
        """Read-only editor inventory; active entries and superseded originals are distinct."""
        store, c = self.store, self.store.connection
        if c.in_transaction:
            raise LedgerError("Inventory requires a committed read snapshot.")
        c.execute("BEGIN")
        try:
            accounts, observations = store.accounts(), store.observations()
            scoped = {a["id"] for a in self.review.plan["accounts"] if a["source_account_id"] is not None}
            dates = observation_date_provenance(store)
            corrections = dict(c.execute("SELECT original_key,replacement_key FROM LedgerCorrections"))
            previous = {replacement: original for original, replacement in corrections.items()}
            reviews = dict(c.execute("SELECT entry_key,reviewed FROM LedgerReviews ORDER BY sequence"))
            rows = []
            for (payload,) in c.execute("SELECT payload FROM LedgerEntries ORDER BY key"):
                entry = decode_entry(payload)
                try:
                    movement, counterparts = self._movement(entry, accounts, observations, scoped)
                except LedgerError:
                    continue
                rows.append(
                    {
                        "entry": entry.payload(),
                        "account_name": accounts[movement.account_id].name,
                        "amount_minor": movement.amount_minor,
                        "reviewed": bool(reviews.get(entry.key, entry.reviewed)),
                        "active": entry.key not in corrections,
                        "previous_key": previous.get(entry.key),
                        "replacement_key": corrections.get(entry.key),
                        "date_provenance": dates.get(movement.allocations[0].observation_id, "unknown"),
                        "categories": [
                            {
                                "account_id": p.account_id,
                                "name": accounts[p.account_id].name,
                                "amount_minor": p.amount_minor,
                            }
                            for p in counterparts
                        ],
                    }
                )
            return rows
        finally:
            c.execute("ROLLBACK")

    def apply(self, plan):
        """Atomically create needed category mappings and reverse/replace a checked plan."""
        if (
            plan.get("rule") != self.rule
            or plan.get("candidate_hash") != key(self.review.plan)
            or plan.get("preview_hash") != key({k: v for k, v in plan.items() if k != "preview_hash"})
        ):
            raise LedgerError("Correction preview changed or belongs to different evidence.")
        store, c = self.store, self.store.connection
        with store._transaction():
            existing = c.execute(
                "SELECT replacement_key,reason FROM LedgerCorrections WHERE original_key=?", (plan["original_key"],)
            ).fetchone()
            if existing:
                if existing == (plan["replacement"]["key"], plan["reason"]) and store._existing(
                    decode_entry(encoded(plan["replacement"]))
                ):
                    return existing[0]
                raise LedgerError("Original entry was already corrected; select its active replacement.")
            fresh = self._build(plan["original_key"], plan["splits"], plan["reason"])
            if fresh != plan:
                raise LedgerError("Correction inputs changed since preview. Review a fresh preview before applying.")
            for account in fresh["category_accounts"]:
                if not c.execute("SELECT 1 FROM LedgerAccounts WHERE id=?", (account["id"],)).fetchone():
                    c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (account["id"], None, encoded(account)))
            return store._correct(
                plan["original_key"], decode_entry(encoded(fresh["replacement"])), reason=plan["reason"]
            )
