import click
from typing_extensions import Unpack

from inspect_ai._util.constants import DEFAULT_SERVER_HOST, DEFAULT_VIEW_PORT
from inspect_ai._view.view import view

from .common import CommonOptions, common_options, resolve_common_options


@click.command("view", hidden=True)
@click.option(
    "--host",
    default=DEFAULT_SERVER_HOST,
    help="Tcp/Ip host",
)
@click.option("--port", default=DEFAULT_VIEW_PORT, help="Tcp/Ip port")
@common_options
def view_command(
    host: str,
    port: int,
    **kwargs: Unpack[CommonOptions],
) -> None:
    # read common options
    (log_dir, log_level) = resolve_common_options(kwargs)

    # run the viewer
    view(log_dir, host, port, log_level)
