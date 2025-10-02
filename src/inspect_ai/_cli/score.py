from __future__ import annotations

import contextlib
from typing import AsyncGenerator

import anyio
import click
import rich
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from typing_extensions import Unpack

from inspect_ai._cli.util import int_or_bool_flag_callback, parse_cli_config
from inspect_ai._display import display
from inspect_ai._display.core.results import task_scores
from inspect_ai._display.core.rich import rich_theme
from inspect_ai._eval.context import init_eval_context
from inspect_ai._eval.score import (
    ScoreAction,
    resolve_scorers,
    score_async,
)
from inspect_ai._util._async import configured_async_backend
from inspect_ai._util.file import filesystem
from inspect_ai._util.platform import platform_init
from inspect_ai.log._log import EvalLog, EvalSample
from inspect_ai.log._recorders import create_recorder_for_location

from .common import CommonOptions, common_options, process_common_options


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
    envvar="INSPECT_SCORE_OVERWRITE",
    help="Overwrite log file with the scored version",
)
@click.option(
    "--output-file",
    type=click.Path(dir_okay=False, writable=True),
    envvar="INSPECT_SCORE_OUTPUT_FILE",
    help="Output file to write the scored log to.",
)
@click.option(
    "--stream",
    flag_value="true",
    type=str,
    is_flag=False,
    default=False,
    callback=int_or_bool_flag_callback(True, false_value=False, is_one_true=False),
    help="Stream the samples through the scoring process instead of reading the entire log into memory. Useful for large logs. Set to an integer to limit the number of concurrent samples being scored.",
    envvar="INSPECT_SCORE_STREAM",
)
@common_options
def score_command(
    log_file: str,
    overwrite: bool | None,
    output_file: str | None,
    scorer: str | None,
    s: tuple[str, ...] | None,
    action: ScoreAction | None,
    stream: int | bool = False,
    **common: Unpack[CommonOptions],
) -> None:
    """Score a previous evaluation run."""
    process_common_options(common)

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
            stream=stream,
        )

    anyio.run(run_score, backend=configured_async_backend())


async def score(
    log_dir: str,
    log_file: str,
    scorer: str | None,
    s: tuple[str, ...] | None,
    overwrite: bool,
    action: ScoreAction | None,
    log_level: str | None,
    output_file: str | None = None,
    stream: int | bool = False,
) -> None:
    platform_init()

    init_eval_context(log_level, None)
    scorer_args = parse_cli_config(args=s, config=None)

    recorder = create_recorder_for_location(log_file, log_dir)
    eval_log = await recorder.read_log(log_file, header_only=bool(stream))
    num_samples = (
        len(eval_log.samples)
        if eval_log.samples
        else eval_log.results.total_samples
        if eval_log.results
        else None
    )
    if num_samples is None or num_samples == 0:
        raise ValueError(
            f"Cannot determine the number of samples to score for {log_file}"
        )

    scorers = resolve_scorers(eval_log, scorer, scorer_args)
    if len(scorers) == 0:
        raise ValueError(
            "Unable to resolve any scorers for this log. Please specify a scorer using the '--scorer' param."
        )
    action = resolve_action(eval_log, action)
    output_file = _resolve_output_file(
        log_file, output_file=output_file, overwrite=overwrite
    )
    write_recorder = create_recorder_for_location(output_file, log_dir)

    read_sample = None
    if stream:
        sample_map = await recorder.read_log_sample_ids(log_file)
        semaphore = anyio.Semaphore(len(sample_map) if stream is True else stream)

        @contextlib.asynccontextmanager
        async def _read_sample(idx_sample: int) -> AsyncGenerator[EvalSample, None]:
            async with semaphore:
                sample = await recorder.read_log_sample(
                    log_file, *sample_map[idx_sample]
                )
                yield sample
                await write_recorder.log_sample(eval_log.eval, sample)
                del sample

        read_sample = _read_sample
        await write_recorder.log_init(eval_log.eval, location=output_file)
        await write_recorder.log_start(eval_log.eval, eval_log.plan)

    eval_log = await score_async(
        log=eval_log,
        scorers=scorers,
        action=action,
        copy=False,
        samples=read_sample,
    )

    if stream:
        await write_recorder.log_finish(
            eval_log.eval,
            eval_log.status,
            eval_log.stats,
            eval_log.results,
            eval_log.reductions,
            eval_log.error,
        )
    else:
        await recorder.write_log(output_file, eval_log)

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
    log_file: str, output_file: str | None, overwrite: bool
) -> str:
    # resolve the output file (we may overwrite, use the passed file name, or suggest a new name)
    output_file = output_file or log_file
    output_fs = filesystem(output_file or log_file)

    if not output_fs.exists(output_file) or overwrite:
        return output_file

    # Ask if we should overwrite
    file_action = Prompt.ask(
        f"Overwrite {output_file} or create new file?",
        choices=["overwrite", "create", "o", "c"],
        default="create",
    )
    if file_action in ["overwrite", "o"]:
        return output_file

    # parse the file path, which could be a local file path
    # or an S3 url.
    dir_name = output_fs.sep.join(output_file.split(output_fs.sep)[:-1])
    file_name = output_file.split(output_fs.sep)[-1]
    file_stem = file_name.split(".")[0]
    file_ext = ".".join(file_name.split(".")[1:])

    # suggest a new file name
    new_output_file = f"{dir_name}{output_fs.sep}{file_stem}-scored.{file_ext}"
    count = 0
    while output_fs.exists(new_output_file):
        count = count + 1
        new_output_file = (
            f"{dir_name}{output_fs.sep}{file_stem}-scored-{count}.{file_ext}"
        )

    # confirm the file name
    user_file = Prompt.ask("Output file name?", default=new_output_file)
    return user_file


def resolve_action(eval_log: EvalLog, action: ScoreAction | None) -> ScoreAction:
    if action is not None:
        return action

    if eval_log.results is not None and len(eval_log.results.scores) > 0:
        user_action = Prompt.ask(
            "Overwrite existing scores or append as additional scores?",
            choices=["overwrite", "append", "o", "a"],
            default="append",
        )
        return "overwrite" if user_action in ["overwrite", "o"] else "append"
    else:
        return "overwrite"
