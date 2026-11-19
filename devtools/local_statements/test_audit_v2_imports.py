"""Public synthetic audit checks: runtime policy, safe metadata and refusal boundaries."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock, Thread

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core import v2_pdf_routing, v2_source_pipeline
from parsetrail.core.v2_bounded_pdf_text import DecodedPDFText
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import V2ProfileStore
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.local_statements import audit_v2_imports as audit

REPO = Path(__file__).resolve().parents[2]
DEFINITION = REPO / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,PRIVATE ACCOUNT NAME,PRIVATE MERCHANT,$1200.00,$2200.00\n"
    b"10/02/2026,PRIVATE ACCOUNT NAME,PRIVATE GROCER,-$57.43,$2142.57\n"
)


@pytest.fixture
def setup(tmp_path):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / DEFINITION.name).write_bytes(DEFINITION.read_bytes())
    sources = tmp_path / "sources"
    sources.mkdir()
    return sources, definitions


def catalog(definitions):
    return audit.load_catalog(definitions=definitions)


def run(sources, definitions, **kwargs):
    verified, mode = catalog(definitions)
    return audit.audit_directory(sources, catalog=verified, mode=mode, **kwargs)


def test_real_csv_recognition_is_read_only_and_report_omits_private_fields(setup, tmp_path, monkeypatch):
    sources, definitions = setup
    path = sources / "private-filename.csv"
    path.write_bytes(SOURCE)
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Audit must not open a financial profile")

    monkeypatch.setattr(V2ProfileStore, "open", forbidden)
    report = run(sources, definitions)
    record = report["files"][0]
    assert report["summary"]["recognized"] == 1 and audit.exit_code(report) == 0
    assert report["mode"] == "development_definitions_not_installed_catalog"
    assert record["source_sha256"] == hashlib.sha256(SOURCE).hexdigest()
    candidate = record["candidates"][0]
    assert candidate["row_count"] == 2 and candidate["source_account_group_count"] == 1
    assert candidate["start"]["iso"] == "2026-10-01" and candidate["end"]["iso"] == "2026-10-02"
    assert candidate["start"]["provenance"] == "derived"
    text = json.dumps(report)
    for private in ("private-filename", "PRIVATE", "$1200.00", "preview_rows", "source_identity", '"raw"'):
        assert private not in text
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert list(tmp_path.rglob("*.db")) == []


def test_runtime_pdf_routing_and_warning_policy_are_projected_without_raw_text(setup, monkeypatch):
    sources, definitions = setup
    (definitions / DEFINITION.name).unlink()
    citi = REPO / "devtools/parser_engine_pilot/legacy-citi-pilot-definition.json"
    (definitions / citi.name).write_bytes(citi.read_bytes())
    (sources / "sample.pdf").write_bytes(b"%PDF-public-synthetic")
    text = "\n".join(
        (
            "www.citicards.com",
            "Account number ending in: 1234",
            "Billing Period: 01/01/26-01/31/26",
            "Previous balance $100.00",
            "New balance $90.00",
            "Date Description Amount",
            "01/05 AUTOPAY AUTO-PMT -$20.00",
            "01/10 01/09 FOREIGN PURCHASE $10.00",
            "PRIVATE UNCLASSIFIED $7.00",
        )
    )

    def decode(_source, *, cancelled=None):
        assert cancelled is not None
        return DecodedPDFText((text,), (("Producer", "Public synthetic fixture"),))

    monkeypatch.setattr(v2_pdf_routing, "decode_pdf", decode)
    monkeypatch.setattr(v2_source_pipeline, "decode_pdf_default_layout", decode)
    report = run(sources, definitions)
    assert audit.exit_code(report) == 1
    candidate = report["files"][0]["candidates"][0]
    assert candidate["parser_id"] == "pdf_citicc_201505" and candidate["row_count"] == 2
    warning = next(warning for warning in candidate["warnings"] if warning["code"] == "unclassified_monetary_line")
    assert warning == {
        "code": "unclassified_monetary_line",
        "classification": "requires_review",
        "occurrence_count": 1,
        "locations": [{"kind": "pdf_line", "page": 1, "line": 9}],
    }
    assert "PRIVATE" not in json.dumps(report) and "$7.00" not in json.dumps(report)


def test_patterns_recursion_and_file_limit_bound_selection(setup):
    sources, definitions = setup
    (sources / "one.csv").write_bytes(SOURCE)
    (sources / "ignore.csv").write_bytes(b"unrelated")
    nested = sources / "nested"
    nested.mkdir()
    (nested / "one.csv").write_bytes(SOURCE)
    report = run(sources, definitions, patterns=("ONE*.csv",))
    assert report["summary"]["files_selected"] == 1
    report = run(sources, definitions, patterns=("one.csv",), recursive=True, show_filenames=True)
    assert {record["file"] for record in report["files"]} == {"one.csv", "nested/one.csv"}
    with pytest.raises(ValueError, match="audit_file_limit"):
        run(sources, definitions, patterns=("one.csv",), recursive=True, max_files=1)
    with pytest.raises(ValueError, match="audit_pattern_invalid"):
        run(sources, definitions, patterns=("../*.csv",))
    for pattern in ("C:outside.csv", "name.pdf:stream.csv"):
        with pytest.raises(ValueError, match="audit_pattern_invalid"):
            run(sources, definitions, patterns=(pattern,))


def test_read_bounds_and_source_changes_are_refused(setup, monkeypatch):
    sources, definitions = setup
    path = sources / "one.csv"
    path.write_bytes(SOURCE)
    with pytest.raises(ValueError, match="source_size"):
        audit.read_limited(path, 2)
    original = audit.recognize_catalog_source

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        path.write_bytes(SOURCE + b"changed")
        return result

    monkeypatch.setattr(audit, "recognize_catalog_source", mutate)
    report = run(sources, definitions)
    assert report["files"][0]["error"] == "source_changed" and audit.exit_code(report) == 1


def test_selected_source_link_is_refused(setup, tmp_path):
    sources, _definitions = setup
    path = sources / "one.csv"
    path.write_bytes(SOURCE)
    linked = tmp_path / "linked.csv"
    try:
        linked.symlink_to(path)
    except OSError:
        pytest.skip("This Windows account cannot create symbolic links")
    with pytest.raises(ValueError, match="source_file_unavailable"):
        audit.read_limited(linked, 10000)


def test_exact_filenames_require_no_sibling_directory_inventory(setup, monkeypatch):
    sources, definitions = setup
    (sources / "one.csv").write_bytes(SOURCE)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Exact selected names must not inventory siblings")

    monkeypatch.setattr(audit.os, "walk", forbidden)
    report = run(sources, definitions, patterns=("one.csv", "one.csv"))
    assert report["summary"]["recognized"] == report["summary"]["files_selected"] == 1
    report = run(sources, definitions, patterns=("missing.csv",))
    assert report["summary"]["failed"] == 1 and audit.exit_code(report) == 1
    assert report["files"][0]["error"] == "source_file_unavailable"


def test_unreadable_subtree_refuses_incomplete_selection_without_private_error(setup, monkeypatch):
    sources, definitions = setup

    def unreadable(_directory, *, followlinks, onerror):
        assert not followlinks
        onerror(PermissionError("PRIVATE subtree path"))
        return iter(())

    monkeypatch.setattr(audit.os, "walk", unreadable)
    with pytest.raises(ValueError, match="^audit_directory_unavailable$"):
        run(sources, definitions, recursive=True)


def test_per_file_failures_are_redacted_and_do_not_stop_later_sources(setup, monkeypatch):
    sources, definitions = setup
    (sources / "first.csv").write_bytes(b"invalid header")
    (sources / "last.csv").write_bytes(SOURCE)
    report = run(sources, definitions)
    assert report["summary"]["failed"] == report["summary"]["recognized"] == 1
    assert report["files"][0]["error"] == "no_matching_format"

    def bad(*_args, **_kwargs):
        raise RuntimeError("PRIVATE document path/account/text")

    monkeypatch.setattr(audit, "recognize_catalog_source", bad)
    report = run(sources, definitions)
    assert report["summary"]["failed"] == 2 and "PRIVATE" not in json.dumps(report)
    assert {record["error"] for record in report["files"]} == {"audit_file_failed"}


def test_ambiguous_csv_retains_all_candidates_without_claiming_import_failure(setup):
    sources, definitions = setup
    alternate = json.loads(DEFINITION.read_bytes())
    alternate["parser_id"] = "synthetic_other_csv"
    (definitions / "other-definition.json").write_text(json.dumps(alternate), encoding="utf-8")
    (sources / "one.csv").write_bytes(SOURCE)
    report = run(sources, definitions)
    assert report["files"][0]["status"] == "ambiguous" and len(report["files"][0]["candidates"]) == 2
    assert report["summary"]["failed"] == 0 and report["summary"]["requires_review"] == 1
    assert audit.exit_code(report) == 1


def test_cancellation_keeps_only_completed_metadata_and_report_budget_is_bounded(setup, monkeypatch):
    sources, definitions = setup
    for name in ("one.csv", "two.csv"):
        (sources / name).write_bytes(SOURCE)
    stop = Event()
    original_queue = audit.OrderedPreparation

    class StopAfterCompletedFile(original_queue):
        @contextmanager
        def take_next(self):
            with super().take_next() as record:
                yield record
            stop.set()

    monkeypatch.setattr(audit, "OrderedPreparation", StopAfterCompletedFile)
    report = run(sources, definitions, cancelled=stop.is_set)
    assert report["summary"]["files_completed"] == 1
    assert report["summary"]["files_remaining"] == 1 and audit.exit_code(report) == 130
    monkeypatch.setattr(audit, "OrderedPreparation", original_queue)
    monkeypatch.setattr(audit, "MAX_REPORT_BYTES", 1)
    report = run(sources, definitions)
    assert report["summary"]["files_completed"] == 0 and report["summary"]["metadata_limit_reached"]
    assert audit.exit_code(report) == 1


def test_parallel_preparations_overlap_but_metadata_matches_serial_order(setup, monkeypatch):
    sources, definitions = setup
    source_indices = {}
    for index in range(6):
        data = SOURCE.replace(b"PRIVATE MERCHANT", f"PRIVATE MERCHANT {index}".encode())
        (sources / f"{index:02d}.csv").write_bytes(data)
        source_indices[data] = index
    verified, mode = catalog(definitions)
    original = audit.recognize_catalog_source
    lock = Lock()
    releases = [Event() for _ in range(4)]
    done = [Event() for _ in range(4)]
    started = Event()
    active = peak = 0

    def recognize(source, **kwargs):
        nonlocal active, peak
        index = source_indices[source]
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 4:
                started.set()
        try:
            if index < 4:
                assert releases[index].wait(10), "test gate did not release"
            return original(source, **kwargs)
        finally:
            with lock:
                active -= 1
            if index < 4:
                done[index].set()

    monkeypatch.setattr(audit, "recognize_catalog_source", recognize)
    results, failures = [], []

    def run_parallel():
        try:
            results.append(audit.audit_directory(sources, catalog=verified, mode=mode, workers=4))
        except BaseException as error:
            failures.append(error)

    runner = Thread(target=run_parallel)
    runner.start()
    try:
        assert started.wait(10), "four independent preparations did not overlap"
        for index in (3, 2, 1):
            releases[index].set()
            assert done[index].wait(10)
        assert not results
    finally:
        for release in releases:
            release.set()
        runner.join(20)
    assert not runner.is_alive() and not failures and peak == 4
    assert results[0]["summary"]["recognized"] == 6
    serial = audit.audit_directory(sources, catalog=verified, mode=mode, workers=1)
    assert results[0] == serial


def test_cancelling_four_active_audit_preparations_joins_them(setup, monkeypatch):
    sources, definitions = setup
    for index in range(8):
        (sources / f"{index:02d}.csv").write_bytes(SOURCE)
    entered, release, stop = Event(), Event(), Event()
    lock = Lock()
    started = finished = 0
    original = audit.recognize_catalog_source

    def recognize(source, **kwargs):
        nonlocal started, finished
        with lock:
            started += 1
            if started == 4:
                entered.set()
        try:
            assert release.wait(10), "test cancellation gate did not release"
            return original(source, **kwargs)
        finally:
            with lock:
                finished += 1

    monkeypatch.setattr(audit, "recognize_catalog_source", recognize)
    results = []
    runner = Thread(target=lambda: results.append(run(sources, definitions, workers=4, cancelled=stop.is_set)))
    runner.start()
    try:
        assert entered.wait(10)
        stop.set()
    finally:
        release.set()
        runner.join(20)
    assert not runner.is_alive() and started == finished == 4
    assert len(results) == 1 and audit.exit_code(results[0]) == 130
    assert results[0]["files"] == [] and results[0]["summary"]["files_remaining"] == 8


@pytest.mark.parametrize("workers", [0, 5, True, 1.5])
def test_invalid_workers_refuse_before_selecting_sources(setup, monkeypatch, workers):
    sources, definitions = setup

    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid concurrency must not select source paths")

    monkeypatch.setattr(audit, "selected_paths", forbidden)
    with pytest.raises(ValueError, match="import_preparation_workers_invalid"):
        run(sources, definitions, workers=workers)


def test_cli_verified_catalog_aggregate_stdout_report_creation_and_no_overwrite(setup, tmp_path, capsys):
    sources, definitions = setup
    (sources / "private-name.csv").write_bytes(SOURCE)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _catalog = signed_catalog_bytes(definitions, key, release_sequence=4, source_revision="a" * 40)
    release = tmp_path / "release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    trust = tmp_path / "public-keys.json"
    trust.write_text(json.dumps({key_id_for_public_key(public): public.hex()}), encoding="utf-8")
    report = tmp_path / "audit.json"
    args = [
        str(sources),
        "--catalog-release",
        str(release),
        "--trust-keys",
        str(trust),
        "--report",
        str(report),
        "--show-filenames",
    ]
    assert audit.main(args) == 0
    stdout = capsys.readouterr().out
    assert "PRIVATE" not in stdout and "private-name" not in stdout and "source_sha256" not in stdout
    saved = json.loads(report.read_text(encoding="utf-8"))
    assert saved["files"][0]["file"] == "private-name.csv" and saved["mode"] == "verified_release"
    before = report.read_bytes()
    assert audit.main(args) == 2 and report.read_bytes() == before
    capsys.readouterr()
    (release / "catalog.sig").write_bytes(b"0" * 64)
    assert audit.main(args[:5]) == 2
    assert "invalid_signature" in capsys.readouterr().out
