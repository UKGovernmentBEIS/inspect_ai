import asyncio
import inspect
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, cast

from inspect_ai._display import display
from inspect_ai._eval.loader import load_module
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.platform import platform_init
from inspect_ai._util.registry import registry_create, registry_unqualified_name
from inspect_ai.log import (
    EvalLog,
)
from inspect_ai.log._log import EvalMetricDefinition
from inspect_ai.model import ModelName
from inspect_ai.scorer import Metric, Scorer, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._reducer import (
    ScoreReducer,
    ScoreReducers,
    create_reducers,
    reducer_log_names,
)
from inspect_ai.scorer._scorer import scorer_create, unique_scorer_name
from inspect_ai.solver import TaskState

from .task.results import eval_results


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
            target=Target(sample.target),
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
            log.samples[index].scores = {k: v.score for k, v in score.items()}

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


async def task_score(log: EvalLog) -> EvalLog:
    ## TODO: Why would we need to change the run dir when scoring?

    # confirm we have a scorer
    scorers = scorers_from_log(log)
    if len(scorers) == 0:
        raise ValueError("You must specify a scorer for evals to be scored.")

    # confirm we have samples
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("There are no samples to score in the log.")

    task_name = log.eval.task
    display().print(f"Scoring {len(log.samples)} samples for task: {task_name}")

    # perform scoring
    log = await score_async(log, scorers)

    # compute and log metrics
    display().print(f"Aggregating scores for task: {task_name}")
    if log.samples:
        sample_scores = [
            {
                score_key: SampleScore(
                    score=score,
                    sample_id=sample.id,
                    sample_metadata=sample.metadata,
                )
                for score_key, score in sample.scores.items()
            }
            for sample in log.samples
            if sample.scores is not None
        ]

        epochs_reducer = reducers_from_log(log)
        metrics = metrics_from_log(log)

        log.results, log.reductions = eval_results(
            log.results.total_samples if log.results else 0,
            sample_scores,
            epochs_reducer,
            scorers,
            metrics,
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
            score=result,
            sample_id=state.sample_id,
            sample_metadata=state.metadata,
            scorer=registry_unqualified_name(scorer),
        )

    progress()
    return results


def metrics_from_log(log: EvalLog) -> list[Metric] | dict[str, list[Metric]] | None:
    # See if we have metrics in the eval itself
    if log.eval.metrics:
        if isinstance(log.eval.metrics, list):
            return [metric_from_log(metric) for metric in log.eval.metrics]
        else:
            return {
                key: [metric_from_log(metric) for metric in metrics]
                for key, metrics in log.eval.metrics.items()
            }
    return None


def metric_from_log(metric: EvalMetricDefinition) -> Metric:
    return cast(
        Metric, registry_create("metric", metric.name, **(metric.options or {}))
    )


def reducers_from_log(log: EvalLog) -> list[ScoreReducer] | None:
    return create_reducers(log.eval.config.epochs_reducer)


def scorers_from_log(log: EvalLog) -> list[Scorer]:
    """
    Create a list of Scorer objects from an evaluation log.

    Args:
        log: EvalLog object containing evaluation configuration and results

    Returns:
        list[Scorer]: List of initialized scorers
    """
    # resolve the scorer path
    scorer_path = Path(log.eval.task_file) if log.eval.task_file else None

    # See if we can create scorers from the eval itself
    if log.eval.scorers is not None:
        return (
            [
                load_scorer(
                    scorer=score.name, scorer_path=scorer_path, **(score.options or {})
                )
                for score in log.eval.scorers
            ]
            if log.results
            else []
        )

    # Otherwise, perhaps we can re-create them from the results
    return (
        [
            load_scorer(scorer=score.name, scorer_path=scorer_path, **score.params)
            for score in log.results.scores
        ]
        if log.results
        else []
    )


def load_scorer(scorer: str, scorer_path: Path | None = None, **kwargs: Any) -> Scorer:
    """
    Load a scorer

    Args:
        scorer: The scorer name
        scorer_path: An optional path to a scorer file
        **kwargs: Additional keyword arguments passed to the scorer initialization

    Returns:
        Scorer: the loaded scorer

    Raises:
        PrerequisiteError: If the scorer cannot be found, loaded, or lacks required type annotations
    """
    try:
        # try loading directly from the registry
        return scorer_create(scorer, **kwargs)
    except ValueError:
        # We need a valid path to a scorer file to try to load the scorer from there
        if not scorer_path:
            raise PrerequisiteError(
                f"The scorer '{scorer}' couldn't be loaded. Please provide a path to the file containing the scorer using the '--scorer' parameter"
            )

        if not scorer_path.exists():
            raise PrerequisiteError(
                f"The scorer `{scorer}` couldn't be loaded. The file '{scorer_path}' was not found. Please provide a path to the file containing the scorer using the '--scorer' parameter"
            )

        # We have the path to a file, so load that and try again
        try:
            load_module(scorer_path)
            scorer_fn = scorer_create(scorer, **kwargs)

            # See if the scorer doesn't have type annotations. Currently the registry will not load
            # the function without type annotations.
            # TODO: We could consider calling this ourselves if we're certain it is what we're looking for
            signature = inspect.signature(scorer_fn)
            if signature.return_annotation is inspect.Signature.empty:
                raise PrerequisiteError(
                    f"The scorer '{scorer}' in the file '{scorer_path}' requires return type annotations. Please add type annotations to load the scorer."
                )
            return scorer_fn
        except ValueError:
            # we still couldn't load this, request the user provide a path
            raise PrerequisiteError(
                f"The scorer {scorer} in the file '{scorer_path}' couldn't be loaded. Please provide a path to the file containing the scorer using the '--scorer' parameter."
            )
