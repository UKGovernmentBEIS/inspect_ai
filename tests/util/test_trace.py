import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from inspect_ai._util.constants import TRACE
from inspect_ai._util.trace import trace_action


class ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def capture_logger_records(logger: logging.Logger) -> Iterator[list[logging.LogRecord]]:
    handler = ListHandler()
    original_level = logger.level
    original_propagate = logger.propagate
    original_handlers = list(logger.handlers)
    logger.handlers = [handler]
    logger.setLevel(TRACE)
    logger.propagate = False
    try:
        yield handler.records
    finally:
        logger.handlers = original_handlers
        logger.setLevel(original_level)
        logger.propagate = original_propagate


def test_trace_action_preserves_exception_from_plain_worker_thread() -> None:
    logger = logging.getLogger("inspect_ai.tests.trace")
    error: list[BaseException] = []

    def run_trace_action() -> None:
        try:
            with trace_action(logger, "Worker", "sync"):
                raise RuntimeError("filestore boom")
        except BaseException as exc:
            error.append(exc)

    with capture_logger_records(logger) as records:
        worker = threading.Thread(target=run_trace_action)
        worker.start()
        worker.join(timeout=1)

    assert worker.is_alive() is False
    assert len(error) == 1
    assert isinstance(error[0], RuntimeError)
    assert str(error[0]) == "filestore boom"
    assert any(
        record.name == logger.name
        and record.levelno == TRACE
        and getattr(record, "event", None) == "error"
        and getattr(record, "error_type", None) == "RuntimeError"
        for record in records
    )
