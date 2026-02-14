from __future__ import annotations

import contextlib
import functools
from copy import deepcopy
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    AsyncGenerator,
    Callable,
    Literal,
    Sequence,
    Tuple,
)

if TYPE_CHECKING:
    from inspect_ai.scorer._scorers import Scorers

import anyio

from inspect_ai._display import display as display_manager
from inspect_ai._eval.context import init_task_context
from inspect_ai._eval.loader import scorer_from_spec
from inspect_ai._eval.task.task import resolve_scorer, resolve_scorer_metrics
from inspect_ai._util._async import configured_async_backend, run_coroutine, tg_collect
from inspect_ai._util.platform import platform_init, running_in_notebook
from inspect_ai._util.registry import registry_create, registry_unqualified_name
from inspect_ai.event._event import Event
from inspect_ai.event._score import ScoreEvent
from inspect_ai.event._tree import (
    EventTreeSpan,
    event_sequence,
    event_tree,
    walk_node_spans,
)
from inspect_ai.log import (
    EvalLog,
)
from inspect_ai.log._log import EvalMetricDefinition, EvalSample
from inspect_ai.log._score import _find_scorers_span
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ModelName
from inspect_ai.model._model import get_model
from inspect_ai.model._model_config import model_roles_config_to_model_roles
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
    scorers: "Scorers",
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
    sample: EvalSample, new_events: Sequence[Event], action: ScoreAction
) -> list[Event]:
    sample_event_tree = event_tree(sample.events)
    final_scorers_node = _find_scorers_span(sample_event_tree)

    if final_scorers_node is None:
        return [*sample.events, *new_events]

    (new_scorers_tree,) = event_tree(new_events)
    assert isinstance(new_scorers_tree, EventTreeSpan)
    if action == "append":
        # Add the new score nodes to the existing scorer node's children
        for child in new_scorers_tree.children:
            if isinstance(child, EventTreeSpan):
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
    scorers: "Scorers",
    epochs_reducer: ScoreReducers | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
    samples: Callable[[int], AsyncContextManager[EvalSample]] | None = None,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog):
         Evaluation log. Only the headers are needed if `samples`
         is passed as well.
       scorers (list[Scorer]): Scorers to apply to log
       epochs_reducer (ScoreReducers  | None):
         Reducer function(s) for aggregating scores in each sample.
         Defaults to previously used reducer(s).
       action: Whether to append or overwrite this score
       display: Progress/status display
       copy: Whether to deepcopy the log before scoring.
       samples:
         Function to read samples from the log, which accepts the
         sample index and async yields an EvalSample. Can be used to
         stream samples without loading the entire log into memory.

    Returns:
       Log with scores yielded by scorer.
    """
    if samples is None and log.samples is None:
        raise ValueError("There are no samples to score in the log.")

    # resolve scorers
    resolved_scorers = resolve_scorer(scorers)

    if copy:
        # deepcopy so we don't mutate the passed log
        log = deepcopy(log)

    total_samples: int | None = None
    if samples is None:
        _samples = log.samples
        assert _samples is not None

        @contextlib.asynccontextmanager
        async def _read_sample(idx_sample: int) -> AsyncGenerator[EvalSample, None]:
            yield _samples[idx_sample]

        samples = _read_sample
        total_samples = len(_samples)
    else:
        total_samples = log.results.total_samples if log.results else None

    assert total_samples is not None

    if not display_type_initialized():
        init_display_type(display or "plain")

    # prime the scoring tasks
    action = action or "append"

    with display_manager().progress(total=total_samples) as p:
        scorer_names: list[str] | None = None
        scores: list[dict[str, SampleScore] | None] = [None] * total_samples

        async def _score_sample(idx_sample: int) -> None:
            nonlocal scorer_names
            sample_score: dict[str, SampleScore] = {}

            async with samples(idx_sample) as sample:
                # run the task, capturing the resulting sample scores
                # and sample names for later use. The sample scores
                # returned here are only the _newly created_ scores
                # which means that metrics below are being computed
                # only for the new scores (not all scores on the sample)
                #
                # We need to capture the the full sample score here
                # since the sample score carries the scorer name that generated
                # it (so using sample.scores directly isn't enough)
                sample_score, names = await _run_score_task(
                    log, sample, resolved_scorers, action
                )

            assert sample.scores is not None
            scores[idx_sample] = sample_score
            if scorer_names is None:
                scorer_names = names
            p.update(1)

        await tg_collect(
            (
                functools.partial(_score_sample, idx_sample)
                for idx_sample in range(total_samples)
            )
        )

        # collect metrics from EvalLog (they may overlap w/ the scorer metrics,
        # that will be taken care of in eval_results)
        log_metrics = metrics_from_log_header(log)

        # resolve the scorer metrics onto the scorers
        resolved_scorers = resolve_scorer_metrics(resolved_scorers, log_metrics) or []

        # override epochs_reducer if specified
        epochs_reducer = create_reducers(epochs_reducer)
        if epochs_reducer is not None:
            log.eval.config.epochs_reducer = reducer_log_names(epochs_reducer)
        else:
            epochs_reducer = reducers_from_log_header(log)

        # compute metrics
        results, reductions = eval_results(
            total_samples,
            list(filter(None, scores)),
            epochs_reducer,
            resolved_scorers,
            log_metrics,
            scorer_names,
            log.results.early_stopping if log.results else None,
        )

        # Since the metrics calculation above is only be done using the scorers
        # and scores that were generated during this scoring run, we need to process
        # the results carefully, depending upon whether the action was "append" or "overwrite"
        log.reductions = reductions
        if action == "overwrite" or log.results is None:
            # Completely replace the results with the new results
            log.results = results
        else:
            # Only update the results with the new scores, leaving the rest
            # of the results as they were
            log.results.scores.extend(results.scores)

    return log


async def _run_score_task(
    log_header: EvalLog,
    sample: EvalSample,
    scorers: list[Scorer],
    action: ScoreAction,
) -> Tuple[dict[str, SampleScore], list[str]]:
    target = Target(sample.target)
    state = TaskState(
        model=ModelName(log_header.eval.model),
        sample_id=sample.id,
        epoch=sample.epoch,
        input=sample.input,
        target=target,
        choices=sample.choices,
        messages=sample.messages,
        output=sample.output,
        completed=True,
        metadata=sample.metadata,
        store=sample.store,
        scores=(sample.scores or {}).copy() if action == "append" else {},
        sample_uuid=sample.uuid,
    )

    # get the model then initialize the async context
    model = get_model(
        model=log_header.eval.model,
        config=log_header.plan.config.merge(log_header.eval.model_generate_config),
        **log_header.eval.model_args,
    )

    # get the model roles
    model_roles = model_roles_config_to_model_roles(log_header.eval.model_roles)

    # initialize active model and store
    init_task_context(model, model_roles)
    init_subtask_store(state.store)

    # load a copy of the current sample events into the transcript
    init_transcript(Transcript([*sample.events]))

    if state.scores is None:
        state.scores = {}
    existing_score_names = [*state.scores]

    results: dict[str, SampleScore] = {}
    scorer_names: list[str] = []
    async with span(name="scorers"):
        for scorer in scorers:
            scorer_name = unique_scorer_name(
                scorer, list({*existing_score_names, *results})
            )
            scorer_names.append(scorer_name)
            async with span(name=scorer_name, type="scorer"):
                score_result = await scorer(state, target)
                if scorer_name in state.scores:
                    raise RuntimeError(
                        f"Scorer {scorer_name} has modified state.scores"
                    )
                if score_result is not None:
                    state.scores[scorer_name] = score_result

                    transcript()._event(
                        ScoreEvent(
                            score=score_result,
                            target=target.target,
                            model_usage=sample.model_usage or None,
                        )
                    )

                    results[scorer_name] = SampleScore(
                        score=score_result,
                        sample_id=state.sample_id,
                        sample_metadata=state.metadata,
                        scorer=registry_unqualified_name(scorer),
                    )

    # slice off only the newly added events
    new_events = transcript().events[len(sample.events) :]

    sample.scores = _get_updated_scores(sample, results, action=action)
    sample.events = _get_updated_events(sample, new_events, action=action)

    # return the actual sample scorers and scorer names that
    # were used to generate this set of scores
    return results, scorer_names


def metrics_from_log_header(
    log: EvalLog,
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None:
    # See if we have metrics in the eval itself
    if log.eval.metrics:
        if isinstance(log.eval.metrics, list):
            result: list[Metric | dict[str, list[Metric]]] = []
            for metric_item in log.eval.metrics:
                if isinstance(metric_item, dict):
                    # It's a dict of metric groups
                    result.append(
                        {
                            key: [metric_from_log(metric) for metric in metrics]
                            for key, metrics in metric_item.items()
                        }
                    )
                else:
                    # It's a direct metric
                    result.append(metric_from_log(metric_item))
            return result
        else:
            return {
                key: [metric_from_log(metric) for metric in metrics]
                for key, metrics in log.eval.metrics.items()
            }
    return None


def metric_from_log(metric: EvalMetricDefinition) -> Metric:
    return registry_create("metric", metric.name, **(metric.options or {}))


def reducers_from_log_header(log: EvalLog) -> list[ScoreReducer] | None:
    return create_reducers(log.eval.config.epochs_reducer)


def resolve_scorers(
    log: EvalLog, scorer: str | None = None, scorer_args: dict[str, Any] | None = None
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
