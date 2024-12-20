from contextlib import contextmanager
from logging import Logger
from typing import Any, Generator

from inspect_ai._util.constants import TRACE


@contextmanager
def trace_action(
    logger: Logger, category: str, name: str, *args: Any, **kwargs: Any
) -> Generator[None, None, None]:
    logger.log(TRACE, f"[{category}] Entering: {name}", *args, **kwargs)
    try:
        yield
    finally:
        logger.log(TRACE, f"[{category}] Exiting: {name}", *args, **kwargs)


def trace_message(
    logger: Logger, category: str, message: str, *args: Any, **kwargs: Any
) -> None:
    logger.log(TRACE, f"[{category}] {message}", *args, **kwargs)
