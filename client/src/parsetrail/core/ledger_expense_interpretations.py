"""Explicit expense/refund interpretations of wholly unallocated cash/card evidence."""

import json
from contextlib import contextmanager
from dataclasses import asdict

from parsetrail.core.ledger import Allocation, JournalEntry, LedgerError, Posting, identifier, validate_entry
from parsetrail.core.ledger_expense_corrections import expense_split
from parsetrail.core.ledger_opening_review import observation_date_provenance
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import decode_entry, encoded

RULE = "expense-interpretation-1"
DEFAULT_REASON = "Explicitly classified as ordinary expense/refund"


class ExpenseInterpretations:
    def __init__(self, review):
        self.review, self.store = review, review.store
        self.scope = {o["id"]: o for o in review.plan["observations"]}

    @contextmanager
    def _snapshot(self):
        c = self.store.connection
        if c.in_transaction:
            raise LedgerError("Interpretation preview requires a committed read snapshot.")
        c.execute("BEGIN")
        try:
            yield
        finally:
            c.execute("ROLLBACK")

    def _history(self):
        c = self.store.connection
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ExpenseInterpretations'").fetchone():
            return {}
        return {
            oid: json.loads(payload)
            for oid, payload in c.execute("SELECT observation_id,payload FROM ExpenseInterpretations")
        }

    def _proposal(self, oid):
        c = self.store.connection
        row = c.execute("SELECT id,payload FROM JournalProposals WHERE observation_id=?", (oid,)).fetchone()
        if row is None:
            return None
        pid, payload = row
        if self.review.proposals.get(pid) != payload:
            raise LedgerError("Original proposal changed; refresh the workspace.")
        return {"id": pid, "payload": json.loads(payload), "decision": self.review.decisions().get(pid)}

    def inventory(self):
        """Only wholly unallocated evidence without a pending ordinary proposal is editable."""
        with self._snapshot():
            c, store = self.store.connection, self.store
            accounts, observations, used = store.accounts(), store.observations(), store.consumed()
            dates, history = observation_date_provenance(store), self._history()
            decisions = self.review.decisions()
            proposals = {
                oid: {"id": pid, "payload": json.loads(payload), "decision": decisions.get(pid)}
                for pid, oid, payload in c.execute("SELECT id,observation_id,payload FROM JournalProposals")
            }
            sources = {
                tid: json.loads(payload) for tid, payload in c.execute("SELECT id,payload FROM SourceTransactions")
            }
            rows = []
            for oid in sorted(self.scope):
                if used.get(oid) or oid in history:
                    continue
                proposal = proposals.get(oid)
                if proposal and (not proposal["decision"] or proposal["decision"]["action"] != "rejected"):
                    continue
                observation = observations[oid]
                raw = sources[oid.removeprefix("source:")]
                rows.append(
                    {
                        "observation_id": oid,
                        "account_name": accounts[observation.account_id].name,
                        "amount_minor": observation.amount_minor,
                        "posting_date": observation.posting_date.isoformat(),
                        "description": raw["Description"],
                        "date_provenance": dates.get(oid, "unknown"),
                        "proposal": proposal,
                        "status": "Rejected proposal" if proposal else "Unclassified",
                    }
                )
            return rows

    def preview(self, observation_id, splits, reason=""):
        with self._snapshot():
            return self._build(observation_id, splits, reason)

    def _build(self, observation_id, splits, reason):
        identifier(observation_id)
        if observation_id not in self.scope:
            raise LedgerError("Choose eligible nonzero cash/card evidence from this candidate workspace.")
        store, c = self.store, self.store.connection
        observations, accounts = store.observations(), store.accounts()
        observation = observations[observation_id]
        current = {**asdict(observation), "posting_date": observation.posting_date.isoformat()}
        if current != self.scope[observation_id]:
            raise LedgerError("Source observation differs from its verified candidate plan.")
        if store.consumed().get(observation_id) or observation_id in self._history():
            raise LedgerError("Evidence is already allocated; use its posted interpretation or correction workflow.")
        proposal = self._proposal(observation_id)
        if proposal and (not proposal["decision"] or proposal["decision"]["action"] != "rejected"):
            raise LedgerError(
                "Review the existing ordinary proposal first; accept it or explicitly reject its interpretation."
            )
        if isinstance(reason, str):
            reason = reason.strip()
            if not reason and not proposal:
                reason = DEFAULT_REASON
        identifier(reason)
        tid = observation_id.removeprefix("source:")
        source = json.loads(c.execute("SELECT payload FROM SourceTransactions WHERE id=?", (tid,)).fetchone()[0])
        splits, mappings, counterparts = expense_split(store, accounts, observation, splits)
        request = {"rule": RULE, "observation_id": observation_id, "splits": splits, "reason": reason}
        entry = JournalEntry(
            "expense-interpretation:" + key(request),
            "event:" + tid,
            observation.posting_date,
            source["Description"],
            (
                Posting(
                    observation.account_id,
                    observation.amount_minor,
                    (Allocation(observation_id, observation.amount_minor),),
                ),
                *counterparts,
            ),
            reviewed=True,
            reason=reason,
        )
        plan = json.loads(
            encoded(
                {
                    **request,
                    "candidate_hash": key(self.review.plan),
                    "observation": current,
                    "source_hash": key(source),
                    "proposal": proposal,
                    "entry": entry.payload(),
                    "category_accounts": mappings,
                    "date_provenance": observation_date_provenance(store).get(observation_id, "unknown"),
                }
            )
        )
        return {**plan, "preview_hash": key(plan)}

    def apply(self, plan):
        if (
            plan.get("rule") != RULE
            or plan.get("candidate_hash") != key(self.review.plan)
            or plan.get("preview_hash") != key({k: v for k, v in plan.items() if k != "preview_hash"})
        ):
            raise LedgerError("Interpretation preview changed or belongs to different evidence.")
        store, c = self.store, self.store.connection
        with store._transaction():
            existing = self._history().get(plan["observation_id"])
            entry = decode_entry(encoded(plan["entry"]))
            if existing:
                if existing == plan and store._existing(entry):
                    return entry.key
                raise LedgerError("Evidence already has an interpretation; use its active correction workflow.")
            fresh = self._build(plan["observation_id"], plan["splits"], plan["reason"])
            if fresh != plan:
                raise LedgerError("Interpretation inputs changed since preview; review a fresh preview.")
            c.execute("""CREATE TABLE IF NOT EXISTS ExpenseInterpretations(
                observation_id TEXT PRIMARY KEY REFERENCES LedgerObservations(id),
                entry_key TEXT NOT NULL UNIQUE REFERENCES LedgerEntries(key), payload TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
            for action in ("UPDATE", "DELETE"):
                c.execute(
                    f"CREATE TRIGGER IF NOT EXISTS ExpenseInterpretations_{action} BEFORE {action} ON ExpenseInterpretations "
                    "BEGIN SELECT RAISE(ABORT,'Expense interpretations are immutable'); END"
                )
            for account in fresh["category_accounts"]:
                if not c.execute("SELECT 1 FROM LedgerAccounts WHERE id=?", (account["id"],)).fetchone():
                    c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (account["id"], None, encoded(account)))
            if store._existing(entry):
                raise LedgerError("Posting exists without its interpretation decision.")
            usage = validate_entry(entry, store.accounts(), store.observations(), store.consumed())
            store._insert(entry, usage)
            c.execute(
                "INSERT INTO ExpenseInterpretations(observation_id,entry_key,payload) VALUES(?,?,?)",
                (plan["observation_id"], entry.key, encoded(plan)),
            )
            return entry.key
