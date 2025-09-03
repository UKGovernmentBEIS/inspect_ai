import functools
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Literal

import anyio

from inspect_ai._display import display as display_manager
from inspect_ai._eval.context import init_task_context
from inspect_ai._eval.loader import scorer_from_spec
from inspect_ai._util._async import configured_async_backend, run_coroutine, tg_collect
from inspect_ai._util.platform import platform_init, running_in_notebook
from inspect_ai._util.registry import registry_create, registry_unqualified_name
from inspect_ai.log import (
    EvalLog,
    ScoreEvent,
)
from inspect_ai.log._log import EvalMetricDefinition, EvalSample
from inspect_ai.log._model import model_roles_config_to_model_roles
from inspect_ai.log._transcript import Event, Transcript, init_transcript, transcript
from inspect_ai.log._tree import SpanNode, event_sequence, event_tree, walk_node_spans
from inspect_ai.model import ModelName
from inspect_ai.model._model import get_model
from inspect_ai.scorer import Metric, Scorer, Target
from inspect_ai.scorer._metric import SampleScore, Score
from inspect_ai.scorer._reducer import (
    ScoreReducer,
    ScoreReducers,
    create_reducers,
    reducer_log_names,
)
from inspect_ai.scorer._scorer import ScorerSpec, unique_scorer_name
from inspect_ai.solver import TaskState
from inspect_ai.util._display import (
    DisplayType,
    display_type_initialized,
    init_display_type,
)
from inspect_ai.util._span import span
from inspect_ai.util._store import init_subtask_store

from .task.results import eval_results

ScoreAction = Literal["append", "overwrite"]


def score(
    log: EvalLog,
    scorers: Scorer | list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (Scorer): List of Scorers to apply to log
       epochs_reducer (ScoreReducers | None):
           Reducer function(s) for aggregating scores in each sample.
           Defaults to previously used reducer(s).
       action: Whether to append or overwrite this score
       display: Progress/status display
       copy: Whether to deepcopy the log before scoring.

    Returns:
       Log with scores yielded by scorer.
    """
    # standard platform init for top level entry points
    platform_init()

    # initialize display type
    init_display_type(display)

    # resolve scorers into a list
    scorers = [scorers] if isinstance(scorers, Scorer) else scorers

    if running_in_notebook():
        return run_coroutine(
            score_async(log, scorers, epochs_reducer, action, copy=copy)
        )
    else:
        return anyio.run(
            functools.partial(score_async, copy=copy),
            log,
            scorers,
            epochs_reducer,
            action,
            backend=configured_async_backend(),
        )


def _get_updated_scores(
    sample: EvalSample, scores: dict[str, SampleScore], action: ScoreAction
) -> dict[str, Score]:
    if action == "overwrite":
        return {k: v.score for k, v in scores.items()}

    updated_scores: dict[str, Score] = {**(sample.scores or {})}
    for key, score in scores.items():
        new_key = key
        count = 0
        while new_key in updated_scores:
            # This key already exists, dedupe its name
            count = count + 1
            new_key = f"{key}-{count}"

        updated_scores[new_key] = score.score

    return updated_scores


def _get_updated_events(
    sample: EvalSample, transcript: Transcript, action: ScoreAction
) -> list[Event]:
    final_scorers_node: SpanNode | None = None
    sample_event_tree = event_tree(sample.events)
    for node in walk_node_spans(sample_event_tree):
        if node.type == "scorers" and node.name == "scorers":
            final_scorers_node = node

    if final_scorers_node is None:
        return [*sample.events, *transcript.events]

    (new_scorers_tree,) = event_tree(transcript.events)
    assert isinstance(new_scorers_tree, SpanNode)
    if action == "append":
        # Add the new score nodes to the existing scorer node's children
        for child in new_scorers_tree.children:
            if isinstance(child, SpanNode):
                child.parent_id = final_scorers_node.id
        final_scorers_node.children.extend(new_scorers_tree.children)
    else:
        # Entirely replace the existing scorer node and its children, which will
        # also mean updating the timestamps associated with the scorers span
        if final_scorers_node.parent_id is None:
            siblings = sample_event_tree
        else:
            scorer_insert_point = None
            for node in walk_node_spans(sample_event_tree):
                if node.id == final_scorers_node.parent_id:
                    scorer_insert_point = node
                    break

            assert scorer_insert_point is not None
            siblings = scorer_insert_point.children

        idx_scorer_event = siblings.index(final_scorers_node)
        siblings[idx_scorer_event] = new_scorers_tree
        new_scorers_tree.parent_id = final_scorers_node.parent_id
    return list(event_sequence(sample_event_tree))


async def score_async(
    log: EvalLog,
    scorers: list[Scorer],
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (list[Scorer]): Scorers to apply to log
       epochs_reducer (ScoreReducers  | None):
         Reducer function(s) for aggregating scores in each sample.
         Defaults to previously used reducer(s).
       action: Whether to append or overwrite this score
       display: Progress/status display
       copy: Whether to deepcopy the log before scoring.

    Returns:
       Log with scores yielded by scorer.
    """
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("There are no samples to score in the log.")

    if not display_type_initialized():
        init_display_type(display or "plain")

    if copy:
        # deepcopy so we don't mutate the passed log
        log = deepcopy(log)

    assert (
        log.samples is not None  # make the type checker happy after re-assignment above
    )

    # prime the scoring tasks
    action = action or "append"
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
            store=sample.store,
            scores=(sample.scores or {}).copy() if action == "append" else {},
        )
        for sample in log.samples
    ]
    with display_manager().progress(total=len(states)) as p:

        def progress() -> None:
            p.update(1)

        # do scoring
        scores_and_events: list[
            tuple[dict[str, SampleScore], Transcript]
        ] = await tg_collect(
            [
                functools.partial(
                    run_score_task, log, state, Target(sample.target), scorers, progress
                )
                for (sample, state) in zip(log.samples, states)
            ]
        )

        # write them back (gather ensures that they come back in the same order)
        for idx_sample, (scores, transcript) in enumerate(scores_and_events):
            sample = log.samples[idx_sample]
            sample.scores = _get_updated_scores(sample, scores, action=action)
            sample.events = _get_updated_events(sample, transcript, action=action)

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
            len(log.samples),
            [
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
            ],
            epochs_reducer,
            scorers,
            log_metrics,
        )

    return log


async def run_score_task(
    log: EvalLog,
    state: TaskState,
    target: Target,
    scorers: list[Scorer],
    progress: Callable[..., None],
) -> tuple[dict[str, SampleScore], Transcript]:
    # get the model then initialize the async context
    model = get_model(
        model=log.eval.model,
        config=log.plan.config.merge(log.eval.model_generate_config),
        **log.eval.model_args,
    )

    # get the model roles
    model_roles = model_roles_config_to_model_roles(log.eval.model_roles)

    # initialize active model and store
    init_task_context(model, model_roles)
    init_subtask_store(state.store)
    init_transcript(Transcript())

    if state.scores is None:
        state.scores = {}
    existing_score_names = [*state.scores]

    results: dict[str, SampleScore] = {}
    async with span(name="scorers"):
        for scorer in scorers:
            scorer_name = unique_scorer_name(
                scorer, list({*existing_score_names, *results})
            )
            async with span(name=scorer_name, type="scorer"):
                score_result = await scorer(state, target)
                if scorer_name in state.scores:
                    raise RuntimeError(
                        f"Scorer {scorer_name} has modified state.scores"
                    )
                state.scores[scorer_name] = score_result

                transcript()._event(
                    ScoreEvent(
                        score=score_result,
                        target=target.target,
                    )
                )

                results[scorer_name] = SampleScore(
                    score=score_result,
                    sample_id=state.sample_id,
                    sample_metadata=state.metadata,
                    scorer=registry_unqualified_name(scorer),
                )

    progress()
    return results, transcript()


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
