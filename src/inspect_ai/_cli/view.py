import click
from typing_extensions import Unpack

from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._view.view import view

from .common import CommonOptions, common_options, resolve_common_options


@click.command("view")
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
@common_options
def view_command(
    recursive: bool,
    host: str,
    port: int,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """View evaluation logs."""
    # read common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # run the viewer
    view(
        log_dir=log_dir, recursive=recursive, host=host, port=port, log_level=log_level
    )
