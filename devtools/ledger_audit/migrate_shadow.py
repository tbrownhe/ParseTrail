"""Create a private, disposable ledger from an inactive verified recovery snapshot."""

import argparse
import json
from pathlib import Path

from parsetrail.core.ledger_migration import create_shadow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-id", required=True, help="Stable identity for this legacy database across reruns.")
    parser.add_argument("--approved-preview", type=Path, required=True, help="Owner-reviewed HSA correction JSON.")
    args = parser.parse_args()
    try:
        report = create_shadow(
            args.source, args.archive, args.output, source_id=args.source_id, approved_preview=args.approved_preview
        )
    except Exception as exc:
        print(
            f"Shadow migration failed ({type(exc).__name__}). Output is incomplete; review privately and use a new directory."
        )
        return 1
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "plan_sha256",
                    "source_unchanged",
                    "replay_unchanged",
                    "entry_count",
                    "added_source_row_count",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
