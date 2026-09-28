"""Replay a private archive with repository parsers into a disposable fresh DB."""

import argparse
import json
from pathlib import Path

from loguru import logger
from parsetrail.core.ledger_rebuild import create_rebuild
from parsetrail.core.plugin_loader import load_plugin
from parsetrail.core.recovery_bundle import digest


class SourceRegistry:
    """Development-only registry; never substitutes for production signature checks."""

    def __init__(self):
        self.parsers, self.metadata = {}, {}
        self.manifest = {}
        root = Path(__file__).resolve().parents[2] / "client/src/parsetrail/plugins"
        for path in sorted(root.glob("*.py")):
            if path.name == "__init__.py":
                continue
            name, parser, metadata = load_plugin(path)
            self.parsers[name], self.metadata[name] = parser, metadata
            self.manifest[name] = {"version": metadata["VERSION"], "sha256": digest(path)}

    def get_parser(self, plugin_id):
        return self.parsers[plugin_id]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manual-review", type=Path, help="Owner-reviewed, snapshot-bound manual asset-value annotations."
    )
    args = parser.parse_args()
    logger.remove()
    report = create_rebuild(
        args.source,
        args.archive,
        args.output,
        SourceRegistry(),
        lambda n, total: print(f"Parsed {n}/{total} sources", flush=True) if n % 50 == 0 else None,
        manual_review=args.manual_review,
    )
    print(json.dumps({k: v for k, v in report.items() if k != "totals"}, indent=2))


if __name__ == "__main__":
    main()
