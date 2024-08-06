from contextvars import ContextVar
from logging import INFO, Logger, LogRecord

_logger_records_context_var = ContextVar[list[LogRecord]]("logger_records", default=[])


def init_logger_records() -> None:
    _logger_records_context_var.set([])


def notify_logger_record(record: LogRecord, write: bool) -> None:
    if write:
        _logger_records_context_var.get().append(record)
    if record.levelno <= INFO and "429" in record.getMessage():
        _rate_limit_count_context_var.set(_rate_limit_count_context_var.get() + 1)


def logger_records() -> list[LogRecord]:
    return _logger_records_context_var.get()


_rate_limit_count_context_var = ContextVar[int]("rate_limit_count", default=0)


def init_http_rate_limit_count() -> None:
    _rate_limit_count_context_var.set(0)


def http_rate_limit_count() -> int:
    return _rate_limit_count_context_var.get()


def warn_once(logger: Logger, message: str) -> None:
    if message not in _warned:
        logger.warning(message)
        _warned.append(message)


_warned: list[str] = []
