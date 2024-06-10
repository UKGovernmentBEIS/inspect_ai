import click

from inspect_ai.model import ModelName, cache_clear, cache_path


@click.group("cache")
def cache_command() -> None:
    """Manage the inspect cache."""
    return None


@cache_command.command()
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
    type=str,
    help="Clear the cache for a specific model (e.g. --model=openai/gpt-4).",
)
def clear(all: bool, model: str) -> None:
    """Clear all cache files. Requires either --all or --model flags."""
    if model:
        cache_clear(model=str(ModelName(model)))
    elif all:
        cache_clear()
    else:
        raise click.ClickException("Need to specify either --all or --model.")


@cache_command.command()
def path() -> None:
    """Prints the location of the cache directory."""
    print(cache_path())
