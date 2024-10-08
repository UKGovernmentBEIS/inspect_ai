import os
from logging import (
    INFO,
    WARNING,
    FileHandler,
    Formatter,
    LogRecord,
    addLevelName,
    getLevelName,
    getLogger,
)

from rich.console import ConsoleRenderable
from rich.logging import RichHandler
from rich.text import Text
from typing_extensions import override

from inspect_ai._util.constants import (
    ALL_LOG_LEVELS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_LEVEL_TRANSCRIPT,
    HTTP,
    HTTP_LOG_LEVEL,
    PKG_NAME,
    SANDBOX,
    SANDBOX_LOG_LEVEL,
)
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import notify_logger_record

from .rich import rich_console


# log handler that filters messages to stderr and the log file
class LogHandler(RichHandler):
    def __init__(self, levelno: int, transcript_levelno: int) -> None:
        super().__init__(levelno, console=rich_console())
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

    @override
    def emit(self, record: LogRecord) -> None:
        # demote httpx and return notifications to log_level http
        if record.name == "httpx" or "Retrying request" in record.getMessage():
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
    if log_level == "tools":
        log_level = "sandbox"

    # register http and tools levels
    addLevelName(HTTP, HTTP_LOG_LEVEL)
    addLevelName(SANDBOX, SANDBOX_LOG_LEVEL)

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
        _logHandler = LogHandler(min(HTTP, levelno), transcript_levelno)
        getLogger().addHandler(_logHandler)

    # establish default capture level
    capture_level = min(HTTP, levelno)

    # see all the messages (we won't actually display/write all of them)
    getLogger().setLevel(capture_level)
    getLogger(PKG_NAME).setLevel(capture_level)
    getLogger("httpx").setLevel(capture_level)

    # set the levelno on the global handler
    _logHandler.display_level = levelno


_logHandler: LogHandler | None = None
