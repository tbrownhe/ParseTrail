"""Explicit source-contracted loan payment/interest bundles; no inferred openings."""

import json
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import date

from parsetrail.core.ledger import (
    AccountKind,
    Allocation,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Observation,
    Posting,
    identifier,
    validate_entry,
)
from parsetrail.core.ledger_categories import LOAN_INTEREST
from parsetrail.core.ledger_opening_review import observation_date_provenance
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.ledger_transfers import TransferReview, validate_window

RULE = "capital-one-loan-payments-2"
WF_RULE = "wells-fargo-loan-payments-1"
PAYMENT_CONTRACTS = {
    ("pdf_capitaloneauto_202402", "0.2.1"): {
        "rule": RULE,
        "name": "Capital One Auto",
        "payment": "Payment Received",
        "interest": "Interest Fee",
        "balance_basis": "Opening principal is derived from closing principal and activity; not independent reconciliation.",
        "period_basis": "Printed transaction-history range; boundary timing remains unreviewed.",
        "component_basis": "Payment total and separate interest component; interest is recognized once.",
    },
    ("pdf_wfloanper_202306", "0.2.0"): {
        "rule": WF_RULE,
        "name": "Wells Fargo Personal Loan",
        "payment": "PAYMENT",
        "interest": "INTEREST PAYMENT",
        "balance_basis": "Printed prior/ending principal for ordinary statements; balances remain unreviewed.",
        "period_basis": "Parser assumes a 31-day statement period; coverage is not established.",
        "component_basis": "Payment combines same-date principal and interest. Separate extra-principal rows and synthetic origination stay outside this workflow.",
    },
}
SUPPORTED_RULES = frozenset(c["rule"] for c in PAYMENT_CONTRACTS.values())
DEFAULT_REASON = "Confirmed loan payment and separately evidenced interest"


def payment_contract(bundle):
    source = bundle["sources"][0]["file"]
    return PAYMENT_CONTRACTS[(source["plugin"], source["version"])]


class LoanPayments:
    def __init__(self, review):
        self.review, self.store = review, review.store

    @contextmanager
    def _snapshot(self):
        c = self.store.connection
        if c.in_transaction:
            raise LedgerError("Loan preview requires a committed read snapshot.")
        c.execute("BEGIN")
        try:
            yield
        finally:
            c.execute("ROLLBACK")

    def decisions(self):
        c = self.store.connection
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='LoanPaymentDecisions' AND type='table'").fetchone():
            return {}
        return {
            tid: json.loads(payload)
            for tid, payload in c.execute("SELECT payment_id,payload FROM LoanPaymentDecisions")
        }

    def _context(self):
        c = self.store.connection
        metadata = {
            name: json.loads(payload) for name, payload in c.execute("SELECT name,payload FROM RetainedMetadata")
        }
        types = {r["AccountTypeID"]: r for r in metadata["AccountTypes"]}
        loan_ids = {
            r["AccountID"]
            for r in metadata["Accounts"]
            if types[r["AccountTypeID"]]["AccountType"] == "Loan"
            and types[r["AccountTypeID"]]["AssetType"] == "Debt"
            and r["CurrencyCode"] == "USD"
        }
        rows = {tid: json.loads(payload) for tid, payload in c.execute("SELECT id,payload FROM SourceTransactions")}
        statements = {sid: json.loads(payload) for sid, payload in c.execute("SELECT id,payload FROM SourceStatements")}
        files = {fid: json.loads(payload) for fid, payload in c.execute("SELECT id,payload FROM SourceFiles")}
        members, sources = defaultdict(list), defaultdict(set)
        for sid, tid in c.execute("SELECT statement_id,transaction_id FROM SourceMemberships"):
            if statements[sid]["account_id"] != rows[tid]["AccountID"]:
                raise LedgerError("Loan evidence has inconsistent source ownership.")
            members[sid].append(tid)
            sources[tid].add(sid)
        eligible = {}
        for sid, s in statements.items():
            f = files[s["source"]]
            ids = members[sid]
            contract_key = (f.get("plugin"), f.get("version"))
            if (
                s["account_id"] in loan_ids
                and contract_key in PAYMENT_CONTRACTS
                and f["status"] == s["status"] == "parsed"
                and not any(rows[t]["Description"] == "LOAN ORIGINATION" for t in ids)
                and len(ids) == len(set(ids))
                and all(
                    rows[t]["CurrencyCode"] == "USD" and s["start"] <= rows[t]["PostingDate"] <= s["end"] for t in ids
                )
                and s["closing_minor"] - s["opening_minor"] == sum(rows[t]["AmountMinor"] for t in ids)
            ):
                eligible[sid] = contract_key
        admitted = {
            tid
            for tid in rows
            if sources[tid] and sources[tid] <= eligible.keys() and len({eligible[sid] for sid in sources[tid]}) == 1
        }
        bundles = {}
        interest_usage = Counter()
        for tid in sorted(admitted):
            p = rows[tid]
            contract_key = eligible[next(iter(sources[tid]))]
            contract = PAYMENT_CONTRACTS[contract_key]
            if p["Description"] != contract["payment"] or p["AmountMinor"] <= 0:
                continue
            interest = sorted(
                t
                for t in admitted
                if rows[t]["AccountID"] == p["AccountID"]
                and rows[t]["PostingDate"] == p["PostingDate"]
                and rows[t]["Description"] == contract["interest"]
                and eligible[next(iter(sources[t]))] == contract_key
                and sources[t] & sources[tid]
            )
            blockers = []
            if len(interest) != 1:
                blockers.append("Interest component is missing or ambiguous")
            elif rows[interest[0]]["AmountMinor"] > 0 or p["AmountMinor"] + rows[interest[0]]["AmountMinor"] < 0:
                blockers.append("Interest/principal signs require a separate interpretation")
            else:
                interest_usage[interest[0]] += 1
            source_ids = sorted(sources[tid] | {sid for t in interest for sid in sources[t]})
            bundles[tid] = {
                "payment": p,
                "interest": [rows[t] for t in interest],
                "blockers": blockers,
                "sources": [
                    {"statement": statements[sid], "file": files[statements[sid]["source"]]} for sid in source_ids
                ],
            }
        for bundle in bundles.values():
            if len(bundle["interest"]) == 1 and interest_usage[bundle["interest"][0]["id"]] > 1:
                bundle["blockers"].append("Interest component is shared by multiple possible payments")
        cash_accounts = {
            a["id"]
            for a in self.review.plan["accounts"]
            if a["source_account_id"] is not None and a["kind"] == AccountKind.ASSET
        }
        cash_ids = {
            o["id"]
            for o in self.review.plan["observations"]
            if o["account_id"] in cash_accounts and o["amount_minor"] < 0
        }
        pending = dict(
            c.execute(
                "SELECT p.observation_id,p.id FROM JournalProposals p LEFT JOIN ProposalDecisions d ON p.id=d.proposal_id WHERE d.proposal_id IS NULL"
            )
        )
        return bundles, cash_ids, pending, rows

    def snapshot(self, window_days=7):
        validate_window(window_days)
        with self._snapshot():
            bundles, cash_ids, pending, rows = self._context()
            observations, accounts, used = self.store.observations(), self.store.accounts(), self.store.consumed()
            decisions, dates = self.decisions(), observation_date_provenance(self.store)
            pairs, counts = [], Counter()
            for tid, b in bundles.items():
                p = b["payment"]
                for oid in sorted(cash_ids):
                    o = observations[oid]
                    if (
                        o.currency != "USD"
                        or -o.amount_minor != p["AmountMinor"]
                        or abs((o.posting_date - date.fromisoformat(p["PostingDate"])).days) > window_days
                    ):
                        continue
                    blockers = list(b["blockers"])
                    if oid in pending:
                        blockers.append("Reject the pending expense/refund interpretation first")
                    if any(used.get(x) for x in [oid, "source:" + tid, *("source:" + i["id"] for i in b["interest"])]):
                        blockers.append("A source movement is already allocated")
                    if tid in decisions:
                        blockers.append("Loan payment already confirmed")
                    counts[tid] += 1
                    counts[oid] += 1
                    pairs.append(
                        {
                            "payment_id": tid,
                            "outgoing_id": oid,
                            "bank": accounts[o.account_id].name,
                            "loan": accounts["account:" + str(p["AccountID"])].name,
                            "bank_date": str(o.posting_date),
                            "loan_date": p["PostingDate"],
                            "amount_minor": p["AmountMinor"],
                            "interest_minor": -b["interest"][0]["AmountMinor"] if len(b["interest"]) == 1 else None,
                            "blockers": blockers,
                            "bank_description": rows[oid.removeprefix("source:")]["Description"],
                            "date_provenance": [dates.get(oid, "unknown"), dates.get("source:" + tid, "unknown")],
                            "sources": b["sources"],
                            "source_contract": payment_contract(b),
                        }
                    )
            for pair in pairs:
                pair["alternatives"] = [counts[pair["outgoing_id"]], counts[pair["payment_id"]]]
            return {
                "pairs": pairs,
                "decisions": decisions,
                "unmatched_payment_ids": sorted(tid for tid in bundles if not counts[tid] and tid not in decisions),
                "components": bundles,
            }

    def preview(self, outgoing_id, payment_id, *, reason="", window_days=7):
        with self._snapshot():
            return self._build(outgoing_id, payment_id, reason, window_days)

    def _build(self, outgoing_id, payment_id, reason, window_days, *, correcting=None):
        validate_window(window_days)
        reason = reason.strip() or DEFAULT_REASON if isinstance(reason, str) else reason
        identifier(reason)
        bundles, cash_ids, pending, _ = self._context()
        if outgoing_id not in cash_ids or payment_id not in bundles:
            raise LedgerError("Choose eligible cash evidence and a supported loan payment.")
        bundle = bundles[payment_id]
        if bundle["blockers"]:
            raise LedgerError("; ".join(bundle["blockers"]))
        if outgoing_id in pending:
            raise LedgerError("Reject the pending ordinary expense/refund proposal before loan confirmation.")
        if payment_id in self.decisions() and correcting is None:
            raise LedgerError("Loan payment already confirmed; changes require a correction workflow.")
        accounts, observations, used = self.store.accounts(), self.store.observations(), self.store.consumed()
        if correcting is not None:
            for entry in correcting["entries"]:
                for oid, amount in self.store.connection.execute(
                    "SELECT observation_id,amount FROM LedgerAllocations WHERE entry_key=?", (entry["key"],)
                ):
                    used[oid] -= amount
        outgoing = observations[outgoing_id]
        payment, interest = bundle["payment"], bundle["interest"][0]
        incoming = Observation(
            "source:" + payment_id,
            "account:" + str(payment["AccountID"]),
            payment["AmountMinor"],
            date.fromisoformat(payment["PostingDate"]),
        )
        if accounts[incoming.account_id].kind != AccountKind.LIABILITY or accounts[
            incoming.account_id
        ].source_account_id != str(payment["AccountID"]):
            raise LedgerError("Loan account mapping conflicts with source ownership.")
        if (
            -outgoing.amount_minor != incoming.amount_minor
            or outgoing.currency != incoming.currency
            or abs((outgoing.posting_date - incoming.posting_date).days) > window_days
        ):
            raise LedgerError("Bank and loan payments must be exact opposites within the date window.")
        new_observations = [incoming]
        if interest["AmountMinor"]:
            new_observations.append(
                Observation(
                    "source:" + interest["id"], incoming.account_id, interest["AmountMinor"], incoming.posting_date
                )
            )
        if any(used.get(o.id) for o in [outgoing, *new_observations]):
            raise LedgerError("A loan or cash source movement is already allocated.")
        for o in new_observations:
            o.validate(accounts)
            if o.id in observations and o != observations[o.id]:
                raise LedgerError("Loan observation conflicts with retained evidence.")
            observations[o.id] = o
        mappings, interest_postings = [], []
        if interest["AmountMinor"]:
            if LOAN_INTEREST.id in accounts and accounts[LOAN_INTEREST.id] != LOAN_INTEREST:
                raise LedgerError("Fixed loan interest account conflicts with its required mapping.")
            mappings = [asdict(LOAN_INTEREST)]
            interest_postings = [Posting(LOAN_INTEREST.id, -interest["AmountMinor"])]
        request = {
            "rule": payment_contract(bundle)["rule"],
            "outgoing_id": outgoing_id,
            "payment_id": payment_id,
            "interest_account_id": LOAN_INTEREST.id if interest_postings else None,
            "reason": reason,
            "window_days": window_days,
        }
        if correcting is not None:
            request["previous_hash"] = correcting["preview_hash"]
        revision = "loan-payment:" + key(request)
        event = correcting["entries"][0]["event_id"] if correcting is not None else revision
        transfers, clearing = TransferReview.entries(outgoing, incoming, "card_payment", reason)
        entries = [
            replace(e, key=f"{revision}:payment:{i}", event_id=event, description="Confirmed loan payment")
            for i, e in enumerate(transfers)
        ]
        if interest_postings:
            o = new_observations[1]
            entries.append(
                JournalEntry(
                    revision + ":interest",
                    event,
                    o.posting_date,
                    "Confirmed loan interest component",
                    (Posting(o.account_id, o.amount_minor, (Allocation(o.id, o.amount_minor),)), *interest_postings),
                    reviewed=True,
                    reason=reason,
                )
            )
        if clearing:
            if clearing.id in accounts and accounts[clearing.id] != clearing:
                raise LedgerError("Loan payment clearing mapping conflicts.")
            mappings.append(asdict(clearing))
        for mapping in mappings:
            accounts[mapping["id"]] = LedgerAccount(**{**mapping, "kind": AccountKind(mapping["kind"])})
        for entry in entries:
            for oid, amount in validate_entry(entry, accounts, observations, used).items():
                used[oid] = used.get(oid, 0) + amount
        dates = observation_date_provenance(self.store)
        plan = json.loads(
            encoded(
                {
                    **request,
                    "candidate_hash": key(self.review.plan),
                    "source_basis": bundle,
                    "new_observations": [{**asdict(o), "posting_date": str(o.posting_date)} for o in new_observations],
                    "accounts": mappings,
                    "entries": [e.payload() for e in entries],
                    "interest_minor": -interest["AmountMinor"],
                    "principal_reduction_minor": incoming.amount_minor + interest["AmountMinor"],
                    "date_provenance": [dates.get(o.id, "unknown") for o in [outgoing, *new_observations]],
                }
            )
        )
        return {**plan, "preview_hash": key(plan)}

    def apply(self, plan):
        if (
            plan.get("rule") not in SUPPORTED_RULES
            or plan.get("candidate_hash") != key(self.review.plan)
            or plan.get("preview_hash") != key({k: v for k, v in plan.items() if k != "preview_hash"})
        ):
            raise LedgerError("Loan preview changed or belongs to different evidence.")
        c = self.store.connection
        with self.store._transaction():
            existing = self.decisions().get(plan["payment_id"])
            if existing:
                if existing == plan and all(self.store._existing(decode_entry(encoded(e))) for e in plan["entries"]):
                    return [e["key"] for e in plan["entries"]]
                raise LedgerError("Loan payment already has a different confirmation.")
            fresh = self._build(*(plan[k] for k in ("outgoing_id", "payment_id", "reason", "window_days")))
            if fresh != plan:
                raise LedgerError("Loan inputs changed since preview; review a fresh preview.")
            c.execute("""CREATE TABLE IF NOT EXISTS LoanPaymentDecisions(payment_id TEXT PRIMARY KEY REFERENCES SourceTransactions(id),
                payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
            for action in ("UPDATE", "DELETE"):
                c.execute(
                    f"CREATE TRIGGER IF NOT EXISTS LoanPaymentDecisions_{action} BEFORE {action} ON LoanPaymentDecisions BEGIN SELECT RAISE(ABORT,'Loan decisions are immutable'); END"
                )
            for a in plan["accounts"]:
                if not c.execute("SELECT 1 FROM LedgerAccounts WHERE id=?", (a["id"],)).fetchone():
                    c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (a["id"], None, encoded(a)))
            for o in plan["new_observations"]:
                if not c.execute("SELECT 1 FROM LedgerObservations WHERE id=?", (o["id"],)).fetchone():
                    c.execute("INSERT INTO LedgerObservations VALUES(?,?,?)", (o["id"], o["account_id"], encoded(o)))
            accounts, observations, used = self.store.accounts(), self.store.observations(), self.store.consumed()
            for payload in plan["entries"]:
                entry = decode_entry(encoded(payload))
                if self.store._existing(entry):
                    raise LedgerError("Loan posting exists without its decision.")
                usage = validate_entry(entry, accounts, observations, used)
                self.store._insert(entry, usage)
                for oid, amount in usage.items():
                    used[oid] = used.get(oid, 0) + amount
            c.execute(
                "INSERT INTO LoanPaymentDecisions(payment_id,payload) VALUES(?,?)", (plan["payment_id"], encoded(plan))
            )
            return [e["key"] for e in plan["entries"]]
