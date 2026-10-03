"""Produce a private read-only opening-readiness report from verified artifacts."""

import argparse
import json
from pathlib import Path

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_openings import build_opening_readiness
from parsetrail.core.ledger_store import encoded
from parsetrail.core.recovery_bundle import digest


def create_report(rebuild_folder, candidates_folder, output):
    rebuild_report = json.loads((rebuild_folder / "report.json").read_text(encoding="utf-8"))
    candidate_report = json.loads((candidates_folder / "report.json").read_text(encoding="utf-8"))
    checksums = {
        rebuild_folder / "plan.json": rebuild_report["plan_sha256"],
        rebuild_folder / "fresh.db": rebuild_report["database_sha256"],
        rebuild_folder / "legacy.db": rebuild_report["source_sha256"],
        candidates_folder / "proposals.json": candidate_report["proposal_sha256"],
        candidates_folder / "candidates.db": candidate_report["database_sha256"],
    }
    if any(digest(path) != expected for path, expected in checksums.items()):
        raise LedgerError("Opening audit input changed after verification.")
    if any(
        Path(str(path) + suffix).exists()
        for path in checksums
        if path.suffix == ".db"
        for suffix in ("-wal", "-shm", "-journal")
    ):
        raise LedgerError("Opening audit requires inactive verified inputs.")
    rebuild = json.loads((rebuild_folder / "plan.json").read_text(encoding="utf-8"))
    candidates = json.loads((candidates_folder / "proposals.json").read_text(encoding="utf-8"))
    result = build_opening_readiness(rebuild, candidates)
    if result != build_opening_readiness(rebuild, candidates):
        raise LedgerError("Opening audit is not deterministic.")
    output.mkdir(parents=True, exist_ok=False)
    (output / "readiness.json").write_text(encoded(result), encoding="utf-8")
    if any(digest(path) != expected for path, expected in checksums.items()):
        raise LedgerError("Opening audit inputs changed while reading.")
    report = {
        k: result[k]
        for k in (
            "rule",
            "anchor_count",
            "unambiguous_nonzero_count",
            "zero_balance_count",
            "continuity_summary",
            "journal_entries_posted",
            "ready_for_opening_posting",
            "ready_for_cutover",
        )
    }
    report.update(
        {
            "readiness_sha256": digest(output / "readiness.json"),
            "source_unchanged": True,
            "replay_identical": True,
            "input_checksums": {str(path): sha for path, sha in checksums.items()},
        }
    )
    (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", required=True, type=Path)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = create_report(args.rebuild, args.candidates, args.output)
    print(json.dumps({k: v for k, v in report.items() if k != "input_checksums"}, indent=2))


if __name__ == "__main__":
    main()
