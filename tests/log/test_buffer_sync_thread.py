import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from inspect_ai.event._info import InfoEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer import database as database_module
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.filestore import SampleBufferFilestore
from inspect_ai.log._recorders.types import SampleEvent


@pytest.fixture
def shared_db(tmp_path: Path) -> Iterator[SampleBufferDatabase]:
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
        release = getattr(db, "_test_release_sync", None)
        if release is not None:
            release.set()
        db.cleanup()


def _force_sync_due(db: SampleBufferDatabase) -> None:
    db._sync_time = time.monotonic() - 60


def _write_event(db: SampleBufferDatabase, data: str = "event") -> None:
    db.log_events([SampleEvent(id="sample", epoch=1, event=InfoEvent(data=data))])


def test_sync_returns_while_filestore_sync_is_blocked(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    shared_db._test_release_sync = release

    def blocked_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_sync)

    _force_sync_due(shared_db)
    before = time.monotonic()
    _write_event(shared_db)
    elapsed = time.monotonic() - before

    assert elapsed < 0.5
    assert started.wait(timeout=1)

    release.set()


def test_sync_requests_do_not_run_concurrently(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    shared_db._test_release_sync = release_first
    active_calls = 0
    max_active_calls = 0
    call_lock = threading.Lock()

    def blocked_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        nonlocal active_calls, max_active_calls
        with call_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
        first_started.set()
        release_first.wait(timeout=5)
        with call_lock:
            active_calls -= 1

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_sync)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert first_started.wait(timeout=1)

    for index in range(5):
        _force_sync_due(shared_db)
        _write_event(shared_db, f"burst-{index}")

    with call_lock:
        assert max_active_calls == 1

    release_first.set()


def test_pending_sync_runs_after_active_sync_finishes(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    shared_db._test_release_sync = release_first
    call_count = 0
    call_lock = threading.Lock()

    def controlled_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_started.set()
            release_first.wait(timeout=5)
        elif current_call == 2:
            second_started.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", controlled_sync)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert first_started.wait(timeout=1)

    _write_event(shared_db, "pending")
    release_first.set()

    assert second_started.wait(timeout=1)
    with call_lock:
        assert call_count == 2


def test_sync_exception_does_not_prevent_later_sync(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0
    second_call = threading.Event()
    call_lock = threading.Lock()

    def flaky_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        nonlocal calls
        with call_lock:
            calls += 1
            current_call = calls
        if current_call == 1:
            raise RuntimeError("boom")
        second_call.set()

    monkeypatch.setattr(database_module, "sync_to_filestore", flaky_sync)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")

    recovered = False
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        with call_lock:
            if calls >= 1 and shared_db._sync_thread is None:
                recovered = True
                break
        time.sleep(0.01)
    assert recovered

    _force_sync_due(shared_db)
    _write_event(shared_db, "second")

    assert second_call.wait(timeout=1)


def test_sync_logs_worker_exception_when_trace_action_runs_in_thread(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sync_called = threading.Event()

    def failing_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        sync_called.set()
        raise RuntimeError("filestore boom")

    monkeypatch.setattr(database_module, "sync_to_filestore", failing_sync)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert sync_called.wait(timeout=1)

    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if shared_db._sync_thread is None:
            break
        time.sleep(0.01)

    assert any(
        record.exc_info is not None
        and isinstance(record.exc_info[1], RuntimeError)
        and str(record.exc_info[1]) == "filestore boom"
        for record in caplog.records
    )


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
) -> None:
    started = threading.Event()
    release = threading.Event()
    cleanup_db_called = False
    cleanup_filestore_called = False
    shared_db._test_release_sync = release

    def blocked_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        started.set()
        release.wait(timeout=5)

    def record_cleanup_db(path: Path) -> None:
        nonlocal cleanup_db_called
        cleanup_db_called = True

    def record_cleanup_filestore(self: SampleBufferFilestore) -> None:
        nonlocal cleanup_filestore_called
        cleanup_filestore_called = True

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_sync)
    monkeypatch.setattr(database_module, "cleanup_sample_buffer_db", record_cleanup_db)
    monkeypatch.setattr(SampleBufferFilestore, "cleanup", record_cleanup_filestore)
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 0.01)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert started.wait(timeout=1)

    shared_db.cleanup()

    assert cleanup_db_called is False
    assert cleanup_filestore_called is False
    assert shared_db._sync_closed is True

    release.set()


def test_cleanup_waits_for_active_sync_then_deletes(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = threading.Event()
    release = threading.Event()
    shared_db._test_release_sync = release
    cleanup_db_called = False
    cleanup_filestore_called = False

    def blocked_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        started.set()
        release.wait(timeout=5)

    def record_cleanup_db(path: Path) -> None:
        nonlocal cleanup_db_called
        cleanup_db_called = True

    def record_cleanup_filestore(self: SampleBufferFilestore) -> None:
        nonlocal cleanup_filestore_called
        cleanup_filestore_called = True

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_sync)
    monkeypatch.setattr(database_module, "cleanup_sample_buffer_db", record_cleanup_db)
    monkeypatch.setattr(SampleBufferFilestore, "cleanup", record_cleanup_filestore)
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 1)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert started.wait(timeout=1)

    sync_thread = shared_db._sync_thread
    assert sync_thread is not None
    original_join = sync_thread.join
    join_started = threading.Event()

    def join_with_signal(timeout: float | None = None) -> None:
        join_started.set()
        original_join(timeout=timeout)

    monkeypatch.setattr(sync_thread, "join", join_with_signal)

    cleanup_done = threading.Event()
    cleanup_errors: list[BaseException] = []

    def run_cleanup() -> None:
        try:
            shared_db.cleanup()
        except BaseException as exc:
            cleanup_errors.append(exc)
        else:
            cleanup_done.set()

    cleanup_thread = threading.Thread(target=run_cleanup)
    cleanup_thread.start()
    assert join_started.wait(timeout=1)

    assert cleanup_done.is_set() is False

    release.set()
    cleanup_thread.join(timeout=1)
    if cleanup_errors:
        raise cleanup_errors[0]

    assert cleanup_done.is_set()
    assert cleanup_db_called is True
    assert cleanup_filestore_called is True


def test_cleanup_from_sync_worker_does_not_delete_while_worker_is_on_stack(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_started = threading.Event()
    sync_finished = threading.Event()
    cleanup_calls: list[str] = []
    cleanup_lock = threading.Lock()
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

    def record_cleanup_db(path: Path) -> None:
        with cleanup_lock:
            cleanup_calls.append("db")

    def record_cleanup_filestore(self: SampleBufferFilestore) -> None:
        with cleanup_lock:
            cleanup_calls.append("filestore")

    monkeypatch.setattr(database_module, "sync_to_filestore", sync_that_cleans_up)
    monkeypatch.setattr(database_module, "cleanup_sample_buffer_db", record_cleanup_db)
    monkeypatch.setattr(SampleBufferFilestore, "cleanup", record_cleanup_filestore)

    _force_sync_due(shared_db)
    _write_event(shared_db, "cleanup-from-worker")

    assert cleanup_started.wait(timeout=1)
    assert sync_finished.wait(timeout=1)

    assert worker_thread is not None
    worker_thread.join(timeout=1)
    assert worker_thread.is_alive() is False
    assert cleanup_calls == []
    assert shared_db._sync_closed is True


def test_cleanup_discards_pending_sync_work(
    shared_db: SampleBufferDatabase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    join_started = threading.Event()
    cleanup_done = threading.Event()
    cleanup_calls: list[str] = []
    cleanup_errors: list[BaseException] = []
    call_count = 0
    call_lock = threading.Lock()
    cleanup_lock = threading.Lock()
    shared_db._test_release_sync = release_first

    def blocked_first_sync(
        db: SampleBufferDatabase,
        filestore: SampleBufferFilestore,
    ) -> None:
        nonlocal call_count
        with call_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_started.set()
            release_first.wait(timeout=5)

    def record_cleanup_db(path: Path) -> None:
        with cleanup_lock:
            cleanup_calls.append("db")

    def record_cleanup_filestore(self: SampleBufferFilestore) -> None:
        with cleanup_lock:
            cleanup_calls.append("filestore")

    monkeypatch.setattr(database_module, "sync_to_filestore", blocked_first_sync)
    monkeypatch.setattr(database_module, "cleanup_sample_buffer_db", record_cleanup_db)
    monkeypatch.setattr(SampleBufferFilestore, "cleanup", record_cleanup_filestore)
    monkeypatch.setattr(database_module, "SYNC_CLEANUP_TIMEOUT", 1)

    _force_sync_due(shared_db)
    _write_event(shared_db, "first")
    assert first_started.wait(timeout=1)

    _force_sync_due(shared_db)
    _write_event(shared_db, "pending")
    assert shared_db._sync_pending is True

    sync_thread = shared_db._sync_thread
    assert sync_thread is not None
    original_join = sync_thread.join

    def join_with_signal(timeout: float | None = None) -> None:
        join_started.set()
        original_join(timeout=timeout)

    monkeypatch.setattr(sync_thread, "join", join_with_signal)

    def run_cleanup() -> None:
        try:
            shared_db.cleanup()
        except BaseException as exc:
            cleanup_errors.append(exc)
        finally:
            cleanup_done.set()

    cleanup_thread = threading.Thread(target=run_cleanup)
    cleanup_thread.start()
    assert join_started.wait(timeout=1)
    assert cleanup_done.is_set() is False

    release_first.set()
    cleanup_thread.join(timeout=1)
    if cleanup_errors:
        raise cleanup_errors[0]

    assert cleanup_done.is_set()
    with call_lock:
        assert call_count == 1
    assert cleanup_calls == ["db", "filestore"]


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

    shared_db._sync_thread = threading.current_thread()
    shared_db._sync_pending = True

    sync_filestore = shared_db._sync_filestore
    assert sync_filestore is not None

    with pytest.raises(SyncStopped):
        shared_db._sync_to_filestore(sync_filestore)

    assert shared_db._sync_thread is None
    assert shared_db._sync_pending is False
