"""Replace the bank match of a whole confirmed loan payment, retaining evidence."""

import json

from parsetrail.core.ledger import LedgerError, identifier
from parsetrail.core.ledger_loan_payments import SUPPORTED_RULES, LoanPayments
from parsetrail.core.ledger_opening_review import observation_date_provenance
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import validate_window

RULE = "loan-bank-match-correction-1"


class LoanPaymentCorrections:
    def __init__(self, review):
        self.review, self.store = review, review.store
        self.payments = LoanPayments(review)

    def decisions(self):
        c = self.store.connection
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='LoanPaymentCorrections'").fetchone():
            return {}
        return {
            previous: json.loads(payload)
            for previous, payload in c.execute("SELECT previous_hash,payload FROM LoanPaymentCorrections")
        }

    def _history(self, payment_id):
        first = self.payments.decisions().get(payment_id)
        if not first:
            raise LedgerError("Choose a confirmed loan payment.")
        decisions = self.decisions()
        history, seen = [first], set()
        while history[-1]["preview_hash"] in decisions:
            previous = history[-1]
            if previous["preview_hash"] in seen:
                raise LedgerError("Loan correction history contains a cycle.")
            seen.add(previous["preview_hash"])
            correction = decisions[previous["preview_hash"]]
            if correction["previous"] != previous or correction["payment_id"] != payment_id:
                raise LedgerError("Loan correction history conflicts with the original decision.")
            history.append(correction["replacement"])
        return history

    def histories(self):
        with self.payments._snapshot():
            return {tid: self._history(tid) for tid in self.payments.decisions()}

    def _active(self, payment_id):
        previous = self._history(payment_id)[-1]
        if previous["rule"] not in SUPPORTED_RULES:
            raise LedgerError("Earlier category-choice test decisions require a fresh fixed-category workspace.")
        if any(
            not self.store._existing(decode_entry(encoded(e))) or self.store.entry_status(e["key"])["superseded"]
            for e in previous["entries"]
        ):
            raise LedgerError("The saved loan bundle is missing or already corrected outside this workflow.")
        return previous

    def candidates(self, payment_id, window_days=7):
        validate_window(window_days)
        with self.payments._snapshot():
            previous = self._active(payment_id)
            _, cash_ids, pending, raw = self.payments._context()
            observations, accounts, used = self.store.observations(), self.store.accounts(), self.store.consumed()
            incoming = observations["source:" + payment_id]
            dates = observation_date_provenance(self.store)
            rows = []
            for oid in sorted(cash_ids):
                o = observations[oid]
                if (
                    -o.amount_minor != incoming.amount_minor
                    or abs((o.posting_date - incoming.posting_date).days) > window_days
                ):
                    continue
                blockers = []
                if oid == previous["outgoing_id"]:
                    blockers.append("Current bank match")
                elif used.get(oid):
                    blockers.append("Bank movement is already allocated")
                if oid in pending:
                    blockers.append("Reject the pending expense/refund interpretation first")
                sources = self.store.connection.execute(
                    "SELECT f.payload FROM SourceMemberships m JOIN SourceStatements s ON s.id=m.statement_id JOIN SourceFiles f ON f.id=s.source_id WHERE m.transaction_id=?",
                    (oid.removeprefix("source:"),),
                ).fetchall()
                rows.append(
                    {
                        "outgoing_id": oid,
                        "account": accounts[o.account_id].name,
                        "date": str(o.posting_date),
                        "amount_minor": -o.amount_minor,
                        "description": raw[oid.removeprefix("source:")]["Description"],
                        "date_provenance": dates.get(oid, "unknown"),
                        "blockers": blockers,
                        "sources": [json.loads(s[0]).get("filename", "Retained bank source") for s in sources],
                    }
                )
            return rows

    def preview(self, payment_id, outgoing_id, reason, window_days=7):
        with self.payments._snapshot():
            return self._build(payment_id, outgoing_id, reason, window_days)

    def _build(self, payment_id, outgoing_id, reason, window_days):
        identifier(reason)
        reason = reason.strip()
        previous = self._active(payment_id)
        if outgoing_id == previous["outgoing_id"]:
            raise LedgerError("Choose a different bank movement; the match is unchanged.")
        replacement = self.payments._build(outgoing_id, payment_id, reason, window_days, correcting=previous)
        for field in (
            "source_basis",
            "new_observations",
            "interest_minor",
            "principal_reduction_minor",
            "interest_account_id",
        ):
            if replacement[field] != previous[field]:
                raise LedgerError("Loan components changed; this workflow only corrects the bank match.")
        before = self.store.observations()[previous["outgoing_id"]]
        after = self.store.observations()[outgoing_id]
        plan = {
            "rule": RULE,
            "candidate_hash": key(self.review.plan),
            "payment_id": payment_id,
            "previous": previous,
            "replacement": replacement,
            "reason": reason,
            "window_days": window_days,
            "cash_effect": {
                "released_account_id": before.account_id,
                "released_date": str(before.posting_date),
                "replacement_account_id": after.account_id,
                "replacement_date": str(after.posting_date),
                "amount_minor": -after.amount_minor,
            },
        }
        return {**plan, "preview_hash": key(plan)}

    def apply(self, plan):
        if (
            plan.get("rule") != RULE
            or plan.get("candidate_hash") != key(self.review.plan)
            or plan.get("preview_hash") != key({k: v for k, v in plan.items() if k != "preview_hash"})
        ):
            raise LedgerError("Loan correction preview changed or belongs to different evidence.")
        c = self.store.connection
        with self.store._transaction():
            previous = plan["previous"]["preview_hash"]
            saved = self.decisions().get(previous)
            if saved and saved != plan:
                raise LedgerError("This loan match already has a different correction.")
            if not saved:
                fresh = self._build(
                    plan["payment_id"], plan["replacement"]["outgoing_id"], plan["reason"], plan["window_days"]
                )
                if fresh != plan:
                    raise LedgerError("Loan match changed since preview; review a fresh correction.")
                for a in plan["replacement"]["accounts"]:
                    if not c.execute("SELECT 1 FROM LedgerAccounts WHERE id=?", (a["id"],)).fetchone():
                        c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (a["id"], None, encoded(a)))
            result = self.store._correct_bundle(
                plan["preview_hash"],
                [e["key"] for e in plan["previous"]["entries"]],
                [decode_entry(encoded(e)) for e in plan["replacement"]["entries"]],
                reason=plan["reason"],
            )
            if not saved:
                c.execute("""CREATE TABLE IF NOT EXISTS LoanPaymentCorrections(previous_hash TEXT PRIMARY KEY,
                    payment_id TEXT NOT NULL REFERENCES LoanPaymentDecisions(payment_id), payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
                for action in ("UPDATE", "DELETE"):
                    c.execute(
                        f"CREATE TRIGGER IF NOT EXISTS LoanPaymentCorrections_{action} BEFORE {action} ON LoanPaymentCorrections BEGIN SELECT RAISE(ABORT,'Loan corrections are immutable'); END"
                    )
                c.execute(
                    "INSERT INTO LoanPaymentCorrections(previous_hash,payment_id,payload) VALUES(?,?,?)",
                    (previous, plan["payment_id"], encoded(plan)),
                )
            return result
