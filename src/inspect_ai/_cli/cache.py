import click
from rich import print
from rich.table import Table

from inspect_ai._display.logger import init_logger
from inspect_ai.model import (
    ModelName,
    cache_clear,
    cache_list_expired,
    cache_path,
    cache_prune,
    cache_size,
)

from .common import log_level_options


def _readable_size(size: int) -> str:
    if size < 1024:
        return f"{size}  B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"

    return f"{size / (1024 * 1024):.2f} MB"


def _print_table(title: str, paths: list[tuple[str, int]]) -> None:
    """Lists all current model caches with their sizes.

    Args:
        title(str): Title of the table.
        paths(list[tuple[str, int]]): List of paths and their sizes (in bytes).
    """
    table = Table(title=title)
    table.add_column("Model")
    table.add_column("Size", justify="right")
    for model, size in paths:
        table.add_row(model, _readable_size(size))

    print(table)


@click.group("cache")
def cache_command() -> None:
    """Manage the inspect cache."""
    return None


@cache_command.command()
@log_level_options
@click.option(
    "--all",
    is_flag=True,
    default=False,
    help="Clear all cache files in the cache directory.",
)
@click.option(
    "--model",
    default=None,
    metavar="MODEL",
    multiple=True,
    type=str,
    help="Clear the cache for a specific model (e.g. --model=openai/gpt-4). Can be passed multiple times.",
)
def clear(
    all: bool, model: tuple[str, ...], log_level: str, log_level_transcript: str
) -> None:
    """Clear all cache files. Requires either --all or --model flags."""
    init_logger(log_level, log_level_transcript)

    if model:
        _print_table(
            title="Clearing the following caches", paths=cache_size(subdirs=list(model))
        )
        for single_model in model:
            cache_clear(model=str(ModelName(single_model)))
    elif all:
        _print_table(title="Clearing the following caches", paths=cache_size())
        cache_clear()
    else:
        raise click.ClickException("Need to specify either --all or --model.")


@cache_command.command()
def path() -> None:
    """Prints the location of the cache directory."""
    print(cache_path())


@cache_command.command(name="list")
@click.option(
    "--pruneable",
    is_flag=True,
    default=False,
    help="Only list cache entries that can be pruned due to expiry (see inspect cache prune --help).",
)
def list_caches(pruneable: bool) -> None:
    """Lists all current model caches with their sizes."""
    if pruneable:
        expired_cache_entries = cache_list_expired()
        if expired_cache_entries:
            _print_table(
                title="The following models can be pruned due to cache expiry",
                paths=cache_size(files=expired_cache_entries),
            )
        else:
            print("No expired cache entries.")
    else:
        _print_table(title="Cache Sizes", paths=cache_size())


@cache_command.command()
@log_level_options
@click.option(
    "--model",
    default=None,
    metavar="MODEL",
    multiple=True,
    type=str,
    help="Only prune a specific model (e.g. --model=openai/gpt-4). Can be passed multiple times.",
)
def prune(log_level: str, log_level_transcript: str, model: tuple[str, ...]) -> None:
    """Prune all expired cache entries

    Over time the cache directory can grow, but many cache entries will be
    expired. This command will remove all expired cache entries for ease of
    maintenance.
    """
    init_logger(log_level, log_level_transcript)

    expired_cache_entries = cache_list_expired(list(model))

    if expired_cache_entries:
        _print_table(
            title="Pruning the following caches",
            paths=cache_size(files=expired_cache_entries),
        )

        cache_prune(expired_cache_entries)
    else:
        print("No expired cache entries to prune.")
