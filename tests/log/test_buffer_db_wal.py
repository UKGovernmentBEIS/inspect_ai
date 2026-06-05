"""Tests for SampleBufferDatabase WAL mode and write retry (issue #4148)."""

import threading
import time
from pathlib import Path
from sqlite3 import OperationalError

import pytest

from inspect_ai.event._info import InfoEvent
from inspect_ai.log._log import EvalSampleSummary
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent


def _make_db(tmp_path: Path) -> SampleBufferDatabase:
    return SampleBufferDatabase(location="wal_test", create=True, db_dir=tmp_path)


def _summary(id: str = "s", epoch: int = 1) -> EvalSampleSummary:
    return EvalSampleSummary(id=id, epoch=epoch, input="in", target="out")


def test_journal_mode_is_wal(tmp_path: Path) -> None:
    """The database runs in WAL mode."""
    db = _make_db(tmp_path)
    try:
        db.start_sample(_summary())
        with db._get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert str(mode).lower() == "wal"
            # -shm exists while a WAL connection is open
            shm = db.db_path.with_name(f"{db.db_path.name}-shm")
            assert shm.exists()
    finally:
        db.cleanup()


def test_concurrent_readers_writer_no_lock(tmp_path: Path) -> None:
    """Concurrent readers and a writer don't raise "database is locked"."""
    db = _make_db(tmp_path)
    db.start_sample(_summary())

    errors: list[BaseException] = []
    stop = threading.Event()

    def writer() -> None:
        try:
            for i in range(150):
                db.log_events(
                    [SampleEvent(id="s", epoch=1, event=InfoEvent(data=f"e{i}"))]
                )
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()

    def reader() -> None:
        try:
            while not stop.is_set():
                db.get_sample_data("s", 1)
                db.get_samples()
                db.sample_event_count("s", 1)
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer)] + [
        threading.Thread(target=reader) for _ in range(4)
    ]
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads), "threads did not finish in time"
        assert errors == [], f"unexpected contention errors: {errors!r}"
    finally:
        stop.set()
        db.cleanup()


def test_cleanup_removes_wal_sidecars_and_dir(tmp_path: Path) -> None:
    """Cleanup removes the db plus -wal/-shm sidecars and the (now empty) dir."""
    db = _make_db(tmp_path)
    db.start_sample(_summary())

    wal = db.db_path.with_name(f"{db.db_path.name}-wal")
    shm = db.db_path.with_name(f"{db.db_path.name}-shm")
    # touch the sidecars so there's something for cleanup to remove
    wal.touch()
    shm.touch()
    parent = db.db_path.parent

    db.cleanup()

    assert not db.db_path.exists()
    assert not wal.exists()
    assert not shm.exists()
    assert not parent.exists()


def test_retry_on_locked_retries_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient lock error is retried, then the write succeeds."""
    db = _make_db(tmp_path)
    try:
        monkeypatch.setattr(time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def op() -> None:
            calls["n"] += 1
            if calls["n"] < 3:
                raise OperationalError("database is locked")

        db._retry_on_locked(op)
        assert calls["n"] == 3
    finally:
        db.cleanup()


def test_retry_on_locked_propagates_non_lock_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-lock errors propagate without retrying."""
    db = _make_db(tmp_path)
    try:
        monkeypatch.setattr(time, "sleep", lambda *_: None)
        calls = {"n": 0}

        def op() -> None:
            calls["n"] += 1
            raise OperationalError("no such table: events")

        with pytest.raises(OperationalError, match="no such table"):
            db._retry_on_locked(op)
        assert calls["n"] == 1
    finally:
        db.cleanup()
