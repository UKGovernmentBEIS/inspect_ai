from typing import Any, cast

from inspect_ai._eval.task.log import TaskLogger
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase


class TaskLoggerShim(TaskLogger):
    def __init__(self, buffer_db: Any) -> None:
        self._buffer_db = cast(SampleBufferDatabase, buffer_db)
        self._init_stale_flush_state()
        self._finished = False
