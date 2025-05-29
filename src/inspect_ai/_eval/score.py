import functools
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Literal

import anyio

from inspect_ai._display import display
from inspect_ai._eval.context import init_task_context
from inspect_ai._eval.loader import scorer_from_spec
from inspect_ai._util._async import configured_async_backend, run_coroutine, tg_collect
from inspect_ai._util.platform import platform_init, running_in_notebook
from inspect_ai._util.registry import registry_create, registry_unqualified_name
from inspect_ai.log import (
    EvalLog,
)
from inspect_ai.log._log import EvalMetricDefinition
from inspect_ai.log._model import model_roles_config_to_model_roles
from inspect_ai.model import ModelName
from inspect_ai.model._model import get_model
from inspect_ai.scorer import Metric, Scorer, Target
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._reducer import (
    ScoreReducer,
    ScoreReducers,
    create_reducers,
    reducer_log_names,
)
from inspect_ai.scorer._scorer import ScorerSpec, unique_scorer_name
from inspect_ai.solver import TaskState

from .task.results import eval_results

ScoreAction = Literal["append", "overwrite"]


def score(
    log: EvalLog,
    scorers: Scorer | list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (Scorer): List of Scorers to apply to log
       epochs_reducer (ScoreReducers | None):
           Reducer function(s) for aggregating scores in each sample.
           Defaults to previously used reducer(s).
       action: Whether to append or overwrite this score

    Returns:
       Log with scores yielded by scorer.
    """
    # standard platform init for top level entry points
    platform_init()

    # resolve scorers into a list
    scorers = [scorers] if isinstance(scorers, Scorer) else scorers

    if running_in_notebook():
        return run_coroutine(score_async(log, scorers, epochs_reducer, action))
    else:
        return anyio.run(
            score_async,
            log,
            scorers,
            epochs_reducer,
            action,
            backend=configured_async_backend(),
        )


async def score_async(
    log: EvalLog,
    scorers: list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (list[Scorer]): Scorers to apply to log
       epochs_reducer (ScoreReducers  | None):
         Reducer function(s) for aggregating scores in each sample.
         Defaults to previously used reducer(s).
       action: Whether to append or overwrite this score



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

        # do scoring
        scores: list[dict[str, SampleScore]] = await tg_collect(
            [
                functools.partial(
                    run_score_task, log, state, Target(sample.target), scorers, progress
                )
                for (sample, state) in zip(log.samples, states)
            ]
        )

        # write them back (gather ensures that they come back in the same order)
        for index, score in enumerate(scores):
            if action == "overwrite":
                log.samples[index].scores = {k: v.score for k, v in score.items()}
            else:
                existing_scores = log.samples[index].scores or {}
                new_scores = {k: v.score for k, v in score.items()}

                for key, value in new_scores.items():
                    if key not in existing_scores:
                        existing_scores[key] = value
                    else:
                        # This key already exists, dedupe its name
                        count = 1
                        while f"{key}-{count}" in existing_scores.keys():
                            count = count + 1
                        existing_scores[f"{key}-{count}"] = value
                log.samples[index].scores = existing_scores

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


async def task_score(
    log: EvalLog,
    scorer: str | None = None,
    scorer_args: dict[str, Any] | None = None,
    action: ScoreAction | None = None,
) -> EvalLog:
    # confirm we have a scorer
    scorers = resolve_scorers(log, scorer, scorer_args)
    if len(scorers) == 0:
        raise ValueError(
            "Unable to resolve any scorers for this log. Please specify a scorer using the '--scorer' param."
        )

    # confirm we have samples
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("There are no samples to score in the log.")

    task_name = log.eval.task
    display().print(f"\nScoring {task_name} ({len(log.samples)} samples)")

    # perform scoring
    log = await score_async(log=log, scorers=scorers, action=action)

    # compute and log metrics
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
    log: EvalLog,
    state: TaskState,
    target: Target,
    scorers: list[Scorer],
    progress: Callable[..., None],
) -> dict[str, SampleScore]:
    # get the model then initialize the async context
    model = get_model(
        model=log.eval.model,
        config=log.plan.config.merge(log.eval.model_generate_config),
        **log.eval.model_args,
    )

    # get the model roles
    model_roles = model_roles_config_to_model_roles(log.eval.model_roles)

    # initialize active model
    init_task_context(model, model_roles)

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
    return registry_create("metric", metric.name, **(metric.options or {}))


def reducers_from_log(log: EvalLog) -> list[ScoreReducer] | None:
    return create_reducers(log.eval.config.epochs_reducer)


def resolve_scorers(
    log: EvalLog, scorer: str | None, scorer_args: dict[str, Any] | None
) -> list[Scorer]:
    """
    Create a list of Scorer objects from an evaluation log.

    Args:
        log: EvalLog object containing evaluation configuration and results
        scorer:: Scorer name (simple name or file.py@name).
        scorer_args: Dictionary of scorer arguments

    Returns:
        list[Scorer]: List of initialized scorers
    """
    # resolve the scorer path
    task_path = Path(log.eval.task_file) if log.eval.task_file else None

    # If there is an explicit scorer
    if scorer:
        return [
            scorer_from_spec(
                spec=ScorerSpec(scorer=scorer),
                task_path=task_path,
                **(scorer_args or {}),
            )
        ]
    # See if we can create scorers from the eval itself
    elif log.eval.scorers is not None:
        return (
            [
                scorer_from_spec(
                    spec=ScorerSpec(scorer=score.name),
                    task_path=task_path,
                    **(score.options or {}),
                )
                for score in log.eval.scorers
            ]
            if log.results
            else []
        )

    # Otherwise, perhaps we can re-create them from the results
    return (
        [
            scorer_from_spec(
                spec=ScorerSpec(scorer=score.name), task_path=task_path, **score.params
            )
            for score in log.results.scores
        ]
        if log.results
        else []
    )
