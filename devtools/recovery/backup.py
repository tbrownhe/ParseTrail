"""Create or restore a private local recovery bundle without loading the GUI/profile."""

import argparse
import json
from pathlib import Path

from parsetrail.core.recovery_bundle import create_bundle, restore_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--archive", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("restore")
    restore.add_argument("--bundle", type=Path, required=True)
    restore.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_bundle(args.source, args.archive, args.output)
            print(json.dumps({"verified": True, "bundle_sha256": result["bundle_sha256"]}))
        else:
            result = restore_bundle(args.bundle, args.output)
            print(json.dumps({"verified": True, "verified_members": result["verified_members"]}))
    except Exception as exc:
        # Do not print financial filenames, database contents, or archive paths.
        print(
            f"Recovery failed ({type(exc).__name__}); output is incomplete. Review privately and retry in a new directory."
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
