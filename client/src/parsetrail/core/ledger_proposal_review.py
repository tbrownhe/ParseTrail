"""Explicit ordinary-proposal decisions, isolated from the active client profile."""

import json
import shutil
from dataclasses import replace
from pathlib import Path

from parsetrail.core.ledger import LedgerError, identifier, validate_entry
from parsetrail.core.ledger_candidates import apply_candidates
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_store import LedgerStore, decode_entry, encoded
from parsetrail.core.recovery_bundle import digest

DEFAULT_ACCEPTANCE_REASON = "Accepted as ordinary expense/refund"


def prepare_review(candidates: Path, output: Path) -> Path:
    """Create a separately writable review copy; refuse overwrites and active inputs."""
    source = candidates / "candidates.db"
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise LedgerError("Use an inactive proposal database.")
    report = json.loads((candidates / "report.json").read_text(encoding="utf-8"))
    expected = {source: report["database_sha256"], candidates / "proposals.json": report["proposal_sha256"]}
    if any(digest(path) != checksum for path, checksum in expected.items()):
        raise LedgerError("Proposal artifacts have changed since verification.")
    plan = json.loads((candidates / "proposals.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    target = output / "review.db"
    shutil.copyfile(source, target)
    if digest(target) != expected[source]:
        raise LedgerError("Proposal database changed while copying.")
    with LedgerStore(target) as store:
        if store.connection.execute("SELECT id,payload FROM JournalProposalPlans").fetchall() != [
            (key(plan), encoded(plan))
        ]:
            raise LedgerError("Proposal database does not belong to this plan.")
        apply_candidates(store, plan)
        with store._transaction():
            store.connection.execute(
                "CREATE TABLE ProposalReviewMeta(version INTEGER PRIMARY KEY, proposal_hash TEXT NOT NULL, source_hash TEXT NOT NULL)"
            )
            store.connection.execute("INSERT INTO ProposalReviewMeta VALUES(1,?,?)", (key(plan), expected[source]))
            store.connection.execute("""CREATE TABLE ProposalDecisions(
                proposal_id TEXT PRIMARY KEY REFERENCES JournalProposals(id),
                action TEXT NOT NULL CHECK(action IN ('accepted','rejected')), reason TEXT NOT NULL,
                entry_key TEXT UNIQUE REFERENCES LedgerEntries(key),
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
                CHECK((action='accepted' AND entry_key IS NOT NULL) OR (action='rejected' AND entry_key IS NULL)))""")
            for table in ("ProposalReviewMeta", "ProposalDecisions"):
                for action in ("UPDATE", "DELETE"):
                    store.connection.execute(
                        f"CREATE TRIGGER {table}_{action} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT,'Proposal decisions are immutable'); END"
                    )
    if any(digest(path) != checksum for path, checksum in expected.items()):
        raise LedgerError("Source changed during review preparation.")
    (output / "review.json").write_text(
        encoded({"version": 1, "proposal_hash": key(plan), "source_hash": expected[source]}), encoding="utf-8"
    )
    return target


class ProposalReview:
    """Open only a prepared review folder. Decisions and postings commit together."""

    def __init__(self, folder: Path):
        manifest = json.loads((folder / "review.json").read_text(encoding="utf-8"))
        if manifest.get("version") != 1:
            raise LedgerError("Unsupported proposal review workspace version.")
        self.store = LedgerStore(folder / "review.db")
        try:
            c = self.store.connection
            if c.execute("SELECT version,proposal_hash,source_hash FROM ProposalReviewMeta").fetchall() != [
                (1, manifest["proposal_hash"], manifest["source_hash"])
            ]:
                raise LedgerError("Review database does not belong to this workspace.")
            if (
                c.execute("PRAGMA integrity_check").fetchall() != [("ok",)]
                or c.execute("PRAGMA foreign_key_check").fetchall()
            ):
                raise LedgerError("Review database integrity check failed.")
            plans = c.execute("SELECT id,payload FROM JournalProposalPlans").fetchall()
            if (
                len(plans) != 1
                or plans[0][0] != manifest["proposal_hash"]
                or key(json.loads(plans[0][1])) != plans[0][0]
            ):
                raise LedgerError("Review proposal plan changed.")
            self.plan = json.loads(plans[0][1])
            self.proposals = dict(c.execute("SELECT id,payload FROM JournalProposals"))
            if self.proposals != {p["key"]: encoded(p) for p in self.plan["proposals"]}:
                raise LedgerError("Review proposals differ from their verified plan.")
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.store.connection.close()

    def decisions(self) -> dict:
        return {
            pid: {"action": action, "reason": reason, "entry_key": entry, "created_at": when}
            for pid, action, reason, entry, when in self.store.connection.execute("SELECT * FROM ProposalDecisions")
        }

    def decide(self, proposal_ids: list[str], action: str, reason: str = "") -> None:
        """Accept/post or reject the entire batch. Exact retries do not duplicate history."""
        if isinstance(reason, str):
            reason = reason.strip()
            if action == "accepted" and not reason:
                reason = DEFAULT_ACCEPTANCE_REASON
        identifier(reason)
        if action not in {"accepted", "rejected"} or not proposal_ids or len(set(proposal_ids)) != len(proposal_ids):
            raise LedgerError("Choose distinct proposals and an explicit accept or reject decision.")
        store = self.store
        with store._transaction():
            decisions = self.decisions()
            accounts, observations, used = store.accounts(), store.observations(), store.consumed()
            for pid in proposal_ids:
                row = store.connection.execute("SELECT payload FROM JournalProposals WHERE id=?", (pid,)).fetchone()
                if row is None or row[0] != self.proposals.get(pid):
                    raise LedgerError("Selected proposal is missing or has changed. Refresh the review.")
                if pid in decisions:
                    if (decisions[pid]["action"], decisions[pid]["reason"]) == (action, reason):
                        continue
                    raise LedgerError(
                        "A selected proposal already has a decision. Posted changes require a correction."
                    )
                entry_key = None
                if action == "accepted":
                    draft = decode_entry(row[0])
                    entry = replace(draft, key=f"accepted:{pid}", reviewed=True, reason=reason)
                    if store._existing(entry):
                        raise LedgerError("Posting exists without its proposal decision.")
                    usage = validate_entry(entry, accounts, observations, used)
                    # Use the kernel insertion primitive inside this decision transaction.
                    store._insert(entry, usage)
                    for oid, amount in usage.items():
                        used[oid] = used.get(oid, 0) + amount
                    entry_key = entry.key
                store.connection.execute(
                    "INSERT INTO ProposalDecisions(proposal_id,action,reason,entry_key) VALUES(?,?,?,?)",
                    (pid, action, reason, entry_key),
                )
