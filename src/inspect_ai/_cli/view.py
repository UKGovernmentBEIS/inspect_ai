import functools
import os
from typing import Any, Callable, cast

import click
from typing_extensions import Unpack

from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._view.view import view
from inspect_ai.log._bundle import bundle_log_dir, embed_log_dir

from .common import (
    CommonOptions,
    CommonOptionsNoLogDir,
    common_options,
    common_options_no_log_dir,
    log_dir_option,
    process_common_options,
)


def resolve_view_log_dirs(log_dir_flags: tuple[str, ...], env: str | None) -> list[str]:
    """Resolve the viewer's log dirs from --log-dir flags and INSPECT_LOG_DIR.

    Flags take precedence; the env var is comma-split (comma is used rather
    than os.pathsep so `s3://` / `file://` URIs survive). Falls back to
    `./logs` when neither is provided.

    Args:
        log_dir_flags: Values from repeated `--log-dir` options.
        env: Raw `INSPECT_LOG_DIR` value, or None.

    Returns:
        Ordered list of directory paths/URIs (at least one element).
    """
    if log_dir_flags:
        return [d.rstrip("/\\") for d in log_dir_flags]
    if env:
        return [d.strip().rstrip("/\\") for d in env.split(",") if d.strip()]
    return ["./logs"]


def start_options(func: Callable[..., Any]) -> Callable[..., click.Context]:
    @click.option(
        "--recursive",
        type=bool,
        is_flag=True,
        default=True,
        help="Include all logs in log_dir recursively.",
    )
    @click.option(
        "--host",
        default=DEFAULT_SERVER_HOST,
        help="Tcp/Ip host. Note: you can use `0.0.0.0` to expose the viewer and connect remotely (e.g. SSH).",
    )
    @click.option("--port", default=DEFAULT_VIEW_PORT, help="TCP/IP port")
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


# Define the base command group
@click.group(name="view", invoke_without_command=True)
@start_options
@log_dir_option(multiple=True)
@common_options_no_log_dir
@click.pass_context
def view_command(ctx: click.Context, /, **kwargs: Any) -> None:
    """Inspect log viewer.

    Learn more about using the log viewer at https://inspect.aisi.org.uk/log-viewer.html.
    """
    if ctx.invoked_subcommand is None:
        ctx.invoke(start, **kwargs)
    else:
        pass


@view_command.command("start")
@start_options
@log_dir_option(multiple=True)
@common_options_no_log_dir
def start(
    recursive: bool,
    host: str,
    port: int,
    log_dir: tuple[str, ...],
    **common: Unpack[CommonOptionsNoLogDir],
) -> None:
    """View evaluation logs."""
    # read common options
    process_common_options(common)

    # resolve log dirs (repeatable flag + comma-delimited env var)
    log_dirs = resolve_view_log_dirs(log_dir, os.environ.get("INSPECT_LOG_DIR"))

    # resolve optional auth token
    INSPECT_VIEW_AUTHORIZATION_TOKEN = "INSPECT_VIEW_AUTHORIZATION_TOKEN"
    authorization = os.environ.get(INSPECT_VIEW_AUTHORIZATION_TOKEN, None)
    if authorization:
        # this indicates we are in vscode -- we want to set the log level to HTTP
        # in vscode, updated versions of the extension do this but we set it
        # manually here as a temporary bridge for running against older versions
        common["log_level"] = "HTTP"
        del os.environ[INSPECT_VIEW_AUTHORIZATION_TOKEN]
        os.unsetenv(INSPECT_VIEW_AUTHORIZATION_TOKEN)

    # run the viewer
    view(
        log_dir=log_dirs,
        recursive=recursive,
        host=host,
        port=port,
        authorization=authorization,
        log_level=common["log_level"],
    )


@view_command.command("bundle")
@common_options
@click.option(
    "--output-dir",
    required=True,
    help="The directory where bundled output will be placed.",
)
@click.option(
    "--overwrite",
    type=bool,
    is_flag=True,
    default=False,
    help="Overwrite files in the output directory.",
)
def bundle_command(
    output_dir: str,
    overwrite: bool,
    **common: Unpack[CommonOptions],
) -> None:
    """Bundle evaluation logs"""
    # process common options
    process_common_options(common)

    bundle_log_dir(
        output_dir=output_dir, log_dir=common["log_dir"], overwrite=overwrite
    )


@view_command.command("embed")
@common_options
def embed_command(
    **common: Unpack[CommonOptions],
) -> None:
    """Embed a lightweight viewer into a log directory."""
    process_common_options(common)

    embed_log_dir(log_dir=common["log_dir"])
