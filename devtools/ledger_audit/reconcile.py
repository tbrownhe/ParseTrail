"""Export a private reconciliation snapshot from an inactive prepared opening workspace."""

import argparse
from pathlib import Path

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_proposal_review import ProposalReview
from parsetrail.core.ledger_reviewed_reconciliation import ReviewedReconciliation
from parsetrail.core.ledger_store import encoded
from parsetrail.core.recovery_bundle import digest


def create_report(folder, output):
    database = folder / "review.db"
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise LedgerError("Reconciliation export requires an inactive review workspace.")
    checksums = {p: digest(p) for p in (database, folder / "review.json")}
    with ProposalReview(folder, read_only=True) as review:
        service = ReviewedReconciliation(review)
        result = service.snapshot()
        if service.snapshot() != result:
            raise LedgerError("Reconciliation inputs changed or replay differed.")
    if any(digest(p) != checksum for p, checksum in checksums.items()):
        raise LedgerError("Reconciliation workspace changed during export.")
    output.mkdir(parents=True, exist_ok=False)
    target = output / "reconciliation.json"
    target.write_text(encoded(result), encoding="utf-8")
    report = {
        "rule": result["rule"],
        "input_version": result["input_version"],
        "summary": result["summary"],
        "reconciliation_sha256": digest(target),
        "workspace_unchanged": True,
        "replay_identical": True,
        "journal_entries_posted": 0,
        "ready_for_cutover": False,
        "input_checksums": {str(p): checksum for p, checksum in checksums.items()},
    }
    (output / "report.json").write_text(encoded(report), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    create_report(args.folder, args.output)
    print("Private reconciliation snapshot saved; workspace unchanged. No report cutover.")


if __name__ == "__main__":
    main()
