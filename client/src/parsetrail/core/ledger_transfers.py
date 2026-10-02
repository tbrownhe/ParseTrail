"""Reviewed cash transfers/card payments with exact source-date preservation."""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from dataclasses import asdict

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Posting,
    identifier,
    validate_entry,
)
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import encoded

DEFAULT_REASON = "Confirmed transfer between owned accounts"


def pair_id(left, right):
    return "transfer:" + key(sorted((left, right)))


def pair_kind(outgoing, incoming, accounts):
    if (
        outgoing.amount_minor >= 0
        or incoming.amount_minor != -outgoing.amount_minor
        or outgoing.currency != incoming.currency
        or outgoing.account_id == incoming.account_id
    ):
        return None
    sender, receiver = accounts[outgoing.account_id], accounts[incoming.account_id]
    if sender.kind != AccountKind.ASSET:
        return None
    if receiver.kind == AccountKind.ASSET:
        return "cash_transfer"
    if receiver.kind == AccountKind.LIABILITY:
        return "card_payment"
    return None


def validate_window(window_days):
    if type(window_days) is not int or not 0 <= window_days <= 31:
        raise LedgerError("Choose a matching window between 0 and 31 days.")


class TransferReview:
    """Uses only eligible cash/card observations from a prepared ProposalReview."""

    def __init__(self, review):
        self.review, self.store = review, review.store
        self.scope = {o["id"] for o in review.plan["observations"]}
        c = self.store.connection
        with self.store._transaction():
            c.execute("""CREATE TABLE IF NOT EXISTS TransferDecisions(
                id TEXT PRIMARY KEY, outgoing_id TEXT NOT NULL REFERENCES LedgerObservations(id),
                incoming_id TEXT NOT NULL REFERENCES LedgerObservations(id),
                action TEXT NOT NULL CHECK(action IN ('confirmed','dismissed')), reason TEXT NOT NULL,
                window_days INTEGER NOT NULL CHECK(window_days BETWEEN 0 AND 31),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                CHECK(outgoing_id != incoming_id))""")
            c.execute("""CREATE TABLE IF NOT EXISTS TransferEntries(
                transfer_id TEXT NOT NULL REFERENCES TransferDecisions(id),
                entry_key TEXT NOT NULL UNIQUE REFERENCES LedgerEntries(key), PRIMARY KEY(transfer_id,entry_key))""")
            for table in ("TransferDecisions", "TransferEntries"):
                for action in ("UPDATE", "DELETE"):
                    c.execute(
                        f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'Transfer decisions are immutable'); END"
                    )

    def decisions(self):
        return {
            pid: {
                "outgoing_id": outgoing,
                "incoming_id": incoming,
                "action": action,
                "reason": reason,
                "window_days": days,
                "created_at": when,
            }
            for pid, outgoing, incoming, action, reason, days, when in self.store.connection.execute(
                "SELECT * FROM TransferDecisions"
            )
        }

    def pending_expenses(self):
        return dict(
            self.store.connection.execute("""
            SELECT p.observation_id,p.id FROM JournalProposals p
            LEFT JOIN ProposalDecisions d ON d.proposal_id=p.id WHERE d.proposal_id IS NULL""")
        )

    def snapshot(self, window_days=7):
        """Suggest only; no decisions, allocation or postings are written."""
        validate_window(window_days)
        accounts = self.store.accounts()
        observations = {oid: o for oid, o in self.store.observations().items() if oid in self.scope}
        used, decisions, pending = self.store.consumed(), self.decisions(), self.pending_expenses()
        positives = defaultdict(list)
        for o in observations.values():
            if o.amount_minor > 0:
                positives[(o.currency, o.amount_minor)].append(o)
        indexed = {}
        for amount, rows in positives.items():
            rows.sort(key=lambda o: (o.posting_date, o.id))
            indexed[amount] = ([o.posting_date.toordinal() for o in rows], rows)
        pairs, degree = {}, Counter()
        for outgoing in sorted(observations.values(), key=lambda o: o.id):
            if outgoing.amount_minor >= 0:
                continue
            days, rows = indexed.get((outgoing.currency, -outgoing.amount_minor), ([], []))
            day = outgoing.posting_date.toordinal()
            for incoming in rows[bisect_left(days, day - window_days) : bisect_right(days, day + window_days)]:
                kind = pair_kind(outgoing, incoming, accounts)
                if not kind:
                    continue
                pid = pair_id(outgoing.id, incoming.id)
                if pid in decisions:
                    status = decisions[pid]["action"]
                elif used.get(outgoing.id) or used.get(incoming.id):
                    status = "allocated"
                else:
                    status = "expense_conflict" if outgoing.id in pending or incoming.id in pending else "available"
                    degree.update((outgoing.id, incoming.id))
                pairs[pid] = {
                    "id": pid,
                    "outgoing_id": outgoing.id,
                    "incoming_id": incoming.id,
                    "kind": kind,
                    "status": status,
                    "amount_minor": incoming.amount_minor,
                    "date_gap_days": abs((outgoing.posting_date - incoming.posting_date).days),
                }
        # Saved decisions stay visible even after narrowing the search window.
        for pid, decision in decisions.items():
            if pid not in pairs:
                outgoing, incoming = [observations[decision[k]] for k in ("outgoing_id", "incoming_id")]
                pairs[pid] = {
                    "id": pid,
                    "outgoing_id": outgoing.id,
                    "incoming_id": incoming.id,
                    "kind": pair_kind(outgoing, incoming, accounts),
                    "status": decision["action"],
                    "amount_minor": incoming.amount_minor,
                    "date_gap_days": abs((outgoing.posting_date - incoming.posting_date).days),
                }
        for pair in pairs.values():
            pair["alternative_counts"] = [degree[pair[k]] for k in ("outgoing_id", "incoming_id")]
            if pair["status"] == "available":
                pair["status"] = "unique_candidate" if pair["alternative_counts"] == [1, 1] else "ambiguous"
        movements = []
        for oid, o in sorted(observations.items()):
            if used.get(oid):
                status = "allocated" if used[oid] == o.amount_minor else "partially_allocated"
            else:
                status = (
                    "no_candidate"
                    if not degree[oid]
                    else "one_candidate"
                    if degree[oid] == 1
                    else "multiple_candidates"
                )
            movements.append(
                {
                    "id": oid,
                    "status": status,
                    "candidate_count": degree[oid],
                    "pending_expense": pending.get(oid),
                    "remaining_minor": o.amount_minor - used.get(oid, 0),
                }
            )
        return {
            "window_days": window_days,
            "pairs": sorted(pairs.values(), key=lambda p: p["id"]),
            "movements": movements,
            "summary": dict(Counter(p["status"] for p in pairs.values())),
        }

    def decide(self, pairs, action, reason="", window_days=7):
        """Atomically confirm/post or dismiss distinct pairs, rechecking current evidence."""
        validate_window(window_days)
        if isinstance(reason, str):
            reason = reason.strip()
            if action == "confirmed" and not reason:
                reason = DEFAULT_REASON
        identifier(reason)
        if action not in {"confirmed", "dismissed"} or not pairs:
            raise LedgerError("Choose explicit transfer pairs and a confirmation or dismissal.")
        store, c = self.store, self.store.connection
        with store._transaction():
            accounts, observations, used = store.accounts(), store.observations(), store.consumed()
            decisions, pending = self.decisions(), self.pending_expenses()
            seen = set()
            for outgoing_id, incoming_id in pairs:
                if outgoing_id not in self.scope or incoming_id not in self.scope:
                    raise LedgerError("Transfer evidence must belong to the cash/card review scope.")
                outgoing, incoming = observations[outgoing_id], observations[incoming_id]
                kind = pair_kind(outgoing, incoming, accounts)
                if not kind or abs((outgoing.posting_date - incoming.posting_date).days) > window_days:
                    raise LedgerError(
                        "Transfer requires opposite exact amounts on distinct owned accounts within the date window."
                    )
                pid = pair_id(outgoing_id, incoming_id)
                if pid in seen:
                    raise LedgerError("A transfer pair occurs more than once in the batch.")
                seen.add(pid)
                if pid in decisions:
                    if (decisions[pid]["action"], decisions[pid]["reason"]) == (action, reason):
                        continue
                    raise LedgerError("This pair already has a decision. Posted changes require correction.")
                if action == "confirmed":
                    if used.get(outgoing_id) or used.get(incoming_id):
                        raise LedgerError("A transfer movement is already wholly or partly allocated.")
                    if outgoing_id in pending or incoming_id in pending:
                        raise LedgerError(
                            "Reject the conflicting ordinary expense/refund proposal before confirming this transfer."
                        )
                    entries, clearing = self.entries(outgoing, incoming, kind, reason)
                    if clearing:
                        existing = accounts.get(clearing.id)
                        if existing and existing != clearing:
                            raise LedgerError("Transfer clearing account has a conflicting mapping.")
                        if not existing:
                            clearing.validate()
                            c.execute(
                                "INSERT INTO LedgerAccounts VALUES(?,?,?)",
                                (clearing.id, None, encoded(asdict(clearing))),
                            )
                            accounts[clearing.id] = clearing
                    for entry in entries:
                        if store._existing(entry):
                            raise LedgerError("Transfer posting exists without its decision.")
                        usage = validate_entry(entry, accounts, observations, used)
                        store._insert(entry, usage)
                        for oid, amount in usage.items():
                            used[oid] = used.get(oid, 0) + amount
                else:
                    entries = []
                c.execute(
                    "INSERT INTO TransferDecisions(id,outgoing_id,incoming_id,action,reason,window_days) VALUES(?,?,?,?,?,?)",
                    (pid, outgoing_id, incoming_id, action, reason, window_days),
                )
                c.executemany("INSERT INTO TransferEntries VALUES(?,?)", [(pid, e.key) for e in entries])

    @staticmethod
    def entries(outgoing, incoming, kind, reason):
        pid = pair_id(outgoing.id, incoming.id)
        description = "Confirmed card payment" if kind == "card_payment" else "Confirmed cash transfer"

        def posting(o):
            return Posting(o.account_id, o.amount_minor, (Allocation(o.id, o.amount_minor),))

        if outgoing.posting_date == incoming.posting_date:
            return [
                JournalEntry(
                    pid,
                    pid,
                    outgoing.posting_date,
                    description,
                    (posting(outgoing), posting(incoming)),
                    reviewed=True,
                    reason=reason,
                )
            ], None
        clearing = LedgerAccount(f"clearing:{pid}", "Transfer in transit", AccountKind.ASSET, purpose="clearing")
        entries = [
            JournalEntry(
                f"{pid}:{side}",
                pid,
                o.posting_date,
                description,
                (posting(o), Posting(clearing.id, -o.amount_minor)),
                reviewed=True,
                reason=reason,
            )
            for side, o in (("outgoing", outgoing), ("incoming", incoming))
        ]
        return entries, clearing
