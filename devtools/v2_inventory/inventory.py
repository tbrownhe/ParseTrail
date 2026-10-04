"""V2-1 read-only source inventory. Write the private result outside the repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path

FORMAT_VERSION = 1
ARCHIVE_SUFFIXES = {".pdf", ".csv", ".xlsx", ".zip", ".txt"}
PATH_SETTINGS = {"db_path", "model_dir", "model_path", "plugin_dir", "log_file", "report_dir"}
SETTINGS = {
    "config_version",
    "onboarding_version",
    "server_url",
    "email",
    "db_path",
    "model_dir",
    "model_path",
    "plugin_dir",
    "log_file",
    "automatic_update_checks",
    "report_dir",
}
LEGACY_SECRET_SETTINGS = {"access_token", "encrypted_access_token", "token_expires_at"}

# A policy for every column in the current 1.x ORM. Unknown fields are never ignored.
FIELDS = {
    "Currencies": {"CurrencyCode", "MinorUnit"},
    "AccountTypes": {"AccountTypeID", "AccountType", "AssetType"},
    "Accounts": {
        "AccountID",
        "AccountName",
        "AccountTypeID",
        "CurrencyCode",
        "Company",
        "Description",
        "AppreciationRate",
    },
    "AccountNumbers": {"AccountNumberID", "AccountID", "AccountNumber"},
    "Categories": {"CategoryID", "Name", "Type", "Active", "ParentID", "BudgetMinor", "BudgetCurrencyCode"},
    "Plugins": {"PluginID", "PluginName", "Version", "Suffix", "Company", "StatementType"},
    "Statements": {
        "StatementID",
        "PluginID",
        "AccountID",
        "ImportedAt",
        "StartDate",
        "EndDate",
        "StartBalanceMinor",
        "EndBalanceMinor",
        "CurrencyCode",
        "TransactionCount",
        "Filename",
        "ContentHashAlgorithm",
        "ContentHash",
        "AccountingContract",
    },
    "Transactions": {
        "TransactionID",
        "AccountID",
        "TransactionDate",
        "PostingDate",
        "AmountMinor",
        "BalanceMinor",
        "CurrencyCode",
        "Description",
        "Fingerprint",
        "FingerprintVersion",
        "CategoryID",
        "Verified",
        "ConfidenceScore",
    },
    "StatementTransactions": {"StatementID", "TransactionID", "StatementRow"},
    "alembic_version": {"version_num"},
}

POLICIES = {
    "Currencies": "preserve_reference_and_validate",
    "AccountTypes": "preserve_reference_and_map_account_kind",
    "Accounts": "preserve_identity_metadata_and_manual_assumptions",
    "AccountNumbers": "preserve_exact_account_aliases",
    "Categories": "preserve_definitions_hierarchy_type_active_and_exact_budgets",
    "Plugins": "retain_parser_provenance_and_verify_replay_availability",
    "Statements": "retain_original_assertions_and_rebuild_from_hashed_source",
    "Transactions": "retain_all_legacy_annotations_and_match_fresh_evidence_conservatively",
    "StatementTransactions": "retain_source_membership_and_row_order",
    "alembic_version": "retain_legacy_format_identity",
}


def _hash(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def _quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _source_markers(source: Path) -> dict[str, dict[str, int | str]]:
    result = {}
    for suffix in ("", "-wal", "-shm", "-journal"):
        path = Path(str(source) + suffix)
        if path.is_file():
            stat = path.stat()
            result[suffix or "database"] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return result


def database_inventory(source: Path) -> dict:
    if not source.is_file():
        raise ValueError("Select an existing SQLite database file.")
    if any(Path(str(source) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError(
            "Select a consistent closed snapshot without SQLite sidecars; this inventory never opens a live WAL database."
        )
    before = _source_markers(source)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=5)) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_violations = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        names = sorted(
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        )
        tables = {}
        issues = []
        for name in names:
            info = list(connection.execute(f"PRAGMA table_info({_quoted(name)})"))
            columns = [row[1] for row in info]
            actual = set(columns)
            expected = FIELDS.get(name)
            if expected is None:
                issues.append({"kind": "unknown_table", "table": name})
            else:
                for field in sorted(actual - expected):
                    issues.append({"kind": "unknown_field", "table": name, "field": field})
                for field in sorted(expected - actual):
                    issues.append({"kind": "missing_field", "table": name, "field": field})
            content = hashlib.sha256()
            primary_key = [row[1] for row in sorted(info, key=lambda row: row[5]) if row[5]]
            order = " ORDER BY " + ",".join(map(_quoted, primary_key)) if primary_key else ""
            for row in connection.execute(f"SELECT * FROM {_quoted(name)}{order}"):
                payload = repr(row).encode("utf-8")
                content.update(len(payload).to_bytes(8, "big"))
                content.update(payload)
            tables[name] = {
                "policy": POLICIES.get(name, "unresolved"),
                "count": connection.execute(f"SELECT count(*) FROM {_quoted(name)}").fetchone()[0],
                "content_sha256": content.hexdigest(),
                "fields": {
                    field: (POLICIES.get(name, "unresolved") if expected and field in expected else "unresolved")
                    for field in columns
                },
            }
        for missing in sorted(set(FIELDS) - set(names)):
            issues.append({"kind": "missing_table", "table": missing})

        state = {}
        if {"Transactions", "Categories", "StatementTransactions"}.issubset(tables) and not any(
            i["kind"] == "missing_field" and i["table"] in {"Transactions", "Categories", "StatementTransactions"}
            for i in issues
        ):
            state = {
                "verified_expense": connection.execute(
                    "SELECT count(*) FROM Transactions t JOIN Categories c ON c.CategoryID=t.CategoryID "
                    "WHERE t.Verified=1 AND c.Type='Expense'"
                ).fetchone()[0],
                "verified_other": connection.execute(
                    "SELECT count(*) FROM Transactions t LEFT JOIN Categories c ON c.CategoryID=t.CategoryID "
                    "WHERE t.Verified=1 AND (c.Type IS NULL OR c.Type<>'Expense')"
                ).fetchone()[0],
                "unverified_categorized": connection.execute(
                    "SELECT count(*) FROM Transactions WHERE Verified=0 AND CategoryID IS NOT NULL"
                ).fetchone()[0],
                "unlinked_transactions": connection.execute(
                    "SELECT count(*) FROM Transactions t WHERE NOT EXISTS "
                    "(SELECT 1 FROM StatementTransactions st WHERE st.TransactionID=t.TransactionID)"
                ).fetchone()[0],
                "unlinked_verified": connection.execute(
                    "SELECT count(*) FROM Transactions t WHERE Verified=1 AND NOT EXISTS "
                    "(SELECT 1 FROM StatementTransactions st WHERE st.TransactionID=t.TransactionID)"
                ).fetchone()[0],
                "manual_closure_markers": connection.execute(
                    "SELECT count(*) FROM Transactions WHERE Description='Manual Entry: Account Closed Manually'"
                ).fetchone()[0],
                "custom_or_builtin_undetermined": tables["Categories"]["count"],
                "budget_targets": connection.execute(
                    "SELECT count(*) FROM Categories WHERE BudgetMinor IS NOT NULL"
                ).fetchone()[0],
            }
        references = []
        reference_fields = {"StatementID", "Filename", "ContentHashAlgorithm", "ContentHash"}
        if "Statements" in tables and reference_fields.issubset(tables["Statements"]["fields"]):
            references = [
                {"statement_id": row[0], "filename": row[1], "algorithm": row[2], "digest": row[3]}
                for row in connection.execute(
                    "SELECT StatementID,Filename,ContentHashAlgorithm,ContentHash FROM Statements ORDER BY StatementID"
                )
            ]
        revisions = []
        if "alembic_version" in tables and "version_num" in tables["alembic_version"]["fields"]:
            revisions = [row[0] for row in connection.execute("SELECT version_num FROM alembic_version")]
        legacy_absent_fields = []
        if revisions == ["0003_precise_financial_schema"]:
            legacy_absent_fields = [
                issue
                for issue in issues
                if issue == {"kind": "missing_field", "table": "Statements", "field": "AccountingContract"}
            ]
            issues = [issue for issue in issues if issue not in legacy_absent_fields]
        plugin_references = []
        if (
            {"Plugins", "Statements"}.issubset(tables)
            and {"PluginID", "PluginName", "Version"}.issubset(tables["Plugins"]["fields"])
            and "PluginID" in tables["Statements"]["fields"]
        ):
            plugin_references = [
                {"plugin_id": row[0], "name": row[1], "version": row[2], "statement_count": row[3]}
                for row in connection.execute(
                    "SELECT p.PluginID,p.PluginName,p.Version,count(s.StatementID) FROM Plugins p "
                    "LEFT JOIN Statements s ON s.PluginID=p.PluginID "
                    "GROUP BY p.PluginID,p.PluginName,p.Version ORDER BY p.PluginID"
                )
            ]
        connection.rollback()
    after = _source_markers(source)
    if before != after:
        issues.append({"kind": "source_changed_during_inventory"})
    if integrity != "ok":
        issues.append({"kind": "integrity_failure"})
    if foreign_key_violations:
        issues.append({"kind": "foreign_key_violations", "count": foreign_key_violations})
    return {
        "tables": tables,
        "state_counts": state,
        "references": references,
        "schema_revisions": revisions,
        "legacy_absent_fields": legacy_absent_fields,
        "plugin_references": plugin_references,
        "source_markers_before": before,
        "source_markers_after": after,
        "issues": issues,
    }


def archive_inventory(archive: Path, references: list[dict]) -> dict:
    if not archive.is_dir():
        return {"files": [], "references": [], "issues": [{"kind": "missing_archive"}]}
    files = []
    issues = []
    seen = set()
    for path in sorted(archive.rglob("*")):
        relative = path.relative_to(archive).as_posix()
        if path.is_symlink() or path.is_junction():
            issues.append({"kind": "archive_link", "path": relative})
            continue
        if not path.is_file():
            continue
        if relative.casefold() in seen:
            issues.append({"kind": "archive_case_collision", "path": relative})
        seen.add(relative.casefold())
        policy = "preserve_original_bytes" if path.suffix.lower() in ARCHIVE_SUFFIXES else "unresolved_file_type"
        if policy == "unresolved_file_type":
            issues.append({"kind": "unknown_archive_file", "path": relative})
        files.append({"path": relative, "size": path.stat().st_size, "sha256": _hash(path), "policy": policy})
    by_path = {item["path"]: item for item in files}
    checked = []
    for ref in references:
        name = ref["filename"]
        safe = isinstance(name, str) and name not in {"", ".", ".."} and "/" not in name and "\\" not in name
        member = by_path.get("SUCCESS/" + name) if safe else None
        status = "invalid_name" if not safe else "missing" if member is None else "matched"
        if member is not None:
            algorithm, expected = ref["algorithm"], ref["digest"]
            path = archive / member["path"]
            if algorithm not in {"md5", "sha256"} or _hash(path, algorithm) != expected:
                status = "hash_mismatch"
        if status != "matched":
            issues.append({"kind": "source_reference_" + status, "statement_id": ref["statement_id"]})
        checked.append(
            {"statement_id": ref["statement_id"], "status": status, "archive_path": member["path"] if member else None}
        )
    return {"files": files, "references": checked, "issues": issues}


def profile_inventory(profile: Path | None) -> dict:
    if profile is None:
        return {"status": "not_selected", "files": [], "settings": {}, "issues": [{"kind": "profile_not_selected"}]}
    if not profile.is_dir():
        return {"status": "missing", "files": [], "settings": {}, "issues": [{"kind": "missing_profile"}]}
    files, issues = [], []
    for path in sorted(profile.rglob("*")):
        relative = path.relative_to(profile).as_posix()
        if path.is_symlink() or path.is_junction():
            issues.append({"kind": "profile_link", "path": relative})
            continue
        if not path.is_file():
            continue
        top = relative.split("/")[0]
        if top in {"config.json", "accounts.json"} or top in {"backup", "models", "plugins", "logs", "downloads"}:
            policy = "retain_private_original_and_map_or_rebuild"
        elif top == "server_public_key.pem":
            policy = "retain_legacy_trust_resource"
        else:
            policy = "unresolved"
            issues.append({"kind": "unknown_profile_file", "path": relative})
        files.append({"path": relative, "size": path.stat().st_size, "sha256": _hash(path), "policy": policy})
    config = profile / "config.json"
    settings = {}
    if config.is_file() and not config.is_symlink():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("Settings root is not an object")
            for key, value in sorted(data.items()):
                if key in LEGACY_SECRET_SETTINGS:
                    settings[key] = {"policy": "keep_in_existing_credential_store_or_legacy_recovery_only"}
                elif key in SETTINGS:
                    setting = {"policy": "preserve_or_map"}
                    if key in PATH_SETTINGS and isinstance(value, str):
                        target = Path(value).expanduser()
                        setting.update(path=value, exists=target.exists())
                        if not target.exists():
                            issues.append({"kind": "missing_configured_path", "key": key})
                    settings[key] = setting
                else:
                    settings[key] = {"policy": "unresolved"}
                    issues.append({"kind": "unknown_setting", "key": key})
        except (OSError, ValueError, UnicodeError):
            issues.append({"kind": "unreadable_settings"})
    else:
        issues.append({"kind": "missing_settings"})
    return {"status": "inventoried", "files": files, "settings": settings, "issues": issues}


def create_inventory(source: Path, archive: Path, profile: Path | None = None) -> dict:
    source = source.resolve(strict=True)
    archive = archive.resolve()
    if profile is not None:
        profile = profile.resolve()
    db = database_inventory(source)
    archive_result = archive_inventory(archive, db.pop("references"))
    profile_result = profile_inventory(profile)
    issues = [*db.pop("issues"), *archive_result.pop("issues"), *profile_result.pop("issues")]
    return {
        "format_version": FORMAT_VERSION,
        "source": {"path": str(source), **db},
        "archive": {"path": str(archive), **archive_result},
        "profile": {"path": str(profile) if profile else None, **profile_result},
        "issue_counts": dict(sorted(Counter(item["kind"] for item in issues).items())),
        "issues": issues,
        "activation_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New private JSON file outside the source tree")
    args = parser.parse_args()
    output = args.output.resolve()
    source, archive = args.source.resolve(strict=True), args.archive.resolve()
    repository = Path(__file__).resolve().parents[2]
    if (
        output.exists()
        or output == source
        or output.is_relative_to(repository)
        or output.is_relative_to(archive)
        or (args.profile and output.is_relative_to(args.profile.resolve()))
    ):
        parser.error("Output must be a new private file outside the repository, source, archive and profile.")
    result = create_inventory(source, archive, args.profile)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(f"Inventory written to {output}; {len(result['issues'])} issue(s). Keep the file private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
