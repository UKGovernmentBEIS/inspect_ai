"""CLI commands for inspect-managed binary downloads.

Subcommands:

- ``restic`` pre-warms the restic binary cache (every supported platform)
  so that a checkpointed eval starts without waiting for downloads.
- ``sandbox-tools`` resolves the sandbox tools binaries (every supported
  platform) so that an install without bundled binaries (e.g. built from
  the sdist) works offline.

Shape is ``inspect download <kind>`` so other downloadable artifacts
can slot in without restructuring the namespace.
"""

from typing import get_args

import anyio
import click
from rich import box
from rich.console import Console
from rich.table import Table

from inspect_ai._util._async import configured_async_backend
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    _binaries_dir,
    _download_from_s3,
    _get_executable_name,
    _get_install_state,
)
from inspect_ai.util._restic import (
    SUPPORTED_PLATFORMS,
    Platform,
    cache_path,
    resolve_restic,
)
from inspect_ai.util._sandbox.recon import Architecture


@click.group("download")
def download_command() -> None:
    """Inspect-managed binary downloads."""


@download_command.command("restic")
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


@download_command.command("sandbox-tools")
def sandbox_tools_command() -> None:
    """Resolve the sandbox tools binaries for every supported platform."""
    anyio.run(_download_all_sandbox_tools, backend=configured_async_backend())


async def _download_all_sandbox_tools() -> None:
    console = Console()

    if _get_install_state() == "edited":
        console.print(
            "The sandbox tools have local edits. Inspect uses local -dev builds, "
            "which it builds on demand. Nothing to download."
        )
        return

    names = [
        _get_executable_name(arch, dev=False, musl=musl)
        for arch in get_args(Architecture)
        for musl in (False, True)
    ]
    states = [(name, await _resolve_sandbox_tool(console, name)) for name in names]

    console.print()
    table = Table(
        title="Sandbox tools",
        title_justify="left",
        title_style="bold",
        box=box.SQUARE,
    )
    table.add_column("Artifact", no_wrap=True)
    table.add_column("Path", overflow="fold")
    table.add_column("State", no_wrap=True)
    for name, state in states:
        table.add_row(name, str(_binaries_dir() / name), state)
    console.print(table)

    if missing := [name for name, state in states if state == "not on S3"]:
        raise click.ClickException(f"Not on S3: {', '.join(missing)}")


async def _resolve_sandbox_tool(console: Console, name: str) -> str:
    if (_binaries_dir() / name).exists():
        console.print(f"[dim]○[/dim] {name}  [dim]already present[/dim]")
        return "already present"
    with console.status(f"Downloading {name}…"):
        downloaded = await _download_from_s3(name)
    if not downloaded:
        console.print(f"[red]✗[/red] {name}  not on S3")
        return "not on S3"
    console.print(f"[green]✓[/green] {name}  downloaded")
    return "downloaded"
