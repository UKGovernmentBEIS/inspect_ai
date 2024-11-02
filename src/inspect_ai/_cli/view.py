import functools
import os
from typing import Any, Callable, cast

import click
from typing_extensions import Unpack

from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._view.view import view
from inspect_ai.log._bundle import bundle_log_dir

from .common import CommonOptions, common_options, process_common_options


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
        help="Tcp/Ip host",
    )
    @click.option("--port", default=DEFAULT_VIEW_PORT, help="TCP/IP port")
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> click.Context:
        return cast(click.Context, func(*args, **kwargs))

    return wrapper


# Define the base command group
@click.group(name="view", invoke_without_command=True)
@start_options
@common_options
@click.pass_context
def view_command(ctx: click.Context, **kwargs: Unpack[CommonOptions]) -> None:
    """View command group."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(start, **kwargs)
    else:
        pass


@view_command.command("start")
@start_options
@common_options
def start(
    recursive: bool,
    host: str,
    port: int,
    **common: Unpack[CommonOptions],
) -> None:
    """View evaluation logs."""
    # read common options
    process_common_options(common)

    # resolve optional auth token
    INSPECT_VIEW_AUTHORIZATION_TOKEN = "INSPECT_VIEW_AUTHORIZATION_TOKEN"
    authorization = os.environ.get(INSPECT_VIEW_AUTHORIZATION_TOKEN, None)
    if authorization:
        del os.environ[INSPECT_VIEW_AUTHORIZATION_TOKEN]
        os.unsetenv(INSPECT_VIEW_AUTHORIZATION_TOKEN)

    # run the viewer
    view(
        log_dir=common["log_dir"],
        recursive=recursive,
        host=host,
        port=port,
        authorization=authorization,
        log_level=common["log_level"],
        log_level_transcript=common["log_level_transcript"],
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
