import asyncio
import datetime
import gzip
import json
import logging
import os
import shutil
import time
import traceback
from contextlib import contextmanager
from logging import Logger
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Generator, Literal, TextIO

import jsonlines
from pydantic import BaseModel, Field, JsonValue
from shortuuid import uuid

from .appdirs import inspect_data_dir
from .constants import TRACE


def inspect_trace_dir() -> Path:
    return inspect_data_dir("traces")


@contextmanager
def trace_action(
    logger: Logger, action: str, message: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]:
    trace_id = uuid()
    start_monotonic = time.monotonic()
    start_wall = time.time()
    pid = os.getpid()
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
            "pid": pid,
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
                "pid": pid,
            },
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
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
                "pid": pid,
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
                "pid": pid,
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
                "pid": pid,
            },
        )
        raise


def trace_message(
    logger: Logger, category: str, message: str, *args: Any, **kwargs: Any
) -> None:
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
                "pid",
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
    pid: int | None = Field(default=None)


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


class TraceFileHandler(RotatingFileHandler):
    def __init__(
        self,
        filename: str,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
    ) -> None:
        super().__init__(filename, mode, maxBytes, backupCount, encoding, delay)

    def rotation_filename(self, default_name: str) -> str:
        """
        Returns the name of the rotated file.

        Args:
            default_name: The default name that would be used for rotation

        Returns:
            The modified filename with .gz extension
        """
        return default_name + ".gz"

    def rotate(self, source: str, dest: str) -> None:
        """
        Compresses the source file and moves it to destination.

        Args:
            source: The source file to be compressed
            dest: The destination path for the compressed file
        """
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(source)
