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
