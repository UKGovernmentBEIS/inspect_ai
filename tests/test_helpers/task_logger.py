from typing import Any, cast

import anyio

from inspect_ai._eval.task.log import TaskLogger
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase


class TaskLoggerShim(TaskLogger):
    def __init__(self, buffer_db: Any) -> None:
        self._buffer_db = cast(SampleBufferDatabase, buffer_db)
        self._samples_completed = 0
        self._logged_sample_keys = set()
        self._cancelled_sample_keys = set()
        self._init_stale_flush_state()
        self._finished = False
        self._prior_seeded = False
        self._prior_read_limit = anyio.Semaphore(4)
        self._seeded_pending = set()
