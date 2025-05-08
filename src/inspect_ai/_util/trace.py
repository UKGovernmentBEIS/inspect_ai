import datetime
import gzip
import json
import logging
import os
import shutil
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from logging import FileHandler, Logger
from pathlib import Path
from typing import Any, Callable, Generator, Literal, TextIO

import anyio
import jsonlines
from pydantic import BaseModel, Field, JsonValue
from shortuuid import uuid

from .appdirs import inspect_data_dir
from .constants import TRACE


def inspect_trace_dir() -> Path:
    return inspect_data_dir("traces")


def inspect_trace_file() -> Path:
    return inspect_trace_dir() / f"trace-{os.getpid()}.log"


@contextmanager
def trace_action(
    logger: Logger, action: str, message: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]:
    """Trace a long running or poentially unreliable action.

    Trace actions for which you want to collect data on the resolution
    (e.g. succeeded, cancelled, failed, timed out, etc.) and duration of.

    Traces are written to the `TRACE` log level (which is just below
    `HTTP` and `INFO`). List and read trace logs with `inspect trace list`
    and related commands (see `inspect trace --help` for details).

    Args:
       logger (Logger): Logger to use for tracing (e.g. from `getLogger(__name__)`)
       action (str): Name of action to trace (e.g. 'Model', 'Subprocess', etc.)
       message (str): Message describing action (can be a format string w/ args or kwargs)
       *args (Any): Positional arguments for `message` format string.
       **kwargs (Any): Named args for `message` format string.
    """
    trace_id = uuid()
    start_monotonic = time.monotonic()
    start_wall = time.time()
    detail = message % args if args else message % kwargs if kwargs else message

    def trace_message(event: str) -> str:
        return f"{action}: {detail} ({event})"

    logger.log(
        TRACE,
        trace_message("enter"),
        extra={
            "action": action,
            "detail": detail,
            "event": "enter",
            "trace_id": str(trace_id),
            "start_time": start_wall,
        },
    )

    try:
        yield
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            trace_message("exit"),
            extra={
                "action": action,
                "detail": detail,
                "event": "exit",
                "trace_id": str(trace_id),
                "duration": duration,
            },
        )
    except (KeyboardInterrupt, anyio.get_cancelled_exc_class()):
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            trace_message("cancel"),
            extra={
                "action": action,
                "detail": detail,
                "event": "cancel",
                "trace_id": str(trace_id),
                "duration": duration,
            },
        )
        raise
    except TimeoutError:
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            trace_message("timeout"),
            extra={
                "action": action,
                "detail": detail,
                "event": "timeout",
                "trace_id": str(trace_id),
                "duration": duration,
            },
        )
        raise
    except Exception as ex:
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            trace_message("error"),
            extra={
                "action": action,
                "detail": detail,
                "event": "error",
                "trace_id": str(trace_id),
                "duration": duration,
                "error": getattr(ex, "message", str(ex)) or repr(ex),
                "error_type": type(ex).__name__,
                "stacktrace": traceback.format_exc(),
            },
        )
        raise


def trace_message(
    logger: Logger, category: str, message: str, *args: Any, **kwargs: Any
) -> None:
    """Log a message using the TRACE log level.

    The `TRACE` log level is just below `HTTP` and `INFO`). List and
    read trace logs with `inspect trace list` and related commands
    (see `inspect trace --help` for details).

    Args:
       logger (Logger): Logger to use for tracing (e.g. from `getLogger(__name__)`)
       category (str): Category of trace message.
       message (str): Trace message (can be a format string w/ args or kwargs)
       *args (Any): Positional arguments for `message` format string.
       **kwargs (Any): Named args for `message` format string.
    """
    logger.log(TRACE, f"[{category}] {message}", *args, **kwargs)


class TraceFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Base log entry with standard fields
        output: dict[str, JsonValue] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),  # This handles the % formatting of the message
        }

        # Add basic context its not a TRACE message
        if record.levelname != "TRACE":
            if hasattr(record, "module"):
                output["module"] = record.module
            if hasattr(record, "funcName"):
                output["function"] = record.funcName
            if hasattr(record, "lineno"):
                output["line"] = record.lineno

        # Add any structured fields from extra
        elif hasattr(record, "action"):
            # This is a trace_action log
            for key in [
                "action",
                "detail",
                "event",
                "trace_id",
                "start_time",
                "duration",
                "error",
                "error_type",
                "stacktrace",
            ]:
                if hasattr(record, key):
                    output[key] = getattr(record, key)

        # Handle any unexpected extra attributes
        for key, value in record.__dict__.items():
            if key not in output and key not in (
                "args",
                "lineno",
                "funcName",
                "module",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "levelno",
                "levelname",
                "msecs",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            ):
                output[key] = value

        return json.dumps(
            output, default=str
        )  # default=str handles non-serializable objects

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        # ISO format with timezone
        dt = datetime.datetime.fromtimestamp(record.created)
        return dt.isoformat()


class TraceRecord(BaseModel):
    timestamp: str
    level: str
    message: str


class SimpleTraceRecord(TraceRecord):
    action: None = Field(default=None)


class ActionTraceRecord(TraceRecord):
    action: str
    event: Literal["enter", "cancel", "error", "timeout", "exit"]
    trace_id: str
    detail: str = Field(default="")
    start_time: float | None = Field(default=None)
    duration: float | None = Field(default=None)
    error: str | None = Field(default=None)
    error_type: str | None = Field(default=None)
    stacktrace: str | None = Field(default=None)


@dataclass
class TraceFile:
    file: Path
    mtime: float


def list_trace_files() -> list[TraceFile]:
    trace_files: list[TraceFile] = [
        TraceFile(file=f, mtime=f.lstat().st_mtime)
        for f in inspect_trace_dir().iterdir()
        if f.is_file()
    ]
    trace_files.sort(key=lambda f: f.mtime, reverse=True)
    return trace_files


def read_trace_file(file: Path) -> list[TraceRecord]:
    def read_file(f: TextIO) -> list[TraceRecord]:
        jsonlines_reader = jsonlines.Reader(f)
        trace_records: list[TraceRecord] = []
        for trace in jsonlines_reader.iter(type=dict):
            if "action" in trace:
                trace_records.append(ActionTraceRecord(**trace))
            else:
                trace_records.append(SimpleTraceRecord(**trace))
        return trace_records

    if file.name.endswith(".gz"):
        with gzip.open(file, "rt") as f:
            return read_file(f)
    else:
        with open(file, "r") as f:
            return read_file(f)


def rotate_trace_files() -> None:
    # if multiple inspect processes start up at once they
    # will all be attempting to rotate at the same time,
    # which can lead to FileNotFoundError -- ignore these
    # errors if they occur
    try:
        rotate_files = list_trace_files()[10:]
        for file in rotate_files:
            file.file.unlink(missing_ok=True)
    except (FileNotFoundError, OSError):
        pass


def compress_trace_log(log_handler: FileHandler) -> Callable[[], None]:
    def compress() -> None:
        # ensure log is closed
        log_handler.close()

        # compress
        trace_file = Path(log_handler.baseFilename)
        if trace_file.exists():
            with open(trace_file, "rb") as f_in:
                with gzip.open(trace_file.with_suffix(".log.gz"), "wb") as f_out:
                    shutil.copyfileobj(f_in, f_out)
            trace_file.unlink()

    return compress
