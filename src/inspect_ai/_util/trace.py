import asyncio
import time
import traceback
from contextlib import contextmanager
from logging import Logger
from typing import Any, Generator

from shortuuid import uuid

from inspect_ai._util.constants import TRACE


@contextmanager
def trace_action(
    logger: Logger, category: str, name: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]:
    trace_id = uuid()
    start_monotonic = time.monotonic()
    start_wall = time.time()
    logger.log(
        TRACE,
        f"[{category}: {trace_id}] Enter: {name} (at {start_wall:.2f})",
        *args,
        **kwargs,
    )
    try:
        yield
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            f"[{category}: {trace_id}] Exit: {name} (took {duration:.2f}s)",
            *args,
            **kwargs,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            f"[{category}: {trace_id}] Cancel: {name} (after {duration:.2f}s)",
            *args,
            **kwargs,
        )
        raise
    except Exception as ex:
        duration = time.monotonic() - start_monotonic
        logger.log(
            TRACE,
            f"[{category}: {trace_id}] Error: {name} (after {duration:.2f}s) - {ex}\n{traceback.format_exc()}",
            *args,
            **kwargs,
        )
        raise


def trace_message(
    logger: Logger, category: str, message: str, *args: Any, **kwargs: Any
) -> None:
    logger.log(TRACE, f"[{category}] {message}", *args, **kwargs)
