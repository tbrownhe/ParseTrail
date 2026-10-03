"""Read-only, versioned reconciliation of reviewed cash/card source evidence."""

from collections import Counter
from contextlib import contextmanager

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_opening_review import OpeningReview, observation_date_provenance
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reconciliation import evaluate_statement
from parsetrail.core.ledger_store import decode_entry

RULE = "reviewed-reconciliation-1"
VERSION_TABLES = (
    "JournalProposalPlans",
    "OpeningPlans",
    "SourceFiles",
    "SourceStatements",
    "SourceMemberships",
    "LedgerAccounts",
    "LedgerObservations",
    "LedgerStatements",
    "LedgerEntries",
    "LedgerAllocations",
    "LedgerCorrections",
    "LedgerReviews",
    "SourceDateProvenance",
    "SourceAssertions",
    "OpeningDecisions",
)


class ReviewedReconciliation:
    """No postings, assertions, migrations or kernel reconciliation records are written.

    Each calculation uses one SQLite read snapshot. Input versions include review
    assertions and corrections, not just journal entries. Results are conservative:
    balance agreement, interpretation review and source coverage stay separate.
    """

    def __init__(self, review):
        self.review, self.store = review, review.store

    @contextmanager
    def _snapshot(self):
        c = self.store.connection
        if c.in_transaction:
            raise LedgerError("Reconciliation requires its own committed read snapshot.")
        c.execute("BEGIN")
        try:
            yield
        finally:
            c.execute("ROLLBACK")

    def _version(self):
        c = self.store.connection
        return key(
            {
                "rule": RULE,
                "tables": {table: sorted(c.execute(f"SELECT * FROM {table}").fetchall()) for table in VERSION_TABLES},
            }
        )

    def is_current(self, report):
        with self._snapshot():
            return report.get("rule") == RULE and report.get("input_version") == self._version()

    def snapshot(self):
        with self._snapshot():
            return self._evaluate()

    def _evaluate(self):
        store, c = self.store, self.store.connection
        # Reload the saved plan inside this read transaction; never cache assertions.
        openings = OpeningReview(self.review)
        version = self._version()
        accounts, observations = store.accounts(), store.observations()
        remaining = store.evidence_remaining()
        dates = observation_date_provenance(store)
        entries = [decode_entry(payload) for (payload,) in c.execute("SELECT payload FROM LedgerEntries ORDER BY key")]
        superseded = {row[0] for row in c.execute("SELECT original_key FROM LedgerCorrections")}
        reviews = dict(c.execute("SELECT entry_key,reviewed FROM LedgerReviews ORDER BY sequence"))
        active = [e for e in entries if e.key not in superseded and e.origin != "reversal"]
        opening_states = {aid: openings.status(aid) for aid in openings.anchors}
        eligible = {sid.removeprefix("statement:") for (sid,) in c.execute("SELECT id FROM LedgerStatements")}
        results = []
        for sid, raw in sorted(openings.sources.items()):
            aid = f"account:{raw['account_id']}"
            if aid not in opening_states:
                continue
            row = {
                "statement_id": sid,
                "account_id": aid,
                "start": raw["start"],
                "end": raw["end"],
                "source_id": raw["source"],
                "opening_state": opening_states[aid]["state"],
                "reconciled": False,
            }
            if sid not in eligible:
                row.update(
                    status="unavailable",
                    exceptions=["statement_not_eligible"],
                    eligibility=self.review.plan["statement_decisions"][sid],
                )
                results.append(row)
                continue
            statement = openings.effective_statement(sid)
            provenance = openings.provenance(sid)
            balance = evaluate_statement(statement, accounts, observations, entries, superseded, remaining)
            exceptions = list(balance["exceptions"])
            if not provenance["timing_confirmed"]:
                exceptions.append("source_period_timing_unverified")
            if opening_states[aid]["state"] not in {"posted", "confirmed_zero"}:
                exceptions.append("opening_position_unverified_or_stale")
            date_issues = {
                oid: dates.get(oid, "unknown")
                for oid in statement.observation_ids
                if dates.get(oid, "unknown") != "reported"
            }
            if provenance["posting_dates"] != "reported" or date_issues:
                exceptions.append("posting_dates_not_verified")
            unresolved = {oid: remaining[oid] for oid in statement.observation_ids if remaining[oid]}
            unreviewed = sorted(
                e.key
                for e in active
                if e.posting_date <= statement.end_date
                and any(p.account_id == aid for p in e.postings)
                and not reviews.get(e.key, e.reviewed)
            )
            row.update(
                status="checked",
                reconciled=not exceptions,
                exceptions=exceptions,
                balance_check=balance,
                source_review=provenance,
                unresolved_observations=unresolved,
                date_uncertain_observations=date_issues,
                posted_interpretations_reviewed=not unreviewed,
                unreviewed_entry_keys=unreviewed,
            )
            results.append(row)
        # These are source-period facts, not statement/account certification. In
        # particular, a later statement may reconcile while an earlier gap remains.
        coverage = []
        for aid, anchor in sorted(openings.anchors.items()):
            boundaries = [b for b in openings.plan["continuity"] if b["account_id"] == anchor["account_id"]]
            issues = [b for b in boundaries if b["status"] != "adjacent_balances_agree"]
            periods = [r for r in results if r["account_id"] == aid]
            coverage.append(
                {
                    "account_id": aid,
                    "first_start": min((r["start"] for r in periods), default=None),
                    "last_end": max((r["end"] for r in periods), default=None),
                    "has_source_periods": bool(periods),
                    "has_coverage_gaps": any(b["status"] == "coverage_gap" for b in boundaries),
                    "continuity_exceptions": issues,
                    "unavailable_statement_ids": [r["statement_id"] for r in periods if r["status"] == "unavailable"],
                    "all_statements_reconciled": bool(periods) and all(r["reconciled"] for r in periods),
                    "opening_state": opening_states[aid],
                }
            )
        return {
            "rule": RULE,
            "input_version": version,
            "candidate_hash": key(self.review.plan),
            "opening_plan_hash": key(openings.plan),
            "statements": results,
            "accounts": coverage,
            "incomplete_source_ids": openings.plan["incomplete_source_ids"],
            "outside_scope_statement_ids": sorted(set(openings.sources) - {r["statement_id"] for r in results}),
            "unmapped_movements": [
                d for d in self.review.plan["decisions"] if f"source:{d['transaction_id']}" not in observations
            ],
            "remaining_observations": {oid: amount for oid, amount in sorted(remaining.items()) if amount},
            "summary": {
                "statements": len(results),
                "reconciled": sum(r["reconciled"] for r in results),
                "exceptions": dict(sorted(Counter(e for r in results for e in r["exceptions"]).items())),
            },
            "journal_entries_posted": 0,
            "ready_for_cutover": False,
        }
