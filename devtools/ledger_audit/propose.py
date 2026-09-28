"""Generate unposted cash/card journal proposals from an accepted fresh rebuild."""

import argparse
import json
from pathlib import Path

from parsetrail.core.ledger_candidates import create_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(create_candidates(args.rebuild, args.output), indent=2))


if __name__ == "__main__":
    main()
