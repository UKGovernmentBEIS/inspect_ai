from logging import INFO, LogRecord

_logger_records: list[LogRecord] = []
_rate_limit_records: list[LogRecord] = []


def init_logger_records() -> None:
    _logger_records.clear()
    _rate_limit_records.clear()


def notify_logger_record(record: LogRecord, write: bool) -> None:
    if write:
        _logger_records.append(record)
    if record.levelno <= INFO and "429" in record.getMessage():
        _rate_limit_records.append(record)


def logger_http_rate_limit_count() -> int:
    return len(_rate_limit_records)


def collect_logger_records() -> list[LogRecord]:
    records = _logger_records.copy()
    _logger_records.clear()
    _rate_limit_records.clear()
    return records
