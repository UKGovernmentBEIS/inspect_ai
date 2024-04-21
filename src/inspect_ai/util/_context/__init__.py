from .concurrency import init_concurrency
from .logger import init_logger_records
from .subprocess import init_subprocess


def init_async_context(max_subprocesses: int | None = None) -> None:
    init_concurrency()
    init_subprocess(max_subprocesses)
    init_logger_records()
