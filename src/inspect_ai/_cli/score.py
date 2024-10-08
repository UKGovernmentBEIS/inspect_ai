import asyncio

import click
from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._eval.context import init_eval_context, init_task_context
from inspect_ai._eval.loader import load_tasks
from inspect_ai._eval.score import task_score
from inspect_ai._util.constants import SCORED_SUFFIX
from inspect_ai.log._file import JSONRecorder
from inspect_ai.model import get_model

from .common import CommonOptions, common_options, resolve_common_options


@click.command("score")
@click.argument("task", type=str)
@click.argument("log-file", type=str, required=False)
@click.option(
    "--no-overwrite",
    type=bool,
    is_flag=True,
    help="Do not overwrite unscored log_files with the scored version (instead write a new file w/ '-scored' appended)",
)
@common_options
def score_command(
    task: str,
    log_file: str | None,
    no_overwrite: bool | None,
    **kwargs: Unpack[CommonOptions],
) -> None:
    """Score a previous evaluation run."""
    # read common options
    (log_dir, log_level, log_level_transcript) = resolve_common_options(kwargs)

    # score
    asyncio.run(
        score(
            task,
            log_dir,
            log_file,
            False if no_overwrite else True,
            log_level,
            log_level_transcript,
        )
    )


async def score(
    task: str,
    log_dir: str,
    log_file: str | None,
    overwrite: bool,
    log_level: str | None,
    log_level_transcript: str | None,
) -> None:
    # init eval context
    init_eval_context(None, log_level, log_level_transcript)

    # read the eval log
    recorder = JSONRecorder(log_dir)
    log_file = log_file if log_file else recorder.latest_log_file_path()
    eval_log = recorder.read_log(log_file)

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

    # instantiate the task so we can get its scorer and metrics
    score_task = load_tasks([task], model)[0]

    # re-score the task
    eval_log = await task_score(score_task, eval_log)

    # re-write the log (w/ a -score suffix if requested)
    scored = f"{SCORED_SUFFIX}.json"
    if not overwrite and not log_file.endswith(scored):
        log_file = log_file.removesuffix(".json") + scored
    recorder.write_log(log_file, eval_log)

    # print results
    display().print(f"\n{eval_log.eval.task}")
    if eval_log.results:
        for score in eval_log.results.scores:
            for name, metric in score.metrics.items():
                display().print(f"{name}: {metric.value}")
    display().print(f"log: {log_file}\n")
