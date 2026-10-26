from __future__ import annotations

import contextlib
import functools
import logging
from copy import deepcopy
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    AsyncGenerator,
    Callable,
    Iterable,
    Literal,
    NamedTuple,
    Sequence,
    Tuple,
    cast,
)

if TYPE_CHECKING:
    from inspect_ai.scorer._scorers import Scorers

import anyio

from inspect_ai._display import display as display_manager
from inspect_ai._eval.context import init_task_context
from inspect_ai._eval.loader import load_file_tasks, scorer_from_spec
from inspect_ai._eval.task.task import resolve_scorer, resolve_scorer_metrics
from inspect_ai._sentinel._scope import sentinel_scope
from inspect_ai._util._async import configured_async_backend, run_coroutine, tg_collect
from inspect_ai._util.platform import platform_init, running_in_notebook
from inspect_ai._util.registry import (
    LOG_METRIC_OPTION_TYPES,
    DisallowedRegistryArg,
    RegistryNameNotFound,
    create_registry_object,
    has_registry_params,
    is_model_dict,
    is_registry_dict,
    registry_lookup,
    registry_params,
    registry_unqualified_name,
)
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
from inspect_ai.log._condense import resolve_sample_attachments
from inspect_ai.log._headline import headline_metric_ref, resolve_headline_metric
from inspect_ai.log._log import EvalMetricDefinition, EvalSample
from inspect_ai.log._resolve import rebind_sample_timelines
from inspect_ai.log._score import _find_scorers_span
from inspect_ai.log._transcript import Transcript, init_transcript, transcript
from inspect_ai.model import ModelName
from inspect_ai.model._model import Model, ModelRoles, get_model
from inspect_ai.model._model_config import model_roles_config_to_model_roles
from inspect_ai.model._util import resolve_model_roles
from inspect_ai.scorer import Metric, Scorer, Target
from inspect_ai.scorer._metric import SampleScore, Score
from inspect_ai.scorer._reducer import (
    ScoreReducer,
    ScoreReducers,
    create_reducers,
    reducer_log_names,
)
from inspect_ai.scorer._scorer import ScorerSpec, as_scorer_spec, unique_scorer_name
from inspect_ai.solver import TaskState
from inspect_ai.util._display import (
    DisplayType,
    display_type_initialized,
    init_display_type,
)
from inspect_ai.util._span import SCORER_SPAN_TYPE, SCORERS_SPAN_NAME, span
from inspect_ai.util._store import init_subtask_store

from .task.log import resolve_eval_scorers
from .task.results import ScorerInfo, eval_results

logger = logging.getLogger(__name__)

ScoreAction = Literal["append", "overwrite"]


def score(
    log: EvalLog,
    scorers: "Scorers",
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None = None,
    epochs_reducer: ScoreReducers | None = None,
    model: str | Model | None = None,
    model_roles: ModelRoles | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog): Evaluation log.
       scorers (Scorer): List of Scorers to apply to log
       metrics (list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None):
           Alternative metrics (overrides the metrics provided by the
           specified scorer and log).
       epochs_reducer (ScoreReducers | None):
           Reducer function(s) for aggregating scores in each sample.
           Defaults to previously used reducer(s).
       model: Optional. Model used for re-scoring (replaces the primary
           model reconstructed from the log header).
       model_roles: Optional. Named model roles used for re-scoring
           (merged over the model roles reconstructed from the log header).
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
            score_async(
                log,
                scorers,
                metrics,
                epochs_reducer,
                model=model,
                model_roles=model_roles,
                action=action,
                copy=copy,
            )
        )
    else:
        return anyio.run(
            functools.partial(
                score_async,
                model=model,
                model_roles=model_roles,
                action=action,
                copy=copy,
            ),
            log,
            scorers,
            metrics,
            epochs_reducer,
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
    metrics: list[Metric | dict[str, list[Metric]]]
    | dict[str, list[Metric]]
    | None = None,
    epochs_reducer: ScoreReducers | None = None,
    model: str | Model | None = None,
    model_roles: ModelRoles | None = None,
    action: ScoreAction | None = None,
    display: DisplayType | None = None,
    copy: bool = True,
    samples: Callable[[int], AsyncContextManager[EvalSample]] | None = None,
    *,
    _log_scorers: bool = False,
) -> EvalLog:
    """Score an evaluation log.

    Args:
       log (EvalLog):
         Evaluation log. Only the headers are needed if `samples`
         is passed as well.
       scorers (list[Scorer]): Scorers to apply to log
       metrics (list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None):
         Alternative metrics (overrides the metrics provided by the
         specified scorer and log).
       epochs_reducer (ScoreReducers  | None):
         Reducer function(s) for aggregating scores in each sample.
         Defaults to previously used reducer(s).
       model: Optional. Model used for re-scoring (replaces the primary
         model reconstructed from the log header).
       model_roles: Optional. Named model roles used for re-scoring
         (merged over the model roles reconstructed from the log header).
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

    # resolve the active model and model_roles for the scoring task context.
    # caller-supplied overrides win; otherwise reconstruct from the log header
    active_model = (
        model
        if isinstance(model, Model)
        else get_model(model)
        if model is not None
        else get_model(
            model=log.eval.model,
            config=log.plan.config.merge(log.eval.model_generate_config),
            base_url=log.eval.model_base_url,
            **log.eval.model_args,
        )
    )
    log_roles = model_roles_config_to_model_roles(log.eval.model_roles) or {}
    active_roles = {**log_roles, **(resolve_model_roles(model_roles) or {})}

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

    # collect metrics from EvalLog (they may overlap w/ the scorer metrics,
    # that will be taken care of in eval_results). For append, the new scorer
    # uses its own metrics -- the original eval's metrics are already baked
    # into log.results.scores and don't need to be recreated. Resolved before
    # scoring so that a metric that can't be rebuilt fails before any scorer
    # runs. The log is trusted only when its own scorers are being run.
    log_metrics = metrics or (
        metrics_from_log_header(
            log,
            task_import=LogTaskFileImport(log, trust_log=True, import_task_file=False)
            if _log_scorers
            else LogTaskFileImport(log, trust_log=False, opt_in=SCORE_OPT_IN),
        )
        if action != "append"
        else None
    )

    with display_manager().progress(total=total_samples) as p:
        scorer_names: list[str] | None = None
        scores: list[dict[str, SampleScore] | None] = [None] * total_samples
        # tally the per-sample error state as we go so an overwrite can restate
        # completed_samples exactly rather than falling back to len(scores)
        sample_completed: list[bool] = [False] * total_samples

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
                    log, sample, resolved_scorers, active_model, active_roles, action
                )

            assert sample.scores is not None
            scores[idx_sample] = sample_score
            sample_completed[idx_sample] = sample.error is None
            if scorer_names is None:
                scorer_names = names
            p.update(1)

        await tg_collect(
            (
                functools.partial(_score_sample, idx_sample)
                for idx_sample in range(total_samples)
            )
        )

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
            early_stopping=log.results.early_stopping if log.results else None,
            metadata=log.results.metadata if log.results else None,
            # eval-set completeness contract (see EvalResults.logged_samples):
            # rescoring must not make a drained log read complete
            logged_samples=log.results.logged_samples if log.results else None,
            completed_samples=sum(sample_completed),
            # resolved below instead: these results cover only the scorers run
            # in this pass, so an "append" would resolve the headline against a
            # partial score list
            headline_metric=None,
        )

        # Update log.eval.scorers to reflect the scorers actually applied so
        # that subsequent recompute_metrics() (which derives ScorerInfo from
        # this header list) operates on the right entries.
        applied_eval_scorers = (
            resolve_eval_scorers([as_scorer_spec(s) for s in resolved_scorers]) or []
        )

        # Since the metrics calculation above is only be done using the scorers
        # and scores that were generated during this scoring run, we need to process
        # the results carefully, depending upon whether the action was "append" or "overwrite"
        if action == "overwrite" or log.results is None:
            # Completely replace the results (and reductions) with the new ones
            log.reductions = reductions
            log.results = results
            log.eval.scorers = applied_eval_scorers
        else:
            # Only update the results with the new scores, leaving the rest
            # of the results as they were. The reductions computed here cover
            # just the scorers run in this pass, so append them to the existing
            # ones instead of overwriting -- otherwise every pre-existing
            # scorer's reductions would be silently dropped.
            if reductions is not None:
                log.reductions = (log.reductions or []) + reductions
            log.results.scores.extend(results.scores)
            log.eval.scorers = (log.eval.scorers or []) + applied_eval_scorers

        resolved_headline = resolve_headline_metric(
            log.results, log.eval.headline_metric
        )
        log.results.headline = (
            headline_metric_ref(resolved_headline) if resolved_headline else None
        )

    return log


class SampleTaskState(NamedTuple):
    """A ``TaskState`` rebuilt from a serialized sample, ready for scorers."""

    state: TaskState
    target: Target
    sample: EvalSample
    """The attachment-resolved variant of the input sample."""


def task_state_from_sample(
    sample: EvalSample,
    *,
    model: Model,
    model_name: str | Model,
    model_roles: dict[str, Model | list[Model]] | None,
    append_scores: bool,
) -> SampleTaskState:
    """Rebuild a scoring-ready ``TaskState`` from a serialized sample.

    The post-hoc scoring recipe behind ``inspect score`` / ``score_async``:
    resolve attachment references (rebinding timelines to the resolved
    events), construct the ``TaskState``, bind the task context and subtask
    store, and seed a fresh transcript with the sample's events and
    timelines.

    Args:
        sample: The serialized sample to rebuild from.
        model: The active model bound for scorer calls.
        model_name: Spec for the ``TaskState``'s model name (callers may
            carry a model string that differs from ``model``'s resolution,
            e.g. the eval log header's).
        model_roles: Model roles bound for grader role resolution.
        append_scores: Seed ``TaskState.scores`` with the sample's existing
            scores (the ``inspect score`` append action) rather than empty.
    """
    # resolve attachment:// refs so scorers see real content rather than
    # opaque hashes; rebind timelines to the resolved event objects. Done
    # per-sample so peak memory is bounded by concurrency, not sample count.
    resolved_sample = sample
    if sample.attachments:
        resolved_sample = resolve_sample_attachments(sample)
        resolved_sample = rebind_sample_timelines(resolved_sample)

    target = Target(resolved_sample.target)
    state = TaskState(
        model=ModelName(model_name),
        sample_id=resolved_sample.id,
        epoch=resolved_sample.epoch,
        input=resolved_sample.input,
        target=target,
        choices=resolved_sample.choices,
        messages=resolved_sample.messages,
        output=resolved_sample.output,
        completed=True,
        metadata=resolved_sample.metadata,
        store=resolved_sample.store,
        scores=dict(resolved_sample.scores or {}) if append_scores else {},
        sample_uuid=resolved_sample.uuid,
    )

    # initialize active model and store
    init_task_context(model, model_roles)
    init_subtask_store(state.store)

    # load a copy of the current sample events into the transcript
    init_transcript(
        Transcript([*resolved_sample.events], log_model_api=False, bounded=False)
    )

    # restore stored timelines so timeline-dependent scorers (e.g. scout
    # @scanner(timeline=True), petri's audit_judge) work on re-score
    for tl in resolved_sample.timelines or []:
        transcript().add_timeline(tl)

    return SampleTaskState(state=state, target=target, sample=resolved_sample)


async def _run_score_task(
    log_header: EvalLog,
    sample: EvalSample,
    scorers: list[Scorer],
    model: Model,
    model_roles: dict[str, Model | list[Model]],
    action: ScoreAction,
) -> Tuple[dict[str, SampleScore], list[str]]:
    state, target, resolved_sample = task_state_from_sample(
        sample,
        model=model,
        model_name=log_header.eval.model,
        model_roles=model_roles,
        append_scores=action == "append",
    )

    if state.scores is None:
        state.scores = {}
    existing_score_names = [*state.scores]

    results: dict[str, SampleScore] = {}
    scorer_names: list[str] = []
    async with span(name=SCORERS_SPAN_NAME):
        for scorer in scorers:
            scorer_name = unique_scorer_name(
                scorer, list({*existing_score_names, *results})
            )
            scorer_names.append(scorer_name)
            async with span(name=scorer_name, type=SCORER_SPAN_TYPE):
                with sentinel_scope("scorer", final=True):
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
                            scorer=scorer_name,
                            scorer_args=registry_params(scorer)
                            if has_registry_params(scorer)
                            else None,
                            model_usage=resolved_sample.model_usage or None,
                            role_usage=resolved_sample.role_usage or None,
                        )
                    )

                    results[scorer_name] = SampleScore(
                        score=score_result,
                        sample_id=state.sample_id,
                        sample_metadata=state.metadata,
                        scorer=registry_unqualified_name(scorer),
                    )

    # slice off only the newly added events
    new_events = transcript().events[len(resolved_sample.events) :]

    sample.scores = _get_updated_scores(sample, results, action=action)
    sample.events = _get_updated_events(sample, new_events, action=action)

    # return the actual sample scorers and scorer names that
    # were used to generate this set of scores
    return results, scorer_names


TRUST_LOG_OPT_IN = (
    "To trust the log, pass trust_log=True (inspect log recover: --trust-log); "
    "this imports the log's task file and runs its code, so do it only for logs "
    "you trust."
)
"""Closing advice of untrusted-log metric errors for recompute, edit and recovery."""

SCORE_OPT_IN = (
    "To score without the log's metrics, pass metrics= (inspect score: --metric). "
    "If you trust the log, rescore with its own scorers instead (inspect score "
    "without --scorer)."
)
"""Closing advice of untrusted-log metric errors when rescoring with the caller's scorers."""

LogMetricDefinitions = (
    list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
    | dict[str, list[EvalMetricDefinition]]
)


class LogTaskFileImport:
    """The trust decision and task-file import for one recompute, recovery or rescore.

    Shared by the metric resolvers of one operation (scorer metrics and
    task-level metrics), so the task file is imported at most once per
    operation and reported once.
    """

    def __init__(
        self,
        log: EvalLog,
        *,
        trust_log: bool,
        import_task_file: bool = True,
        opt_in: str | None = TRUST_LOG_OPT_IN,
        dependency_advice: str | None = None,
    ) -> None:
        """Create the tracker.

        Args:
            log: Log whose metrics are being rebuilt.
            trust_log: Whether the log may choose code: import the task file
                for unregistered metrics, and rebuild metric options without
                restriction.
            import_task_file: With `trust_log`, whether to import the task
                file for unregistered metrics. `False` is for rescoring with
                the log's own scorers, which trusts options but fails on a
                missing metric as it always has.
            opt_in: Closing advice of untrusted-log errors, naming an option
                the caller actually has (`None` for no advice).
            dependency_advice: Advice appended to the error for an object
                nested in metric options that is not registered (the task
                file is not imported for those).
        """
        self.trust_log = trust_log
        self.import_task_file = import_task_file
        self.opt_in = opt_in
        self.dependency_advice = dependency_advice
        self.task_file = log.eval.task_file
        self.task_path = Path(self.task_file).absolute() if self.task_file else None
        self.imported = False

    def import_metrics_file(self, name: str) -> bool:
        """Import the task file to load metric `name`, if trusted and not yet done.

        Returns:
            Whether the task file has been imported.
        """
        if self.imported:
            return True
        if (
            not self.trust_log
            or not self.import_task_file
            or self.task_path is None
            or not self.task_path.exists()
        ):
            return False
        load_file_tasks(self.task_path)
        self.imported = True
        logger.info(
            f"Imported task file {self.task_path} (recorded in the log) to load "
            f"metric '{name}'."
        )
        return True

    def missing_metric_error(self, name: str, used_by: str) -> RegistryNameNotFound:
        message = f"Metric '{name}' ({used_by}) is not registered."
        if self.task_file:
            message += (
                f" If it is defined in the task file ('{self.task_file}'), import "
                "that module first."
            )
        else:
            message += " Install or import the module that defines it first."
        if not self.trust_log and self.opt_in:
            message += f" {self.opt_in}"
        return RegistryNameNotFound(message, registry_type="metric", name=name)


def ensure_metrics_registered(
    definitions: Iterable[tuple[EvalMetricDefinition, str]],
    task_import: LogTaskFileImport,
) -> None:
    """Import the task file for unregistered metrics, when trusted to.

    Only runs when `task_import` may import the task file, which must happen
    before anything is built. Otherwise metrics are found missing as they are
    built, in order, so an earlier failure decides the outcome.

    Each definition comes with the label used in the error ("used by scorer
    'my_scorer'" or "a task-level metric"). Metric registry dicts nested in
    options are checked too.

    Raises:
        RegistryNameNotFound: A metric is still not registered after the
            import (a `LookupError`).
    """
    if not (task_import.trust_log and task_import.import_task_file):
        return
    missing = [
        (name, used_by)
        for definition, used_by in definitions
        for name in _metric_names(definition)
        if registry_lookup("metric", name) is None
    ]
    if missing and task_import.import_metrics_file(missing[0][0]):
        missing = [m for m in missing if registry_lookup("metric", m[0]) is None]
    if missing:
        raise task_import.missing_metric_error(*missing[0])


def _metric_names(definition: EvalMetricDefinition) -> list[str]:
    """Names of the metric and the metrics nested in its options.

    Walks the options the way `registry_arg()` resolves them: a mapping of
    arguments is never itself a registry dict, and a model dict is passed to
    the model as is.
    """
    names = [definition.name]

    def walk_args(args: dict[str, Any]) -> None:
        for value in args.values():
            walk(value)

    def walk(value: Any) -> None:
        if is_registry_dict(value):
            if value["type"] == "metric":
                names.append(value["name"])
            walk_args(value["params"])
        elif is_model_dict(value):
            return
        elif isinstance(value, dict):
            walk_args(value)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk_args(definition.options or {})
    return names


def _flatten_metric_definitions(
    metrics: LogMetricDefinitions,
) -> list[EvalMetricDefinition]:
    if isinstance(metrics, dict):
        return [md for mds in metrics.values() for md in mds]
    flat: list[EvalMetricDefinition] = []
    for item in metrics:
        if isinstance(item, dict):
            flat.extend(md for mds in item.values() for md in mds)
        else:
            flat.append(item)
    return flat


def _metrics_from_definitions(
    metrics: LogMetricDefinitions, task_import: LogTaskFileImport, used_by: str
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]]:
    def build(metric: EvalMetricDefinition) -> Metric:
        return metric_from_log(metric, task_import=task_import, used_by=used_by)

    if isinstance(metrics, dict):
        return {key: [build(md) for md in mds] for key, mds in metrics.items()}
    result: list[Metric | dict[str, list[Metric]]] = []
    for item in metrics:
        if isinstance(item, dict):
            result.append({key: [build(md) for md in mds] for key, mds in item.items()})
        else:
            result.append(build(item))
    return result


def metrics_from_log_header(
    log: EvalLog, *, task_import: LogTaskFileImport | None = None
) -> list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None:
    """Rebuild the log's task-level metrics (`eval.metrics`).

    Args:
        log: Log to read.
        task_import: Trust decision for this operation (default: untrusted).

    Raises:
        LookupError: A metric is not registered.
        DisallowedRegistryArg: Untrusted metric options name a model or a
            non-metric registry object.
    """
    if not log.eval.metrics:
        return None
    task_import = task_import or LogTaskFileImport(log, trust_log=False)
    ensure_metrics_registered(
        (
            (md, "a task-level metric")
            for md in _flatten_metric_definitions(log.eval.metrics)
        ),
        task_import,
    )
    return _metrics_from_definitions(
        log.eval.metrics, task_import, "a task-level metric"
    )


def metric_from_log(
    metric: EvalMetricDefinition,
    *,
    task_import: LogTaskFileImport | None = None,
    used_by: str = "a metric",
) -> Metric:
    """Rebuild one metric definition from a log.

    Untrusted (the default) options may construct only metrics and reducers.
    `used_by` labels the metric in a missing-metric error.
    """
    trusted = task_import is not None and task_import.trust_log
    try:
        return cast(
            Metric,
            create_registry_object(
                "metric",
                metric.name,
                metric.options or {},
                allowed_types=None if trusted else LOG_METRIC_OPTION_TYPES,
            ),
        )
    except DisallowedRegistryArg as ex:
        ex.advice = task_import.opt_in if task_import else TRUST_LOG_OPT_IN
        raise
    except RegistryNameNotFound as ex:
        if ex.registry_type == "metric" and ex.name is not None and task_import:
            # the metric itself, or one nested in its options
            raise task_import.missing_metric_error(ex.name, used_by) from ex
        message = (
            f"Metric '{metric.name}' needs an object that is not registered "
            f"({ex}). Install the package that defines it, or import the module "
            "that defines it, first."
        )
        if task_import and task_import.dependency_advice:
            message = f"{message} {task_import.dependency_advice}"
        raise RegistryNameNotFound(message) from ex


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
        return [
            scorer_from_spec(
                spec=ScorerSpec(scorer=score.name),
                task_path=task_path,
                **(score.options or {}),
            )
            for score in log.eval.scorers
        ]

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


def resolve_scorers_info(
    log: EvalLog, *, task_import: LogTaskFileImport | None = None
) -> list[ScorerInfo]:
    """Build ScorerInfo objects from an evaluation log for metrics recomputation.

    Args:
        log: Log to read.
        task_import: Trust decision for this operation (default: untrusted).

    Raises:
        LookupError: A scorer metric is not registered.
        DisallowedRegistryArg: Untrusted metric options name a model or a
            non-metric registry object.
    """
    if log.eval.scorers is None:
        return []

    task_import = task_import or LogTaskFileImport(log, trust_log=False)
    ensure_metrics_registered(
        (
            (md, f"used by scorer '{s.name}'")
            for s in log.eval.scorers
            if s.metrics
            for md in _flatten_metric_definitions(s.metrics)
        ),
        task_import,
    )

    # s.metrics holds EvalMetricDefinition entries (serialized name + options).
    # ScorerInfo needs callable Metric instances since eval_results invokes them
    # via call_metric().
    return [
        ScorerInfo(
            name=s.name,
            metrics=_metrics_from_definitions(
                s.metrics, task_import, f"used by scorer '{s.name}'"
            )
            if s.metrics
            else [],
            params=s.options or {},
            metadata=s.metadata or {},
        )
        for s in log.eval.scorers
    ]
