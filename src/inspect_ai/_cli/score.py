from __future__ import annotations

import pathlib
from typing import TYPE_CHECKING

import anyio
import click
import rich
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_config
from inspect_ai._display import display
from inspect_ai._display.core.results import task_scores
from inspect_ai._display.core.rich import rich_theme
from inspect_ai._eval.context import init_eval_context
from inspect_ai._eval.score import ScoreAction, task_score
from inspect_ai._util._async import configured_async_backend
from inspect_ai.log._log import EvalLog
from inspect_ai.log._recorders import create_recorder_for_location

from .common import CommonOptions, common_options, process_common_options

if TYPE_CHECKING:
    from _typeshed import StrPath


@click.command("score")
@click.argument("log-file", type=str, required=True)
@click.option(
    "--scorer",
    type=str,
    envvar="INSPECT_SCORE_SCORER",
    help="Scorer to use for scoring",
)
@click.option(
    "-S",
    multiple=True,
    type=str,
    envvar="INSPECT_SCORE_SCORER_ARGS",
    help="One or more scorer arguments (e.g. -S arg=value)",
)
@click.option(
    "--action",
    type=click.Choice(["append", "overwrite"]),
    envvar="INSPECT_SCORE_SCORER_ACTION",
    help="Whether to append or overwrite the existing scores.",
)
@click.option(
    "--overwrite",
    type=bool,
    is_flag=True,
    help="Overwrite log file with the scored version",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True),
    help="Output file to write the scored log to.",
)
@common_options
def score_command(
    log_file: str,
    overwrite: bool | None,
    output_file: str | None,
    scorer: str | None,
    s: tuple[str] | None,
    action: ScoreAction | None,
    **common: Unpack[CommonOptions],
) -> None:
    """Score a previous evaluation run."""
    # read common options
    process_common_options(common)

    # score
    async def run_score() -> None:
        return await score(
            log_dir=common["log_dir"],
            log_file=log_file,
            output_file=output_file,
            scorer=scorer,
            s=s,
            overwrite=False if overwrite is None else overwrite,
            action=action,
            log_level=common["log_level"],
        )

    anyio.run(run_score, backend=configured_async_backend())


async def score(
    log_dir: str,
    log_file: str,
    scorer: str | None,
    s: tuple[str] | None,
    overwrite: bool,
    action: ScoreAction | None,
    log_level: str | None,
    output_file: str | None = None,
) -> None:
    # init eval context
    init_eval_context(log_level, None)
    scorer_args = parse_cli_config(args=s, config=None)

    # read the eval log
    recorder = create_recorder_for_location(log_file, log_dir)
    eval_log = await recorder.read_log(log_file)

    # resolve the target output file (prompts user)
    output_file = _resolve_output_file(
        log_file, output_file=output_file, overwrite=overwrite
    )

    # resolve action
    action = resolve_action(eval_log, action)

    # check that there are samples therein
    if eval_log.samples is None or len(eval_log.samples) == 0:
        raise ValueError(f"{log_file} does not include samples to score")

    # re-score the task
    eval_log = await task_score(
        log=eval_log, scorer=scorer, scorer_args=scorer_args, action=action
    )

    # re-write the log
    await recorder.write_log(output_file, eval_log)

    # print results
    print_results(output_file, eval_log)


def print_results(output_file: str, eval_log: EvalLog) -> None:
    # the theme
    theme = rich_theme()

    # Create results panel
    grid = Table.grid(expand=True)
    grid.add_column()
    grid.add_row("")

    if eval_log.results:
        for row in task_scores(eval_log.results.scores, pad_edge=True):
            grid.add_row(row)

    grid.add_row("")
    grid.add_row(f" Log: [{theme.link}]{output_file}[/{theme.link}]")

    p = Panel(
        title=f"[bold][{theme.meta}]Results for {eval_log.eval.task}[/bold][/{theme.meta}]",
        title_align="left",
        renderable=grid,
    )

    # Print the results panel
    display().print("")
    console = rich.get_console()
    console.print(p)


def _resolve_output_file(
    log_file: str, output_file: StrPath | None, overwrite: bool
) -> str:
    # resolve the output file (we may overwrite, use the passed file name, or suggest a new name)
    output_file = pathlib.Path(output_file or log_file)
    if not output_file.exists() or overwrite:
        return str(output_file)

    # Ask if we should overwrite
    file_action = Prompt.ask(
        f"Overwrite {output_file} or create new file?",
        choices=["overwrite", "create", "o", "c"],
        default="create",
    )
    if file_action in ["overwrite", "o"]:
        return str(output_file)

    new_output_file = output_file.with_stem(f"{output_file.stem}-scored")
    count = 0
    while new_output_file.exists():
        count = count + 1
        new_output_file = output_file.with_stem(f"{output_file.stem}-scored-{count}")

    user_file = Prompt.ask("Output file name?", default=new_output_file.name)
    return str(output_file.parent / user_file)


def resolve_action(eval_log: EvalLog, action: ScoreAction | None) -> ScoreAction:
    if action is not None:
        return action

    if eval_log.results is not None and len(eval_log.results.scores) > 0:
        user_action = Prompt.ask(
            "Overwrite existing scores or append as additional scores?",
            choices=["overwrite", "append", "o", "a"],
            default="append",
        )
        return "overwrite" if user_action in ["ovewrite", "o"] else "append"
    else:
        return "overwrite"
