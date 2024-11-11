import asyncio
from copy import deepcopy
from typing import Callable, cast

from inspect_ai._display import display
from inspect_ai._util.path import chdir_python
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_create
from inspect_ai.log import (
    EvalLog,
    EvalMetric,
)
from inspect_ai.model import ModelName
from inspect_ai.scorer import Metric, Score, Scorer, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._reducer import (
    ScoreReducer,
    ScoreReducers,
    create_reducers,
    reducer_log_names,
)
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import TaskState

from .task import Task
from .task.results import eval_results
from .task.util import task_run_dir


def score(
    log: EvalLog,
    scorers: Scorer | list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (Scorer): List of Scorers to apply to log
       epochs_reducer (ScoreReducers | None):
           Reducer function(s) for aggregating scores in each sample.
           Defaults to previously used reducer(s).

    Returns:
       Log with scores yielded by scorer.
    """
    # standard platform init for top level entry points
    platform_init()

    # resolve scorers into a list
    scorers = [scorers] if isinstance(scorers, Scorer) else scorers

    return asyncio.run(score_async(log, scorers, epochs_reducer))


async def score_async(
    log: EvalLog,
    scorers: list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (list[Scorer]): Scorers to apply to log
       epochs_reducer (ScoreReducers  | None):
         Reducer function(s) for aggregating scores in each sample.
         Defaults to previously used reducer(s).


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
            run_score_task(state, Target(sample.target), scorers, progress)
            for (sample, state) in zip(log.samples, states)
        ]

        # do scoring
        scores: list[dict[str, SampleScore]] = await asyncio.gather(*tasks)

        # write them back (gather ensures that they come back in the same order)
        for index, score in enumerate(scores):
            log.samples[index].scores = cast(dict[str, Score], score)

        # collect metrics from EvalLog (they may overlap w/ the scorer metrics,
        # that will be taken care of in eval_results)
        log_metrics = metrics_from_log(log)

        # override epochs_reducer if specified
        epochs_reducer = create_reducers(epochs_reducer)
        if epochs_reducer:
            log.eval.config.epochs_reducer = reducer_log_names(epochs_reducer)
        else:
            epochs_reducer = reducers_from_log(log)

        # compute metrics
        log.results, log.reductions = eval_results(
            len(log.samples), scores, epochs_reducer, scorers, log_metrics
        )

    return log


async def task_score(task: Task, log: EvalLog) -> EvalLog:
    with chdir_python(task_run_dir(task)):
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
        sample_scores = [
            {
                score_key: SampleScore(
                    sample_id=sample.id,
                    value=score.value,
                    answer=score.answer,
                    explanation=score.explanation,
                    metadata=score.metadata,
                )
                for score_key, score in sample.scores.items()
            }
            for sample in log.samples
            if sample.scores is not None
        ]

        log.results, log.reductions = eval_results(
            log.results.total_samples if log.results else 0,
            sample_scores,
            task.epochs_reducer,
            task.scorer,
            task.metrics,
        )
    return log


async def run_score_task(
    state: TaskState,
    target: Target,
    scorers: list[Scorer],
    progress: Callable[..., None],
) -> dict[str, SampleScore]:
    results: dict[str, SampleScore] = {}
    for scorer in scorers:
        result = await scorer(state, target)
        scorer_name = unique_scorer_name(scorer, list(results.keys()))

        results[scorer_name] = SampleScore(
            sample_id=state.sample_id,
            value=result.value,
            answer=result.answer,
            explanation=result.explanation,
            metadata=result.metadata,
        )

    progress()
    return results


def metrics_from_log(log: EvalLog) -> list[Metric]:
    return (
        [
            metric_from_log(metric)
            for score in log.results.scores
            for metric in score.metrics.values()
        ]
        if log.results
        else []
    )


def metric_from_log(metric: EvalMetric) -> Metric:
    return cast(Metric, registry_create("metric", metric.name, **metric.options))


def reducers_from_log(log: EvalLog) -> list[ScoreReducer] | None:
    return create_reducers(log.eval.config.epochs_reducer)
