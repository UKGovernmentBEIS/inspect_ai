"""Unit tests for ``TaskLogger`` on-demand flush + buffer-config directives.

These exercise the small directive surface in isolation (a real ``TaskLogger``
is expensive to build), constructing a bare instance via ``__new__`` and wiring
only the attributes the methods touch — a fake recorder records ``flush`` calls.
"""

import anyio

from inspect_ai._eval.task.log import TaskLogger


class FakeRecorder:
    def __init__(self) -> None:
        self.flushes = 0

    async def flush(self, eval: object) -> None:
        self.flushes += 1


def _logger(pending: list[tuple[str | int, int]], flush_buffer: int = 10) -> TaskLogger:
    logger = TaskLogger.__new__(TaskLogger)
    logger.recorder = FakeRecorder()  # type: ignore[assignment]
    logger.eval = object()  # type: ignore[assignment]
    logger.flush_pending = list(pending)
    logger.flush_buffer = flush_buffer
    logger._buffer_db = None
    logger._finished = False
    logger._flush_lock = anyio.Lock()
    return logger


async def test_flush_samples_writes_pending_and_clears() -> None:
    logger = _logger([("s1", 1), ("s2", 1)])
    recorder: FakeRecorder = logger.recorder  # type: ignore[assignment]

    flushed = await logger.flush_samples()
    assert flushed == 2
    assert recorder.flushes == 1
    assert logger.flush_pending == []


async def test_flush_samples_noop_when_nothing_pending() -> None:
    logger = _logger([])
    recorder: FakeRecorder = logger.recorder  # type: ignore[assignment]

    flushed = await logger.flush_samples()
    assert flushed == 0
    # nothing pending → no remote write at all
    assert recorder.flushes == 0


async def test_flush_samples_finished_is_noop() -> None:
    # after log_finish the recorder is torn down; a still-attached flush
    # directive (kept visible under --ctl-server=keep) must no-op rather than
    # reach into the gone recorder
    logger = _logger([("s1", 1)])
    recorder: FakeRecorder = logger.recorder  # type: ignore[assignment]
    logger._finished = True

    flushed = await logger.flush_samples()
    assert flushed == 0
    assert recorder.flushes == 0


async def test_buffer_config_finished_reports_no_pending() -> None:
    # log_finish clears flush_pending, so a finished eval reports 0 pending
    # rather than the stale count it carried before the final write
    logger = _logger([], flush_buffer=7)
    logger._finished = True

    config = logger.buffer_config()
    assert config.pending == 0
    assert config.log_buffer == 7


async def test_buffer_config_read() -> None:
    logger = _logger([("s1", 1)], flush_buffer=7)
    config = logger.buffer_config()
    assert config.log_buffer == 7
    assert config.pending == 1
    assert config.log_shared is None


async def test_buffer_config_set_log_buffer() -> None:
    logger = _logger([], flush_buffer=10)

    config = logger.buffer_config(log_buffer=3)
    assert config.log_buffer == 3
    assert logger.flush_buffer == 3

    # clamped to a minimum of 1
    assert logger.buffer_config(log_buffer=0).log_buffer == 1


async def test_buffer_config_log_shared_noop_without_buffer_db() -> None:
    logger = _logger([], flush_buffer=10)
    # no buffer db → setting log_shared is silently ignored, report stays None
    config = logger.buffer_config(log_shared=5)
    assert config.log_shared is None


class _OffBufferDb:
    """A buffer db with realtime logging on but no shared sync (CLI log_shared=0).

    set_sync_interval is a no-op (returns False) and the effective interval
    stays None — mirrors SampleBufferDatabase when no filestore was created.
    """

    def __init__(self) -> None:
        self.set_calls: list[int] = []

    def set_sync_interval(self, seconds: int) -> bool:
        self.set_calls.append(seconds)
        return False

    @property
    def shared_sync_interval(self) -> int | None:
        return None


async def test_buffer_config_reports_off_when_no_shared_sync() -> None:
    # a buffer db exists (realtime on) but shared sync is off — report None,
    # not a raw 0/interval
    logger = _logger([], flush_buffer=10)
    logger._buffer_db = _OffBufferDb()  # type: ignore[assignment]
    assert logger.buffer_config().log_shared is None


async def test_buffer_config_shared_enable_rejected_reports_off() -> None:
    # --shared 5 on a buffer with no shared sync can't enable it at runtime;
    # the rejected request must not be echoed back as if it took effect
    logger = _logger([], flush_buffer=10)
    db = _OffBufferDb()
    logger._buffer_db = db  # type: ignore[assignment]

    config = logger.buffer_config(log_shared=5)
    assert config.log_shared is None
    assert db.set_calls == [5]  # the no-op attempt was made and ignored
