"""Local database/statement recovery bundles; no settings, credentials or migrations."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import stat
import time
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath

FORMAT_VERSION = 1
MAX_BYTES = 20 * 1024**3
MAX_FILES = 100_000
# Pending institution exports can include a ZIP and accompanying text notes.
# They are copied as opaque evidence, never unpacked or executed.
ARCHIVE_SUFFIXES = {".pdf", ".csv", ".xlsx", ".zip", ".txt"}


class RecoveryError(ValueError):
    """Recovery evidence is incomplete, inconsistent, or unsafe to restore."""


def digest(path: Path, algorithm: str = "sha256") -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, algorithm).hexdigest()


def read_only(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve(strict=True).as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def inspect_database(path: Path) -> dict:
    """Check relational integrity and fingerprint all schema and record values."""
    with closing(read_only(path)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise RecoveryError("Database integrity check failed.")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise RecoveryError("Database foreign-key check failed.")
        tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
        required = {"Accounts", "Statements", "Transactions", "StatementTransactions", "alembic_version"}
        if not required.issubset(tables):
            raise RecoveryError("Unsupported database schema.")
        counts = {
            table: connection.execute('SELECT count(*) FROM "' + table.replace('"', '""') + '"').fetchone()[0]
            for table in tables
        }
        semantic = hashlib.sha256()
        for line in connection.iterdump():
            semantic.update(line.encode("utf-8") + b"\n")
        return {
            "row_counts": counts,
            "schema_revisions": sorted(row[0] for row in connection.execute("SELECT version_num FROM alembic_version")),
            "semantic_sha256": semantic.hexdigest(),
        }


def safe_member(name: str) -> str:
    """Portable relative names only; exclude traversal, Windows devices and ADS."""
    parts = PurePosixPath(name).parts
    if not parts or PurePosixPath(name).is_absolute() or "/".join(parts) != name:
        raise RecoveryError("Invalid bundle member path.")
    devices = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}
    for part in parts:
        if (
            part in {".", ".."}
            or part.endswith((".", " "))
            or any(char in part for char in '\\:<>"|?*')
            or any(ord(char) < 32 for char in part)
            or part.split(".")[0].upper() in devices
        ):
            raise RecoveryError("Unsafe bundle member path.")
    return name


def archive_inventory(root: Path) -> dict[str, Path]:
    files = {}
    folded = set()
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise RecoveryError("Archive links are unsupported; select a physical statement tree.")
        if path.is_dir():
            continue
        if not path.is_file() or path.suffix.lower() not in ARCHIVE_SUFFIXES:
            raise RecoveryError("Archive contains an unsupported file; review the source tree.")
        name = safe_member("archive/" + path.relative_to(root).as_posix())
        if name.casefold() in folded:
            raise RecoveryError("Archive paths collide on a case-insensitive filesystem.")
        folded.add(name.casefold())
        files[name] = path
    return files


def check_references(database: Path, archive: Path) -> dict:
    """Match each snapshot statement to its archived bytes, including shared files."""
    problems = []
    files = set()
    cache = {}
    with closing(read_only(database)) as connection:
        rows = connection.execute(
            "SELECT StatementID,Filename,ContentHashAlgorithm,ContentHash FROM Statements ORDER BY StatementID"
        ).fetchall()
    for statement_id, filename, algorithm, expected in rows:
        try:
            safe_member(filename)
            if len(PurePosixPath(filename).parts) != 1 or algorithm not in {"md5", "sha256"}:
                raise RecoveryError("Unsupported statement reference.")
            path = archive / "SUCCESS" / filename
            if not path.is_file():
                problems.append({"statement_id": statement_id, "reason": "missing"})
                continue
            key = (filename, algorithm)
            if key not in cache:
                cache[key] = digest(path, algorithm)
            if cache[key] != expected:
                problems.append({"statement_id": statement_id, "reason": "hash_mismatch"})
            files.add(filename)
        except (RecoveryError, TypeError):
            problems.append({"statement_id": statement_id, "reason": "invalid_reference"})
    return {"statement_count": len(rows), "referenced_file_count": len(files), "problems": problems}


def new_directory(path: Path) -> Path:
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=False)
    return path


def create_bundle(source: Path, archive: Path, output: Path) -> dict:
    """Leave an incomplete directory on failure, never publish a partial bundle."""
    source, archive = source.resolve(strict=True), archive.resolve(strict=True)
    if not source.is_file() or not archive.is_dir():
        raise RecoveryError("Select a database file and managed statement directory.")
    output = output.resolve()
    if output == archive or output.is_relative_to(archive) or source.is_relative_to(output):
        raise RecoveryError("Bundle output must be outside the source tree.")
    output = new_directory(output)
    snapshot = output / "snapshot.db"
    deadline = time.monotonic() + 60

    def progress(_status, _remaining, _total):
        if time.monotonic() > deadline:
            raise RecoveryError("Snapshot timed out; retry after stopping database writes.")

    with closing(read_only(source)) as original, closing(sqlite3.connect(snapshot)) as target:
        original.backup(target, pages=256, progress=progress)
    database = inspect_database(snapshot)
    files = archive_inventory(archive)
    references = check_references(snapshot, archive)
    (output / "source-review.json").write_text(json.dumps(references, indent=2) + "\n", encoding="utf-8")
    if references["problems"]:
        raise RecoveryError("Missing or mismatched statement sources; see private source-review.json.")
    files = {"database.db": snapshot, **files}
    if len(files) > MAX_FILES or sum(path.stat().st_size for path in files.values()) > MAX_BYTES:
        raise RecoveryError("Bundle exceeds supported size limits.")
    members = {}
    partial = output / "recovery.zip.partial"
    with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, path in files.items():
            before = digest(path)
            size = path.stat().st_size
            bundle.write(path, name)
            if digest(path) != before or path.stat().st_size != size:
                raise RecoveryError("A source file changed while being copied; retry into a new directory.")
            members[name] = {"size": size, "sha256": before}
        manifest = {
            "format_version": FORMAT_VERSION,
            "database": database,
            "references": references,
            "members": members,
        }
        bundle.writestr("manifest.json", json.dumps(manifest, indent=2) + "\n")
    # Read copied bytes, independently of the originals, before naming a complete bundle.
    restore_bundle(partial, output / "restore-test")
    partial.rename(output / "recovery.zip")
    result = {"bundle_sha256": digest(output / "recovery.zip"), **manifest}
    (output / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def restore_bundle(bundle_path: Path, output: Path) -> dict:
    """Restore only from the bundle, into a new isolated directory, without executing SQL."""
    bundle_path = bundle_path.resolve(strict=True)
    if bundle_path.is_relative_to(output.resolve()):
        raise RecoveryError("Restore output must not contain the bundle.")
    with zipfile.ZipFile(bundle_path) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > MAX_FILES + 1 or len({name.casefold() for name in names}) != len(names):
            raise RecoveryError("Duplicate members or excessive file count.")
        for entry in entries:
            safe_member(entry.filename)
            mode = entry.external_attr >> 16
            if entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits & 1:
                raise RecoveryError("Directories, symbolic links and encrypted members are unsupported.")
        if sum(entry.file_size for entry in entries) > MAX_BYTES:
            raise RecoveryError("Bundle exceeds supported size limits.")
        if "manifest.json" not in names or bundle.getinfo("manifest.json").file_size > 32 * 1024**2:
            raise RecoveryError("Missing or oversized manifest.")
        manifest = json.loads(bundle.read("manifest.json"))
        if manifest.get("format_version") != FORMAT_VERSION:
            raise RecoveryError("Unsupported bundle format.")
        members = manifest["members"]
        if set(names) != set(members) | {"manifest.json"} or "database.db" not in members:
            raise RecoveryError("Bundle contents do not match the manifest.")
        if any(name != "database.db" and not name.startswith("archive/") for name in members):
            raise RecoveryError("Unexpected bundle member.")
        output = new_directory(output)
        for name, expected in members.items():
            entry = bundle.getinfo(name)
            if entry.file_size != expected["size"]:
                raise RecoveryError("Bundle member size mismatch.")
            target = output.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, target.open("xb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
            if digest(target) != expected["sha256"]:
                raise RecoveryError("Bundle member checksum mismatch.")
    database = inspect_database(output / "database.db")
    if database != manifest["database"]:
        raise RecoveryError("Restored database contents differ from the snapshot.")
    references = check_references(output / "database.db", output / "archive")
    if references["problems"] or references != manifest["references"]:
        raise RecoveryError("Restored statement sources do not match the database.")
    result = {"database": database, "references": references, "verified_members": len(members)}
    (output / "restore-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
