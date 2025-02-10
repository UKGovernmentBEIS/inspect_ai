import asyncio
import os
from typing import Literal

import click
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_config
from inspect_ai._display import display
from inspect_ai._eval.context import init_eval_context, init_task_context
from inspect_ai._eval.score import task_score
from inspect_ai._util.constants import SCORED_SUFFIX
from inspect_ai.log._recorders import create_recorder_for_location
from inspect_ai.model import get_model

from .common import CommonOptions, common_options, process_common_options


@click.command("score")
@click.argument("log-file", type=str, required=True)
@click.option(
    "--no-overwrite",
    type=bool,
    is_flag=True,
    help="Do not overwrite unscored log_files with the scored version (instead write a new file w/ '-scored' appended)",
)
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
@common_options
def score_command(
    log_file: str,
    no_overwrite: bool | None,
    scorer: str | None,
    s: tuple[str] | None,
    action: Literal["append", "overwrite"] | None,
    **common: Unpack[CommonOptions],
) -> None:
    """Score a previous evaluation run."""
    # read common options
    process_common_options(common)

    # score
    asyncio.run(
        score(
            log_dir=common["log_dir"],
            log_file=log_file,
            scorer=scorer,
            s=s,
            overwrite=False if no_overwrite else True,
            action=action,
            log_level=common["log_level"],
        )
    )


async def score(
    log_dir: str,
    log_file: str,
    scorer: str | None,
    s: tuple[str] | None,
    overwrite: bool,
    action: Literal["append", "overwrite"] | None,
    log_level: str | None,
) -> None:
    # init eval context
    init_eval_context(log_level, None)
    scorer_args = parse_cli_config(args=s, config=None)

    # read the eval log
    recorder = create_recorder_for_location(log_file, log_dir)
    eval_log = await recorder.read_log(log_file)

    # check that there are samples therein
    if eval_log.samples is None or len(eval_log.samples) == 0:
        raise ValueError(f"{log_file} does not include samples to score")

    # get the model then initialize the async context
    model = get_model(
        model=eval_log.eval.model,
        config=eval_log.plan.config,
        **eval_log.eval.model_args,
    )

    # initialize active model
    init_task_context(model)

    # re-score the task
    eval_log = await task_score(
        log=eval_log, scorer=scorer, scorer_args=scorer_args, action=action
    )

    # re-write the log (w/ a -score suffix if requested)
    _, ext = os.path.splitext(log_file)
    scored = f"{SCORED_SUFFIX}{ext}"
    if not overwrite and not log_file.endswith(scored):
        log_file = log_file.removesuffix(ext) + scored
    await recorder.write_log(log_file, eval_log)

    # print results
    display().print("")
    display().print(f"\nResults for {eval_log.eval.task}")
    if eval_log.results:
        for score in eval_log.results.scores:
            display().print(f"{score.name}")
            for name, metric in score.metrics.items():
                display().print(f" - {name}: {metric.value}")
    display().print(f"log: {log_file}\n")
