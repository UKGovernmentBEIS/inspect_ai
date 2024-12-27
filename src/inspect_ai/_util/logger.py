import os
from logging import (
    DEBUG,
    INFO,
    WARNING,
    FileHandler,
    Formatter,
    Logger,
    LogRecord,
    addLevelName,
    getLevelName,
    getLogger,
)
from pathlib import Path

import rich
from rich.console import ConsoleRenderable
from rich.logging import RichHandler
from rich.text import Text
from typing_extensions import override

from .constants import (
    ALL_LOG_LEVELS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_LEVEL_TRANSCRIPT,
    HTTP,
    HTTP_LOG_LEVEL,
    PKG_NAME,
    TRACE,
    TRACE_LOG_LEVEL,
)
from .error import PrerequisiteError
from .trace import TraceFileHandler, TraceFormatter, inspect_trace_dir

TRACE_FILE_NAME = "trace.log"


# log handler that filters messages to stderr and the log file
class LogHandler(RichHandler):
    def __init__(self, levelno: int, transcript_levelno: int) -> None:
        super().__init__(levelno, console=rich.get_console())
        self.transcript_levelno = transcript_levelno
        self.display_level = WARNING
        # log into an external file if requested via env var
        file_logger = os.environ.get("INSPECT_PY_LOGGER_FILE", None)
        self.file_logger = FileHandler(file_logger) if file_logger else None
        if self.file_logger:
            self.file_logger.setFormatter(
                Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )

        # see if the user has a special log level for the file
        file_logger_level = os.environ.get("INSPECT_PY_LOGGER_LEVEL", "")
        if file_logger_level:
            self.file_logger_level = int(getLevelName(file_logger_level.upper()))
        else:
            self.file_logger_level = 0

        # add a trace handler
        default_trace_file = inspect_trace_dir() / TRACE_FILE_NAME
        have_existing_trace_file = default_trace_file.exists()
        env_trace_file = os.environ.get("INSPECT_TRACE_FILE", None)
        trace_file = Path(env_trace_file) if env_trace_file else default_trace_file
        trace_total_files = 10
        self.trace_logger = TraceFileHandler(
            trace_file.as_posix(),
            backupCount=trace_total_files - 1,  # exclude the current file (10 total)
        )
        self.trace_logger.setFormatter(TraceFormatter())
        if have_existing_trace_file:
            self.trace_logger.doRollover()

        # set trace level
        trace_level = os.environ.get("INSPECT_TRACE_LEVEL", TRACE_LOG_LEVEL)
        self.trace_logger_level = int(getLevelName(trace_level.upper()))

    @override
    def emit(self, record: LogRecord) -> None:
        # demote httpx and return notifications to log_level http
        if (
            record.name == "httpx"
            or "http" in record.name
            or "Retrying request" in record.getMessage()
        ):
            record.levelno = HTTP
            record.levelname = HTTP_LOG_LEVEL

        # skip httpx event loop is closed errors
        if "Event loop is closed" in record.getMessage():
            return

        # write to stderr if we are at or above the threshold
        if record.levelno >= self.display_level:
            super().emit(record)

        # write to file if the log file level matches. if the
        # user hasn't explicitly specified a level then we
        # take the minimum of 'info' and the display level
        if self.file_logger and record.levelno >= (
            self.file_logger_level or min(self.display_level, INFO)
        ):
            self.file_logger.emit(record)

        # write to trace if the trace level matches.
        if self.trace_logger and record.levelno >= self.trace_logger_level:
            self.trace_logger.emit(record)

        # eval log always gets info level and higher records
        # eval log only gets debug or http if we opt-in
        write = record.levelno >= self.transcript_levelno
        notify_logger_record(record, write)

    @override
    def render_message(self, record: LogRecord, message: str) -> ConsoleRenderable:
        return Text.from_ansi(message)


# initialize logging -- this function can be called multiple times
# in the lifetime of the process (the levelno will update globally)
def init_logger(
    log_level: str | None = None, log_level_transcript: str | None = None
) -> None:
    # backwards compatibility for 'tools'
    if log_level == "sandbox" or log_level == "tools":
        log_level = "trace"

    # register http and tools levels
    addLevelName(HTTP, HTTP_LOG_LEVEL)
    addLevelName(TRACE, TRACE_LOG_LEVEL)

    def validate_level(option: str, level: str) -> None:
        if level not in ALL_LOG_LEVELS:
            log_levels = ", ".join([level.lower() for level in ALL_LOG_LEVELS])
            raise PrerequisiteError(
                f"Invalid {option} '{level.lower()}'. Log level must be one of {log_levels}"
            )

    # resolve default log level
    log_level = (
        log_level if log_level else os.getenv("INSPECT_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    ).upper()
    validate_level("log level", log_level)

    # reolve log file level
    log_level_transcript = (
        log_level_transcript
        if log_level_transcript
        else os.getenv("INSPECT_LOG_LEVEL_TRANSCRIPT", DEFAULT_LOG_LEVEL_TRANSCRIPT)
    ).upper()
    validate_level("log file level", log_level_transcript)

    # convert to integer
    levelno = getLevelName(log_level)
    transcript_levelno = getLevelName(log_level_transcript)

    # init logging handler on demand
    global _logHandler
    if not _logHandler:
        _logHandler = LogHandler(min(DEBUG, levelno), transcript_levelno)
        getLogger().addHandler(_logHandler)

    # establish default capture level
    capture_level = min(TRACE, levelno)

    # see all the messages (we won't actually display/write all of them)
    getLogger().setLevel(capture_level)
    getLogger(PKG_NAME).setLevel(capture_level)
    getLogger("httpx").setLevel(capture_level)
    getLogger("botocore").setLevel(DEBUG)

    # set the levelno on the global handler
    _logHandler.display_level = levelno


_logHandler: LogHandler | None = None


def notify_logger_record(record: LogRecord, write: bool) -> None:
    from inspect_ai.log._message import LoggingMessage
    from inspect_ai.log._transcript import LoggerEvent, transcript

    if write:
        transcript()._event(LoggerEvent(message=LoggingMessage.from_log_record(record)))
    global _rate_limit_count
    if (record.levelno <= INFO and "429" in record.getMessage()) or (
        record.levelno == DEBUG
        # See https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html#validating-retry-attempts
        # for boto retry logic / log messages (this is tracking standard or adapative retries)
        and "botocore.retries.standard" in record.name
        and "Retry needed, retrying request after delay of:" in record.getMessage()
    ):
        _rate_limit_count = _rate_limit_count + 1


_rate_limit_count = 0


def init_http_rate_limit_count() -> None:
    global _rate_limit_count
    _rate_limit_count = 0


def http_rate_limit_count() -> int:
    return _rate_limit_count


def warn_once(logger: Logger, message: str) -> None:
    if message not in _warned:
        logger.warning(message)
        _warned.append(message)


_warned: list[str] = []
