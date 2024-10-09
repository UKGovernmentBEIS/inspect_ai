import functools
import os
from typing import Any, Callable, Tuple, cast

import click
from typing_extensions import TypedDict

from inspect_ai._util.constants import (
    ALL_LOG_LEVELS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_LEVEL_TRANSCRIPT,
)


class CommonOptions(TypedDict):
    log_level: str
    log_level_transcript: str
    log_dir: str
    no_ansi: bool | None
    debug: bool
    debug_port: int
    debug_errors: bool


def log_level_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--log-level",
        type=click.Choice(
            [level.lower() for level in ALL_LOG_LEVELS],
            case_sensitive=False,
        ),
        default=DEFAULT_LOG_LEVEL,
        envvar="INSPECT_LOG_LEVEL",
        help=f"Set the log level (defaults to '{DEFAULT_LOG_LEVEL}')",
    )
    @click.option(
        "--log-level-transcript",
        type=click.Choice(
            [level.lower() for level in ALL_LOG_LEVELS],
            case_sensitive=False,
        ),
        default=DEFAULT_LOG_LEVEL_TRANSCRIPT,
        envvar="INSPECT_LOG_LEVEL_TRANSCRIPT",
        help=f"Set the log level of the transcript (defaults to '{DEFAULT_LOG_LEVEL_TRANSCRIPT}')",
    )
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def common_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @log_level_options
    @click.option(
        "--log-dir",
        type=str,
        default="./logs",
        envvar="INSPECT_LOG_DIR",
        help="Directory for log files.",
    )
    @click.option(
        "--no-ansi",
        type=bool,
        is_flag=True,
        help="Do not print ANSI control characters.",
        envvar="INSPECT_NO_ANSI",
    )
    @click.option(
        "--debug", is_flag=True, envvar="INSPECT_DEBUG", help="Wait to attach debugger"
    )
    @click.option(
        "--debug-port",
        default=5678,
        envvar="INSPECT_DEBUG_PORT",
        help="Port number for debugger",
    )
    @click.option(
        "--debug-errors",
        type=bool,
        is_flag=True,
        envvar="INSPECT_DEBUG_ERRORS",
        help="Raise task errors (rather than logging them) so they can be debugged.",
    )
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def resolve_common_options(options: CommonOptions) -> Tuple[str, str, str]:
    # disable ansi if requested
    if options["no_ansi"]:
        os.environ["INSPECT_NO_ANSI"] = "1"

    # attach debugger if requested
    if options["debug"]:
        import debugpy  # type: ignore

        debugpy.listen(options["debug_port"])
        print("Waiting for debugger attach")
        debugpy.wait_for_client()
        print("Debugger attached")

    # return resolved options
    return (options["log_dir"], options["log_level"], options["log_level_transcript"])
