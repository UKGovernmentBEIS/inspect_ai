import asyncio
import os
from typing import Literal

import click
from rich.prompt import Prompt
from typing_extensions import Unpack

from inspect_ai._cli.util import parse_cli_config
from inspect_ai._display import display
from inspect_ai._eval.context import init_eval_context, init_task_context
from inspect_ai._eval.score import task_score
from inspect_ai._util.file import basename, dirname, exists
from inspect_ai.log._log import EvalLog
from inspect_ai.log._recorders import create_recorder_for_location
from inspect_ai.model import get_model

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
    help="Overwrite log file with the scored version",
)
@common_options
def score_command(
    log_file: str,
    overwrite: bool | None,
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
            overwrite=False if overwrite is None else overwrite,
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
    output_file: str | None = None,
) -> None:
    # init eval context
    init_eval_context(log_level, None)
    scorer_args = parse_cli_config(args=s, config=None)

    # read the eval log
    recorder = create_recorder_for_location(log_file, log_dir)
    eval_log = await recorder.read_log(log_file)

    # resolve the target output file (prompts user)
    output_file = resolve_output_file(
        log_file, output_file=output_file, overwrite=overwrite
    )

    # resolve action
    action = resolve_action(eval_log, action)

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

    # re-write the log
    await recorder.write_log(output_file, eval_log)

    # print results
    display().print(f"\nResults for {eval_log.eval.task}")
    if eval_log.results:
        for score in eval_log.results.scores:
            display().print(f"{score.name}")
            for name, metric in score.metrics.items():
                display().print(f" - {name}: {metric.value}")
    display().print(f"\nLog file written to {output_file}\n")


def resolve_output_file(log_file: str, output_file: str | None, overwrite: bool) -> str:
    # resolve the output file (we may overwrite, use the passed file name, or suggest a new name)
    if output_file is None:
        if overwrite:
            # explicitly asked to overwrite
            return log_file
        else:
            if exists(log_file):
                # Ask if we should overwrite
                confirm = Prompt.ask(
                    f"Overwrite file {basename(log_file)}?",
                    choices=["yes", "no", "y", "n"],
                    default="no",
                )
                if confirm in ["yes", "y"]:
                    return log_file
                else:
                    file_name = basename(log_file)
                    base_dir = dirname(log_file)
                    _, ext = os.path.splitext(file_name)
                    count = 1
                    while exists(
                        f"{os.path.join(base_dir, f'{file_name.removesuffix(ext)}-{count}{ext}')}"
                    ):
                        count = count + 1

                    suggested_file = f"{file_name.removesuffix(ext)}-{count}{ext}"
                    user_file = Prompt.ask("Output file name?", default=suggested_file)
                    return os.path.join(base_dir, user_file)
            else:
                return log_file
    else:
        return output_file


def resolve_action(
    eval_log: EvalLog, action: Literal["append", "overwrite"] | None
) -> Literal["append", "overwrite"]:
    if action is not None:
        return action

    if eval_log.results is not None and len(eval_log.results.scores) > 0:
        user_action = Prompt.ask(
            f"The task {eval_log.eval.task} has already been scored. Would you like to overwrite these scores or append an additional score?",
            choices=["overwrite", "append", "o", "a"],
            default="append",
        )
        return "overwrite" if user_action in ["ovewrite", "o"] else "append"
    else:
        return "overwrite"
