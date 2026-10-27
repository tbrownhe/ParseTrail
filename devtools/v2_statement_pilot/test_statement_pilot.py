"""Synthetic archive import and pinned local pilot lifecycle verification."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOL = Path(__file__).with_name("prepare_pilot.py")


def tool_module():
    spec = importlib.util.spec_from_file_location("statement_pilot_under_test", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_tool(helper, *args):
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    return subprocess.run(
        [sys.executable, "-B", str(helper), *map(str, args)],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )


@pytest.fixture(scope="module")
def pilot(tmp_path_factory):
    root = tmp_path_factory.mktemp("statement-pilot") / "pilot"
    result = run_tool(TOOL, "--prepare-at", root)
    assert result.returncode == 0, result.stderr
    initial = json.loads(result.stdout)
    assert initial == {
        "schema": 22,
        "catalog_definitions": 23,
        "source_count": 0,
        "journal_count": 0,
        "financial_account_count": 0,
        "binding_count": 0,
    }
    return root


def test_prepare_and_pinned_startup_refuse_overwrite(pilot):
    profile = pilot / "review.db"
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    helper = pilot / "runtime/devtools/v2_statement_pilot/prepare_pilot.py"
    checked = run_tool(helper, "--verify", pilot)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["catalog_definitions"] == 23
    startup = run_tool(helper, "--smoke-ui", pilot)
    assert startup.returncode == 0, startup.stderr
    assert json.loads(startup.stdout)["profile_unchanged"] is True
    manifest = json.loads((pilot / "runtime-manifest.json").read_text())
    for record in manifest["files"]:
        assert hashlib.sha256((pilot / "runtime" / record["path"]).read_bytes()).hexdigest() == record["sha256"]
    refused = run_tool(TOOL, "--prepare-at", pilot)
    assert refused.returncode == 1 and "FileExistsError" in refused.stderr
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
    assert "devtools\\v2_statement_pilot\\prepare_pilot.py" in (pilot / "Open-statement-pilot.cmd").read_text()
    assert "PRIVATE" not in startup.stdout
    assert not list(pilot.rglob("*.key"))


def test_archive_import_retry_recovery_and_no_authored_money(pilot, tmp_path):
    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.core.v2_source_recovery import recover_source_original

    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

    archive = tmp_path / "archive"
    nested = archive / "nested"
    nested.mkdir(parents=True)
    cases = family_sources()
    csv = next(case for case in cases if case.suffix == ".csv")
    pdf = next(case for case in cases if case.definition_name == "capital-one-loan-pilot-definition.json")
    originals = {
        archive / "confidential-name.csv": csv.source,
        nested / "loan-private.pdf": pdf.source,
        nested / "copy-private.pdf": pdf.source,
        archive / "unsupported.xlsx": b"not imported",
        archive / "broken-private.pdf": b"not a PDF",
    }
    for path, content in originals.items():
        path.write_bytes(content)
    helper = pilot / "runtime/devtools/v2_statement_pilot/prepare_pilot.py"
    result = run_tool(helper, "--import-archive", archive, "--pilot", pilot)
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout.splitlines()[-1])
    assert summary["selected_files"] == 4
    assert summary["discovery"]["unsupported_files"] == 1
    assert summary["outcomes"]["imported"] == 2
    assert summary["outcomes"]["already_imported"] == 1
    assert summary["outcomes"]["failed"] == 1
    assert summary["journals"] == summary["financial_accounts"] == summary["bindings"] == 0
    assert all(path.name not in result.stdout + result.stderr for path in originals)
    retried = run_tool(helper, "--import-archive", archive, "--pilot", pilot)
    assert retried.returncode == 0, retried.stderr
    retry_summary = json.loads(retried.stdout.splitlines()[-1])
    assert retry_summary["source_count_before"] == retry_summary["source_count_after"] == 2
    assert retry_summary["outcomes"]["already_imported"] == 3
    backup = V2ProfileStore.snapshot_to(pilot / "review.db", tmp_path / "backup.dbb")
    restored = V2ProfileStore.snapshot_to(backup, tmp_path / "restored.db")
    with V2ProfileStore.open(restored, read_only=True) as store:
        assert len(store.source_ids()) == 2
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.financial_accounts() == ()
        for source_id in store.source_ids():
            recovered = recover_source_original(restored, source_id, tmp_path / (source_id + ".recovered"))
            assert recovered.read_bytes() in (csv.source, pdf.source)
    assert all(path.read_bytes() == content for path, content in originals.items())
    reports = list((pilot / "imports").glob("*/files.jsonl"))
    assert len(reports) == 2
    assert all(
        json.loads(line)["status"] in {"imported", "already_imported", "failed"}
        for line in reports[0].read_text().splitlines()
    )


def test_archive_safety_bounds_links_and_overlapping_output(tmp_path, monkeypatch):
    module = tool_module()
    archive, pilot = tmp_path / "archive", tmp_path / "pilot"
    archive.mkdir()
    pilot.mkdir()
    (archive / "one.csv").write_bytes(b"one")
    for root, output in ((archive, archive), (archive, archive / "nested"), (pilot / "runtime", pilot)):
        if not root.exists():
            root.mkdir()
        with pytest.raises(module.PilotError, match="archive_overlaps_pilot"):
            module.archive_files(root, output)
    monkeypatch.setattr(module, "MAX_ARCHIVE_FILES", 0)
    with pytest.raises(module.PilotError, match="archive_file_limit"):
        module.archive_files(archive, pilot)
    monkeypatch.setattr(module, "MAX_ARCHIVE_FILES", 100_000)
    link = archive / "loop"
    try:
        link.symlink_to(archive, target_is_directory=True)
    except OSError:
        return  # Windows leaf-symlink permission is separately platform dependent.
    paths, counts = module.archive_files(archive, pilot)
    assert paths == [archive / "one.csv"] and counts["skipped_links"] == 1


def test_pinner_helper_paths_cannot_escape_or_inject_commands():
    from devtools.v2_review_demo.pin_runtime import launcher_text

    for path in (Path("../outside.py"), Path('devtools/bad"name.py'), Path("devtools/%BAD%.py")):
        with pytest.raises(ValueError, match="runtime_helper_path"):
            launcher_text(Path(sys.executable), path)


def test_archive_directory_queue_cannot_exceed_limit(tmp_path, monkeypatch):
    module = tool_module()
    archive = tmp_path / "archive"
    archive.mkdir()
    for index in range(3):
        (archive / str(index)).mkdir()
    monkeypatch.setattr(module, "MAX_ARCHIVE_DIRECTORIES", 2)
    with pytest.raises(module.PilotError, match="archive_directory_limit"):
        module.archive_files(archive, tmp_path / "pilot")


def test_imported_hash_must_match_the_original_checked_bytes(tmp_path, monkeypatch):
    module = tool_module()
    root, archive = tmp_path / "pilot", tmp_path / "archive"
    root.mkdir()
    archive.mkdir()
    (root / "review.db").write_bytes(b"disposable test placeholder")
    (archive / "statement.csv").write_bytes(b"original stays unchanged")
    imported = SimpleNamespace(status="imported", source_sha256="f" * 64, error_code=None)
    workspace = SimpleNamespace(
        profile_path=root / "review.db", import_files=lambda _paths: SimpleNamespace(files=(imported,))
    )
    monkeypatch.setattr(module, "workspace_at", lambda _root: workspace)
    monkeypatch.setattr(
        module,
        "verify",
        lambda _root: {"source_count": 0, "journal_count": 0, "financial_account_count": 0, "binding_count": 0},
    )
    with pytest.raises(module.PilotError, match="archive_source_changed_during_import"):
        module.import_archive(root, archive)
    receipt = json.loads(next((root / "imports").glob("*/files.jsonl")).read_text())
    assert receipt["original_unchanged"] is True
    assert receipt["import_matches_checked_original"] is False
    assert not list((root / "imports").glob("*/summary.json"))
