"""Parallel preparation preserves bounded ownership and ordered accounting choices."""

import gc
import hashlib
import threading
import weakref
from threading import Event, Lock, Thread

import pytest
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_parallel_preparation import OrderedPreparation, PreparationCancelled
from parsetrail.core.v2_prepared_import import PreparedImportSession
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

from .test_v2_workspace import DEFINITION, SOURCE, _workspace
from .test_v2_workspace_account_import import create_plan, workspace_with_choices


@pytest.mark.parametrize("workers", [0, 5, -1, True, "4"])
def test_worker_count_refuses_before_starting(workers):
    with pytest.raises(ValueError, match="import_preparation_workers_invalid"):
        OrderedPreparation((1,), lambda *_args, **_kwargs: pytest.fail("must not run"), workers=workers)


def test_queue_bounds_current_plus_lookahead_and_disposes_before_refill():
    gates = [Event() for _ in range(9)]
    started, live, disposed = [], set(), []
    lock, all_four = Lock(), Event()

    def prepare(index, *, cancelled):
        with lock:
            started.append(index)
            live.add(index)
            assert len(live) <= 4
            if len(started) == 4:
                all_four.set()
        assert gates[index].wait(5) and not cancelled()
        return index

    def dispose(index):
        with lock:
            live.remove(index)
            disposed.append(index)

    with OrderedPreparation(range(9), prepare, dispose=dispose, workers=4) as queue:
        assert all_four.wait(5)
        for index in (3, 2, 1, 0):
            gates[index].set()
        for index in range(9):
            gates[index].set()
            with queue.take_next() as result:
                assert result == index
                assert len(started) <= min(9, index + 4)
                assert index in live
            assert disposed[-1] == index
    assert disposed == list(range(9)) and not live


def test_cancelled_wait_joins_producers_and_disposes_unread_results():
    started = [Event() for _ in range(4)]
    stop, ready = Event(), Event()
    disposed, done = [], []

    def prepare(index, *, cancelled):
        started[index].set()
        if index == 1:
            ready.set()
            return index
        while not cancelled():
            stop.wait(0.01)
        done.append(index)
        raise PreparationCancelled("cancelled")

    with OrderedPreparation(range(4), prepare, dispose=disposed.append, workers=4, cancelled=stop.is_set) as queue:
        assert all(event.wait(5) for event in started) and ready.wait(5)
        stop.set()
        with pytest.raises(PreparationCancelled):
            with queue.take_next():
                pytest.fail("cancelled result must not be consumed")
    assert disposed == [1] and sorted(done) == [0, 2, 3]
    assert not queue._pending and queue._prepare is None
    assert not any(thread.name.startswith("ParseTrailPrepare") for thread in threading.enumerate())


def test_error_order_releases_producer_buffers_and_preserves_later_work():
    references, delivered = [], Event()

    class Buffer:
        pass

    def prepare(index, *, cancelled):
        assert not cancelled()
        if index:
            return index
        buffer = Buffer()
        references.append(weakref.ref(buffer))
        try:
            raise RuntimeError("inner")
        except RuntimeError:
            delivered.set()
            raise ValueError("safe_failure") from None

    with OrderedPreparation(range(3), prepare, workers=3) as queue:
        assert delivered.wait(5)
        with pytest.raises(ValueError, match="safe_failure") as failed:
            with queue.take_next():
                pytest.fail("failure is delivered in source order")
        gc.collect()
        assert references[0]() is None and failed.value.__cause__ is failed.value.__context__ is None
        for expected in (1, 2):
            with queue.take_next() as result:
                assert result == expected


def test_nine_hundred_sources_keep_four_slots_and_release_callbacks():
    live, peak, lock = set(), 0, Lock()

    def prepare(index, *, cancelled):
        nonlocal peak
        assert not cancelled()
        with lock:
            live.add(index)
            peak = max(peak, len(live))
        return index

    def dispose(index):
        with lock:
            live.remove(index)

    with OrderedPreparation(range(900), prepare, dispose=dispose, workers=4) as queue:
        for index in range(900):
            with queue.take_next() as result:
                assert result == index and len(queue._pending) <= 4
    assert not live and peak <= 4
    assert not queue._pending and queue._prepare is queue._dispose is queue._external_cancelled is None


@pytest.mark.parametrize("workers", [1, 2, 4])
def test_source_only_parallel_results_match_single_source_evidence_and_retry(tmp_path, workers):
    workspace = _workspace(tmp_path)
    paths = tuple(tmp_path / f"source-{index}.csv" for index in range(6))
    for index, path in enumerate(paths):
        path.write_bytes(SOURCE.replace(b"Coffee", f"Purchase {index}".encode()))
    source_hashes = tuple(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
    expected = {
        digest: build_source_evidence(path.read_bytes(), DEFINITION, suffix=".csv")
        for path, digest in zip(paths, source_hashes, strict=True)
    }
    result = workspace.import_files(paths + (paths[0],), preparation_workers=workers)
    assert [item.status for item in result.files] == ["imported"] * 6 + ["already_imported"]
    assert tuple(item.source_sha256 for item in result.files[:-1]) == source_hashes
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 6
        for path, digest in zip(paths, source_hashes, strict=True):
            saved = store.load_import(digest)
            assert saved.source == path.read_bytes() and saved.evidence.source_sha256 == digest
            assert saved.evidence == expected[digest]
            assert saved.evidence.payload.rows[0].amount.minor == -400
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_preparations_overlap_out_of_order_but_review_uses_fresh_accounts(tmp_path, monkeypatch):
    workspace, first, _activate = workspace_with_choices(tmp_path)
    paths = (first, *(tmp_path / f"source-{index}.csv" for index in range(1, 4)))
    for index, path in enumerate(paths[1:], 1):
        path.write_bytes(SOURCE.replace(b"Coffee", f"Purchase {index}".encode()))
    all_started, returned = Event(), [Event() for _ in range(4)]
    release = [Event() for _ in range(4)]
    ids = {hashlib.sha256(path.read_bytes()).hexdigest(): index for index, path in enumerate(paths)}
    original, lock, started, completion = PreparedImportSession.__init__, Lock(), [], []

    def constructor(self, source, **kwargs):
        index = ids[hashlib.sha256(source).hexdigest()]
        with lock:
            started.append(index)
            if len(started) == 4:
                all_started.set()
        assert release[index].wait(5)
        original(self, source, **kwargs)
        completion.append(index)
        returned[index].set()

    monkeypatch.setattr(PreparedImportSession, "__init__", constructor)
    seen, results, errors = [], [], []

    def review(path, current):
        seen.append((path, tuple(account.id for account in current.accounts), threading.get_ident()))
        if len(seen) == 1:
            return create_plan(current)
        return prepare_import_accounts(
            current,
            tuple(ImportAccountChoice(group.group_id, "chosen-checking") for group in current.groups),
            "synthetic_posted_csv",
        )

    def run():
        try:
            results.append(workspace.import_files(paths, review_import=review, preparation_workers=4))
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=run)
    thread.start()
    try:
        assert all_started.wait(5)
        for index in (3, 2, 1, 0):
            release[index].set()
            assert returned[index].wait(5)
    finally:
        for gate in release:
            gate.set()
        thread.join(10)
    assert not thread.is_alive() and not errors
    assert completion == [3, 2, 1, 0]
    assert [item[0] for item in seen] == list(paths)
    assert seen[0][1] == () and all(item[1] == ("chosen-checking",) for item in seen[1:])
    assert all(item[2] == thread.ident for item in seen)
    assert [item.status for item in results[0].files] == ["imported"] * 4


def test_prefetched_failure_is_retried_if_source_changed_before_its_turn(tmp_path, monkeypatch):
    workspace, first, _activate = workspace_with_choices(tmp_path)
    second = tmp_path / "second.csv"
    second.write_bytes(b"not a valid export")
    failed_ready, seen = Event(), []
    original = workspace._prepare_batch_source

    def prepare(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == second:
            assert result.error is not None
            failed_ready.set()
        return result

    monkeypatch.setattr(workspace, "_prepare_batch_source", prepare)

    def review(path, current):
        seen.append(path)
        if path == first:
            assert failed_ready.wait(5)
            second.write_bytes(SOURCE.replace(b"Coffee", b"Updated before turn"))
            return create_plan(current)
        return prepare_import_accounts(
            current,
            tuple(ImportAccountChoice(group.group_id, "chosen-checking") for group in current.groups),
            "synthetic_posted_csv",
        )

    result = workspace.import_files((first, second), review_import=review, preparation_workers=2)
    assert [item.status for item in result.files] == ["imported", "imported"] and seen == [first, second]
    saved = workspace.saved_import(result.files[1].source_sha256)
    assert (
        saved.source == second.read_bytes() and saved.evidence.payload.rows[0].description.text == "Updated before turn"
    )


@pytest.mark.parametrize("drift", ["source", "catalog"])
def test_stale_successful_preparation_releases_old_slot_before_repreparing(tmp_path, monkeypatch, drift):
    workspace, first, activate = workspace_with_choices(tmp_path)
    paths = (first, *(tmp_path / f"source-{index}.csv" for index in range(1, 4)))
    for index, path in enumerate(paths[1:], 1):
        path.write_bytes(SOURCE.replace(b"Coffee", f"Purchase {index}".encode()))
    original_init, original_close = PreparedImportSession.__init__, PreparedImportSession.close
    live, lock, prepared_count, all_prepared, peak = set(), Lock(), 0, Event(), 0

    def constructor(self, *args, **kwargs):
        nonlocal prepared_count, peak
        with lock:
            live.add(id(self))
            peak = max(peak, len(live))
            assert len(live) <= 4
        original_init(self, *args, **kwargs)
        with lock:
            prepared_count += 1
            if prepared_count == 4:
                all_prepared.set()

    def close(self):
        with lock:
            live.discard(id(self))
        original_close(self)

    monkeypatch.setattr(PreparedImportSession, "__init__", constructor)
    monkeypatch.setattr(PreparedImportSession, "close", close)
    reviews = []

    def choose(path, review):
        reviews.append((path, review))
        if len(reviews) == 1:
            assert all_prepared.wait(5)
            if drift == "source":
                paths[2].write_bytes(SOURCE.replace(b"Coffee", b"Current source version"))
            else:
                activate(2)
        if not review.accounts:
            return create_plan(review)
        return prepare_import_accounts(
            review,
            tuple(ImportAccountChoice(group.group_id, "chosen-checking") for group in review.groups),
            "synthetic_posted_csv",
        )

    result = workspace.import_files(paths, review_import=choose, preparation_workers=4)
    assert [item.status for item in result.files] == ["imported"] * 4
    assert not live and peak <= 4
    assert prepared_count > 4
    assert all(workspace.saved_import(item.source_sha256).source == item.path.read_bytes() for item in result.files)
    if drift == "catalog":
        assert reviews[1][0] == first and reviews[1][1].recovery_notice


def test_known_source_retry_skips_preparation_and_invalid_worker_count_does_no_work(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    path = tmp_path / "already.csv"
    path.write_bytes(SOURCE)
    workspace.import_file(path)
    before = workspace.profile_path.read_bytes()

    def forbidden(*_args, **_kwargs):
        pytest.fail("saved source must not be decoded again")

    monkeypatch.setattr(PreparedImportSession, "__init__", forbidden)
    result = workspace.import_files((path, path), preparation_workers=4)
    assert [item.status for item in result.files] == ["already_imported", "already_imported"]
    with pytest.raises(ValueError, match="import_preparation_workers_invalid"):
        workspace.import_files((path,), preparation_workers=5)
    assert workspace.profile_path.read_bytes() == before
