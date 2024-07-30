from contextvars import ContextVar
from logging import INFO, LogRecord

_logger_records_context_var = ContextVar[list[LogRecord]]("logger_records", default=[])
_rate_limit_records_context_var = ContextVar[list[LogRecord]](
    "rate_limit_records", default=[]
)


def init_logger_records() -> None:
    _logger_records_context_var.set([])
    _rate_limit_records_context_var.set([])


def notify_logger_record(record: LogRecord, write: bool) -> None:
    if write:
        _logger_records_context_var.get().append(record)
    if record.levelno <= INFO and "429" in record.getMessage():
        _rate_limit_records_context_var.get().append(record)


def logger_http_rate_limit_count() -> int:
    return len(_rate_limit_records_context_var.get())


def logger_records() -> list[LogRecord]:
    return _logger_records_context_var.get()
