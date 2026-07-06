import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from inspect_ai.event._info import InfoEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import database as database_module
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.types import SampleEvent

SyncFunction = Callable[[SampleBufferDatabase, SampleBufferFilestore], None]


class CleanupRecorder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def record_db_cleanup(self, _path: Path) -> None:
        self._record("db")

    def record_filestore_cleanup(self, _filestore: SampleBufferFilestore) -> None:
        self._record("filestore")

    def _record(self, call: str) -> None:
        with self._lock:
            self.calls.append(call)


class SyncRecorder:
    def __init__(self) -> None:
        self.calls = 0
        self.max_active_calls = 0
        self._active_calls = 0
        self._lock = threading.Lock()

    def next_call(self) -> int:
        with self._lock:
            self.calls += 1
            return self.calls

    def begin_call(self) -> int:
        with self._lock:
            self.calls += 1
            self._active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self._active_calls)
            return self.calls

    def end_call(self) -> None:
        with self._lock:
            self._active_calls -= 1


@pytest.fixture
def sync_releases() -> list[threading.Event]:
    return []


@pytest.fixture
def shared_db(
    tmp_path: Path,
    sync_releases: list[threading.Event],
) -> Iterator[SampleBufferDatabase]:
    db = SampleBufferDatabase(
        location=str(tmp_path / "shared.eval"),
        create=True,
        log_shared=30,
        db_dir=tmp_path / "db",
    )
    try:
        db.start_sample(
            EvalSampleSummary(id="sample", epoch=1, input="in", target="out")
        )
        yield db
    finally:
        for release in sync_releases:
            release.set()
        db.cleanup()


@pytest.fixture
def cleanup_recorder(monkeypatch: pytest.MonkeyPatch) -> CleanupRecorder:
    recorder = CleanupRecorder()
    monkeypatch.setattr(
        database_module, "cleanup_sample_buffer_db", recorder.record_db_cleanup
    )
    monkeypatch.setattr(
        SampleBufferFilestore,
        "cleanup",
        lambda filestore: recorder.record_filestore_cleanup(filestore),
    )
    return recorder


def _force_sync_due(db: SampleBufferDatabase) -> None:
    db._sync_time = time.monotonic() - 60


def _write_event(db: SampleBufferDatabase, data: str = "event") -> None:
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data=data))])


def _request_sync(db: SampleBufferDatabase, data: str = "event") -> None:
    _force_sync_due(db)
    _write_event(db, data)


def _assert_event(event: threading.Event, message: str) -> None:
    assert event.wait(timeout=1), message


def _wait_until(predicate: Callable[[], bool], message: str) -> None:
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail(message)


def _blocking_sync(started: threading.Event, release: threading.Event) -> SyncFunction:
    def sync(db: SampleBufferDatabase, filestore: SampleBufferFilestore) -> None:
        started.set()
        release.wait(timeout=5)

    return sync


def _start_blocked_sync(
    db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    release: threading.Event,
    sync_releases: list[threading.Event],
) -> None:
    started = threading.Event()
    sync_releases.append(release)
    monkeypatch.setattr(
        database_module, "sync_to_filestore", _blocking_sync(started, release)
    )

    _request_sync(db, "blocked")
    _assert_event(started, "sync worker did not start")


def _current_sync_thread(db: SampleBufferDatabase) -> threading.Thread:
    sync_thread = db._sync_thread
    assert sync_thread is not None
    return sync_thread


def _signal_when_join_starts(
    monkeypatch: pytest.MonkeyPatch,
    thread: threading.Thread,
) -> threading.Event:
    join_started = threading.Event()
    original_join = thread.join

    def join_with_signal(timeout: float | None = None) -> None:
        join_started.set()
        original_join(timeout=timeout)

    monkeypatch.setattr(thread, "join", join_with_signal)
    return join_started


def _run_in_thread(
    target: Callable[[], None],
) -> tuple[threading.Thread, threading.Event, list[BaseException]]:
    finished = threading.Event()
    errors: list[BaseException] = []

    def run_target() -> None:
        try:
            target()
        except BaseException as exc:
            errors.append(exc)
        finally:
            finished.set()

    thread = threading.Thread(target=run_target)
    thread.start()
    return thread, finished, errors


def _join_or_raise(thread: threading.Thread, errors: list[BaseException]) -> None:
    thread.join(timeout=1)
    if errors:
        raise errors[0]


def test_sync_returns_while_filestore_sync_is_blocked(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    sync_releases: list[threading.Event],
) -> None:
    release = threading.Event()
    started = threading.Event()
    sync_releases.append(release)
    monkeypatch.setattr(
        database_module, "sync_to_filestore", _blocking_sync(started, release)
    )

    before = time.monotonic()
    _request_sync(shared_db)
    elapsed = time.monotonic() - before

    assert elapsed < 0.5
    _assert_event(started, "sync worker did not start")
    release.set()


def test_pending_sync_respects_log_shared_interval(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    sync_releases: list[threading.Event],
) -> None:
    throttle_interval = 1
    shared_db.log_shared = throttle_interval
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    recorder = SyncRecorder()
    sync_times: list[float] = []
    sync_releases.append(release_first)

    def controlled_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        call_number = recorder.begin_call()
        sync_times.append(time.monotonic())
        try:
            if call_number == 1:
                first_started.set()
                release_first.wait(timeout=5)
            elif call_number == 2:
                second_started.set()
        finally:
            recorder.end_call()

    monkeypatch.setattr(database_module, "sync_to_filestore", controlled_sync)

    _request_sync(shared_db, "first")
    _assert_event(first_started, "first sync did not start")

    for index in range(5):
        _write_event(shared_db, f"burst-{index}")

    release_first.set()

    assert second_started.wait(timeout=throttle_interval + 1), (
        "pending sync did not run"
    )
    assert recorder.calls == 2
    assert recorder.max_active_calls == 1
    assert sync_times[1] - sync_times[0] >= throttle_interval * 0.9


def test_sync_worker_thread_identity_is_reused(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_call = threading.Event()
    second_call = threading.Event()
    sync_threads: list[threading.Thread] = []
    recorder = SyncRecorder()

    def recording_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        sync_threads.append(threading.current_thread())
        if recorder.next_call() == 1:
            first_call.set()
        else:
            second_call.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", recording_sync)

    _request_sync(shared_db, "first")
    _assert_event(first_call, "first sync did not run")

    _request_sync(shared_db, "second")
    _assert_event(second_call, "second sync did not run")

    assert len(sync_threads) == 2
    assert sync_threads[0] is sync_threads[1]


def test_sync_exception_does_not_prevent_later_sync(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = SyncRecorder()
    second_call = threading.Event()

    def flaky_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        if recorder.next_call() == 1:
            raise RuntimeError("filestore boom")
        second_call.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", flaky_sync)

    _request_sync(shared_db, "first")
    _wait_until(
        lambda: recorder.calls >= 1 and shared_db._sync_thread is not None,
        "sync worker did not remain available after exception",
    )
    first_thread = shared_db._sync_thread

    _request_sync(shared_db, "second")

    _assert_event(second_call, "second sync did not run")
    assert shared_db._sync_thread is first_thread


def test_sync_request_pending_when_thread_reference_exists_but_not_alive(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        raise AssertionError("sync should not run inline")

    monkeypatch.setattr(database_module, "sync_to_filestore", unexpected_sync)

    shared_db._sync_thread = threading.Thread(target=lambda: None)
    shared_db._sync_time = time.monotonic()

    _write_event(shared_db, "pending")

    assert shared_db._sync_pending is True


def test_cleanup_skips_deletion_when_sync_remains_active(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_recorder: CleanupRecorder,
    sync_releases: list[threading.Event],
) -> None:
    release = threading.Event()
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 0.01)
    _start_blocked_sync(shared_db, monkeypatch, release, sync_releases)

    shared_db.cleanup()

    assert cleanup_recorder.calls == []
    assert shared_db._sync_closed is True
    release.set()


def test_cleanup_from_sync_worker_does_not_delete_while_worker_is_on_stack(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_recorder: CleanupRecorder,
) -> None:
    cleanup_started = threading.Event()
    sync_finished = threading.Event()
    worker_thread: threading.Thread | None = None

    def sync_that_cleans_up(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        nonlocal worker_thread
        worker_thread = threading.current_thread()
        cleanup_started.set()
        db.cleanup()
        sync_finished.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", sync_that_cleans_up)

    _request_sync(shared_db, "cleanup-from-worker")

    _assert_event(cleanup_started, "cleanup did not start in worker")
    _assert_event(sync_finished, "worker cleanup did not finish")

    assert worker_thread is not None
    worker_thread.join(timeout=1)
    assert worker_thread.is_alive() is False
    assert cleanup_recorder.calls == []
    assert shared_db._sync_closed is True


def test_cleanup_discards_pending_sync_work(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_recorder: CleanupRecorder,
    sync_releases: list[threading.Event],
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    recorder = SyncRecorder()
    sync_releases.append(release_first)

    def blocked_first_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        if recorder.next_call() == 1:
            first_started.set()
            release_first.wait(timeout=5)

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_first_sync)
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 1)

    _request_sync(shared_db, "first")
    _assert_event(first_started, "first sync did not start")

    _request_sync(shared_db, "pending")
    assert shared_db._sync_pending is True

    join_started = _signal_when_join_starts(
        monkeypatch,
        _current_sync_thread(shared_db),
    )
    cleanup_thread, cleanup_done, cleanup_errors = _run_in_thread(shared_db.cleanup)
    _assert_event(join_started, "cleanup did not wait for active sync")
    assert cleanup_done.is_set() is False

    release_first.set()
    _join_or_raise(cleanup_thread, cleanup_errors)

    assert cleanup_done.is_set()
    assert recorder.calls == 1
    assert cleanup_recorder.calls == ["db", "filestore"]


def test_cleanup_interrupts_pending_sync_throttle_wait(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_recorder: CleanupRecorder,
    sync_releases: list[threading.Event],
) -> None:
    first_started = threading.Event()
    first_finished = threading.Event()
    release_first = threading.Event()
    recorder = SyncRecorder()
    sync_releases.append(release_first)

    def blocked_first_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        if recorder.next_call() == 1:
            first_started.set()
            release_first.wait(timeout=5)
            first_finished.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_first_sync)
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 1)

    _request_sync(shared_db, "first")
    _assert_event(first_started, "first sync did not start")

    _write_event(shared_db, "pending")
    assert shared_db._sync_pending is True

    release_first.set()
    _assert_event(first_finished, "first sync did not finish")
    _wait_until(
        lambda: shared_db._sync_thread is not None,
        "sync worker did not remain active for pending throttle wait",
    )

    before = time.monotonic()
    shared_db.cleanup()
    elapsed = time.monotonic() - before

    assert elapsed < 0.5
    assert recorder.calls == 1
    assert cleanup_recorder.calls == ["db", "filestore"]


def test_base_exception_finalizes_sync_worker_state(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyncStopped(BaseException):
        pass

    def sync_that_stops(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        raise SyncStopped("stop sync worker")

    monkeypatch.setattr(database_module, "sync_to_filestore", sync_that_stops)

    # The shared_db fixture's start_sample() spawns a live background sync
    # worker. Shut it down before driving _sync_to_filestore() synchronously,
    # otherwise that worker can win the race for the forced-due sync request,
    # consume it, and exit — leaving this thread's direct call blocked forever
    # in _sync_wakeup.wait(timeout=None).
    with shared_db._sync_lock:
        shared_db._sync_closed = True
        shared_db._sync_wakeup.notify_all()
        background_worker = shared_db._sync_thread
    if background_worker is not None and (
        background_worker is not threading.current_thread()
    ):
        background_worker.join(timeout=5)
    shared_db._sync_closed = False

    shared_db._sync_thread = threading.current_thread()
    shared_db._sync_requested = True
    shared_db._sync_pending = True
    _force_sync_due(shared_db)

    sync_filestore = shared_db._sync_filestore
    assert sync_filestore is not None

    with pytest.raises(SyncStopped):
        shared_db._sync_to_filestore(sync_filestore)

    assert shared_db._sync_thread is None
    assert shared_db._sync_pending is False


def test_set_sync_interval_retunes_shared_sync(
    shared_db: SampleBufferDatabase,
) -> None:
    assert shared_db.log_shared == 30

    assert shared_db.set_sync_interval(5) is True
    assert shared_db.log_shared == 5
    assert shared_db._sync_filestore is not None
    assert shared_db._sync_filestore.update_interval == 5

    # clamped to a minimum of 1 second
    assert shared_db.set_sync_interval(0) is True
    assert shared_db.log_shared == 1


def test_set_sync_interval_noop_without_shared_sync(tmp_path: Path) -> None:
    # a buffer opened without `log_shared` has no shared filestore to retune
    db = SampleBufferDatabase(
        location=str(tmp_path / "local.eval"),
        create=True,
        db_dir=tmp_path / "db",
    )
    try:
        assert db.log_shared is None
        assert db.set_sync_interval(5) is False
        assert db.log_shared is None
    finally:
        db.cleanup()


def test_shared_sync_interval_reports_active_value(
    shared_db: SampleBufferDatabase,
) -> None:
    # shared sync is configured (filestore created) → report the interval
    assert shared_db._sync_filestore is not None
    assert shared_db.shared_sync_interval == 30


def test_shared_sync_interval_off_normalizes_to_none(tmp_path: Path) -> None:
    # log_shared=0 ("off" from a normal CLI run) stores 0 but creates no
    # filestore; the effective interval must read as None, not 0
    db = SampleBufferDatabase(
        location=str(tmp_path / "local.eval"),
        create=True,
        log_shared=0,
        db_dir=tmp_path / "db",
    )
    try:
        assert db.log_shared == 0
        assert db._sync_filestore is None
        assert db.shared_sync_interval is None
    finally:
        db.cleanup()
