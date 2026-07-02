import contextlib
import functools
import sys
import time
from copy import copy, deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging import getLogger
from pathlib import PurePath
from typing import Any, Awaitable, Callable, Literal, NamedTuple

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._control.eval_state import (
    finalize_eval,
    record_sample_cancelled,
    record_sample_completed,
    record_sample_errored,
    register_eval,
)
from inspect_ai._display import (
    TaskCancelled,
    TaskError,
    TaskProfile,
    TaskSuccess,
    display,
)
from inspect_ai._display.core.display import TaskCancel, TaskDisplayMetric
from inspect_ai._eval.task.scan import Scanners
from inspect_ai._util._async import aexit_shielded_when, tg_collect
from inspect_ai._util.async_zip import AsyncZipReader
from inspect_ai._util.asyncfiles import get_async_filesystem
from inspect_ai._util.constants import (
    DEFAULT_EPOCHS,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_CONNECTIONS_BATCH,
)
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.error import exception_message, is_cancellation_message
from inspect_ai._util.exception import TerminateSampleError, TerminateTaskError
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.notgiven import NOT_GIVEN
from inspect_ai._util.registry import (
    has_registry_params,
    is_registry_object,
    registry_info,
    registry_log_name,
    registry_params,
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
    read_eval_log_sample_summaries_async,
)
from inspect_ai.log._log import (
    EvalRetryError,
    EvalSampleLimit,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalStatus,
    eval_error,
)
from inspect_ai.log._recorders.buffer.transcript_history_provider import (
    BufferTranscriptHistoryProvider,
)
from inspect_ai.log._recorders.streaming import (
    eval_retry_error_from_history,
    materialize_streaming_sample,
)
from inspect_ai.log._samples import (
    active_sample,
)
from inspect_ai.log._transcript import (
    DEFAULT_RESIDENT_TAIL,
    Transcript,
    TranscriptHistoryProvider,
    init_transcript,
    transcript,
    transcript_bounded_enabled,
)
from inspect_ai.model import (
    GenerateConfig,
    GenerateConfigArgs,
    Model,
    ModelAPI,
    ModelName,
)
from inspect_ai.model._assistant_internal import init_sample_assistant_internal
from inspect_ai.model._model import (
    init_model_usage,
    init_role_usage,
    init_sample_model_data,
    sample_model_fallbacks,
    sample_model_usage,
    sample_role_usage,
)
from inspect_ai.model._model_output import ModelUsage
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
from inspect_ai.util._checkpoint._layout import (
    has_sample_checkpoint,
    sample_checkpoints_dir,
)
from inspect_ai.util._checkpoint._layout.sample_checkpoints_dir import (
    scan_latest_committed_checkpoint,
)
from inspect_ai.util._checkpoint.checkpointer import ResumeCheckpoint
from inspect_ai.util._checkpoint.config import (
    CheckpointConfig,
    merge_checkpoint_configs,
)
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
from inspect_ai.util._limit import turn_limit as create_turn_limit
from inspect_ai.util._limit import working_limit as create_working_limit
from inspect_ai.util._sandbox import SandboxTimeoutError
from inspect_ai.util._sandbox.context import sandbox_connections
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._sandbox.limits import reset_sandbox_limits, set_sandbox_limits
from inspect_ai.util._span import span
from inspect_ai.util._store import init_subtask_store

from ..context import init_task_context
from ..task import Task
from .enqueue import get_task_enqueuer
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
from .scan import (
    resume_scan_previous_sample,
    scan_eval_sample,
    scanned_transcripts_for_resume,
)
from .store import DiskSampleStore, maybe_page_to_disk
from .task_source import TaskSource
from .util import sample_messages, slice_dataset

py_logger = getLogger(__name__)


@dataclass
class PreviousError:
    """Prior attempt of a sample that carries genuine error history.

    Unlike a clean reused `EvalSample` (which short-circuits the re-run),
    this signals that the sample must be re-run with its `error_retries`
    seeded from the prior attempt (see `_seed_error_retries`). This unifies
    task-level retries (eval-set / `retry_immediate`, which mint a fresh
    log per attempt) with sample-level `retry_on_error` so both surface a
    retry count and the prior errors on the surviving sample.

    Carries the full prior `sample` so a retry attempt that is itself torn
    down before re-running this sample can re-log it verbatim, keeping the
    error history intact across the per-attempt log chain (see
    `carry_forward_unlogged_samples`).
    """

    sample: EvalSample


SampleLookup = Callable[
    [int | str, int], Awaitable[EvalSample | ResumeCheckpoint | PreviousError | None]
]
ErrorHistoryIds = Callable[[], Awaitable[set[tuple[int | str, int]]]]


class EvalSampleSource(NamedTuple):
    """A prior attempt's sample source.

    `lookup` resolves one planned `(id, epoch)` to a reusable sample, a
    resume checkpoint, or carried error history. `error_history_ids`
    returns the `(id, epoch)` pairs that errored in the prior attempt —
    the only candidates that can yield a `PreviousError` — so teardown
    carry-forward can probe just those instead of the full plan.
    """

    lookup: SampleLookup
    error_history_ids: ErrorHistoryIds


# Units allocated for sample progress - the total units
# represents the total units of progress for an individual sample
# the remainder are increments of progress within a sample (and
# must sum to the total_progress_units when the sample is complete)
SAMPLE_TOTAL_PROGRESS_UNITS = 1


def _sample_transcript_config(
    logger: TaskLogger | None, sample_id: str | int, epoch: int
) -> tuple[bool, TranscriptHistoryProvider | None]:
    if logger is not None and logger.buffer_db is not None:
        return (
            transcript_bounded_enabled(),
            BufferTranscriptHistoryProvider(logger.buffer_db, sample_id, epoch),
        )
    else:
        return False, None


@dataclass
class TaskRunOptions:
    task: Task
    model: Model
    model_roles: dict[str, Model] | None
    sandbox: SandboxEnvironmentSpec | None
    checkpoint: CheckpointConfig | None
    """Task-level checkpoint config (raw `task.checkpoint`)."""
    eval_checkpoint: CheckpointConfig | None
    """Eval/CLI-level checkpoint config (overrides task/sample)."""
    logger: TaskLogger
    eval_wd: str
    config: EvalConfig = field(default_factory=EvalConfig)
    solver: Solver | None = field(default=None)
    scanner: "Scanners | None" = field(default=None)
    scan_id: str | None = field(default=None)
    tags: list[str] | None = field(default=None)
    run_samples: bool | None = field(default=True)
    score: bool = field(default=True)
    debug_errors: bool = field(default=False)
    sample_source: EvalSampleSource | None = field(default=None)
    display_name: str | None = field(default=None)
    kwargs: GenerateConfigArgs = field(default_factory=lambda: GenerateConfigArgs())
    initial_model_usage: dict[str, ModelUsage] | None = field(default=None)
    initial_role_usage: dict[str, ModelUsage] | None = field(default=None)
    task_source: "TaskSource | None" = field(default=None)
    """Run-level task source notified as this task's samples/task complete."""


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
        # avoid mutating a caller-supplied Plan: resolve_plan may run more than
        # once for the same task (e.g. task-identity hashing in evalset, then the
        # run itself), and prepending in place would stack setup steps each time.
        # A shallow copy preserves finish/cleanup/name and registry identity.
        if plan is solver:
            plan = copy(plan)
        plan.steps = unroll(task.setup) + plan.steps

    return plan


def plan_agent_name(plan: Plan) -> str | None:
    """Unqualified name of the plan's terminal step (agent or solver)."""
    if plan.steps:
        last_step = plan.steps[-1]
        if is_registry_object(last_step):
            return registry_unqualified_name(registry_info(last_step).name)
    return None


def _enqueue_source_tasks(tasks: list[Task] | None) -> None:
    """Add tasks a TaskSource callback returned to the running eval's queue.

    Routes through the run's enqueuer (the same buffer ``enqueue_task`` feeds), so
    the eval loop drains them as the next batch. A no-op if the callback returned
    nothing or there is no active enqueuer.
    """
    if tasks:
        enqueuer = get_task_enqueuer()
        if enqueuer is not None:
            enqueuer.enqueue(tasks)


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
    checkpoint = options.checkpoint
    eval_checkpoint = options.eval_checkpoint
    logger = options.logger
    eval_wd = options.eval_wd
    config = options.config
    solver = options.solver
    scanner = options.scanner
    scan_id = options.scan_id
    tags = options.tags
    score = options.score
    sample_source = options.sample_source
    kwargs = options.kwargs

    # resolve default generate_config for task
    generate_config = task.config.merge(GenerateConfigArgs(**kwargs))

    # seed model/role usage from a prior log when this task is a retry
    # (the deepcopy guards against shared dict mutation across attempts).
    # init_task_context's no-arg init_model_usage/init_role_usage will leave
    # these seeded values in place.
    if options.initial_model_usage:
        init_model_usage(deepcopy(options.initial_model_usage))
    if options.initial_role_usage:
        init_role_usage(deepcopy(options.initial_role_usage))

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
    progress_results: list[dict[str, SampleScore]] = []
    eval_log: EvalLog | None = None
    stats = EvalStats(started_at=iso_now())

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

    # capture sample ids now, before `dataset` may be paged to disk and
    # deleted below — used by register_eval and carry_forward_unlogged_samples
    sample_ids = [s.id for s in dataset if s.id is not None]

    async def finish_task_log(
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None = None,
        reductions: list[EvalSampleReductions] | None = None,
        error: EvalError | None = None,
    ) -> EvalLog:
        """Finish via ``_finish_task_log`` with the run-invariant context.

        Bound once here so every terminal branch finishes with the same
        logger / sample-source / planned-ids context — a new branch can't
        accidentally thread a stale or divergent value.
        """
        return await _finish_task_log(
            logger=logger,
            sample_source=options.sample_source,
            sample_ids=sample_ids,
            epochs=epochs,
            log_images=log_images,
            status=status,
            stats=stats,
            results=results,
            reductions=reductions,
            error=error,
        )

    # handle sample errors (raise as required). use total_samples (sliced
    # dataset * epochs) as the denominator for fractional fail_on_error so
    # the mid-run abort threshold matches the end-of-run check below.
    sample_error_handler = SampleErrorHandler(
        config.fail_on_error if config.continue_on_fail is not True else False,
        total_samples,
    )

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
        agent=plan_agent_name(plan),
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

            sample_semaphore = create_sample_semaphore(
                config, generate_config, model.api, task_id=logger.eval.task_id
            )

            # Register this eval with the process-level state aggregate
            # so the control channel (and other readers) can answer
            # "how many samples queued / running / done?" without
            # polling active_samples() or scanning logs. Paired with
            # the finalize_eval in the finally below.
            register_eval(
                logger.eval.eval_id,
                total_samples,
                task=logger.eval.task,
                task_id=logger.eval.task_id,
                model=str(model),
                log_location=logger.location,
                live=logger,
                sample_ids=sample_ids,
                epochs=epochs,
                run_id=logger.eval.run_id,
                # whether a failure of this attempt will be retried — lets the
                # control channel show cancelled samples as pending (re-run
                # coming) vs cancelled (terminal)
                will_retry=task_cancel.can_retry if task_cancel is not None else False,
            )

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

                scanned_per_scanner = scanned_transcripts_for_resume(
                    scanner, scan_id, profile.log_location
                )

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
                    resume_checkpoint: ResumeCheckpoint | None = None
                    # prior task-attempt errors to seed this re-run's
                    # error_retries (empty unless the sample source reports a
                    # PreviousError); kept distinct from the sample-level
                    # retry list so it doesn't suppress sample init/start emits
                    previous_attempt_errors: list[EvalRetryError] = []
                    if sample_source and sample_id is not None:
                        previous_sample = await sample_source.lookup(sample_id, epoch)
                        if isinstance(previous_sample, EvalSample):
                            progress(SAMPLE_TOTAL_PROGRESS_UNITS)
                            if logger and log_samples:
                                await logger.complete_sample(
                                    condense_sample(previous_sample, log_images),
                                    flush=False,
                                )
                            sample_scores = (
                                {
                                    key: SampleScore(
                                        score=score,
                                        sample_id=previous_sample.id,
                                        sample_metadata=previous_sample.metadata,
                                        scorer=key,
                                    )
                                    for key, score in previous_sample.scores.items()
                                }
                                if previous_sample.scores
                                else {}
                            )
                            await resume_scan_previous_sample(
                                previous_sample,
                                scanner,
                                scanned_per_scanner,
                                sample_semaphore,
                                scan_id=scan_id,
                                eval_id=logger.eval.eval_id,
                                log_location=profile.log_location,
                                model=str(model),
                                eval_spec=logger.eval,
                            )
                            await sample_complete(sample_id, epoch, sample_scores)
                            # reused sample: accumulate its own logged usage
                            record_sample_completed(
                                logger.eval.eval_id,
                                tokens=sum(
                                    u.total_tokens
                                    for u in previous_sample.model_usage.values()
                                ),
                                messages=len(previous_sample.messages),
                            )
                            return sample_scores
                        elif isinstance(previous_sample, ResumeCheckpoint):
                            # signal intent — agent code can branch on
                            # `cp.attempt`. Hydration runs inside
                            # `_CheckpointerSetup.__aenter__`.
                            resume_checkpoint = previous_sample
                        elif isinstance(previous_sample, PreviousError):
                            previous_attempt_errors = _seed_error_retries(
                                previous_sample.sample
                            )

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
                        task=task,
                        task_name=task.name,
                        log_location=profile.log_location,
                        create_sample_state=create_sample_state,
                        sandbox=sandbox,
                        checkpoint=checkpoint,
                        eval_checkpoint=eval_checkpoint,
                        resume_checkpoint=resume_checkpoint,
                        max_sandboxes=config.max_sandboxes,
                        sandbox_cleanup=sandbox_cleanup,
                        plan=plan,
                        scorers=scorers,
                        scorer_names=scorer_names,
                        scanner=scanner,
                        cleanup=task.cleanup,
                        generate=generate,
                        progress=progress,
                        logger=logger if log_samples else None,
                        log_images=log_images,
                        log_model_api=log_model_api,
                        sample_error=sample_error_handler,
                        sample_complete=sample_complete,
                        early_stopping=options.task.early_stopping,
                        task_source=options.task_source,
                        fails_on_error=(
                            config.fail_on_error is not False
                            and config.continue_on_fail is not True
                            and config.score_on_error is not True
                        ),
                        retry_on_error=config.retry_on_error or 0,
                        score_on_error=config.score_on_error or False,
                        error_retries=[],
                        previous_attempt_errors=previous_attempt_errors,
                        turn_limit=config.turn_limit,
                        time_limit=config.time_limit,
                        working_limit=config.working_limit,
                        semaphore=sample_semaphore,
                        eval_set_id=logger.eval.eval_set_id,
                        run_id=logger.eval.run_id,
                        task_id=logger.eval.eval_id,
                        scan_id=options.scan_id,
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
            eval_log = await finish_task_log(
                status="error" if mark_log_as_error else "success",
                stats=stats,
                results=results,
                reductions=reductions,
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

                # compute partial results from samples that completed
                if len(progress_results) > 0:
                    results, reductions = eval_results(
                        samples=profile.samples,
                        scores=progress_results,
                        reducers=task.epochs_reducer,
                        scorers=scorers,
                        metrics=task.metrics,
                        scorer_names=scorer_names,
                    )

                if task_cancel and task_cancel.cancel_type is not None:
                    # User-initiated cancel (abort/retry) — log as error so
                    # eval_set doesn't interpret it as external cancellation
                    cancel_ex = TerminateTaskError(
                        f"Task cancelled by user ({task_cancel.cancel_type})"
                    )
                    error = eval_error(cancel_ex, TerminateTaskError, cancel_ex, None)
                    eval_log = await finish_task_log(
                        status="error",
                        stats=stats,
                        results=results,
                        reductions=reductions,
                        error=error,
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
                    eval_log = await finish_task_log(
                        status="cancelled",
                        stats=stats,
                        results=results,
                        reductions=reductions,
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
                eval_log = await finish_task_log(
                    status="error",
                    stats=stats,
                    results=results,
                    reductions=reductions,
                    error=error,
                )

                # display it
                td.complete(TaskError(logger.samples_completed, type, value, traceback))

        finally:
            # every sample task has exited by here (the try encloses the task
            # group), so any still-unaccounted samples can no longer record
            finalize_eval(logger.eval.eval_id)

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

    # notify a TaskSource (if the run has one) that this task is complete
    # (it may return follow-up tasks to add to the run)
    if options.task_source is not None:
        _enqueue_source_tasks(await options.task_source.task_complete(eval_log))

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
                                name=key,
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


def _sample_usage(state: TaskState) -> dict[str, int]:
    """The just-finished sample's ``tokens`` / ``messages`` for the eval totals.

    Model usage is read from the sample-scoped contextvar (still set on this
    coroutine even though the ``active_sample`` context has exited by the
    terminal block). Spread into ``record_sample_completed`` /
    ``record_sample_errored`` so each terminal outcome is a single call.
    """
    return {
        "tokens": sum(u.total_tokens for u in sample_model_usage().values()),
        "messages": len(state.messages),
    }


def _sample_started() -> float | None:
    """The just-finished sample's start time, for the eval's running-min start.

    Read from the same sample-scoped timing contextvar that backs the logged
    ``started_at`` (set when the sample began, still in scope in the terminal
    block). Passed to ``record_sample_*`` so the eval's reported start pins to
    its first sample even when that sample finished before any control poll
    (see ``EvalState.started_at``). ``None`` for a sample that never started.
    """
    started = sample_start_datetime()
    return started.timestamp() if started is not None else None


async def task_run_sample(
    *,
    task: Task,
    task_name: str,
    log_location: str,
    create_sample_state: Callable[[str | None], Awaitable[tuple[Sample, TaskState]]],
    sandbox: SandboxEnvironmentSpec | None,
    checkpoint: CheckpointConfig | None,
    eval_checkpoint: CheckpointConfig | None,
    resume_checkpoint: ResumeCheckpoint | None,
    max_sandboxes: int | None,
    sandbox_cleanup: bool,
    plan: Plan,
    scorers: list[Scorer] | None,
    scorer_names: list[str] | None,
    scanner: "Scanners | None",
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
    task_source: TaskSource | None,
    retry_on_error: int,
    score_on_error: bool,
    error_retries: list[EvalRetryError],
    previous_attempt_errors: list[EvalRetryError],
    turn_limit: int | None,
    time_limit: int | None,
    working_limit: int | None,
    semaphore: contextlib.AbstractAsyncContextManager[Any],
    eval_set_id: str | None,
    run_id: str,
    task_id: str,
    scan_id: str | None = None,
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
        init_sample_model_data()
        set_sample_state(state)
        sample_transcript_bounded, history_provider = _sample_transcript_config(
            logger, sample_id, state.epoch
        )
        sample_transcript = Transcript(
            log_model_api=log_model_api,
            bounded=sample_transcript_bounded,
            resident_tail=DEFAULT_RESIDENT_TAIL,
            history_provider=history_provider,
        )
        init_transcript(sample_transcript)
        init_subtask_store(state.store)
        sample_transcript._subscribe(on_sample_event)
        if scorers:
            init_scoring_context(scorers, Target(sample.target))
        init_sample_assistant_internal()

        # use sandbox if provided
        #
        # The sandbox CM's `__aexit__` is wrapped so its teardown runs shielded
        # whenever the sample's own cancel was caught upstream (`cancelled_error`
        # set). Otherwise, the eval-level scope's still-cancelled state would
        # re-cancel the first await inside `cleanup_sandbox_environments_sample`,
        # propagating a fresh CancelledError out past the (already shielded)
        # logging block and dropping the in-flight sample from the eval log.
        sandboxenv_cm = (
            aexit_shielded_when(
                sandboxenv_context(
                    task_name, sandbox, max_sandboxes, sandbox_cleanup, sample
                ),
                lambda: cancelled_error is not None,
            )
            if sandbox or sample.sandbox is not None
            else contextlib.nullcontext()
        )

        # resolve checkpoint config across all three levels with
        # precedence eval > sample > task (per-field merge — see
        # `merge_checkpoint_configs`).
        resolved_checkpoint = merge_checkpoint_configs(
            checkpoint, sample.checkpoint, eval_checkpoint
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

        # Derive agent name for the ACP picker / TUI meta row.
        agent_name = plan_agent_name(plan)

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
            checkpoint=resolved_checkpoint,
            resume_checkpoint=resume_checkpoint,
            eval_set_id=eval_set_id,
            run_id=run_id,
            eval_id=task_id,
            agent_name=agent_name,
            # prior failed attempts (task-level seed + sample-level retries),
            # surfaced as the running sample's error history by the control channel
            error_retries=previous_attempt_errors + error_retries,
            # the uuid the logged EvalSample will carry — lets the control
            # channel keep one event cursor valid across running→terminal
            sample_uuid=state.uuid,
        ) as active:
            # check for early stopping
            if early_stopping is not None and logger is not None:
                early_stop = await early_stopping.schedule_sample(
                    state.sample_id, state.epoch
                )
                if early_stop is not None:
                    # count the halt as terminal (not an error) so the eval can
                    # reach `total` and be marked finished
                    record_sample_completed(task_id)
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
                    uuid=state.uuid,
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
                            create_turn_limit(turn_limit),
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
                                        err = active.limit_exceeded_error
                                        # Record a SampleLimitEvent ONLY for a working-time
                                        # limit. `sample.limit_exceeded()` (which set
                                        # `limit_exceeded_error` and cancelled us) has two
                                        # callers: monitor_working_limit(), which records no
                                        # event of its own — so here we are its sole recorder
                                        # — and the sandbox service, which surfaces a bridged
                                        # message/token/cost limit that ALREADY recorded its
                                        # own event at its detection point (e.g.
                                        # check_message_limit). Recording the latter here would
                                        # both duplicate that event and mislabel it "working".
                                        if err.type == "working":
                                            transcript()._event(
                                                SampleLimitEvent(
                                                    type=err.type,
                                                    message=err.message,
                                                    limit=err.limit,
                                                )
                                            )

                                        # capture most recent state for scoring
                                        state = sample_state() or state
                                        limit = EvalSampleLimit(
                                            type=err.type,
                                            limit=err.limit
                                            if err.limit is not None
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
                                                            scorer=scorer_name,
                                                            scorer_args=registry_params(
                                                                scorer
                                                            )
                                                            if has_registry_params(
                                                                scorer
                                                            )
                                                            else None,
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
                                            scorer=name,
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
                            if active.interrupt_action is not None:
                                # Operator-interrupted: log to transcript but
                                # don't propagate to error/retry. The operator
                                # EvalSampleLimit is set in the run() handler.
                                scorer_error = eval_error(
                                    ex, type(ex), ex, ex.__traceback__
                                )
                                transcript()._event(ErrorEvent(error=scorer_error))
                            else:
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
                    def make_eval_sample(include_events: bool = True) -> EvalSample:
                        return create_eval_sample(
                            start_time=start_time,
                            sample=sample,
                            state=state,
                            scores=results,
                            error=error,
                            limit=limit,
                            # the logged sample carries the full retry history:
                            # prior task attempts followed by this eval's
                            # sample-level retries
                            error_retries=previous_attempt_errors + error_retries,
                            started_at=sample_start_datetime(),
                            include_events=include_events,
                        )

                    with anyio.CancelScope(
                        shield=error is not None or cancelled_error is not None
                    ):
                        if logger:
                            # When the full event history is still resident in
                            # memory we can log the sample directly from memory
                            # rather than reading every event back out of the
                            # realtime buffer DB and re-validating it. This is the
                            # case whenever realtime logging is off (no buffer DB)
                            # OR the transcript was not bounded-evicted (events
                            # never exceeded the resident tail — the common case for
                            # high-throughput runs). Only fall back to the streaming
                            # read-back when events were actually evicted.
                            log_from_memory = (
                                logger.buffer_db is None
                                or not sample_transcript.history.resident_events_truncated
                            )
                            eval_sample = await log_sample(
                                eval_sample=make_eval_sample(
                                    include_events=log_from_memory
                                ),
                                logger=logger,
                                log_images=log_images,
                                from_memory=log_from_memory,
                            )
                        else:
                            eval_sample = make_eval_sample()
                        await scan_eval_sample(
                            eval_sample,
                            scanner,
                            scan_id=scan_id,
                            eval_id=task_id,
                            log_location=log_location,
                            model=str(state.model),
                            eval_spec=logger.eval if logger else None,
                        )
                        await emit_attempt_end(will_retry=False)
                        await emit_sample_end(
                            eval_set_id, run_id, task_id, state.uuid, eval_sample
                        )
                    # notify a TaskSource (if the run has one) as each sample
                    # completes, so it can react in real time (and add tasks)
                    if task_source is not None:
                        _enqueue_source_tasks(
                            await task_source.sample_complete(eval_sample, task)
                        )

    # error that should be retried (we do this outside of the above scope so that we can
    # retry outside of the original semaphore -- our retry will therefore go to the back
    # of the sample queue)
    if (
        error
        and retry_on_error > 0
        and cancelled_error is None
        and active.interrupt_action is None
    ):
        await emit_attempt_end(will_retry=True)

        retry_error = _eval_retry_error(error, logger, state.sample_id, state.epoch)

        # remove any buffered sample events
        if logger is not None:
            logger.remove_sample(state.sample_id, state.epoch)

        # recurse w/ tick down of retry_on_error and append of error to error_retries
        return await task_run_sample(
            task=task,
            task_name=task_name,
            log_location=log_location,
            create_sample_state=create_sample_state,
            sandbox=sandbox,
            checkpoint=checkpoint,
            eval_checkpoint=eval_checkpoint,
            resume_checkpoint=resume_checkpoint,
            max_sandboxes=max_sandboxes,
            sandbox_cleanup=sandbox_cleanup,
            plan=plan,
            scorers=scorers,
            scorer_names=scorer_names,
            scanner=scanner,
            cleanup=cleanup,
            generate=generate,
            progress=progress,
            logger=logger,
            log_images=log_images,
            log_model_api=log_model_api,
            sample_error=sample_error,
            sample_complete=sample_complete,
            early_stopping=early_stopping,
            task_source=task_source,
            fails_on_error=fails_on_error,
            # tick retry count down
            retry_on_error=retry_on_error - 1,
            score_on_error=score_on_error,
            # forward on error that caused retry
            error_retries=copy(error_retries) + [retry_error],
            previous_attempt_errors=previous_attempt_errors,
            turn_limit=turn_limit,
            time_limit=time_limit,
            working_limit=working_limit,
            semaphore=semaphore,
            eval_set_id=eval_set_id,
            run_id=run_id,
            task_id=task_id,
            scan_id=scan_id,
            sample_uuid=state.uuid,
        )

    # re-raise cancellation after logging to preserve structured concurrency
    elif cancelled_error is not None:
        # a cancelled sample is terminal but not a genuine error — count it so
        # the eval can reach `total` and be marked finished (eg. a final-attempt
        # failure that cancels an in-flight sibling)
        record_sample_cancelled(
            task_id, started=_sample_started(), **_sample_usage(state)
        )
        raise cancelled_error

    # no error
    elif error is None:
        # call sample_complete callback if we have score results
        if results is not None:
            await sample_complete(state.sample_id, state.epoch, results)
        record_sample_completed(
            task_id, started=_sample_started(), **_sample_usage(state)
        )
        return results

    # we have an error and should raise it
    elif raise_error is not None:
        record_sample_errored(
            task_id, started=_sample_started(), **_sample_usage(state)
        )
        raise raise_error

    # we have an error and should not raise it
    else:
        record_sample_errored(
            task_id, started=_sample_started(), **_sample_usage(state)
        )
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
    include_events: bool = True,
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
        events=list(transcript().events) if include_events else [],
        timelines=list(transcript().timelines) or None,
        attachments=dict(transcript().attachments),
        model_usage=sample_model_usage(),
        role_usage=sample_role_usage(),
        model_fallbacks=sample_model_fallbacks() or None,
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
    eval_sample: EvalSample,
    logger: TaskLogger,
    log_images: bool,
    *,
    from_memory: bool,
) -> EvalSample:
    # No realtime buffer DB, or the full history is still resident in memory:
    # log directly from the in-memory sample (which carries its events). This
    # avoids the open_sample_history -> materialize_streaming_sample round-trip
    # (read every event back out of SQLite + re-validate). `complete_sample`
    # still finalizes the buffer DB via `_finalize_sample`, so when a realtime
    # buffer exists it stays consistent for live viewing.
    if logger.buffer_db is None or from_memory:
        await logger.complete_sample(
            condense_sample(eval_sample, log_images), flush=True
        )
        return eval_sample

    # Events were bounded-evicted from memory: stream them back from the buffer
    # DB (the only place the full history still lives) without re-materializing
    # the whole sample in memory at once.
    logging_sample = condense_sample(
        eval_sample.model_copy(update={"events": [], "events_data": None}),
        log_images,
    )
    with logger.buffer_db.open_sample_history(
        eval_sample.id, eval_sample.epoch
    ) as sample_history:
        materialized_sample = materialize_streaming_sample(eval_sample, sample_history)
        await logger.complete_sample_streaming(
            logging_sample, sample_history, flush=True
        )
    return materialized_sample


# we can reuse samples from a previous eval_log if and only if:
#   - The datasets have not been shuffled OR the samples in the dataset have unique ids
#   - The datasets have the exact same length
def eval_log_sample_source(
    eval_log: EvalLog | None,
    eval_log_info: EvalLogInfo | None,
    dataset: Dataset,
    eval_checkpoints_dir: str | None = None,
) -> EvalSampleSource:
    # return dummy function for no sample source
    async def no_sample_source(id: int | str, epoch: int) -> None:
        return None

    async def no_error_history() -> set[tuple[int | str, int]]:
        return set()

    async def error_history_from_file() -> set[tuple[int | str, int]]:
        """The prior log's errored `(id, epoch)` pairs, from its summaries.

        One bounded read of the summaries index — never per-sample log
        reads. Degrades to "no candidates" on failure: this feeds teardown
        carry-forward, which must not fail (or stall) task shutdown.
        """
        assert eval_log_info is not None
        try:
            summaries = await read_eval_log_sample_summaries_async(eval_log_info)
            return {(s.id, s.epoch) for s in summaries if s.error is not None}
        except Exception as ex:
            py_logger.warning(
                f"Unable to read sample summaries from retry log file: {ex}"
            )
            return set()

    async def _resume_if_checkpointed(
        id: int | str, epoch: int
    ) -> ResumeCheckpoint | None:
        if eval_checkpoints_dir is None:
            return None
        if not await has_sample_checkpoint(eval_checkpoints_dir, id, epoch):
            return None
        prior_sample_dir = sample_checkpoints_dir(eval_checkpoints_dir, id, epoch)
        # Latest parseable checkpoint with ``trigger == "agent_complete"`` =
        # agent finished cleanly, scoring is the next thing → retry can
        # skip the agent loop (the ``"resume_for_scoring"`` attempt).
        checkpoint = await scan_latest_committed_checkpoint(prior_sample_dir)
        attempt: Literal["initial", "resume", "resume_for_scoring"] = (
            "resume_for_scoring"
            if checkpoint is not None and checkpoint.trigger == "agent_complete"
            else "resume"
        )
        return ResumeCheckpoint(
            sample_checkpoints_dir=prior_sample_dir,
            attempt=attempt,
        )

    async def _resume_or_seed_retry(
        id: int | str, epoch: int, sample: EvalSample | None
    ) -> ResumeCheckpoint | PreviousError | None:
        """Resolve a non-clean prior sample (errored, invalidated, or absent).

        Prefers resuming from an on-disk checkpoint. Failing that, an
        errored prior sample yields a `PreviousError` so the re-run seeds
        its `error_retries` with the prior attempt's history; an absent or
        invalidated sample yields `None` (re-run fresh).
        """
        resume = await _resume_if_checkpointed(id, epoch)
        if resume is not None:
            return resume
        if (
            sample is not None
            and sample.error is not None
            and _seed_error_retries(sample)
        ):
            return PreviousError(sample=sample)
        return None

    # take care of no log or no samples in log. Note we still proceed when
    # in-memory samples and `eval_log_info` are both absent if a
    # `eval_checkpoints_dir` is available — the prior eval may have been
    # killed before writing any sample, and on-disk checkpoint files
    # can still drive resume detection in `read_from_memory` below.
    if not eval_log:
        return EvalSampleSource(no_sample_source, no_error_history)
    elif not eval_log.samples and not eval_log_info and not eval_checkpoints_dir:
        return EvalSampleSource(no_sample_source, no_error_history)

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
        return EvalSampleSource(no_sample_source, no_error_history)

    elif eval_log.eval.dataset.samples != len(dataset):
        py_logger.warning(
            "Unable to re-use samples from retry log file because the dataset size changed "
            + f"(log samples {eval_log.eval.dataset.samples}, dataset samples {len(dataset)})"
        )
        return EvalSampleSource(no_sample_source, no_error_history)
    elif eval_log_info:
        reader: AsyncZipReader | None = None

        async def read_from_file(
            id: int | str, epoch: int
        ) -> EvalSample | ResumeCheckpoint | PreviousError | None:
            nonlocal reader
            if not reader:
                reader = AsyncZipReader(get_async_filesystem(), eval_log_info.name)
            try:
                sample = await read_eval_log_sample_async(
                    eval_log_info, id, epoch, reader=reader
                )
            except IndexError:
                return await _resume_if_checkpointed(id, epoch)
            if sample.error is None and sample.invalidation is None:
                return sample
            return await _resume_or_seed_retry(id, epoch, sample)

        return EvalSampleSource(read_from_file, error_history_from_file)
    else:

        async def read_from_memory(
            id: int | str, epoch: int
        ) -> EvalSample | ResumeCheckpoint | PreviousError | None:
            match = next(
                (
                    sample
                    for sample in (eval_log.samples or [])
                    if sample.id == id and sample.epoch == epoch
                ),
                None,
            )
            if match is not None and match.error is None and match.invalidation is None:
                return match
            return await _resume_or_seed_retry(id, epoch, match)

        memory_error_ids = {
            (sample.id, sample.epoch)
            for sample in (eval_log.samples or [])
            if sample.error is not None
        }

        async def memory_error_history() -> set[tuple[int | str, int]]:
            return memory_error_ids

        return EvalSampleSource(read_from_memory, memory_error_history)


def create_sample_semaphore(
    config: EvalConfig,
    generate_config: GenerateConfig,
    modelapi: ModelAPI | None = None,
    task_id: str | None = None,
) -> contextlib.AbstractAsyncContextManager[Any]:
    """Create (or reuse) the task's sample-concurrency semaphore.

    Bounds how many samples run at once so setup work (sandboxes, state)
    stays proportional to what the model can actually serve: an explicit
    ``max_samples`` is honored as a user setpoint; otherwise the adaptive
    path follows the model's connection controller, and the static path
    defaults from ``max_connections`` (so the connection pool always
    saturates).

    Semaphores are task-scoped, not attempt-scoped: they're registered under
    ``task_id`` and an in-process retry reuses its predecessor's semaphore,
    so a mid-flight ``ctl limits --max-samples`` retune survives the retry
    rather than silently reverting to the config value (see the registry's
    rationale in ``_concurrency.py``). The control channel's modify-limits
    directive reads and retunes ``max_samples`` through this same registry
    entry.
    """
    from inspect_ai.model._model import model_concurrency_key
    from inspect_ai.util._concurrency import (
        DynamicSampleLimiter,
        ResizableLimiter,
        adaptive_active,
        register_task_sample_semaphore,
        resolve_adaptive,
        task_sample_semaphore,
    )

    # sample semaphores are task-scoped, not attempt-scoped: an in-process
    # retry reuses its predecessor's semaphore so a mid-flight `ctl limits
    # --max-samples` retune survives the retry rather than silently reverting
    # to the config value (see the registry's rationale in _concurrency.py)
    if task_id is not None:
        existing = task_sample_semaphore(task_id)
        if existing is not None:
            return existing

    semaphore: "ResizableLimiter | DynamicSampleLimiter"
    if config.max_samples is not None:
        # explicit max_samples wins silently — under default-on
        # adaptive_connections, warning when max_samples < adaptive.max
        # would fire for nearly every deliberate max_samples setting.
        # ResizableLimiter (not a fixed Semaphore) so the control channel can
        # retune max_samples mid-eval (see design/control-channel.md phase 3).
        semaphore = ResizableLimiter(config.max_samples)
    elif adaptive_active(
        generate_config.adaptive_connections,
        generate_config.max_connections,
        generate_config.batch,
    ):
        # adaptive: dynamic limiter that tracks this model's controller —
        # sample concurrency grows with the controller's current limit so setup
        # work (sandboxes etc.) stays proportional to actual model concurrency.
        # The connection-pool key scopes the limiter to the task's own model's
        # controller: controllers for other models in the process (graders,
        # eval-set siblings) must not drive it. Without a ModelAPI (tests) the
        # sentinel key matches no controller and the limiter stays at its
        # initial value.
        # Both explicit max_connections and batch mode silently override
        # adaptive (matches the precedence in Model._connection_concurrency).
        semaphore = DynamicSampleLimiter(
            resolve_adaptive(generate_config.adaptive_connections),
            model_concurrency_key(modelapi) if modelapi else "<no-model>",
        )
    else:
        # static path (default max_samples derived from max_connections).
        # ResizableLimiter so the control channel can retune it mid-eval.
        max_samples = (
            generate_config.max_connections
            if generate_config.max_connections is not None
            else DEFAULT_MAX_CONNECTIONS_BATCH
            if generate_config.batch
            else modelapi.max_connections()
            if modelapi
            else DEFAULT_MAX_CONNECTIONS
        )
        semaphore = ResizableLimiter(max_samples)

    if task_id is not None:
        register_task_sample_semaphore(task_id, semaphore)
    return semaphore


def _eval_retry_error(
    error: EvalError,
    logger: TaskLogger | None = None,
    sample_id: str | int | None = None,
    epoch: int | None = None,
) -> EvalRetryError:
    """Create retry error with events from the most recent ModelEvent onward."""
    from inspect_ai.event._model import ModelEvent

    if logger is not None and logger.buffer_db is not None and sample_id is not None:
        if epoch is None:
            raise ValueError(
                "epoch is required when reading retry events from buffer DB"
            )
        with logger.buffer_db.open_sample_history(sample_id, epoch) as sample_history:
            return eval_retry_error_from_history(error, sample_history)

    sample_transcript = transcript()
    transcript_history = sample_transcript.history
    recent_events = (
        transcript_history.events_since_last(ModelEvent)
        if transcript_history.full_history_available
        else []
    )
    return EvalRetryError(
        message=error.message,
        traceback=error.traceback,
        traceback_ansi=error.traceback_ansi,
        events=recent_events,
    )


def _eval_retry_error_from_sample(sample: EvalSample) -> EvalRetryError:
    """Build an `EvalRetryError` from a prior attempt's errored sample.

    Mirrors `_eval_retry_error` (events back to the last ModelEvent) but
    sources the error and events from a stored sample read via the sample
    source rather than the live transcript.
    """
    from inspect_ai.event._model import ModelEvent

    assert sample.error is not None
    events = sample.events or []
    recent_events = list(events)
    for i in range(len(events) - 1, -1, -1):
        if isinstance(events[i], ModelEvent):
            recent_events = list(events[i:])
            break
    return EvalRetryError(
        message=sample.error.message,
        traceback=sample.error.traceback,
        traceback_ansi=sample.error.traceback_ansi,
        events=recent_events,
    )


def _is_cancellation_error(error: EvalError) -> bool:
    # A sample cancelled because a sibling errored (the task was torn down
    # for a task-level retry) never genuinely failed, so it must not count
    # as a retry when the task is re-run.
    return is_cancellation_message(error.message)


def _seed_error_retries(sample: EvalSample) -> list[EvalRetryError]:
    """Prior-attempt retry history to seed a re-run's `error_retries`.

    Carries forward the sample's own `error_retries` (genuine failures from
    earlier attempts) and appends the terminal error — but only when that
    error is a genuine failure. A cancellation (sibling failure tore the
    task down) is skipped so it doesn't inflate the retry count.
    """
    seed = list(sample.error_retries or [])
    if sample.error is not None and not _is_cancellation_error(sample.error):
        seed.append(_eval_retry_error_from_sample(sample))
    return seed


async def carry_forward_unlogged_samples(
    logger: TaskLogger,
    sample_source: EvalSampleSource | None,
    sample_ids: list[str | int],
    epochs: int,
    log_images: bool,
) -> None:
    """Re-log carried error history for planned samples this attempt never logged.

    When a task fails and is retried, the next attempt's sample source is
    built from THIS attempt's log. A sample that errored in an earlier
    attempt but was still pending when this attempt was torn down (a sibling
    failed first, cancelling the rest) would otherwise be absent from this
    log — breaking the per-attempt retry-history chain so the eventual
    surviving sample under-reports its retry count.

    Re-logging the prior record for such samples keeps the chain intact.
    Only samples carrying genuine error history (`PreviousError`) need this,
    and only the prior attempt's *errored* samples can yield one — so the
    probe set is ``sample_source.error_history_ids()`` (at most one
    summaries read) rather than the full plan. This runs at teardown,
    inside the cancellation shield on the Ctrl-C path: probing every
    planned ``(id, epoch)`` stalled shutdown of a large remote retry for
    minutes, uninterruptibly.
    """
    if sample_source is None:
        return
    candidates = await sample_source.error_history_ids()
    if not candidates:
        return
    summaries = await logger.sample_summaries()
    logged = {(s.id, s.epoch) for s in (summaries or [])}
    planned = {
        (sample_id, epoch) for sample_id in sample_ids for epoch in range(1, epochs + 1)
    }
    # sorted for a deterministic re-log order
    for sample_id, epoch in sorted(candidates, key=lambda k: (str(k[0]), k[1])):
        if (sample_id, epoch) in logged or (sample_id, epoch) not in planned:
            continue
        previous = await sample_source.lookup(sample_id, epoch)
        if isinstance(previous, PreviousError):
            await logger.complete_sample(
                condense_sample(previous.sample, log_images), flush=True
            )


async def _finish_task_log(
    *,
    logger: TaskLogger,
    sample_source: EvalSampleSource | None,
    sample_ids: list[str | int],
    epochs: int,
    log_images: bool,
    status: EvalStatus,
    stats: EvalStats,
    results: EvalResults | None = None,
    reductions: list[EvalSampleReductions] | None = None,
    error: EvalError | None = None,
) -> EvalLog:
    """Finish the task log, preserving retry history first on non-success.

    The single finish chokepoint for ``task_run``'s terminal branches: any
    non-success finish is (or may be) a teardown that left planned samples
    unlogged this attempt, and this attempt's log seeds the next attempt — so
    unlogged samples' prior-attempt history is carried forward before the
    finish is written. Routing every terminal branch through here means a
    finish path can't forget the carry-forward (the external-cancellation
    branch once did, silently dropping retry history on Ctrl-C — and
    cancelled logs ARE retry seeds: ``retryable_eval_logs`` includes them and
    eval-set treats any non-success log as incomplete).

    Safe to call on fully-logged attempts (eg. an ``error`` status from the
    ``fail_on_error`` threshold with every sample run): the carry-forward
    re-logs only planned samples absent from this attempt's log whose source
    carries genuine prior error history (``PreviousError``), so it degrades
    to a no-op.
    """
    if status != "success":
        await carry_forward_unlogged_samples(
            logger, sample_source, sample_ids, epochs, log_images
        )
    return await logger.log_finish(status, stats, results, reductions, error)
