"""Prepare and import an explicitly selected local archive into an isolated V2 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT_PATHS = (REPO / "client/src", REPO / "client", REPO)
sys.path[:0] = [str(component) for component in SNAPSHOT_PATHS]
os.environ["PYTHONPATH"] = os.pathsep.join(str(component) for component in SNAPSHOT_PATHS)
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
MAX_ARCHIVE_FILES = 100_000
MAX_ARCHIVE_DIRECTORIES = 20_000


class PilotError(ValueError):
    """A finite pilot operation was refused; messages contain no private input."""


def isolate(root: Path) -> None:
    home = root / "isolated-home"
    home.mkdir(exist_ok=True)
    for key, value in {
        "HOME": home,
        "USERPROFILE": home,
        "APPDATA": home / "AppData/Roaming",
        "LOCALAPPDATA": home / "AppData/Local",
    }.items():
        os.environ[key] = str(value)
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"


def workspace_at(root: Path):
    from parsetrail.core.v2_workspace import V2Workspace

    raw = json.loads((root / "pilot-public-trust.json").read_text(encoding="utf-8"))
    workspace = V2Workspace.open(
        root / "review.db",
        root / "catalog",
        trusted_keys={key: bytes.fromhex(value) for key, value in raw.items()},
        preferences_path=root / "preferences.json",
    )
    workspace.verify_local_configuration()
    return workspace


def _revision() -> str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={REPO.as_posix()}", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", result) is None:
        raise PilotError("pilot_source_revision")
    return result


def prepare(root: Path) -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from parsetrail.core.v2_data_catalog import key_id_for_public_key
    from parsetrail.core.v2_preferences import V2Preferences, save_preferences
    from parsetrail.core.v2_workspace import V2Workspace
    from scripts.v2_catalog_release import signed_catalog_bytes

    from devtools.v2_review_demo.pin_runtime import pin_runtime
    from devtools.v2_review_demo.prepare_demo import inherit_public_catalog_access

    definitions = sorted((REPO / "devtools/parser_engine_pilot").glob("*definition.json"))
    if len(definitions) != 23:
        raise PilotError("pilot_required_catalog_inventory")
    revision = _revision()
    root.mkdir(parents=True, exist_ok=False)
    isolate(root)
    copied = root / "definitions"
    copied.mkdir()
    for path in definitions:
        (copied / path.name).write_bytes(path.read_bytes())
    context = REPO / "devtools/parser_engine_pilot/account-contexts.json"
    (copied / context.name).write_bytes(context.read_bytes())
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    snapshot, signature, _ = signed_catalog_bytes(copied, private, release_sequence=1, source_revision=revision)
    del private
    (root / "pilot-public-trust.json").write_text(json.dumps({key_id: public.hex()}) + "\n", encoding="utf-8")
    release = root / "test-signed-release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace = V2Workspace.create(
        root / "review.db", root / "catalog", trusted_keys={key_id: public}, preferences_path=root / "preferences.json"
    )
    save_preferences(root / "preferences.json", V2Preferences())
    workspace.install_catalog_release(release)
    inherit_public_catalog_access(root)
    initial = verify(root)
    if initial["source_count"] != 0 or initial["journal_count"] != 0 or initial["financial_account_count"] != 0:
        raise PilotError("pilot_initial_state")
    metadata = {
        "format": 1,
        "source_revision": revision,
        "catalog_trust": "local ephemeral engineering pilot key; not production release trust",
        "catalog_definitions": 23,
        "confidential_data": "selected original bytes and evidence are embedded locally in review.db after import",
    }
    (root / "pilot.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    pin_runtime(
        REPO,
        root,
        Path(sys.executable),
        Path(__file__),
        helper_relative=Path("devtools/v2_statement_pilot/prepare_pilot.py"),
        launcher_name="Open-statement-pilot.cmd",
        purpose="Pinned local statement pilot runtime; private profile is not included; not release acceptance",
    )
    (root / "PILOT-GUIDE.txt").write_text(
        "LOCAL V2 STATEMENT PILOT\n\n"
        "Open-statement-pilot.cmd reopens this independent profile.\n"
        "Imported statements remain unposted evidence. Add financial accounts, review account assignments, "
        "then explicitly review openings and supported activity. Unknown values stay unknown.\n"
        "The profile embeds imported original statement bytes. Keep this folder and backups private.\n"
        "Never open your 1.x database in this pilot. Originals are read only; no archive moves occur.\n"
        "Reports initially contain no reviewed money. Import success does not establish complete capture, "
        "balance reconciliation or correct accounting. Unsupported or incomplete evidence remains unresolved.\n"
        "Use Profile > Back up, Restore as a NEW file, and Save selected source original to inspect recovery.\n"
        "Catalog and preferences are separate from the database backup. The test catalog uses a fresh "
        "local key, whose private portion was discarded; this is not a production release.\n"
        "Archive import reports are local confidential files under imports/. Never commit them.\n",
        encoding="utf-8",
    )
    return initial


def verify(root: Path) -> dict:
    from parsetrail.core.v2_profile_store import SCHEMA_VERSION, V2ProfileStore

    workspace = workspace_at(root)
    catalog = workspace.catalog_cache.load_current()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        return {
            "schema": SCHEMA_VERSION,
            "catalog_definitions": len(catalog.definitions),
            "source_count": len(store.source_ids()),
            "journal_count": store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0],
            "financial_account_count": len(store.financial_accounts()),
            "binding_count": store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone()[0],
        }


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def archive_files(archive: Path, pilot: Path) -> tuple[list[Path], dict]:
    """Finite recursive CSV/PDF discovery; never follow a link or enter pilot output."""
    if _linked(archive) or not archive.is_dir():
        raise PilotError("archive_directory_unavailable")
    archive, pilot = archive.resolve(), pilot.resolve()
    if archive.is_relative_to(pilot) or pilot.is_relative_to(archive):
        raise PilotError("archive_overlaps_pilot")
    paths, pending = [], [archive]
    counters = Counter()
    discovered_directories = 1
    discovered_entries = 0
    if discovered_directories > MAX_ARCHIVE_DIRECTORIES:
        raise PilotError("archive_directory_limit")
    while pending:
        directory = pending.pop()
        counters["directories"] += 1
        if counters["directories"] > MAX_ARCHIVE_DIRECTORIES:
            raise PilotError("archive_directory_limit")
        try:
            children = []
            for child in directory.iterdir():
                discovered_entries += 1
                if discovered_entries > MAX_ARCHIVE_FILES + MAX_ARCHIVE_DIRECTORIES:
                    raise PilotError("archive_directory_entry_limit")
                children.append(child)
            children.sort(key=lambda path: path.name)
        except OSError:
            counters["unreadable_directories"] += 1
            continue
        for path in children:
            if _linked(path):
                counters["skipped_links"] += 1
            elif path.is_dir():
                discovered_directories += 1
                if discovered_directories > MAX_ARCHIVE_DIRECTORIES:
                    raise PilotError("archive_directory_limit")
                pending.append(path)
            elif path.is_file():
                counters["all_files"] += 1
                if counters["all_files"] > MAX_ARCHIVE_FILES:
                    raise PilotError("archive_file_limit")
                if path.suffix.lower() in {".csv", ".pdf"}:
                    paths.append(path)
                else:
                    counters["unsupported_files"] += 1
    paths.sort()
    return paths, dict(counters)


def _file_hash(path: Path) -> tuple[str, int]:
    from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES

    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while block := stream.read(min(1024 * 1024, MAX_SOURCE_BYTES - size + 1)):
            size += len(block)
            if size > MAX_SOURCE_BYTES:
                raise PilotError("archive_source_size_changed")
            digest.update(block)
    return digest.hexdigest(), size


def import_archive(root: Path, archive: Path, *, progress: Callable[[dict], None] | None = None) -> dict:
    """Import evidence only, with restart-safe receipts flushed after each result."""
    from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES
    from parsetrail.core.v2_workspace import MAX_BATCH_FILES

    isolate(root)
    workspace = workspace_at(root)
    initial = verify(root)
    if initial["journal_count"] or initial["financial_account_count"] or initial["binding_count"]:
        raise PilotError("archive_import_requires_unreviewed_pilot")
    paths, discovery = archive_files(archive, root)
    reports = root / "imports"
    reports.mkdir(exist_ok=True)
    run = reports / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
    run.mkdir()
    counts = Counter()
    fingerprints = {}
    started = last_progress = time.monotonic()

    def progress_state(completed: int) -> dict:
        return {
            "completed": completed,
            "selected_files": len(paths),
            "outcomes": dict(counts),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "profile_bytes": workspace.profile_path.stat().st_size,
        }

    if progress:
        progress(progress_state(0))
    with (run / "files.jsonl").open("x", encoding="utf-8") as log:
        for batch_start in range(0, len(paths), MAX_BATCH_FILES):
            batch = paths[batch_start : batch_start + MAX_BATCH_FILES]
            for path in batch:
                relative = path.relative_to(archive.resolve()).as_posix()
                try:
                    if _linked(path) or path.stat().st_size > MAX_SOURCE_BYTES:
                        counts["refused_shape_or_size"] += 1
                        log.write(json.dumps({"relative_path": relative, "status": "refused_shape_or_size"}) + "\n")
                        log.flush()
                        continue
                    before = _file_hash(path)
                except OSError:
                    counts["unreadable_files"] += 1
                    log.write(json.dumps({"relative_path": relative, "status": "unreadable"}) + "\n")
                    log.flush()
                    continue
                fingerprints[str(path)] = before
                result = workspace.import_files((path,)).files[0]
                after = _file_hash(path)
                unchanged = after == before
                matches_original = (
                    result.source_sha256 == before[0] if result.status in {"imported", "already_imported"} else None
                )
                record = {
                    "relative_path": relative,
                    "status": result.status,
                    "source_sha256": result.source_sha256,
                    "error_code": result.error_code,
                    "original_sha256": before[0],
                    "original_bytes": before[1],
                    "original_unchanged": unchanged,
                    "import_matches_checked_original": matches_original,
                }
                log.write(json.dumps(record, ensure_ascii=True) + "\n")
                log.flush()
                counts[result.status] += 1
                if result.error_code:
                    counts["failure_code:" + _safe_code(result.error_code)] += 1
                if not unchanged or matches_original is False:
                    raise PilotError("archive_source_changed_during_import")
                completed = sum(value for key, value in counts.items() if not key.startswith("failure_code:"))
                if progress and (completed % 25 == 0 or time.monotonic() - last_progress >= 30):
                    progress(progress_state(completed))
                    last_progress = time.monotonic()
    final = verify(root)
    if final["journal_count"] or final["financial_account_count"] or final["binding_count"]:
        raise PilotError("archive_import_created_authored_state")
    summary = {
        "selected_files": len(paths),
        "discovery": discovery,
        "outcomes": dict(counts),
        "source_count_before": initial["source_count"],
        "source_count_after": final["source_count"],
        "journals": 0,
        "financial_accounts": 0,
        "bindings": 0,
        "originals_checked": len(fingerprints),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "profile_bytes": workspace.profile_path.stat().st_size,
        "accounting_review": "not performed; imports are unposted evidence",
    }
    (run / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def _safe_code(value: str) -> str:
    return value if re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,100}", value) else "unclassified_import_failure"


def _profile_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def open_pilot(root: Path, *, smoke: bool = False) -> int:
    isolate(root)
    if not smoke:
        os.environ.pop("QT_QPA_PLATFORM", None)
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication

    workspace = workspace_at(root)
    before = _profile_digest(workspace.profile_path) if smoke else None
    app = QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(workspace)
    window.setWindowTitle("ParseTrail - local V2 statement pilot")
    if smoke:
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        QTimer.singleShot(100, app.quit)
    window.show()
    result = app.exec()
    window.close()
    if smoke:
        if _profile_digest(workspace.profile_path) != before:
            raise PilotError("pilot_startup_changed_profile")
        print(json.dumps({"startup": "passed", "platform": app.platformName(), "profile_unchanged": True}))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-at", type=Path)
    mode.add_argument("--open", type=Path)
    mode.add_argument("--verify", type=Path)
    mode.add_argument("--smoke-ui", type=Path)
    mode.add_argument("--import-archive", type=Path)
    parser.add_argument("--pilot", type=Path)
    args = parser.parse_args()
    if args.import_archive and args.pilot is None:
        parser.error("--import-archive requires --pilot")
    try:
        if args.prepare_at:
            summary = prepare(args.prepare_at.expanduser().resolve())
        elif args.import_archive:
            summary = import_archive(
                args.pilot.expanduser().resolve(),
                args.import_archive.expanduser(),
                progress=lambda update: print(json.dumps({"progress": update}, sort_keys=True), flush=True),
            )
        elif args.verify:
            isolate(args.verify.resolve())
            summary = verify(args.verify.resolve())
        else:
            return open_pilot((args.open or args.smoke_ui).resolve(), smoke=bool(args.smoke_ui))
        print(json.dumps(summary, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps({"error": _safe_code(str(exc)) if isinstance(exc, PilotError) else type(exc).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
