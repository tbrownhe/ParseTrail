"""Append-only source assertions and atomic reviewed opening positions."""

import json
from dataclasses import asdict, replace
from datetime import date, timedelta
from pathlib import Path

from parsetrail.core.ledger import (
    AccountKind,
    JournalEntry,
    LedgerAccount,
    LedgerError,
    Posting,
    identifier,
    validate_entry,
)
from parsetrail.core.ledger_openings import DATE_LIMITATIONS, RULE
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reconciliation import StatementEvidence
from parsetrail.core.ledger_store import decode_entry, encoded
from parsetrail.core.recovery_bundle import digest

OPENING_REASON = "Confirmed source-backed opening position"


def observation_date_provenance(store):
    """Conservative date labels for existing review consumers, including older copies."""
    c = store.connection
    files = {fid: json.loads(payload).get("plugin") for fid, payload in c.execute("SELECT id,payload FROM SourceFiles")}
    basis = {
        sid: "estimated" if files[fid] in DATE_LIMITATIONS else "unknown"
        for sid, fid in c.execute("SELECT id,source_id FROM SourceStatements")
    }
    fixed_estimates = {sid for sid, value in basis.items() if value == "estimated"}
    tables = {name for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "SourceAssertions" in tables:
        for sid, payload in c.execute("SELECT statement_id,payload FROM SourceAssertions ORDER BY sequence"):
            if sid not in fixed_estimates:
                basis[sid] = json.loads(payload)["posting_dates"]
    memberships = {}
    for tid, sid in c.execute("SELECT transaction_id,statement_id FROM SourceMemberships"):
        memberships.setdefault(f"source:{tid}", set()).add(basis[sid])
    return {
        oid: "estimated" if "estimated" in values else "reported" if values == {"reported"} else "unknown"
        for oid, values in memberships.items()
    }


class OpeningReview:
    """Only operates inside an explicitly prepared disposable ProposalReview."""

    def __init__(self, review, readiness_folder: Path | None = None):
        self.review, self.store = review, review.store
        c = self.store.connection
        self.sources = {
            sid: json.loads(payload) for sid, payload in c.execute("SELECT id,payload FROM SourceStatements")
        }
        self.files = {fid: json.loads(payload) for fid, payload in c.execute("SELECT id,payload FROM SourceFiles")}
        if readiness_folder is not None:
            report = json.loads((readiness_folder / "report.json").read_text(encoding="utf-8"))
            path = readiness_folder / "readiness.json"
            if digest(path) != report["readiness_sha256"]:
                raise LedgerError("Opening readiness artifact changed.")
            plan = json.loads(path.read_text(encoding="utf-8"))
            self._validate_plan(plan)
            with self.store._transaction():
                c.execute("CREATE TABLE IF NOT EXISTS OpeningPlans(id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
                prior = c.execute("SELECT id,payload FROM OpeningPlans").fetchall()
                if prior and prior != [(key(plan), encoded(plan))]:
                    raise LedgerError("Workspace already belongs to a different opening plan.")
                if not prior:
                    c.execute("INSERT INTO OpeningPlans VALUES(?,?)", (key(plan), encoded(plan)))
                c.execute("""CREATE TABLE IF NOT EXISTS SourceDateProvenance(
                    statement_id TEXT PRIMARY KEY REFERENCES SourceStatements(id), basis TEXT NOT NULL,
                    reason TEXT NOT NULL)""")
                for s in review.plan["statements"]:
                    sid = s["id"].removeprefix("statement:")
                    plugin = self.files[self.sources[sid]["source"]]["plugin"]
                    basis = "estimated" if plugin in DATE_LIMITATIONS else "unknown"
                    reason = DATE_LIMITATIONS.get(plugin, "Bank posting dates have not been independently reviewed.")
                    c.execute("INSERT OR IGNORE INTO SourceDateProvenance VALUES(?,?,?)", (sid, basis, reason))
                c.execute("""CREATE TABLE IF NOT EXISTS SourceAssertions(
                    sequence INTEGER PRIMARY KEY, statement_id TEXT NOT NULL REFERENCES SourceStatements(id),
                    payload TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')))""")
                c.execute("""CREATE TABLE IF NOT EXISTS OpeningDecisions(
                    account_id TEXT PRIMARY KEY REFERENCES LedgerAccounts(id), opening_date TEXT NOT NULL,
                    amount INTEGER NOT NULL, provenance_hash TEXT NOT NULL, reason TEXT NOT NULL,
                    entry_key TEXT UNIQUE REFERENCES LedgerEntries(key),
                    created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                    CHECK((amount=0 AND entry_key IS NULL) OR (amount!=0 AND entry_key IS NOT NULL)))""")
                for table in ("OpeningPlans", "SourceDateProvenance", "SourceAssertions", "OpeningDecisions"):
                    for action in ("UPDATE", "DELETE"):
                        c.execute(
                            f"CREATE TRIGGER IF NOT EXISTS {table}_{action} BEFORE {action} ON {table} "
                            "BEGIN SELECT RAISE(ABORT,'Opening review history is immutable'); END"
                        )
        plans = c.execute("SELECT id,payload FROM OpeningPlans").fetchall()
        if len(plans) != 1 or key(json.loads(plans[0][1])) != plans[0][0]:
            raise LedgerError("Opening workspace plan is missing or changed.")
        self.plan = json.loads(plans[0][1])
        self._validate_plan(self.plan)
        self.anchors = {f"account:{a['account_id']}": a for a in self.plan["anchors"]}

    def _validate_plan(self, plan):
        if plan["rule"] != RULE:
            raise LedgerError("Unsupported opening readiness rule.")
        if plan["candidate_hash"] != key(self.review.plan) or plan["rebuild_hash"] != self.review.plan["rebuild_hash"]:
            raise LedgerError("Opening plan belongs to different source evidence.")
        expected_accounts = {
            int(a["source_account_id"]) for a in self.review.plan["accounts"] if a["source_account_id"] is not None
        }
        if {a["account_id"] for a in plan["anchors"]} != expected_accounts or len(plan["anchors"]) != len(
            expected_accounts
        ):
            raise LedgerError("Opening plan account scope differs from the candidate plan.")
        for anchor in plan["anchors"]:
            rows = [s for s in self.sources.values() if s["account_id"] == anchor["account_id"]]
            start = min((s["start"] for s in rows), default=None)
            first = [s for s in rows if s["start"] == start]
            amounts = {s["opening_minor"] for s in first}
            amount = next(iter(amounts)) if len(amounts) == 1 else None
            day = (date.fromisoformat(start) - timedelta(days=1)).isoformat() if start else None
            if (
                set(anchor["statement_ids"]) != {s["id"] for s in first}
                or anchor["proposed_amount_minor"] != amount
                or anchor["proposed_date"] != day
            ):
                raise LedgerError("Opening proposal differs from its earliest source evidence.")

    def provenance(self, sid):
        baseline = self.store.connection.execute(
            "SELECT basis,reason FROM SourceDateProvenance WHERE statement_id=?", (sid,)
        ).fetchone()
        if not baseline:
            raise LedgerError("Statement is outside the eligible source-review scope.")
        row = self.store.connection.execute(
            "SELECT sequence,payload FROM SourceAssertions WHERE statement_id=? ORDER BY sequence DESC LIMIT 1", (sid,)
        ).fetchone()
        if row:
            return {**json.loads(row[1]), "sequence": row[0]}
        return {
            "sequence": None,
            "opening": "assumed",
            "closing": "assumed",
            "timing_confirmed": False,
            "posting_dates": baseline[0],
            "reference": "",
            "reason": baseline[1],
            "source_hash": key(self.sources[sid]),
        }

    def assert_source(self, sid, *, opening, closing, timing_confirmed, posting_dates, reference, reason):
        """Record a user's source assertion, not an automatic certification."""
        identifier(reference)
        identifier(reason)
        if (
            opening not in {"reported", "derived", "assumed"}
            or closing not in {"reported", "derived", "assumed"}
            or type(timing_confirmed) is not bool
            or posting_dates not in {"reported", "estimated", "unknown"}
        ):
            raise LedgerError("Source provenance and timing must be explicit supported values.")
        c = self.store.connection
        with self.store._transaction():
            previous = self.provenance(sid)
            baseline = c.execute("SELECT basis FROM SourceDateProvenance WHERE statement_id=?", (sid,)).fetchone()[0]
            if baseline == "estimated" and posting_dates != "estimated":
                raise LedgerError(
                    "Known posting-date proxies must remain estimated; corrected source evidence needs a separate workflow."
                )
            payload = {
                "opening": opening,
                "closing": closing,
                "timing_confirmed": timing_confirmed,
                "posting_dates": posting_dates,
                "reference": reference.strip(),
                "reason": reason.strip(),
                "source_hash": key(self.sources[sid]),
            }
            if {k: v for k, v in previous.items() if k != "sequence"} != payload:
                c.execute("INSERT INTO SourceAssertions(statement_id,payload) VALUES(?,?)", (sid, encoded(payload)))

    def effective_statement(self, sid):
        """Reviewed view only. Raw kernel statement/provenance are never rewritten.

        Callers must retain provenance(sid).posting_dates for date-sensitive use.
        This accessor does not certify reconciliation or coverage.
        """
        provenance = self.provenance(sid)
        row = self.store.connection.execute(
            "SELECT payload FROM LedgerStatements WHERE id=?", (f"statement:{sid}",)
        ).fetchone()
        if not row:
            raise LedgerError("Kernel statement is not available.")
        payload = json.loads(row[0])
        payload.update(
            start_date=date.fromisoformat(payload["start_date"]),
            end_date=date.fromisoformat(payload["end_date"]),
            observation_ids=tuple(payload["observation_ids"]),
        )
        statement = StatementEvidence(**payload)
        if provenance["timing_confirmed"]:
            statement = replace(
                statement, opening_provenance=provenance["opening"], closing_provenance=provenance["closing"]
            )
        return statement

    def decisions(self):
        return {
            aid: {
                "date": day,
                "amount_minor": amount,
                "provenance_hash": basis,
                "reason": reason,
                "entry_key": entry,
                "created_at": when,
            }
            for aid, day, amount, basis, reason, entry, when in self.store.connection.execute(
                "SELECT * FROM OpeningDecisions"
            )
        }

    def status(self, account_id):
        anchor = self.anchors[account_id]
        blockers = [b for b in anchor["blockers"] if b != "source_balance_and_timing_review_required"]
        assertions = []
        for sid in anchor["statement_ids"]:
            if self.store.connection.execute(
                "SELECT 1 FROM SourceDateProvenance WHERE statement_id=?", (sid,)
            ).fetchone():
                p = self.provenance(sid)
                assertions.append((sid, p))
                if p["opening"] != "reported" or not p["timing_confirmed"]:
                    blockers.append("source_balance_and_timing_review_required")
            else:
                blockers.append("earliest_statement_not_eligible")
        basis = key(assertions)
        decision = self.decisions().get(account_id)
        if decision:
            state = (
                "stale_source_review"
                if decision["provenance_hash"] != basis or blockers
                else "confirmed_zero"
                if decision["amount_minor"] == 0
                else "posted"
            )
        else:
            state = "blocked" if blockers else "ready_for_confirmation"
        return {"state": state, "blockers": sorted(set(blockers)), "provenance_hash": basis, "decision": decision}

    def confirm_opening(self, account_id, reason=OPENING_REASON, *, expected_provenance_hash=None):
        identifier(reason)
        c, store = self.store.connection, self.store
        with store._transaction():
            if account_id not in self.anchors:
                raise LedgerError("Opening account is outside this review plan.")
            anchor, state = self.anchors[account_id], self.status(account_id)
            if expected_provenance_hash is not None and expected_provenance_hash != state["provenance_hash"]:
                raise LedgerError("Source review changed since selection. Refresh before confirming the opening.")
            if state["decision"]:
                if state["state"] in {"posted", "confirmed_zero"} and state["decision"]["reason"] == reason:
                    return
                raise LedgerError("Opening already recorded; changed evidence or interpretation requires a correction.")
            if state["state"] != "ready_for_confirmation":
                raise LedgerError(
                    "Opening is blocked until its earliest printed balance and inclusive-period timing are reviewed."
                )
            amount, day = anchor["proposed_amount_minor"], date.fromisoformat(anchor["proposed_date"])
            # Do not use an opening to offset earlier postings or to book another opening.
            for (payload,) in c.execute("SELECT payload FROM LedgerEntries"):
                entry = decode_entry(payload)
                if any(p.account_id == account_id for p in entry.postings) and (
                    entry.posting_date <= day or entry.origin == "opening"
                ):
                    raise LedgerError(
                        "Earlier postings or an existing opening require separate reconciliation/correction."
                    )
            entry_key = None
            if amount:
                accounts = store.accounts()
                equity = LedgerAccount("equity:opening", "Opening equity", AccountKind.EQUITY, purpose="opening_equity")
                if equity.id in accounts and accounts[equity.id] != equity:
                    raise LedgerError("Opening equity account mapping conflicts.")
                if equity.id not in accounts:
                    c.execute("INSERT INTO LedgerAccounts VALUES(?,?,?)", (equity.id, None, encoded(asdict(equity))))
                    accounts[equity.id] = equity
                entry_key = "opening:" + key([key(self.plan), account_id])
                entry = JournalEntry(
                    entry_key,
                    entry_key,
                    day,
                    "Reviewed opening position",
                    (Posting(account_id, amount), Posting(equity.id, -amount)),
                    origin="opening",
                    reviewed=True,
                    reason=reason,
                )
                if store._existing(entry):
                    raise LedgerError("Opening posting exists without its decision.")
                usage = validate_entry(entry, accounts, store.observations(), store.consumed())
                store._insert(entry, usage)
            c.execute(
                "INSERT INTO OpeningDecisions(account_id,opening_date,amount,provenance_hash,reason,entry_key) VALUES(?,?,?,?,?,?)",
                (account_id, day.isoformat(), amount, state["provenance_hash"], reason, entry_key),
            )
