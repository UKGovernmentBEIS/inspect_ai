import asyncio
from copy import deepcopy
from typing import Callable, cast

from inspect_ai._display import display
from inspect_ai._util.dotenv import dotenv_environ
from inspect_ai._util.path import chdir_python
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import (
    registry_create,
)
from inspect_ai.log import (
    EvalLog,
    EvalMetric,
)
from inspect_ai.model import ModelName
from inspect_ai.scorer import Metric, Score, Scorer, Target
from inspect_ai.solver import TaskState

from .task import Task
from .task.results import eval_results
from .task.util import task_run_dir


def score(log: EvalLog, scorer: Scorer) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorer (Scorer): Scorer to apply to log
       metrics: (list[Metric]): Additional metrics to compute
         (Scorer built-in metrics are always computed).

    Returns:
       Log with scores yielded by scorer.
    """
    # standard platform init for top level entry points
    platform_init()

    return asyncio.run(score_async(log, scorer))


async def score_async(log: EvalLog, scorer: Scorer) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorer (Scorer): Scorer to apply to log

    Returns:
       Log with scores yielded by scorer.
    """
    # deepcopy so we don't mutate the passed log
    log = deepcopy(log)

    # confirm we have samples
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("There are no samples to score in the log.")

    # prime the scoring tasks
    states = [
        TaskState(
            model=ModelName(log.eval.model),
            sample_id=sample.id,
            epoch=sample.epoch,
            input=sample.input,
            choices=sample.choices,
            messages=sample.messages,
            output=sample.output,
            completed=True,
            metadata=sample.metadata,
        )
        for sample in log.samples
    ]
    with display().progress(total=len(states)) as p:

        def progress() -> None:
            p.update(1)

        tasks = [
            run_score_task(state, Target(sample.target), scorer, progress)
            for (sample, state) in zip(log.samples, states)
        ]

        # do scoring
        scores = await asyncio.gather(*tasks)

        # write them back (gather ensures that they come back in the same order)
        for index, score in enumerate(scores):
            log.samples[index].score = score

        # collect metrics from EvalLog (they may overlap w/ the scorer metrics,
        # that will be taken care of in eval_results)
        log_metrics = metrics_from_log(log)

        # compute metrics
        log.results = eval_results(scores, scorer, log_metrics)

    return log


async def task_score(task: Task, log: EvalLog) -> EvalLog:
    with chdir_python(task_run_dir(task)), dotenv_environ():
        # confirm we have a scorer
        if task.scorer is None:
            raise ValueError("You must specify a scorer for evals to be scored.")

        # confirm we have samples
        if log.samples is None or len(log.samples) == 0:
            raise ValueError("There are no samples to score in the log.")

        task_name = task.name
        display().print(f"Scoring {len(log.samples)} samples for task: {task_name}")

        # perform scoring
        log = await score_async(log, task.scorer)

    # compute and log metrics
    display().print(f"Aggregating scores for task: {task_name}")
    if task.scorer and log.samples:
        log.results = eval_results(
            [sample.score for sample in log.samples if isinstance(sample.score, Score)],
            task.scorer,
            task.metrics,
        )
    return log


async def run_score_task(
    state: TaskState,
    target: Target,
    scorer: Scorer,
    progress: Callable[..., None],
) -> Score:
    result = await scorer(state, target)
    progress()
    return result


def metrics_from_log(log: EvalLog) -> list[Metric]:
    return (
        [metric_from_log(metric) for metric in log.results.metrics.values()]
        if log.results
        else []
    )


def metric_from_log(metric: EvalMetric) -> Metric:
    return cast(Metric, registry_create("metric", metric.name, **metric.options))
