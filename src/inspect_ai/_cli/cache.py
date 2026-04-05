import click
from rich import print
from rich.table import Table

from inspect_ai._util.logger import init_logger
from inspect_ai.model import (
    ModelName,
    cache_clear,
    cache_list_expired,
    cache_path,
    cache_prune,
    cache_size,
)
from inspect_ai.scorer._cache import (
    score_cache_clear,
    score_cache_list_expired,
    score_cache_path,
    score_cache_prune,
    score_cache_size,
)

from .common import log_level_options


def _readable_size(size: int) -> str:
    if size < 1024:
        return f"{size}  B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"

    return f"{size / (1024 * 1024):.2f} MB"


def _print_table(
    title: str, paths: list[tuple[str, int]], name_column: str = "Model"
) -> None:
    """Lists all current caches with their sizes.

    Args:
        title(str): Title of the table.
        paths(list[tuple[str, int]]): List of paths and their sizes (in bytes).
        name_column(str): Header for the name column (e.g. "Model" or "Scorer").
    """
    table = Table(title=title)
    table.add_column(name_column)
    table.add_column("Size", justify="right")
    for model, size in paths:
        table.add_row(model, _readable_size(size))

    print(table)


@click.group("cache")
def cache_command() -> None:
    """Manage the inspect cache (model outputs and scorer outputs).

    Learn more about model output caching at https://inspect.aisi.org.uk/caching.html.
    """
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
@click.option(
    "--scores",
    is_flag=True,
    default=False,
    help="Clear the score cache instead of the model cache.",
)
def clear(all: bool, model: tuple[str, ...], scores: bool, log_level: str) -> None:
    """Clear all cache files. Requires either --all, --model, or --scores flags."""
    init_logger(log_level)

    if scores:
        sizes = score_cache_size()
        if sizes:
            _print_table(
                title="Clearing the following score caches",
                paths=sizes,
                name_column="Scorer",
            )
        score_cache_clear()
    elif model:
        _print_table(
            title="Clearing the following caches", paths=cache_size(subdirs=list(model))
        )
        for single_model in model:
            cache_clear(model=str(ModelName(single_model)))
    elif all:
        _print_table(title="Clearing the following caches", paths=cache_size())
        cache_clear()
        sizes = score_cache_size()
        if sizes:
            _print_table(
                title="Clearing the following score caches",
                paths=sizes,
                name_column="Scorer",
            )
        score_cache_clear()
    else:
        raise click.ClickException(
            "Need to specify either --all, --model, or --scores."
        )


@cache_command.command()
@click.option(
    "--scores",
    is_flag=True,
    default=False,
    help="Print the score cache path instead of the model cache path.",
)
def path(scores: bool) -> None:
    """Prints the location of the cache directory."""
    if scores:
        print(score_cache_path())
    else:
        print(cache_path())


@cache_command.command(name="list")
@click.option(
    "--pruneable",
    is_flag=True,
    default=False,
    help="Only list cache entries that can be pruned due to expiry (see inspect cache prune --help).",
)
@click.option(
    "--scores",
    is_flag=True,
    default=False,
    help="List score caches instead of model caches.",
)
def list_caches(pruneable: bool, scores: bool) -> None:
    """Lists all current caches with their sizes."""
    if scores:
        if pruneable:
            expired = score_cache_list_expired()
            if expired:
                _print_table(
                    title="The following score caches can be pruned due to expiry",
                    paths=score_cache_size(files=expired),
                    name_column="Scorer",
                )
            else:
                print("No expired score cache entries.")
        else:
            sizes = score_cache_size()
            if sizes:
                _print_table(
                    title="Score Cache Sizes", paths=sizes, name_column="Scorer"
                )
            else:
                print("No score cache entries.")
    else:
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
@click.option(
    "--scores",
    is_flag=True,
    default=False,
    help="Prune score caches instead of model caches.",
)
def prune(log_level: str, model: tuple[str, ...], scores: bool) -> None:
    """Prune all expired cache entries

    Over time the cache directory can grow, but many cache entries will be
    expired. This command will remove all expired cache entries for ease of
    maintenance.
    """
    init_logger(log_level)

    if scores:
        expired = score_cache_list_expired()
        if expired:
            _print_table(
                title="Pruning the following score caches",
                paths=score_cache_size(files=expired),
                name_column="Scorer",
            )
            score_cache_prune(expired)
        else:
            print("No expired score cache entries to prune.")
    else:
        expired_cache_entries = cache_list_expired(list(model))

        if expired_cache_entries:
            _print_table(
                title="Pruning the following caches",
                paths=cache_size(files=expired_cache_entries),
            )

            cache_prune(expired_cache_entries)
        else:
            print("No expired cache entries to prune.")
