"""Read-only P2-1 source replay and category-preservation probe on a closed copy.

No source bytes, names, amounts or row-level evidence are written or printed.
This uses unsigned checkout code for development comparison, not installed-client trust.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
from collections import Counter
from pathlib import Path

from loguru import logger
from parsetrail.core.interfaces import IParser, class_variables, validate_parser
from parsetrail.core.ledger_migration import read_legacy
from parsetrail.core.ledger_rebuild import match_categories, replay_sources
from parsetrail.core.parser_classification import validate_routing_metadata

if __package__:
    from .inventory import archive_inventory, database_inventory
else:  # Direct script execution keeps this directory on sys.path.
    from inventory import archive_inventory, database_inventory


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class SourceRegistry:
    """Load all checkout parser classes without importing writable runtime settings."""

    def __init__(self) -> None:
        self.classes = {}
        self.metadata = {}
        source_dir = Path(__file__).resolve().parents[2] / "client" / "src" / "parsetrail" / "plugins"
        for path in sorted(source_dir.glob("*.py")):
            if path.name == "__init__.py":
                continue
            parser = importlib.import_module(f"parsetrail.plugins.{path.stem}").Parser
            validate_parser(parser, class_variables(IParser))
            if parser.PLUGIN_NAME != path.stem or parser.PLUGIN_NAME in self.classes:
                raise ValueError("Parser source identity is inconsistent.")
            metadata = {
                key: getattr(parser, key)
                for key in (
                    "PLUGIN_NAME",
                    "VERSION",
                    "SUFFIX",
                    "COMPANY",
                    "STATEMENT_TYPE",
                    "SEARCH_STRING",
                    "ROUTING_RULE",
                )
                if hasattr(parser, key)
            }
            validate_routing_metadata(metadata)
            self.classes[parser.PLUGIN_NAME] = parser
            self.metadata[parser.PLUGIN_NAME] = metadata
        if not self.classes:
            raise ValueError("No checkout parsers were found.")

    def get_parser(self, plugin_id: str):
        return self.classes[plugin_id]


def summarize(legacy: dict, evidence: dict, categories: dict) -> dict:
    statuses = Counter(file.get("status", "unknown") for file in evidence["files"].values())
    parser_counts = Counter(
        file["plugin"] for file in evidence["files"].values() if file.get("status") == "parsed" and file.get("plugin")
    )
    decisions = categories["decisions"]
    total = sum(row["original_count"] for row in categories["totals"])
    restored = sum(row["restored_count"] for row in categories["totals"])
    pending = sum(row["pending_count"] for row in categories["totals"])
    if total != restored + pending or total != len(decisions):
        raise ValueError("Verified expense category conservation failed.")
    return {
        "legacy_statement_count": len(legacy["Statements"]),
        "legacy_transaction_count": len(legacy["Transactions"]),
        "replayed_source_file_count": len(evidence["files"]),
        "replayed_statement_count": len(evidence["statements"]),
        "replayed_transaction_evidence_count": len(evidence["transactions"]),
        "unreferenced_archive_file_count": len(evidence["unreferenced_archive_files"]),
        "source_status_counts": dict(sorted(statuses.items())),
        "parser_file_counts": dict(sorted(parser_counts.items())),
        "verified_expense_assertions": {
            "original": total,
            "restored": restored,
            "pending": pending,
            "reason_counts": dict(sorted(Counter(row["status"] for row in decisions).items())),
        },
    }


def parser_bindings(legacy: dict, evidence: dict) -> dict:
    """Bind historical parser revisions to observed checkout replay results."""
    plugins = {row["PluginID"]: row for row in legacy["Plugins"]}
    pairs = Counter()
    targets = {}
    unresolved = 0
    for statement in legacy["Statements"]:
        old = plugins.get(statement["PluginID"])
        source = evidence["legacy_sources"].get(str(statement["StatementID"]))
        current = evidence["files"].get(source, {}) if source else {}
        if old is None or current.get("status") != "parsed" or not current.get("plugin"):
            unresolved += 1
            continue
        old_revision = (old["PluginName"], old["Version"])
        new_revision = (current["plugin"], current["version"])
        pairs[(*old_revision, *new_revision)] += 1
        targets.setdefault(old_revision, set()).add(current["plugin"])
    return {
        "bindings": [
            {
                "legacy_parser": old_name,
                "legacy_version": old_version,
                "checkout_parser": new_name,
                "checkout_version": new_version,
                "statement_count": count,
            }
            for (old_name, old_version, new_name, new_version), count in sorted(pairs.items())
        ],
        "ambiguous_legacy_revisions": [
            {"legacy_parser": name, "legacy_version": version}
            for (name, version), revisions in sorted(targets.items())
            if len(revisions) > 1
        ],
        "unresolved_statement_count": unresolved,
    }


def probe(source: Path, archive: Path, *, progress=None) -> dict:
    source = source.resolve(strict=True)
    archive = archive.resolve(strict=True)
    before = _hash(source)
    database = database_inventory(source)
    references = database.pop("references")
    if database["issues"]:
        raise ValueError("Source schema or integrity has unresolved issues.")
    archive_report = archive_inventory(archive, references)
    if archive_report["issues"]:
        raise ValueError("Archive sources have unresolved issues; run the V2-1 inventory first.")
    # Parser modules and PDF libraries may log document content. Suppress Loguru
    # entirely; this probe exposes only aggregate status and public parser IDs.
    logger.remove()
    legacy = read_legacy(source)
    registry = SourceRegistry()
    evidence = replay_sources(legacy, archive, registry, progress=progress)
    categories = match_categories(legacy, evidence)
    if _hash(source) != before or any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Source changed or gained SQLite sidecars during replay.")
    result = summarize(legacy, evidence, categories)
    result["legacy_parser_bindings"] = parser_bindings(legacy, evidence)
    result["checkout_parser_count"] = len(registry.classes)
    result["source_unchanged"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Closed source database copy")
    parser.add_argument("--archive", required=True, type=Path, help="Managed archive directory")
    args = parser.parse_args()
    result = probe(args.source, args.archive)
    for key, value in result.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
