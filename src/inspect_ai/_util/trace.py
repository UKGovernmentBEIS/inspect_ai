import asyncio
import datetime
import json
import logging
import time
import traceback
from contextlib import contextmanager
from logging import Logger
from typing import Any, Generator

from pydantic import JsonValue
from shortuuid import uuid

from inspect_ai._util.constants import TRACE


@contextmanager
def trace_action(
    logger: Logger, action: str, message: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]:
    trace_id = uuid()
    start_monotonic = time.monotonic()
    start_wall = time.time()
    formatted_message = (
        message % args if args else message % kwargs if kwargs else message
    )

    def trace_message(event: str) -> str:
        return f"Action: {action} - {formatted_message} ({event})"

    logger.log(
        TRACE,
        trace_message("enter"),
        extra={
            "action": action,
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
                "event": "exit",
                "trace_id": str(trace_id),
                "duration": duration,
            },
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            trace_message("cancel"),
            extra={
                "action": action,
                "event": "cancel",
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
                "event": "error",
                "trace_id": str(trace_id),
                "duration": duration,
                "error": str(ex),
                "error_type": type(ex).__name__,
                "stacktrace": traceback.format_exc(),
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
