"""Read-only opening-position readiness and source-period continuity audit."""

from collections import Counter, defaultdict
from datetime import date, timedelta

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_rebuild import key

RULE = "opening-readiness-1"
DATE_LIMITATIONS = {
    "pdf_chasecc_202602": "Only transaction dates are supplied; the parser uses a statement-bounded posting-date proxy. Exact posting dates are not established."
}


def build_opening_readiness(rebuild, candidates):
    """Propose no postings and promote no provenance or review assertions."""
    if candidates["rebuild_hash"] != key(rebuild):
        raise LedgerError("Opening evidence and candidate plan belong to different rebuilds.")
    evidence = rebuild["evidence"]
    accounts = {int(a["source_account_id"]): a for a in candidates["accounts"] if a["source_account_id"] is not None}
    groups = defaultdict(list)
    for sid, row in evidence["statements"].items():
        if row["account_id"] in accounts:
            groups[row["account_id"]].append({**row, "id": sid})
    kernel = {s["id"].removeprefix("statement:"): s for s in candidates["statements"]}
    incomplete_sources = sorted(fid for fid, f in evidence["files"].items() if f["status"] != "parsed")
    anchors, continuity = [], []
    for aid, account in sorted(accounts.items()):
        rows = sorted(groups[aid], key=lambda s: (s["start"], s["end"], s["id"]))
        if not rows:
            anchors.append(
                {
                    "account_id": aid,
                    "account_name": account["name"],
                    "status": "no_source_statement",
                    "blockers": ["no_source_statement"],
                    "sources": [],
                    "proposed_amount_minor": None,
                    "proposed_date": None,
                    "statement_ids": [],
                }
            )
            continue
        for row in rows:
            if not date.min < date.fromisoformat(row["start"]) <= date.fromisoformat(row["end"]):
                raise LedgerError("Opening audit requires valid inclusive statement periods.")
        earliest = [s for s in rows if s["start"] == rows[0]["start"]]
        amounts = {s["opening_minor"] for s in earliest}
        blockers = ["source_balance_and_timing_review_required"]
        if len(amounts) != 1:
            blockers.append("conflicting_earliest_openings")
        if incomplete_sources:
            blockers.append("source_replay_incomplete")
        if any(s["id"] not in kernel for s in earliest):
            blockers.append("earliest_statement_not_eligible")
        if any(
            o["account_id"] == account["id"] and o["posting_date"] < rows[0]["start"]
            for o in candidates["observations"]
        ):
            blockers.append("movement_before_earliest_statement")
        sources = []
        for row in earliest:
            file = evidence["files"][row["source"]]
            k = kernel.get(row["id"])
            sources.append(
                {
                    "statement_id": row["id"],
                    "source_id": row["source"],
                    "filename": file["filename"],
                    "plugin": file["plugin"],
                    "parser_manifest": rebuild.get("parser_manifest", {}).get(file["plugin"]),
                    "start": row["start"],
                    "end": row["end"],
                    "opening_minor": row["opening_minor"],
                    "closing_minor": row["closing_minor"],
                    "source_provenance": row["balance_provenance"],
                    "opening_provenance": k["opening_provenance"] if k else "unavailable",
                    "closing_provenance": k["closing_provenance"] if k else "unavailable",
                    "eligibility": candidates["statement_decisions"][row["id"]]["status"],
                }
            )
        notes = sorted(
            {
                DATE_LIMITATIONS[evidence["files"][s["source"]]["plugin"]]
                for s in rows
                if evidence["files"][s["source"]]["plugin"] in DATE_LIMITATIONS
            }
        )
        amount = next(iter(amounts)) if len(amounts) == 1 else None
        anchors.append(
            {
                "account_id": aid,
                "account_name": account["name"],
                "status": "needs_source_review",
                "proposed_amount_minor": amount,
                "proposed_date": (date.fromisoformat(rows[0]["start"]) - timedelta(days=1)).isoformat(),
                "date_basis": "Conditional cutoff immediately before the earliest inclusive statement period; not an account-opening date.",
                "statement_ids": [s["id"] for s in earliest],
                "sources": sources,
                "blockers": blockers,
                "posting_date_limitations": notes,
                "zero_balance_requires_no_journal": amount == 0,
                "reviewed": False,
                "posted": False,
            }
        )
        # Sweep the furthest covered endpoint: nested/duplicate periods must not
        # manufacture a later gap or let an arbitrary closing balance win a tie.
        end, frontier = None, []
        for row in rows:
            start, close = date.fromisoformat(row["start"]), date.fromisoformat(row["end"])
            if end is not None:
                gap = (start - end).days - 1
                if gap > 0:
                    status = "coverage_gap"
                elif gap < 0:
                    status = "overlapping_periods"
                elif len({s["closing_minor"] for s in frontier}) > 1:
                    status = "conflicting_prior_closings"
                elif row["opening_minor"] != frontier[0]["closing_minor"]:
                    status = "adjacent_balance_difference"
                else:
                    status = "adjacent_balances_agree"
                continuity.append(
                    {
                        "account_id": aid,
                        "status": status,
                        "prior_statement_ids": sorted(s["id"] for s in frontier),
                        "next_statement_id": row["id"],
                        "prior_end": end.isoformat(),
                        "next_start": start.isoformat(),
                        "uncovered_days": max(gap, 0),
                        "gap_start": (end + timedelta(days=1)).isoformat() if gap > 0 else None,
                        "gap_end": (start - timedelta(days=1)).isoformat() if gap > 0 else None,
                        "endpoint_differences_minor": sorted(
                            {row["opening_minor"] - s["closing_minor"] for s in frontier}
                        ),
                        "independently_verified": False,
                    }
                )
            if end is None or close > end:
                end, frontier = close, [row]
            elif close == end:
                frontier.append(row)
    return {
        "rule": RULE,
        "rebuild_hash": key(rebuild),
        "candidate_hash": key(candidates),
        "anchors": anchors,
        "continuity": continuity,
        "incomplete_source_ids": incomplete_sources,
        "continuity_summary": dict(sorted(Counter(c["status"] for c in continuity).items())),
        "anchor_count": len(anchors),
        "unambiguous_nonzero_count": sum(a["proposed_amount_minor"] not in (None, 0) for a in anchors),
        "zero_balance_count": sum(a["proposed_amount_minor"] == 0 for a in anchors),
        "journal_entries_posted": 0,
        "ready_for_opening_posting": False,
        "ready_for_cutover": False,
    }
