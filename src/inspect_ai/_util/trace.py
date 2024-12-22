from contextlib import contextmanager
from logging import Logger
from typing import Any, Generator

from shortuuid import uuid

from inspect_ai._util.constants import TRACE


@contextmanager
def trace_action(
    logger: Logger, category: str, name: str
) -> Generator[None, None, None]:
    trace_id = uuid()
    logger.log(TRACE, f"[{category}: {trace_id}] Entering: {name}")
    try:
        yield
    except Exception as ex:
        logger.log(TRACE, f"[{category}: {trace_id}] Error: {name} ({ex})")
        raise
    finally:
        logger.log(TRACE, f"[{category}: {trace_id}] Exiting: {name}")


def trace_message(logger: Logger, category: str, message: str) -> None:
    logger.log(TRACE, f"[{category}] {message}")
