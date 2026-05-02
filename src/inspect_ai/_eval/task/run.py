import contextlib
import functools
import importlib
import sys
import time
from copy import copy, deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Literal

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    display,
)
from inspect_ai._display.core.display import TaskCancel, TaskDisplayMetric
from inspect_ai._util._async import tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS_BATCH,
)
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.error import exception_message
from inspect_ai._util.exception import TerminateSampleError, TerminateTaskError
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.notgiven import NOT_GIVEN
from inspect_ai._util.registry import (
    is_registry_object,
    registry_log_name,
    registry_unqualified_name,
)
from inspect_ai._util.working import (
    init_sample_working_time,
    sample_start_datetime,
    sample_waiting_time,
)
from inspect_ai._view.notify import view_notify_eval
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.event._error import ErrorEvent
from inspect_ai.event._sample_init import SampleInitEvent
from inspect_ai.event._sample_limit import SampleLimitEvent
from inspect_ai.event._score import ScoreEvent
from inspect_ai.log import (
    EvalConfig,
    EvalError,
    EvalLog,
    EvalResults,
    EvalSample,
    EvalStats,
)
from inspect_ai.log._condense import condense_sample
from inspect_ai.log._file import (
    EvalLogInfo,
    eval_log_json_str,
    read_eval_log_sample_async,
)
from inspect_ai.log._log import (
    EvalRetryError,
    EvalSampleLimit,
    EvalSampleReductions,
    EvalSampleSummary,
    eval_error,
)
from inspect_ai.log._samples import (
    active_sample,
)
from inspect_ai.log._transcript import (
    Transcript,
    init_transcript,
    transcript,
)
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.model._model import (
    init_sample_model_usage,
    init_sample_role_usage,
    sample_model_usage,
    sample_role_usage,
)
from inspect_ai.scorer import Scorer, Target
from inspect_ai.scorer._metric import Metric, SampleScore
from inspect_ai.scorer._reducer.types import ScoreReducer
from inspect_ai.scorer._score import init_scoring_context
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Plan, TaskState
from inspect_ai.solver._chain import Chain, unroll
from inspect_ai.solver._fork import set_task_generate
from inspect_ai.solver._solver import Solver
from inspect_ai.solver._task_state import sample_state, set_sample_state, state_jsonable
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._early_stopping import (
    EarlyStop,
    EarlyStopping,
    EarlyStoppingSummary,
)
from inspect_ai.util._limit import (
    LimitExceededError,
    monitor_working_limit,
    record_sample_limit_data,
)
from inspect_ai.util._limit import time_limit as create_time_limit
from inspect_ai.util._limit import working_limit as create_working_limit
from inspect_ai.util._sandbox import SandboxTimeoutError
from inspect_ai.util._sandbox.context import sandbox_connections
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._sandbox.limits import reset_sandbox_limits, set_sandbox_limits
from inspect_ai.util._span import span
from inspect_ai.util._store import init_subtask_store

from ..context import init_task_context
from ..task import Task
from .error import SampleErrorHandler, _should_eval_fail
from .generate import task_generate
from .images import (
    sample_with_base64_content,
    sample_without_base64_content,
    state_without_base64_content,
    states_with_base64_content,
)
from .log import TaskLogger, collect_eval_data, log_start
from .results import eval_results
from .sandbox import sandboxenv_context
from .store import DiskSampleStore, maybe_page_to_disk
from .util import sample_messages, slice_dataset

py_logger = getLogger(__name__)


EvalSampleSource = Callable[[int | str, int], Awaitable[EvalSample | None]]

# Units allocated for sample progress - the total units
# represents the total units of progress for an individual sample
# the remainder are increments of progress within a sample (and
# must sum to the total_progress_units when the sample is complete)
SAMPLE_TOTAL_PROGRESS_UNITS = 1


@dataclass
class TaskRunOptions:
    task: Task
    model: Model
    model_roles: dict[str, Model] | None
    sandbox: SandboxEnvironmentSpec | None
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    solver: Solver | None = field(default=None)
    tags: list[str] | None = field(default=None)
    run_samples: bool | None = field(default=True)
    score: bool = field(default=True)
    debug_errors: bool = field(default=False)
    sample_source: EvalSampleSource | None = field(default=None)
    display_name: str | None = field(default=None)
    kwargs: GenerateConfigArgs = field(default_factory=lambda: GenerateConfigArgs())


def resolve_plan(task: Task, solver: Solver | None) -> Plan:
    # resolve the plan (unroll chains)
    solver = solver or task.solver
    if isinstance(solver, Plan):
        plan = solver
    elif isinstance(solver, Chain):
        plan = Plan(list(solver), internal=True)
    else:
        plan = Plan(unroll(solver), internal=True)

    # add setup solver(s) if specified
    if task.setup:
        plan.steps = unroll(task.setup) + plan.steps

    return plan


async def task_run(options: TaskRunOptions, task_cancel: TaskCancel | None) -> EvalLog:
    from inspect_ai.hooks._hooks import (
        emit_task_end,
        emit_task_start,
    )
    from inspect_ai.hooks._legacy import send_telemetry_legacy

    # destructure options
    task = options.task
    model = options.model
    model_roles = options.model_roles
    sandbox = options.sandbox
    logger = options.logger
    eval_wd = options.eval_wd
    config = options.config
    solver = options.solver
    tags = options.tags
    score = options.score
    sample_source = options.sample_source
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # init task context
    init_task_context(
        model,
        model_roles,
        generate_config,
        options.task.approval,
    )

    # track stats, results, and log
    results: EvalResults | None = None
    reductions: list[EvalSampleReductions] | None = None
    eval_log: EvalLog | None = None
    stats = EvalStats(started_at=iso_now())

    # handle sample errors (raise as required)
    sample_error_handler = SampleErrorHandler(
        config.fail_on_error if config.continue_on_fail is not True else False,
        len(task.dataset),
    )

    # resolve some config
    model_name = ModelName(model)
    epochs = config.epochs if config.epochs else DEFAULT_EPOCHS
    sandbox_cleanup = config.sandbox_cleanup is not False
    log_images = config.log_images is not False
    log_model_api = config.log_model_api
    log_samples = config.log_samples is not False

    # slice dataset (but don't materialize all sample+state pairs upfront --
    # they are created lazily inside run_sample to keep memory at
    # O(concurrent_samples) instead of O(total_samples * epochs))
    dataset = slice_dataset(task.dataset, config.limit, config.sample_id)
    total_samples = len(dataset) * epochs

    # optionally page dataset to disk if it exceeds the memory budget
    sample_store = maybe_page_to_disk(dataset, config.max_dataset_memory)

    # release in-memory samples now that they're paged to disk
    if sample_store is not dataset:
        del dataset

    # resolve the plan (unroll chains)
    solver = solver or task.solver
    plan = resolve_plan(task, solver)

    # resolve the scorer
    score = score and task.scorer is not None
    scorers: list[Scorer] | None = task.scorer if (score and task.scorer) else None

    # resolve unique scorer names once so sample scoring
    # and aggregation use the same names
    scorer_names: list[str] | None = None
    if scorers:
        scorer_names = []
        for s in scorers:
            scorer_names.append(unique_scorer_name(s, scorer_names))

    scorer_profiles = (
        [registry_log_name(scorer) for scorer in scorers if is_registry_object(scorer)]
        if scorers is not None
        else ["(none)"]
    )

    # compute an eval directory relative log location if we can
    if PurePath(logger.location).is_relative_to(PurePath(eval_wd)):
        log_location = PurePath(logger.location).relative_to(eval_wd).as_posix()
    else:
        log_location = logger.location

    # create task profile for display
    profile = TaskProfile(
        name=options.display_name or task.name,
        file=logger.eval.task_file,
        model=model_name,
        dataset=task.dataset.name or "(samples)",
        scorer=", ".join(scorer_profiles),
        samples=total_samples,
        steps=total_samples * SAMPLE_TOTAL_PROGRESS_UNITS,
        eval_config=config,
        task_args=logger.eval.task_args_passed,
        generate_config=generate_config,
        tags=tags,
        log_location=log_location,
        task_id=logger.eval.task_id,
        task_cancel=task_cancel,
    )

    # set custom sandbox limits
    limit_tokens = set_sandbox_limits()

    with display().task(
        profile,
    ) as td:
        # start the log (do this outside fo the try b/c the try/except assumes
        # that the log is initialized)
        await log_start(logger, plan, generate_config)

        try:
            # return immediately if we are not running samples
            if not options.run_samples:
                return await logger.log_finish("started", stats)

            # call hook
            await emit_task_start(logger)

            # call early stopping if we have it
            stopping_manager: str = ""
            if options.task.early_stopping is not None:
                stopping_manager = await options.task.early_stopping.start_task(
                    logger.eval,
                    samples=[
                        deepcopy(sample_store[i]) for i in range(len(sample_store))
                    ],
                    epochs=epochs,
                )

            with td.progress() as p:
                # forward progress
                def progress(number: int) -> None:
                    p.update(number)

                # provide solvers a function that they can use to generate output
                async def generate(
                    state: TaskState,
                    tool_calls: Literal["loop", "single", "none"] = "loop",
                    **kwargs: Unpack[GenerateConfigArgs],
                ) -> TaskState:
                    return await task_generate(
                        model=model,
                        state=state,
                        tool_calls=tool_calls,
                        cache=kwargs.get("cache", False) or NOT_GIVEN,
                        config=generate_config.merge(kwargs),
                    )

                # set generate for fork module
                set_task_generate(generate)

                # semaphore to limit concurrency
                sample_semaphore = create_sample_semaphore(
                    config, generate_config, model.api
                )

                # track when samples complete and update progress as we go
                progress_results: list[dict[str, SampleScore]] = []

                def update_metrics(metrics: list[TaskDisplayMetric]) -> None:
                    td.update_metrics(metrics)
                    logger.update_metrics(metrics)

                update_metrics_display = update_metrics_display_fn(
                    update_metrics,
                    display_metrics=profile.eval_config.score_display is not False,
                )

                async def sample_complete(
                    sample_id: int | str,
                    epoch: int,
                    sample_score: dict[str, SampleScore],
                ) -> None:
                    # Capture the result
                    progress_results.append(sample_score)

                    # Increment the segment progress
                    td.sample_complete(
                        complete=len(progress_results), total=total_samples
                    )

                    # Update metrics
                    update_metrics_display(
                        len(progress_results),
                        progress_results,
                        scorers,
                        scorer_names,
                        task.epochs_reducer,
                        task.metrics,
                    )

                    # call the early stopping hook
                    if options.task.early_stopping is not None:
                        await options.task.early_stopping.complete_sample(
                            sample_id, epoch, sample_score
                        )

                # initial progress
                td.sample_complete(complete=0, total=total_samples)

                # Update metrics to empty state
                update_metrics_display(
                    len(progress_results),
                    progress_results,
                    scorers,
                    scorer_names,
                    task.epochs_reducer,
                    task.metrics,
                )

                async def run_sample(
                    sample_index: int, epoch: int
                ) -> dict[str, SampleScore] | EarlyStop | None:
                    # check for cached result from previous eval (before
                    # materialization to avoid unnecessary deepcopy + image I/O)
                    sample_id = sample_store[sample_index].id
                    if sample_source and sample_id is not None:
                        previous_sample = await sample_source(sample_id, epoch)
                        if previous_sample:
                            progress(SAMPLE_TOTAL_PROGRESS_UNITS)
                            if logger and log_samples:
                                await logger.complete_sample(
                                    previous_sample, flush=False
                                )
                            sample_scores = (
                                {
                                    key: SampleScore(
                                        score=score,
                                        sample_id=previous_sample.id,
                                        sample_metadata=previous_sample.metadata,
                                    )
                                    for key, score in previous_sample.scores.items()
                                }
                                if previous_sample.scores
                                else {}
                            )
                            await sample_complete(sample_id, epoch, sample_scores)
                            return sample_scores

                    # factory to create sample+state lazily (after semaphore)
                    # so only concurrently executing samples consume memory
                    async def create_sample_state(
                        sample_uuid: str | None = None,
                    ) -> tuple[Sample, TaskState]:
                        sample = deepcopy(sample_store[sample_index])
                        if log_images:
                            sample = await sample_with_base64_content(sample)
                        state = deepcopy(
                            TaskState(
                                sample_id=sample.id or 0,
                                epoch=epoch,
                                model=model_name,
                                input=sample.input,
                                target=Target(sample.target),
                                choices=sample.choices,
                                messages=sample_messages(sample),
                                message_limit=config.message_limit,
                                token_limit=config.token_limit,
                                cost_limit=config.cost_limit,
                                completed=False,
                                metadata=sample.metadata if sample.metadata else {},
                                sample_uuid=sample_uuid,
                            )
                        )
                        return sample, state

                    return await task_run_sample(
                        task_name=task.name,
                        log_location=profile.log_location,
                        create_sample_state=create_sample_state,
                        sandbox=sandbox,
                        max_sandboxes=config.max_sandboxes,
                        sandbox_cleanup=sandbox_cleanup,
                        plan=plan,
                        scorers=scorers,
                        scorer_names=scorer_names,
                        cleanup=task.cleanup,
                        generate=generate,
                        progress=progress,
                        logger=logger if log_samples else None,
                        log_images=log_images,
                        log_model_api=log_model_api,
                        sample_error=sample_error_handler,
                        sample_complete=sample_complete,
                        early_stopping=options.task.early_stopping,
                        fails_on_error=(
                            config.fail_on_error is not False
                            and config.continue_on_fail is not True
                            and config.score_on_error is not True
                        ),
                        retry_on_error=config.retry_on_error or 0,
                        score_on_error=config.score_on_error or False,
                        error_retries=[],
                        time_limit=config.time_limit,
                        working_limit=config.working_limit,
                        semaphore=sample_semaphore,
                        eval_set_id=logger.eval.eval_set_id,
                        run_id=logger.eval.run_id,
                        task_id=logger.eval.eval_id,
                    )

                sample_results = await tg_collect(
                    [
                        functools.partial(run_sample, sample_index, epoch)
                        for epoch in range(1, epochs + 1)
                        for sample_index in range(len(sample_store))
                    ]
                )

            # compute and record metrics if we have scores
            completed_scores = [
                score_dict
                for score_dict in sample_results
                if isinstance(score_dict, dict)
            ]

            early_stops = [
                stopped_sample
                for stopped_sample in sample_results
                if isinstance(stopped_sample, EarlyStop)
            ]

            # call early stopping if we have it
            stopping_summary: EarlyStoppingSummary | None = None
            if options.task.early_stopping is not None:
                stopping_metadata = await options.task.early_stopping.complete_task()
                stopping_summary = EarlyStoppingSummary(
                    manager=stopping_manager,
                    early_stops=early_stops,
                    metadata=stopping_metadata,
                )

            if len(completed_scores) > 0:
                results, reductions = eval_results(
                    samples=profile.samples,
                    scores=completed_scores,
                    reducers=task.epochs_reducer,
                    scorers=scorers,
                    metrics=task.metrics,
                    scorer_names=scorer_names,
                    early_stopping=stopping_summary,
                )

            # collect eval data
            collect_eval_data(stats)

            # use the SampleErrorHandler's authoritative count (incremented in
            # handle_error() exactly once per sample after retries are
            # exhausted). With score_on_error, errored samples now return a
            # populated score dict instead of None, so counting via
            # `result is None` would miss them.
            sample_error_count = sample_error_handler.error_count
            mark_log_as_error = _should_eval_fail(
                sample_error_count, profile.samples, config.fail_on_error
            )

            # finish
            eval_log = await logger.log_finish(
                "error" if mark_log_as_error else "success", stats, results, reductions
            )

            await emit_task_end(logger, eval_log)

            # display task summary
            td.complete(
                TaskSuccess(
                    samples_completed=logger.samples_completed,
                    stats=stats,
                    results=results or EvalResults(),
                )
            )

        except anyio.get_cancelled_exc_class():
            with anyio.CancelScope(shield=True):
                # collect eval data
                collect_eval_data(stats)

                if task_cancel and task_cancel.cancel_type is not None:
                    # User-initiated cancel (abort/retry) — log as error so
                    # eval_set doesn't interpret it as external cancellation
                    cancel_ex = TerminateTaskError(
                        f"Task cancelled by user ({task_cancel.cancel_type})"
                    )
                    error = eval_error(cancel_ex, TerminateTaskError, cancel_ex, None)
                    eval_log = await logger.log_finish(
                        "error", stats, results, reductions, error
                    )
                    td.complete(
                        TaskError(
                            logger.samples_completed,
                            TerminateTaskError,
                            cancel_ex,
                            None,
                        )
                    )
                else:
                    # External cancellation (ctrl+c)
                    eval_log = await logger.log_finish(
                        "cancelled", stats, results, reductions
                    )
                    td.complete(TaskCancelled(logger.samples_completed, stats))

        except BaseException as ex:
            if options.debug_errors:
                raise
            else:
                # get exception info
                type, value, traceback = sys.exc_info()
                type = type if type else BaseException
                value = value if value else ex

                # build eval error
                error = eval_error(ex, type, value, traceback)

                # collect eval data
                collect_eval_data(stats)

                # finish with error status
                eval_log = await logger.log_finish(
                    "error", stats, results, reductions, error
                )

                # display it
                td.complete(TaskError(logger.samples_completed, type, value, traceback))

    # cleanup disk sample store if used
    if isinstance(sample_store, DiskSampleStore):
        sample_store.close()

    # notify the view module that an eval just completed
    # (in case we have a view polling for new evals)
    view_notify_eval(logger.location)

    assert eval_log is not None

    try:
        # Log file locations are emitted to the "new" hooks via the "task end" event,
        if (
            await send_telemetry_legacy("eval_log_location", eval_log.location)
            == "not_handled"
        ):
            # Converting the eval log to JSON is expensive. Only do so if
            # eval_log_location was not handled.
            await send_telemetry_legacy("eval_log", eval_log_json_str(eval_log))
    except Exception as ex:
        py_logger.warning(f"Error occurred sending telemetry: {exception_message(ex)}")

    # restore sandbox limits
    reset_sandbox_limits(limit_tokens)

    # return eval log
    return eval_log


def update_metrics_display_fn(
    update_fn: Callable[[list[TaskDisplayMetric]], None],
    initial_interval: float = 0,
    min_interval: float = 0.9,
    display_metrics: bool = True,
) -> Callable[
    [
        int,
        list[dict[str, SampleScore]],
        list[Scorer] | None,
        list[str] | None,
        ScoreReducer | list[ScoreReducer] | None,
        list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None,
    ],
    None,
]:
    next_compute_time = time.perf_counter() + initial_interval

    def compute(
        sample_count: int,
        sample_scores: list[dict[str, SampleScore]],
        scorers: list[Scorer] | None,
        scorer_names: list[str] | None,
        reducers: ScoreReducer | list[ScoreReducer] | None,
        metrics: list[Metric | dict[str, list[Metric]]]
        | dict[str, list[Metric]]
        | None,
    ) -> None:
        # Don't compute metrics if they are not being displayed
        if not display_metrics:
            return None

        nonlocal next_compute_time
        time_start = time.perf_counter()
        if time_start >= next_compute_time:
            # compute metrics
            results, reductions = eval_results(
                samples=sample_count,
                scores=sample_scores,
                reducers=reducers,
                scorers=scorers,
                metrics=metrics,
                scorer_names=scorer_names,
            )

            # Name, reducer, value
            task_metrics: list[TaskDisplayMetric] = []
            if len(results.scores) > 0:
                for score in results.scores:
                    for key, metric in score.metrics.items():
                        task_metrics.append(
                            TaskDisplayMetric(
                                scorer=score.name,
                                name=metric.name,
                                value=metric.value,
                                reducer=score.reducer,
                                params=metric.params,
                            )
                        )
                update_fn(task_metrics)

            # determine how long to wait before recomputing metrics
            time_end = time.perf_counter()
            elapsed_time = time_end - time_start
            wait = max(min_interval, elapsed_time * 10)
            next_compute_time = time_end + wait

    return compute


async def task_run_sample(
    *,
    task_name: str,
    log_location: str,
    create_sample_state: Callable[[str | None], Awaitable[tuple[Sample, TaskState]]],
    sandbox: SandboxEnvironmentSpec | None,
    max_sandboxes: int | None,
    sandbox_cleanup: bool,
    plan: Plan,
    scorers: list[Scorer] | None,
    scorer_names: list[str] | None,
    cleanup: Callable[[TaskState], Awaitable[None]] | None,
    generate: Generate,
    progress: Callable[[int], None],
    logger: TaskLogger | None,
    log_images: bool,
    log_model_api: bool | None,
    sample_error: SampleErrorHandler,
    sample_complete: Callable[
        [int | str, int, dict[str, SampleScore]], Awaitable[None]
    ],
    fails_on_error: bool,
    early_stopping: EarlyStopping | None,
    retry_on_error: int,
    score_on_error: bool,
    error_retries: list[EvalRetryError],
    time_limit: int | None,
    working_limit: int | None,
    semaphore: contextlib.AbstractAsyncContextManager[Any],
    eval_set_id: str | None,
    run_id: str,
    task_id: str,
    sample_uuid: str | None = None,
) -> dict[str, SampleScore] | EarlyStop | None:
    from inspect_ai.event import Event
    from inspect_ai.hooks._hooks import (
        drain_sample_events,
        emit_sample_attempt_end,
        emit_sample_attempt_start,
        emit_sample_end,
        emit_sample_event,
        emit_sample_init,
        emit_sample_scoring,
        emit_sample_start,
        start_sample_event_emitter,
    )

    # execute under sample semaphore
    async with semaphore:
        # materialize sample+state lazily (deferred until semaphore acquired)
        sample, state = await create_sample_state(sample_uuid)

        # validate that we have sample_id (mostly for the typechecker)
        sample_id = sample.id
        if sample_id is None:
            raise ValueError("sample must have id to run")

        def on_sample_event(event: Event) -> None:
            if logger:
                logger.log_sample_event(sample_id, state.epoch, event)
            emit_sample_event(
                eval_set_id=eval_set_id,
                run_id=run_id,
                eval_id=task_id,
                sample_id=state.uuid,
                event=event,
            )

        # initialise subtask and scoring context
        init_sample_model_usage()
        init_sample_role_usage()
        set_sample_state(state)
        sample_transcript = Transcript(log_model_api=log_model_api)
        init_transcript(sample_transcript)
        init_subtask_store(state.store)
        sample_transcript._subscribe(on_sample_event)
        if scorers:
            init_scoring_context(scorers, Target(sample.target))
        init_sample_assistant_internal()

        # use sandbox if provided
        sandboxenv_cm = (
            sandboxenv_context(
                task_name, sandbox, max_sandboxes, sandbox_cleanup, sample
            )
            if sandbox or sample.sandbox is not None
            else contextlib.nullcontext()
        )

        # helper to handle exceptions (will throw if we've exceeded the limit)
        def handle_error(ex: BaseException) -> tuple[EvalError, BaseException | None]:
            # helper to log sample error
            def log_sample_error() -> None:
                msg = f"Sample error (id: {sample.id}, epoch: {state.epoch}): {exception_message(ex)})"
                if retry_on_error > 0:
                    msg = f"{msg}. Sample will be retried."
                elif score_on_error:
                    msg = f"{msg}. Sample will be scored."
                py_logger.warning(msg)

            # if we have retries left then return EvalError
            if retry_on_error > 0:
                log_sample_error()
                return eval_error(ex, type(ex), ex, ex.__traceback__), None
            else:
                err = sample_error(ex)
                # with score_on_error, suppress the raise so we can score the
                # sample; error_count was still incremented on sample_error()
                # above, so the eval-level fail_on_error threshold continues
                # to apply.
                if score_on_error:
                    log_sample_error()
                    transcript()._event(ErrorEvent(error=err[0]))
                    return err[0], None
                # if we aren't raising the error then print a warning
                if err[1] is None:
                    log_sample_error()
                transcript()._event(ErrorEvent(error=err[0]))
                return err

        async with active_sample(
            task=task_name,
            log_location=log_location,
            model=str(state.model),
            sample=sample,
            epoch=state.epoch,
            message_limit=state.message_limit,
            token_limit=state.token_limit,
            cost_limit=state.cost_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            fails_on_error=fails_on_error or (retry_on_error > 0),
            transcript=sample_transcript,
            eval_set_id=eval_set_id,
            run_id=run_id,
            eval_id=task_id,
        ) as active:
            # check for early stopping
            if early_stopping is not None and logger is not None:
                early_stop = await early_stopping.schedule_sample(
                    state.sample_id, state.epoch
                )
                if early_stop is not None:
                    return early_stop

            start_time: float | None = None
            error: EvalError | None = None
            raise_error: BaseException | None = None
            cancelled_error: BaseException | None = None
            results: dict[str, SampleScore] = {}
            limit: EvalSampleLimit | None = None
            sample_summary: EvalSampleSummary | None = None
            attempt_started = False

            async def emit_attempt_end(will_retry: bool) -> None:
                if sample_summary is None or not attempt_started:
                    return
                await emit_sample_attempt_end(
                    eval_set_id,
                    run_id,
                    task_id,
                    state.uuid,
                    summary=sample_summary,
                    attempt=len(error_retries) + 1,
                    error=error,
                    will_retry=will_retry,
                )

            # begin init
            init_span = span("init", type="init")
            await init_span.__aenter__()
            cleanup_span: contextlib.AbstractAsyncContextManager[None] | None = (
                init_span
            )

            try:
                # sample init event (remove file bodies as they have content or absolute paths)
                event_sample = sample.model_copy(
                    update=dict(files={k: "" for k in sample.files.keys()})
                    if sample.files
                    else None
                )
                transcript()._event(
                    SampleInitEvent(sample=event_sample, state=state_jsonable(state))
                )

                # construct sample summary, used by both emit_sample_init and emit_sample_start
                sample_summary = EvalSampleSummary(
                    id=sample_id,
                    epoch=state.epoch,
                    input=sample.input,
                    choices=sample.choices,
                    target=sample.target,
                    metadata=sample.metadata or {},
                )

                # emit sample init before sandbox creation
                # (only on the first attempt; not re-emitted when the sample is retried after an error)
                if not error_retries:
                    await emit_sample_init(
                        eval_set_id,
                        run_id,
                        task_id,
                        state.uuid,
                        sample_summary,
                    )

                async with sandboxenv_cm:
                    try:
                        # update active sample wth sandboxes now that we are initialised
                        # (ensure that we still exit init context in presence of sandbox error)
                        try:
                            active.sandboxes = await sandbox_connections()
                        finally:
                            await init_span.__aexit__(None, None, None)
                            cleanup_span = None

                        # record start time
                        start_time = time.monotonic()
                        init_sample_working_time(start_time)

                        # run sample w/ optional limits
                        with (
                            state._token_limit,
                            state._cost_limit,
                            state._message_limit,
                            create_time_limit(time_limit),
                            create_working_limit(working_limit),
                        ):

                            async def run(tg: TaskGroup) -> None:
                                # access to state, limit, and errors
                                nonlocal state, limit, error, raise_error

                                try:
                                    # start the sample
                                    active.start(tg)

                                    # monitor working limit in the background
                                    monitor_working_limit()

                                    # start background sample event emitter
                                    start_sample_event_emitter()

                                    # set progress for plan then run it
                                    async with span("solvers"):
                                        state = await plan(state, generate)

                                # some 'cancel' exceptions are actually user interrupts or the
                                # result of monitor_working_limit() - for these exceptions we
                                # want to intercept them and apply the appropriate control flow
                                # so they can continue on and be scored.
                                except anyio.get_cancelled_exc_class() as ex:
                                    if active.interrupt_action:
                                        # record event
                                        transcript()._event(
                                            SampleLimitEvent(
                                                type="operator",
                                                message="Sample completed: interrupted by operator",
                                            )
                                        )

                                        # handle the action
                                        match active.interrupt_action:
                                            case "score":
                                                # continue to scoring (capture the most recent state)
                                                state = sample_state() or state
                                                limit = EvalSampleLimit(
                                                    type="operator", limit=1
                                                )
                                            case "error":
                                                # default error handling
                                                error, raise_error = handle_error(ex)

                                    elif active.limit_exceeded_error:
                                        # record event
                                        transcript()._event(
                                            SampleLimitEvent(
                                                type="working",
                                                message=active.limit_exceeded_error.message,
                                                limit=active.limit_exceeded_error.limit,
                                            )
                                        )

                                        # capture most recent state for scoring
                                        state = sample_state() or state
                                        limit = EvalSampleLimit(
                                            type=active.limit_exceeded_error.type,
                                            limit=active.limit_exceeded_error.limit
                                            if active.limit_exceeded_error.limit
                                            is not None
                                            else -1,
                                        )

                                    # this was not a user interrupt or working time limit so propagate
                                    else:
                                        raise
                                finally:
                                    # ensures that monitor_working_limit() and any coroutines
                                    # created w/ background() are cancelled
                                    tg.cancel_scope.cancel()

                            try:
                                # emit/log sample start
                                if logger is not None:
                                    await logger.start_sample(sample_summary)

                                # only emit the sample start once: not on retries
                                if not error_retries:
                                    await emit_sample_start(
                                        eval_set_id,
                                        run_id,
                                        task_id,
                                        state.uuid,
                                        sample_summary,
                                    )

                                await emit_sample_attempt_start(
                                    eval_set_id,
                                    run_id,
                                    task_id,
                                    state.uuid,
                                    sample_summary,
                                    attempt=len(error_retries) + 1,
                                )
                                attempt_started = True

                                async with anyio.create_task_group() as tg:
                                    tg.start_soon(run, tg)
                            except Exception as ex:
                                raise inner_exception(ex)
                            finally:
                                # capture sample limits
                                record_sample_limit_data(
                                    len((sample_state() or state).messages)
                                )

                    except SandboxTimeoutError as ex:
                        raise RuntimeError(str(ex)) from ex

                    except TimeoutError:
                        # Scoped time limits manifest themselves as LimitExceededError, not
                        # TimeoutError.
                        py_logger.warning(
                            "Unexpected timeout error reached top of sample stack. Are you handling TimeoutError when applying timeouts?"
                        )

                        # capture most recent state for scoring
                        state = sample_state() or state

                    except LimitExceededError as ex:
                        # capture most recent state for scoring
                        state = sample_state() or state
                        limit = EvalSampleLimit(
                            type=ex.type, limit=ex.limit if ex.limit is not None else -1
                        )

                    except TerminateSampleError as ex:
                        # emit event
                        transcript()._event(
                            SampleLimitEvent(
                                type="operator", limit=1, message=ex.reason
                            )
                        )

                        # capture most recent state for scoring
                        state = sample_state() or state
                        limit = EvalSampleLimit(type="operator", limit=1)

                    except anyio.get_cancelled_exc_class() as ex:
                        with anyio.CancelScope(shield=True):
                            cancelled_error = ex
                            # convert to standard error
                            error = eval_error(ex, type(ex), ex, ex.__traceback__)
                            transcript()._event(ErrorEvent(error=error))

                    except Exception as ex:
                        error, raise_error = handle_error(ex)

                    # mark completed
                    state.completed = True

                    # set timeout for scoring. if the original timeout was hit we still
                    # want to provide opportunity for scoring, but we don't necessarily
                    # want to wait the full timeout again (especially in the case where
                    # the cause of the timeout is a hung container and scoring requires
                    # interacting with the container). as a middle ground we use half
                    # of the original timeout value for scoring.
                    scoring_time_limit = time_limit / 2 if time_limit else None

                    set_sample_state(state)
                    if state.scores is None:
                        state.scores = {}
                    solver_score_names = [*state.scores]

                    # scoring
                    with anyio.CancelScope(shield=cancelled_error is not None):
                        await emit_sample_scoring(
                            eval_set_id,
                            run_id,
                            task_id,
                            state.uuid,
                        )
                        try:
                            # timeout during scoring will result in an ordinary sample error
                            with create_time_limit(scoring_time_limit):
                                # score on success, or when score_on_error is on
                                # for the final attempt (no retries left, not cancelled)
                                if error is None or (
                                    score_on_error
                                    and retry_on_error == 0
                                    and cancelled_error is None
                                ):
                                    async with span(name="scorers"):
                                        for scorer_idx, scorer in enumerate(
                                            scorers or []
                                        ):
                                            scorer_name = (
                                                scorer_names[scorer_idx]
                                                if scorer_names
                                                else unique_scorer_name(
                                                    scorer,
                                                    list(
                                                        {*solver_score_names, *results}
                                                    ),
                                                )
                                            )
                                            async with span(
                                                name=scorer_name, type="scorer"
                                            ):
                                                if not scorer:
                                                    continue
                                                score_result = await scorer(
                                                    state, Target(sample.target)
                                                )
                                                if scorer_name in state.scores:
                                                    raise RuntimeError(
                                                        f"Scorer {scorer_name} has modified state.scores"
                                                    )
                                                if score_result is not None:
                                                    state.scores[scorer_name] = (
                                                        score_result
                                                    )

                                                    transcript()._event(
                                                        ScoreEvent(
                                                            score=score_result,
                                                            target=sample.target,
                                                            model_usage=sample_model_usage()
                                                            or None,
                                                            role_usage=sample_role_usage()
                                                            or None,
                                                        )
                                                    )

                                                    results[scorer_name] = SampleScore(
                                                        score=score_result,
                                                        sample_id=sample.id,
                                                        sample_metadata=sample.metadata,
                                                        scorer=registry_unqualified_name(
                                                            scorer
                                                        ),
                                                    )

                                for name in solver_score_names:
                                    score = state.scores[name]
                                    transcript()._event(
                                        ScoreEvent(
                                            score=score,
                                            target=sample.target,
                                            model_usage=sample_model_usage() or None,
                                            role_usage=sample_role_usage() or None,
                                        )
                                    )
                                    results[name] = SampleScore(
                                        score=score,
                                        sample_id=state.sample_id,
                                        sample_metadata=state.metadata,
                                    )

                        except anyio.get_cancelled_exc_class() as ex:
                            with anyio.CancelScope(shield=True):
                                cancelled_error = ex
                                if active.interrupt_action:
                                    transcript()._event(
                                        SampleLimitEvent(
                                            type="operator",
                                            message="Unable to score sample due to operator interruption",
                                        )
                                    )

                                # convert to standard error
                                error = eval_error(ex, type(ex), ex, ex.__traceback__)
                                transcript()._event(ErrorEvent(error=error))

                        except Exception as ex:
                            # handle error
                            error, raise_error = handle_error(ex)
                        finally:
                            # run task cleanup if required (inside sandbox context)
                            if cleanup is not None:
                                with anyio.CancelScope(shield=True):
                                    try:
                                        await cleanup(state)
                                    except Exception as ex:
                                        py_logger.warning(
                                            f"Exception occurred during task cleanup: {ex}",
                                            exc_info=ex,
                                        )

            except Exception as ex:
                error, raise_error = handle_error(ex)
            finally:
                # cleanup the task init span if required
                if cleanup_span is not None:
                    with anyio.CancelScope(shield=cancelled_error is not None):
                        await cleanup_span.__aexit__(None, None, None)

            # complete the sample if there is no error or if there is no retry_on_error in play
            with anyio.CancelScope(shield=cancelled_error is not None):
                # drain sample events for both completion and retry paths
                await drain_sample_events()

                if not error or (retry_on_error == 0) or (cancelled_error is not None):
                    progress(SAMPLE_TOTAL_PROGRESS_UNITS)

                    # if we are logging images then be sure to base64 images injected by solvers
                    if log_images:
                        state = (await states_with_base64_content([state]))[0]

                    # otherwise ensure there are no base64 images in sample or messages
                    else:
                        sample = sample_without_base64_content(sample)
                        state = state_without_base64_content(state)

                    # emit/log sample end
                    eval_sample = create_eval_sample(
                        start_time=start_time,
                        sample=sample,
                        state=state,
                        scores=results,
                        error=error,
                        limit=limit,
                        error_retries=error_retries,
                        started_at=sample_start_datetime(),
                    )
                    if logger:
                        await log_sample(
                            eval_sample=eval_sample,
                            logger=logger,
                            log_images=log_images,
                        )
                    await emit_attempt_end(will_retry=False)
                    await emit_sample_end(
                        eval_set_id, run_id, task_id, state.uuid, eval_sample
                    )

    # error that should be retried (we do this outside of the above scope so that we can
    # retry outside of the original semaphore -- our retry will therefore go to the back
    # of the sample queue)
    if error and retry_on_error > 0 and cancelled_error is None:
        await emit_attempt_end(will_retry=True)

        # remove any buffered sample events
        if logger is not None:
            logger.remove_sample(state.sample_id, state.epoch)

        # recurse w/ tick down of retry_on_error and append of error to error_retries
        return await task_run_sample(
            task_name=task_name,
            log_location=log_location,
            create_sample_state=create_sample_state,
            sandbox=sandbox,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            plan=plan,
            scorers=scorers,
            scorer_names=scorer_names,
            cleanup=cleanup,
            generate=generate,
            progress=progress,
            logger=logger,
            log_images=log_images,
            log_model_api=log_model_api,
            sample_error=sample_error,
            sample_complete=sample_complete,
            early_stopping=early_stopping,
            fails_on_error=fails_on_error,
            # tick retry count down
            retry_on_error=retry_on_error - 1,
            score_on_error=score_on_error,
            # forward on error that caused retry
            error_retries=copy(error_retries) + [_eval_retry_error(error)],
            time_limit=time_limit,
            working_limit=working_limit,
            semaphore=semaphore,
            eval_set_id=eval_set_id,
            run_id=run_id,
            task_id=task_id,
            sample_uuid=state.uuid,
        )

    # re-raise cancellation after logging to preserve structured concurrency
    elif cancelled_error is not None:
        raise cancelled_error

    # no error
    elif error is None:
        # call sample_complete callback if we have score results
        if results is not None:
            await sample_complete(state.sample_id, state.epoch, results)
        return results

    # we have an error and should raise it
    elif raise_error is not None:
        raise raise_error

    # we have an error and should not raise it
    else:
        return None


def create_eval_sample(
    start_time: float | None,
    sample: Sample,
    state: TaskState,
    scores: dict[str, SampleScore],
    error: EvalError | None,
    limit: EvalSampleLimit | None,
    error_retries: list[EvalRetryError],
    started_at: datetime | None = None,
) -> EvalSample:
    # sample must have id to be logged
    id = sample.id
    if id is None:
        raise ValueError(
            f"Samples without IDs cannot be logged: {to_json_str_safe(sample)}"
        )

    # construct sample for logging

    # compute total time if we can
    total_time = time.monotonic() - start_time if start_time is not None else None

    return EvalSample(
        id=id,
        epoch=state.epoch,
        input=sample.input,
        choices=sample.choices,
        target=sample.target,
        metadata=state.metadata or {},
        sandbox=sample.sandbox,
        files=list(sample.files.keys()) if sample.files else None,
        setup=sample.setup,
        messages=state.messages,
        output=state.output,
        scores={k: v.score for k, v in scores.items()},
        store=dict(state.store.items()),
        uuid=state.uuid,
        events=list(transcript().events),
        timelines=list(transcript().timelines) or None,
        attachments=dict(transcript().attachments),
        model_usage=sample_model_usage(),
        role_usage=sample_role_usage(),
        started_at=started_at.isoformat() if started_at is not None else None,
        completed_at=datetime.now(timezone.utc).isoformat(),
        total_time=round(total_time, 3) if total_time is not None else None,
        working_time=round(total_time - sample_waiting_time(), 3)
        if total_time is not None
        else None,
        error=error,
        error_retries=error_retries,
        limit=limit,
    )


async def log_sample(
    eval_sample: EvalSample, logger: TaskLogger, log_images: bool
) -> None:
    await logger.complete_sample(condense_sample(eval_sample, log_images), flush=True)


# we can reuse samples from a previous eval_log if and only if:
#   - The datasets have not been shuffled OR the samples in the dataset have unique ids
#   - The datasets have the exact same length
def eval_log_sample_source(
    eval_log: EvalLog | None,
    eval_log_info: EvalLogInfo | None,
    dataset: Dataset,
) -> EvalSampleSource:
    # return dummy function for no sample source
    async def no_sample_source(id: int | str, epoch: int) -> None:
        return None

    # take care of no log or no samples in log
    if not eval_log:
        return no_sample_source
    elif (not eval_log.samples or len(eval_log.samples) == 0) and not eval_log_info:
        return no_sample_source

    # determine whether all samples in the dataset have ids (if not, then we can't
    # provide a sample source in the case where either dataset is shuffled, as the ids
    # will be auto-assigned based on position, and therefore not stable)
    samples_have_ids = (
        next((sample for sample in dataset if sample.id is None), None) is None
    )

    if (eval_log.eval.dataset.shuffled or dataset.shuffled) and not samples_have_ids:
        py_logger.warning(
            "Unable to re-use samples from retry log file because the dataset was shuffled "
            + "and some samples in the dataset do not have an 'id' field."
        )
        return no_sample_source

    elif eval_log.eval.dataset.samples != len(dataset):
        py_logger.warning(
            "Unable to re-use samples from retry log file because the dataset size changed "
            + f"(log samples {eval_log.eval.dataset.samples}, dataset samples {len(dataset)})"
        )
        return no_sample_source
    elif eval_log_info:
        reader: AsyncZipReader | None = None

        async def read_from_file(id: int | str, epoch: int) -> EvalSample | None:
            nonlocal reader
            if not reader:
                reader = AsyncZipReader(get_async_filesystem(), eval_log_info.name)
            try:
                sample = await read_eval_log_sample_async(
                    eval_log_info, id, epoch, reader=reader
                )
                if sample.error is not None or sample.invalidation is not None:
                    return None
                return sample
            except IndexError:
                return None

        return read_from_file
    else:

        async def read_from_memory(id: int | str, epoch: int) -> EvalSample | None:
            return next(
                (
                    sample
                    for sample in (eval_log.samples or [])
                    if sample.id == id
                    and sample.epoch == epoch
                    and sample.error is None
                    and sample.invalidation is None
                ),
                None,
            )

        return read_from_memory


# semaphore to limit concurrency. default max_samples to
# max_connections + 1 if not explicitly specified (this is
# to make sure it always saturates the connection pool)
def create_sample_semaphore(
    config: EvalConfig,
    generate_config: GenerateConfig,
    modelapi: ModelAPI | None = None,
) -> contextlib.AbstractAsyncContextManager[Any]:
    from inspect_ai.util._concurrency import AdaptiveConcurrency, DynamicSampleLimiter

    if config.max_samples is not None:
        # explicit max_samples wins silently — anticipating that adaptive_connections
        # may become default-on, in which case warning when max_samples < adaptive.max
        # would fire for nearly every deliberate max_samples setting
        return anyio.Semaphore(config.max_samples)
    elif (
        generate_config.adaptive_connections and generate_config.max_connections is None
    ):
        # adaptive: dynamic limiter that tracks the controller(s) — sample
        # concurrency grows with the controller's current limit so setup work
        # (sandboxes etc.) stays proportional to actual model concurrency.
        # Explicit max_connections wins silently (matches the precedence in
        # Model._connection_concurrency).
        adaptive = (
            generate_config.adaptive_connections
            if isinstance(generate_config.adaptive_connections, AdaptiveConcurrency)
            else AdaptiveConcurrency()
        )
        return DynamicSampleLimiter(adaptive)
    else:
        # static path (existing behavior, unchanged)
        max_samples = (
            generate_config.max_connections
            if generate_config.max_connections is not None
            else DEFAULT_MAX_CONNECTIONS_BATCH
            if generate_config.batch
            else modelapi.max_connections()
            if modelapi
            else DEFAULT_MAX_CONNECTIONS
        )
        return anyio.Semaphore(max_samples)


def init_sample_assistant_internal() -> None:
    if importlib.util.find_spec("openai"):
        try:
            from inspect_ai.model._openai_responses import (
                init_sample_openai_assistant_internal,
            )

            init_sample_openai_assistant_internal()
        except ImportError:
            pass

    if importlib.util.find_spec("anthropic"):
        try:
            from inspect_ai.model._providers.anthropic import (
                init_sample_anthropic_assistant_internal,
            )

            init_sample_anthropic_assistant_internal()
        except ImportError:
            pass


def _eval_retry_error(error: EvalError) -> EvalRetryError:
    """Create retry error with events from the most recent ModelEvent onward."""
    from inspect_ai.event._model import ModelEvent

    events = transcript().events
    recent_events = list(events)
    for i in range(len(events) - 1, -1, -1):
        if isinstance(events[i], ModelEvent):
            recent_events = list(events[i:])
            break
    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=recent_events,
    )
