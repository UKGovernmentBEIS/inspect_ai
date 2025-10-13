import atexit
import os
from logging import (
    INFO,
    NOTSET,
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
from typing import TypedDict

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
        self,
        capture_levelno: int,
        display_levelno: int,
        transcript_levelno: int,
        env_prefix: str = "INSPECT",
        trace_dir: Path | None = None,
    ) -> None:
        super().__init__(capture_levelno, console=rich.get_console())
        self.transcript_levelno = transcript_levelno
        self.display_level = display_levelno
        # log into an external file if requested via env var
        file_logger = os.environ.get(f"{env_prefix}_PY_LOGGER_FILE", None)
        self.file_logger = FileHandler(file_logger) if file_logger else None
        if self.file_logger:
            self.file_logger.setFormatter(
                Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )

        # see if the user has a special log level for the file
        file_logger_level = os.environ.get(f"{env_prefix}_PY_LOGGER_LEVEL", "")
        if file_logger_level:
            self.file_logger_level = int(getLevelName(file_logger_level.upper()))
        else:
            self.file_logger_level = 0

        # add a trace file handler
        rotate_trace_files(trace_dir)  # remove oldest if > 10 trace files
        env_trace_file = os.environ.get(f"{env_prefix}_TRACE_FILE", None)
        trace_file = (
            Path(env_trace_file) if env_trace_file else inspect_trace_file(trace_dir)
        )
        self.trace_logger = FileHandler(trace_file)
        self.trace_logger.setFormatter(TraceFormatter())
        atexit.register(compress_trace_log(self.trace_logger))

        # set trace level
        trace_level = os.environ.get(f"{env_prefix}_TRACE_LEVEL", TRACE_LOG_LEVEL)
        self.trace_logger_level = int(getLevelName(trace_level.upper()))

    @override
    def emit(self, record: LogRecord) -> None:
        # write to stderr if we are at or above the threshold
        if record.levelno >= self.display_level and self.display_level != NOTSET:
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


class LogHandlerVar(TypedDict):
    """Mutable container for LogHandler that can be passed by reference."""

    handler: LogHandler | None


# initialize logging
def init_logger(
    log_level: str | None,
    log_level_transcript: str | None = None,
    env_prefix: str = "INSPECT",
    pkg_name: str = PKG_NAME,
    trace_dir: Path | None = None,
    log_handler_var: LogHandlerVar | None = None,
) -> None:
    # provide default log_handler_var (use TypedDict as mutable container)
    if log_handler_var is None:
        log_handler_var = _logHandler

    # backwards compatibility for 'tools'
    if log_level == "sandbox" or log_level == "tools":
        log_level = "trace"

    # register http, trace, and none levels
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
        log_level
        if log_level
        else os.getenv(f"{env_prefix}_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    ).upper()
    validate_level("log level", log_level)

    # reolve transcript log level
    log_level_transcript = (
        log_level_transcript
        if log_level_transcript
        else os.getenv(
            f"{env_prefix}_LOG_LEVEL_TRANSCRIPT", DEFAULT_LOG_LEVEL_TRANSCRIPT
        )
    ).upper()
    validate_level("log file level", log_level_transcript)

    # convert to integer
    levelno = getLevelName(log_level)
    transcript_levelno = getLevelName(log_level_transcript)

    # set capture level for our logs (we won't actually display/write all of them)
    if levelno != NOTSET:
        capture_level = min(TRACE, levelno, transcript_levelno)
    else:
        capture_level = min(TRACE, transcript_levelno)

    # init logging handler on demand
    if log_handler_var["handler"] is None:
        log_handler = LogHandler(
            capture_levelno=capture_level,
            display_levelno=levelno,
            transcript_levelno=transcript_levelno,
            env_prefix=env_prefix,
            trace_dir=trace_dir,
        )
        log_handler_var["handler"] = log_handler

        if log_level != "NOTSET":
            # set the global log level
            getLogger().setLevel(log_level)
            # httpx currently logs all requests at the INFO level
            # this is a bit aggressive and we already do this at
            # our own HTTP level
            getLogger("httpx").setLevel(WARNING)

        # set the log level for our package and inspect_ai
        def configure_logger(pkg: str) -> None:
            getLogger(pkg).setLevel(capture_level)
            getLogger(pkg).addHandler(log_handler)
            getLogger(pkg).propagate = False

        configure_logger(pkg_name)
        if pkg_name != PKG_NAME:
            configure_logger(PKG_NAME)

        # add our logger to the global handlers
        getLogger().addHandler(log_handler)


_logHandler: LogHandlerVar = {"handler": None}


def log_to_transcript(record: LogRecord) -> None:
    from inspect_ai.event._logger import LoggerEvent, LoggingMessage
    from inspect_ai.log._transcript import transcript

    transcript()._event(LoggerEvent(message=LoggingMessage._from_log_record(record)))


def warn_once(logger: Logger, message: str) -> None:
    if message not in _warned:
        logger.warning(message)
        _warned.append(message)


_warned: list[str] = []
