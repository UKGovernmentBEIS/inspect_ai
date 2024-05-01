import click

from inspect_ai._util.dotenv import init_dotenv

from .eval import eval_command
from .info import info_command
from .list import list_command
from .score import score_command
from .view import view_command


@click.group(invoke_without_command=True)
@click.pass_context
def inspect(
    ctx: click.Context,
) -> None:
    # if this was a subcommand then allow it to execute
    if ctx.invoked_subcommand is not None:
        return

    # if invoked as plain 'inspect' just print help and exit
    click.echo(ctx.get_help())
    ctx.exit()


inspect.add_command(eval_command)
inspect.add_command(score_command)
inspect.add_command(view_command)
inspect.add_command(list_command)
inspect.add_command(info_command)


def main() -> None:
    init_dotenv()
    inspect(auto_envvar_prefix="INSPECT")


if __name__ == "__main__":
    main()
