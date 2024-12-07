import functools
from typing import Any, Callable, Literal, cast

import click
from typing_extensions import TypedDict

from inspect_ai._util.constants import (
    ALL_LOG_LEVELS,
    DEFAULT_DISPLAY,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_LEVEL_TRANSCRIPT,
)
from inspect_ai._util.display import init_display_type


class CommonOptions(TypedDict):
    log_level: str
    log_level_transcript: str
    log_dir: str
    display: Literal["full", "rich", "plain", "none"]
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
        callback=clean_log_dir,
        envvar="INSPECT_LOG_DIR",
        help="Directory for log files.",
    )
    @click.option(
        "--display",
        type=click.Choice(["full", "rich", "plain", "none"], case_sensitive=False),
        default=DEFAULT_DISPLAY,
        envvar="INSPECT_DISPLAY",
        help="Set the display type (defaults to 'full')",
    )
    @click.option(
        "--no-ansi",
        type=bool,
        is_flag=True,
        hidden=True,
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


def process_common_options(options: CommonOptions) -> None:
    # propagate display
    if options["no_ansi"]:
        display = "plain"
    else:
        display = options["display"].lower().strip()
    init_display_type(display)

    # attach debugger if requested
    if options["debug"]:
        import debugpy  # type: ignore

        debugpy.listen(options["debug_port"])
        print("Waiting for debugger attach")
        debugpy.wait_for_client()
        print("Debugger attached")


def clean_log_dir(
    ctx: click.Context, param: click.Option, value: str | None
) -> str | None:
    if value is not None:
        value = value.rstrip("/\\")
    return value
