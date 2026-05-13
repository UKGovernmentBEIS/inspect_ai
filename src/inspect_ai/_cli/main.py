import click

from ._lazy_group import LazyGroup

# Registry of subcommands: name -> (import path, short help).
#
# The import path is resolved lazily the first time the subcommand is used,
# so ``inspect --help`` only needs to import ``click`` and this module. The
# short help string is duplicated here (rather than read from the command
# docstring) so the top-level help screen can be rendered without importing
# any subcommand module. An empty short help marks a hidden command.
_SUBCOMMANDS: dict[str, tuple[str, str]] = {
    "cache": (
        "inspect_ai._cli.cache:cache_command",
        "Manage the inspect model output cache.",
    ),
    "download": (
        "inspect_ai._cli.download:download_command",
        "",  # hidden
    ),
    "eval": (
        "inspect_ai._cli.eval:eval_command",
        "Evaluate tasks.",
    ),
    "eval-retry": (
        "inspect_ai._cli.eval:eval_retry_command",
        "Retry failed evaluation(s)",
    ),
    "eval-set": (
        "inspect_ai._cli.eval:eval_set_command",
        "Evaluate a set of tasks with retries.",
    ),
    "info": (
        "inspect_ai._cli.info:info_command",
        "Read configuration and log info.",
    ),
    "list": (
        "inspect_ai._cli.list:list_command",
        "List tasks on the filesystem.",
    ),
    "log": (
        "inspect_ai._cli.log:log_command",
        "Query, read, and convert logs.",
    ),
    "sandbox": (
        "inspect_ai._cli.sandbox:sandbox_command",
        "Manage Sandbox Environments.",
    ),
    "score": (
        "inspect_ai._cli.score:score_command",
        "Score a previous evaluation run.",
    ),
    "trace": (
        "inspect_ai._cli.trace:trace_command",
        "List and read execution traces.",
    ),
    "view": (
        "inspect_ai._cli.view:view_command",
        "Inspect log viewer.",
    ),
}


@click.group(
    cls=LazyGroup,
    lazy_subcommands=_SUBCOMMANDS,
    invoke_without_command=True,
)
@click.option(
    "--version",
    type=bool,
    is_flag=True,
    default=False,
    help="Print the Inspect version.",
)
@click.pass_context
def inspect(ctx: click.Context, version: bool) -> None:
    # if this was a subcommand then allow it to execute
    if ctx.invoked_subcommand is not None:
        return

    if version:
        print(_version())
        ctx.exit()
    else:
        click.echo(ctx.get_help())
        ctx.exit()


def _version() -> str:
    from inspect_ai import __version__

    return __version__


def main() -> None:
    inspect(auto_envvar_prefix="INSPECT")  # pylint: disable=no-value-for-parameter


if __name__ == "__main__":
    main()
