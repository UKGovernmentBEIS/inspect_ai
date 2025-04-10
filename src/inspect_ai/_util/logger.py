import atexit
import os
from logging import (
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
from .trace import (
    TraceFormatter,
    compress_trace_log,
    inspect_trace_file,
    rotate_trace_files,
)

TRACE_FILE_NAME = "trace.log"


# log handler that filters messages to stderr and the log file
class LogHandler(RichHandler):
    def __init__(
        self, capture_levelno: int, display_levelno: int, transcript_levelno: int
    ) -> None:
        super().__init__(capture_levelno, console=rich.get_console())
        self.transcript_levelno = transcript_levelno
        self.display_level = display_levelno
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

        # add a trace file handler
        rotate_trace_files()  # remove oldest if > 10 trace files
        env_trace_file = os.environ.get("INSPECT_TRACE_FILE", None)
        trace_file = Path(env_trace_file) if env_trace_file else inspect_trace_file()
        self.trace_logger = FileHandler(trace_file)
        self.trace_logger.setFormatter(TraceFormatter())
        atexit.register(compress_trace_log(self.trace_logger))

        # set trace level
        trace_level = os.environ.get("INSPECT_TRACE_LEVEL", TRACE_LOG_LEVEL)
        self.trace_logger_level = int(getLevelName(trace_level.upper()))

    @override
    def emit(self, record: LogRecord) -> None:
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

        # eval log gets transcript level or higher
        if record.levelno >= self.transcript_levelno:
            log_to_transcript(record)

    @override
    def render_message(self, record: LogRecord, message: str) -> ConsoleRenderable:
        return Text.from_ansi(message)


# initialize logging -- this function can be called multiple times
# in the lifetime of the process (the levelno will update globally)
def init_logger(log_level: str | None, log_level_transcript: str | None = None) -> None:
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

    # reolve transcript log level
    log_level_transcript = (
        log_level_transcript
        if log_level_transcript
        else os.getenv("INSPECT_LOG_LEVEL_TRANSCRIPT", DEFAULT_LOG_LEVEL_TRANSCRIPT)
    ).upper()
    validate_level("log file level", log_level_transcript)

    # convert to integer
    levelno = getLevelName(log_level)
    transcript_levelno = getLevelName(log_level_transcript)

    # set capture level for our logs (we won't actually display/write all of them)
    capture_level = min(TRACE, levelno, transcript_levelno)

    # init logging handler on demand
    global _logHandler
    if not _logHandler:
        _logHandler = LogHandler(
            capture_levelno=capture_level,
            display_levelno=levelno,
            transcript_levelno=transcript_levelno,
        )

        # set the global log level
        getLogger().setLevel(log_level)

        # set the log level for our package
        getLogger(PKG_NAME).setLevel(capture_level)
        getLogger(PKG_NAME).addHandler(_logHandler)
        getLogger(PKG_NAME).propagate = False

        # add our logger to the global handlers
        getLogger().addHandler(_logHandler)

        # httpx currently logs all requests at the INFO level
        # this is a bit aggressive and we already do this at
        # our own HTTP level
        getLogger("httpx").setLevel(WARNING)


_logHandler: LogHandler | None = None


def log_to_transcript(record: LogRecord) -> None:
    from inspect_ai.log._message import LoggingMessage
    from inspect_ai.log._transcript import LoggerEvent, transcript

    transcript()._event(LoggerEvent(message=LoggingMessage._from_log_record(record)))


def warn_once(logger: Logger, message: str) -> None:
    if message not in _warned:
        logger.warning(message)
        _warned.append(message)


_warned: list[str] = []
