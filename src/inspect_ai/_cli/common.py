import functools
from typing import Any, Callable, Tuple, cast

import click
from typing_extensions import TypedDict

from inspect_ai._util.constants import DEFAULT_LOG_LEVEL


class CommonOptions(TypedDict):
    log_level: str
    log_dir: str
    debug: bool
    debug_port: int


def log_level_option(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--log-level",
        type=click.Choice(
            ["debug", "http", "tools", "info", "warning", "error", "critical"],
            case_sensitive=False,
        ),
        default=DEFAULT_LOG_LEVEL,
        envvar="INSPECT_LOG_LEVEL",
        help=f"Set the log level (defaults to '{DEFAULT_LOG_LEVEL}')",
    )
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def common_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @log_level_option
    @click.option(
        "--log-dir",
        type=str,
        default="./logs",
        envvar="INSPECT_LOG_DIR",
        help="Directory for log files.",
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
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


def resolve_common_options(options: CommonOptions) -> Tuple[str, str]:
    # attach debugger if requested
    if options["debug"]:
        import debugpy  # type: ignore

        debugpy.listen(options["debug_port"])
        print("Waiting for debugger attach")
        debugpy.wait_for_client()
        print("Debugger attached")

    # return resolved options
    return (options["log_dir"], options["log_level"])
