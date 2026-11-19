"""Compare 1/2/4 workers with generated public PDFs, never private statements."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from time import perf_counter

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "client/src"), str(REPOSITORY / "client"), str(REPOSITORY)]


def source_document(index: int, rows: int) -> bytes:
    from devtools.parser_engine_pilot.synthetic_family_sources import pdf_document, text_page

    def dollars(minor):
        return f"${minor // 100:,}.{minor % 100:02d}"

    initial = 100_000
    lines = [
        "Oregon Community Credit Union MemberNumber",
        "FROM 01/01/26",
        "TO 01/31/26",
        "XXXXXX1234 - PRIMARY SAVINGS .",
        "Previous Balance.................... $100.00",
        "Ending Balance...................... $100.00",
        "XXXXXX5678 - REMARKABLE CHECKING .",
        "Previous Balance.................... $1,000.00",
        f"Ending Balance...................... {dollars(initial - rows * 100)}",
    ]
    for row in range(rows):
        day = row * 28 // rows + 1
        balance = initial - (row + 1) * 100
        lines.append(f"01/{day:02d} # Public benchmark document {index} row {row + 1} ($1.00) {dollars(balance)}")
    return pdf_document(tuple(text_page(*lines[offset : offset + 48]) for offset in range(0, len(lines), 48)))


def new_workspace(root: Path):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from parsetrail.core.v2_data_catalog import key_id_for_public_key
    from parsetrail.core.v2_workspace import V2Workspace
    from scripts.v2_catalog_release import signed_catalog_bytes

    root.mkdir()
    pilot = REPOSITORY / "devtools/parser_engine_pilot"
    definitions = root / "definitions"
    definitions.mkdir()
    name = "occu-bank-pilot-definition.json"
    (definitions / name).write_bytes((pilot / name).read_bytes())
    contexts = json.loads((pilot / "account-contexts.json").read_bytes())
    (definitions / "account-contexts.json").write_text(
        json.dumps({"pdf_occubank_201409": contexts["pdf_occubank_201409"]}), encoding="utf-8"
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _catalog = signed_catalog_bytes(definitions, key, release_sequence=1, source_revision="0" * 40)
    del key
    workspace = V2Workspace.create(
        root / "review.db",
        root / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=root / "preferences.json",
    )
    release = root / "release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace.install_catalog_release(release)
    return workspace


@contextmanager
def measurements():
    """Observe real decoder calls and preparation storage, not total process RSS."""
    from parsetrail.core import v2_bounded_pdf_annotations, v2_bounded_pdf_text
    from parsetrail.core.v2_prepared_import import PreparedImportSession

    lock = Lock()
    live = {}
    stats = {"prepared_slots_peak": 0, "canonical_source_bytes_peak": 0, "decoder_calls": 0, "decoder_calls_peak": 0}
    decoders = 0
    original_init, original_close = PreparedImportSession.__init__, PreparedImportSession.close
    original_workers = {module: module.run_worker for module in (v2_bounded_pdf_text, v2_bounded_pdf_annotations)}

    def initialize(session, source, **kwargs):
        with lock:
            live[id(session)] = len(source)
            stats["prepared_slots_peak"] = max(stats["prepared_slots_peak"], len(live))
        original_init(session, source, **kwargs)
        with lock:
            live[id(session)] = len(source) + session._output_bytes
            stats["canonical_source_bytes_peak"] = max(stats["canonical_source_bytes_peak"], sum(live.values()))

    def close(session):
        try:
            return original_close(session)
        finally:
            with lock:
                live.pop(id(session), None)

    def observe_worker(original):
        def run(*args, **kwargs):
            nonlocal decoders
            with lock:
                decoders += 1
                stats["decoder_calls"] += 1
                stats["decoder_calls_peak"] = max(stats["decoder_calls_peak"], decoders)
            try:
                return original(*args, **kwargs)
            finally:
                with lock:
                    decoders -= 1

        return run

    PreparedImportSession.__init__, PreparedImportSession.close = initialize, close
    for module, original in original_workers.items():
        module.run_worker = observe_worker(original)
    try:
        yield stats
        assert not live and decoders == 0, "Preparation or decoder work outlived its owner"
    finally:
        PreparedImportSession.__init__, PreparedImportSession.close = original_init, original_close
        for module, original in original_workers.items():
            module.run_worker = original


def prepare_only(paths: tuple[Path, ...], catalog, workers: int):
    from parsetrail.core.v2_parallel_preparation import OrderedPreparation
    from parsetrail.core.v2_prepared_import import PreparedImportSession

    def prepare(path, *, cancelled):
        return PreparedImportSession(path.read_bytes(), catalog=catalog, suffix=".pdf", cancelled=cancelled)

    digests = []
    with OrderedPreparation(paths, prepare, dispose=lambda session: session.close(), workers=workers) as queue:
        for _path in paths:
            with queue.take_next() as session:
                digests.append(
                    tuple((key, hashlib.sha256(content).hexdigest()) for key, (content, _) in session._outputs.items())
                )
    return digests


def import_all(workspace, paths: tuple[Path, ...], workers: int):
    from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
    from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore

    reviews = 0

    def review(_path, current):
        nonlocal reviews
        reviews += 1
        targets = {
            "1234": FinancialAccount("public-savings", "Public savings", "asset", "occu", product_type="savings"),
            "5678": FinancialAccount("public-checking", "Public checking", "asset", "occu", product_type="checking"),
        }
        existing = {account.id for account in current.accounts}
        workspace.set_allow_abbreviated_account_matching(True)
        workspace.set_import_preview_mode("when_needed")
        return prepare_import_accounts(
            current,
            tuple(ImportAccountChoice(group.group_id, targets[group.source_identity].id) for group in current.groups),
            "pdf_occubank_201409",
            new_accounts=tuple(account for account in targets.values() if account.id not in existing),
        )

    result = workspace.import_files(paths, review_import=review, preparation_workers=workers)
    assert [(item.status, item.error_code) for item in result.files] == [("imported", None)] * len(paths), result
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        evidence = {source: store.load_import(source).evidence.model_dump_json() for source in store.source_ids()}
        bindings = {
            source: tuple(
                (item.source_identity, item.source_identity_form, item.ledger_account_id)
                for item in store.source_account_bindings(source)
            )
            for source in store.source_ids()
        }
        journal_count = store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone()[0]
        row_count = store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone()[0]
    assert reviews == 1 and journal_count == 0
    return evidence, bindings, {"review_requests": reviews, "journal_count": journal_count, "row_count": row_count}


def timed(operation: Callable):
    with measurements() as stats:
        started = perf_counter()
        result = operation()
        stats["wall_seconds"] = round(perf_counter() - started, 4)
    return result, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="NEW output directory beneath repository scratch")
    parser.add_argument("--files", type=int, default=8)
    parser.add_argument("--rows", type=int, default=100)
    args = parser.parse_args(argv)
    root = args.output.resolve()
    if not root.is_relative_to((REPOSITORY / "scratch").resolve()) or root.exists():
        parser.error("--output must name a new directory beneath repository scratch")
    if not 4 <= args.files <= 100 or not 1 <= args.rows <= 500:
        parser.error("--files must be 4..100; --rows must be 1..500")
    root.mkdir(parents=True)
    for key, target in {
        "HOME": root / "app-home",
        "USERPROFILE": root / "app-home",
        "APPDATA": root / "app-home/AppData/Roaming",
        "LOCALAPPDATA": root / "app-home/AppData/Local",
    }.items():
        target.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(target)
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    sources = root / "sources"
    sources.mkdir()
    paths = tuple(sources / f"public-{index:03d}.pdf" for index in range(args.files))
    for index, path in enumerate(paths):
        path.write_bytes(source_document(index, args.rows))
    prepare_workspace = new_workspace(root / "preparation-catalog")
    catalog = prepare_workspace.catalog_cache.load_current()
    report = {
        "scope": "generated_public_pdfs_no_private_inputs_no_owner_acceptance",
        "python": platform.python_version(),
        "platform": platform.platform(),
        "files": args.files,
        "rows_per_file": args.rows,
        "source_bytes": sum(path.stat().st_size for path in paths),
        "measurement": "single ordered 1/2/4 trial; canonical retained bytes exclude models/decoded text/RSS",
        "runs": [],
    }
    baseline_prepared = baseline_imported = None
    for workers in (1, 2, 4):
        prepared, prepare_stats = timed(lambda workers=workers: prepare_only(paths, catalog, workers))
        workspace = new_workspace(root / f"import-{workers}")
        imported, import_stats = timed(
            lambda workspace=workspace, workers=workers: import_all(workspace, paths, workers)
        )
        if baseline_prepared is None:
            baseline_prepared, baseline_imported = prepared, imported[:2]
        assert prepared == baseline_prepared and imported[:2] == baseline_imported
        assert max(prepare_stats["prepared_slots_peak"], import_stats["prepared_slots_peak"]) <= workers
        assert max(prepare_stats["decoder_calls_peak"], import_stats["decoder_calls_peak"]) <= workers
        report["runs"].append(
            {"workers": workers, "prepare": prepare_stats, "import": import_stats, "saved": imported[2], "parity": True}
        )
    (root / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
