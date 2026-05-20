"""Hidden CLI commands for inspect-managed binary downloads.

Currently exposes a single subcommand, ``restic``, which pre-warms the
restic binary cache (every supported platform) so that a checkpointed
eval starts without waiting for downloads.

The command group is hidden (``hidden=True``) for now: checkpointing
itself is not yet user-visible, so exposing the command surface to
customers would advertise functionality that has nothing to do. Shape
is ``inspect download <kind>`` so other downloadable artifacts can slot
in without restructuring the namespace.
"""

import anyio
import click
from rich import box
from rich.console import Console
from rich.table import Table

from inspect_ai._util._async import configured_async_backend
from inspect_ai.util._restic import Platform, resolve_restic
from inspect_ai.util._restic._platform import SUPPORTED_PLATFORMS
from inspect_ai.util._restic._resolver import cache_path


@click.group("download", hidden=True)
def download_command() -> None:
    """Inspect-managed binary downloads (hidden; internal use)."""


@download_command.command("restic", hidden=True)
def restic_command() -> None:
    """Pre-warm the restic binary cache for every supported platform."""
    anyio.run(_download_all_restic, backend=configured_async_backend())


async def _download_all_restic() -> None:
    console = Console()

    for platform in SUPPORTED_PLATFORMS:
        if cache_path(platform).exists():
            console.print(
                f"[dim]○[/dim] {_display_platform(platform)}  [dim]already cached[/dim]"
            )
            continue
        with console.status(f"Downloading {_display_platform(platform)}…"):
            await resolve_restic(platform)
        console.print(f"[green]✓[/green] {_display_platform(platform)}  downloaded")

    console.print()
    table = Table(
        title="Cache state",
        title_justify="left",
        title_style="bold",
        box=box.SQUARE,
    )
    table.add_column("Platform", no_wrap=True)
    table.add_column("Path", overflow="fold")
    for platform in SUPPORTED_PLATFORMS:
        table.add_row(_display_platform(platform), str(cache_path(platform)))
    console.print(table)


def _display_platform(platform: Platform) -> str:
    return platform.replace("_", "/")
