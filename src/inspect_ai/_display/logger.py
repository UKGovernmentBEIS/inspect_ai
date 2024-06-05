import os
from logging import (
    INFO,
    WARNING,
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
    DEFAULT_LOG_LEVEL,
    HTTP,
    HTTP_LOG_LEVEL,
    PKG_NAME,
    TOOLS,
    TOOLS_LOG_LEVEL,
)
from inspect_ai.util._context.logger import notify_logger_record

from .rich import rich_console


# log handler that filters messages to stderr and the log file
class LogHandler(RichHandler):
    def __init__(self, levelno: int) -> None:
        super().__init__(levelno, console=rich_console())
        self.display_level = WARNING

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

        # eval log always gets info level and higher records
        # eval log only gets debug or http if we opt-in
        write = record.levelno >= INFO or record.levelno >= self.display_level
        notify_logger_record(record, write)

    @override
    def render_message(self, record: LogRecord, message: str) -> ConsoleRenderable:
        return Text.from_ansi(message)


# initialize logging -- this function can be called multiple times
# in the lifetime of the process (the levelno will update globally)
def init_logger(log_level: str | None = None) -> None:
    # register http and tools levels
    addLevelName(HTTP, HTTP_LOG_LEVEL)
    addLevelName(TOOLS, TOOLS_LOG_LEVEL)

    # resolve default log level
    log_level = (
        log_level if log_level else os.getenv("INSPECT_LOG_LEVEL", DEFAULT_LOG_LEVEL)
    )

    # convert to integer
    levelno = getLevelName(log_level.upper())

    # init logging handler on demand
    global _logHandler
    if not _logHandler:
        _logHandler = LogHandler(min(HTTP, levelno))
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
