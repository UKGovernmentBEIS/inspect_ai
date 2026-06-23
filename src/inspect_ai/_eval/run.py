import logging
import os
import sys
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, NamedTuple, Set, cast

from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._util.environ import environ_vars
from inspect_ai._util.file import cleanup_s3_sessions
from inspect_ai._util.task import task_display_name
from inspect_ai._util.trace import trace_action
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._checkpoint import CheckpointConfig

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._display import display
from inspect_ai._display.core.active import (
    clear_task_screen,
    init_task_screen,
)
from inspect_ai._display.core.display import CancelType, TaskCancel, TaskSpec
from inspect_ai._eval.task.scan import Scanners
from inspect_ai._util.error import PrerequisiteError, exception_message
from inspect_ai._util.path import chdir
from inspect_ai.dataset._dataset import Dataset
from inspect_ai.log import EvalConfig, EvalLog
from inspect_ai.log._file import EvalLogInfo
from inspect_ai.log._recorders import Recorder
from inspect_ai.model import GenerateConfigArgs
from inspect_ai.model._model import Model, ModelName
from inspect_ai.scorer._metric import to_metric_specs
from inspect_ai.scorer._reducer import ScoreReducer, reducer_log_names
from inspect_ai.scorer._reducer.registry import validate_reducer
from inspect_ai.scorer._scorer import as_scorer_spec
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._checkpoint._layout import (
    eval_checkpoints_dir_from_config,
)
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironmentConfigType,
    TaskCleanup,
    TaskInit,
)
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

from .loader import (
    as_solver_spec,
    solver_from_spec,
)
from .task.log import TaskLogger
from .task.resolved import ResolvedTask
from .task.run import (
    TaskRunOptions,
    eval_log_sample_source,
    plan_agent_name,
    resolve_plan,
    task_run,
)
from .task.sandbox import TaskSandboxEnvironment, resolve_sandbox_for_task_and_sample
from .task.task_source import TaskSource
from .task.util import slice_dataset, task_run_dir

log = logging.getLogger(__name__)


@dataclass
class TaskInjection:
    """Source of additional tasks for a live (TaskSource-driven) eval run.

    Built by ``eval_async`` from the run's enqueuer + ``TaskSource``; consumed by
    :func:`eval_run`, which wraps it with task preparation (``TaskRunOptions`` +
    incremental sandbox startup) before handing a prepared feed to
    :func:`run_multiple`.
    """

    drain: Callable[[], list["ResolvedTask"]]
    """Non-blocking: resolved tasks buffered (enqueued) since the last call."""

    next: Callable[[], Awaitable[list["ResolvedTask"] | None]]
    """Blocking: the next batch of resolved tasks, or ``None`` when complete."""

    set_wake: Callable[[Callable[[], None]], None]
    """Register a callback fired when new tasks are enqueued (wakes dispatch)."""


@dataclass
class PreparedFeed:
    """A live feed of prepared ``TaskRunOptions`` consumed by :func:`run_multiple`."""

    drain: Callable[[], Awaitable[list[TaskRunOptions]]]
    next: Callable[[], Awaitable[list[TaskRunOptions] | None]]
    set_wake: Callable[[Callable[[], None]], None]


async def eval_run(
    eval_set_id: str | None,
    run_id: str,
    tasks: list[ResolvedTask],
    parallel: int,
    eval_config: EvalConfig,
    eval_checkpoint: CheckpointConfig | None,
    recorder: Recorder,
    header_only: bool,
    epochs_reducer: list[ScoreReducer] | None = None,
    solver: Solver | SolverSpec | None = None,
    scanner: "Scanners | None" = None,
    scan_id: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    debug_errors: bool = False,
    run_samples: bool = True,
    score: bool = True,
    task_retry_attempts: int | None = 0,
    task_source: "TaskSource | None" = None,
    inject: TaskInjection | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    # get cwd before any switching
    eval_wd = os.getcwd()

    # resolve solver and solver spec
    if isinstance(solver, Solver):
        eval_solver = solver
        eval_solver_spec = as_solver_spec(solver)
    elif isinstance(solver, SolverSpec):
        eval_solver = solver_from_spec(solver)
        eval_solver_spec = solver
    else:
        eval_solver = None
        eval_solver_spec = None

    # manage sandbox environments incrementally (initial + any injected tasks),
    # tearing them all down once at the end of the run
    sandbox_manager = SandboxManager(
        eval_config,
        eval_config.sandbox_cleanup is not False,
    )

    async def prepare_options(
        resolved_tasks: list[ResolvedTask],
    ) -> list[TaskRunOptions]:
        # ensure sample ids
        for resolved_task in resolved_tasks:
            # add sample ids to dataset if they aren't there (start at 1 not 0)
            task = resolved_task.task
            for id, sample in enumerate(task.dataset):
                if sample.id is None:
                    sample.id = id + 1

            # Ensure sample ids are unique
            ensure_unique_ids(task.dataset)

        # run startup pass for the sandbox environments these tasks need
        if run_samples and any(t.has_sandbox for t in resolved_tasks):
            await sandbox_manager.start(resolved_tasks)

        # create run tasks
        task_run_options: list[TaskRunOptions] = []
        for resolved_task in resolved_tasks:
            with chdir(task_run_dir(resolved_task.task)):
                # tasks can provide their epochs, message_limit,
                # token_limit, time_limit, and fail_on_error so broadcast these
                # into the eval config (so long as they aren't overriding a
                # value specified from eval() or the CLI)
                task = resolved_task.task
                task_eval_config = eval_config.model_copy()

                # sample_ids can be specified per task
                task_eval_config.sample_id = resolve_task_sample_ids(
                    resolved_task.task.name, task_eval_config.sample_id
                )

                # resolve the task scorers
                eval_scorer_specs = (
                    [as_scorer_spec(scorer) for scorer in task.scorer]
                    if task.scorer is not None
                    else None
                )

                # resolve task metrics
                eval_metrics = (
                    to_metric_specs(task.metrics) if task.metrics is not None else None
                )

                # epochs
                if task_eval_config.epochs is None:
                    task_eval_config.epochs = task.epochs
                else:
                    task.epochs = task_eval_config.epochs

                # epochs reducer
                if epochs_reducer is not None:
                    # override task (eval_config already reflects epochs_reducer)
                    task.epochs_reducer = epochs_reducer
                else:
                    # use task (eval_config needs to be updated to reflect task reducer)
                    task_eval_config.epochs_reducer = reducer_log_names(
                        task.epochs_reducer
                    )

                # validate task epochs
                if task.epochs and task.epochs_reducer:
                    for reducer in task.epochs_reducer:
                        validate_reducer(task.epochs, reducer)

                # sample message limit
                if task_eval_config.message_limit is None:
                    task_eval_config.message_limit = task.message_limit
                else:
                    task.message_limit = task_eval_config.message_limit

                # sample token limit
                if task_eval_config.token_limit is None:
                    task_eval_config.token_limit = task.token_limit
                else:
                    task.token_limit = task_eval_config.token_limit

                # sample turn limit
                if task_eval_config.turn_limit is None:
                    task_eval_config.turn_limit = task.turn_limit
                else:
                    task.turn_limit = task_eval_config.turn_limit

                # sample time limit
                if task_eval_config.time_limit is None:
                    task_eval_config.time_limit = task.time_limit
                else:
                    task.time_limit = task_eval_config.time_limit

                # sample execution limit
                if task_eval_config.working_limit is None:
                    task_eval_config.working_limit = task.working_limit
                else:
                    task.working_limit = task_eval_config.working_limit

                # sample cost limit
                if task_eval_config.cost_limit is None:
                    task_eval_config.cost_limit = task.cost_limit
                else:
                    task.cost_limit = task_eval_config.cost_limit

                # fail_on_error
                if task_eval_config.fail_on_error is None:
                    task_eval_config.fail_on_error = task.fail_on_error
                else:
                    task.fail_on_error = task_eval_config.fail_on_error

                # continue_on_fail
                if task_eval_config.continue_on_fail is None:
                    task_eval_config.continue_on_fail = task.continue_on_fail
                else:
                    task.continue_on_fail = task_eval_config.continue_on_fail

                # score_on_error
                if task_eval_config.score_on_error is None:
                    task_eval_config.score_on_error = task.score_on_error
                else:
                    task.score_on_error = task_eval_config.score_on_error

                # merge eval-level and task-level tags
                merged_tags = list(set(tags or []) | set(task.tags or [])) or None

                # create and track the logger
                logger = TaskLogger(
                    task_name=task.name,
                    task_version=task.version,
                    task_file=resolved_task.task_file,
                    task_registry_name=resolved_task.task.registry_name,
                    task_display_name=resolved_task.task.display_name,
                    task_id=resolved_task.id,
                    eval_set_id=eval_set_id,
                    run_id=run_id,
                    solver=eval_solver_spec,
                    tags=merged_tags,
                    model=resolved_task.model,
                    model_roles=resolved_task.model_roles,
                    dataset=task.dataset,
                    scorer=eval_scorer_specs,
                    metrics=eval_metrics,
                    sandbox=resolved_task.sandbox,
                    task_attribs=task.attribs,
                    task_args=getattr(
                        task, TASK_ALL_PARAMS_ATTR, resolved_task.task_args
                    ),
                    task_args_passed=resolved_task.task_args,
                    model_args=resolved_task.model.model_args,
                    eval_config=task_eval_config,
                    metadata=((metadata or {}) | (task.metadata or {})) or None,
                    viewer=task.viewer,
                    recorder=recorder,
                    header_only=header_only,
                )
                await logger.init()

                # append task
                task_run_options.append(
                    TaskRunOptions(
                        task=task,
                        model=resolved_task.model,
                        model_roles=resolved_task.model_roles,
                        sandbox=resolved_task.sandbox,
                        checkpoint=resolved_task.checkpoint,
                        eval_checkpoint=eval_checkpoint,
                        logger=logger,
                        eval_wd=eval_wd,
                        config=task_eval_config,
                        solver=eval_solver,
                        scanner=scanner,
                        scan_id=scan_id,
                        tags=merged_tags,
                        run_samples=run_samples,
                        score=score,
                        debug_errors=debug_errors,
                        sample_source=resolved_task.sample_source,
                        kwargs=kwargs,
                        initial_model_usage=resolved_task.initial_model_usage,
                        initial_role_usage=resolved_task.initial_role_usage,
                        task_source=task_source,
                    )
                )
        return task_run_options

    try:
        # prepare the initial (seed) tasks
        initial_options = await prepare_options(tasks)
        assert initial_options or inject is not None, "Must encounter a task"

        # multiple mode is for running/displaying multiple
        # task definitions, which requires some smart scheduling
        # to ensure that we spread work among models

        # a live (TaskSource-driven) run feeds additional tasks while it is in
        # progress; prepare each injected batch on the fly. Both dispatchers
        # below accept this feed, so a TaskSource works with or without retries.
        feed: PreparedFeed | None = None
        if inject is not None:

            async def feed_drain() -> list[TaskRunOptions]:
                return await prepare_options(inject.drain())

            async def feed_next() -> list[TaskRunOptions] | None:
                more = await inject.next()
                return await prepare_options(more) if more else None

            feed = PreparedFeed(
                drain=feed_drain, next=feed_next, set_wake=inject.set_wake
            )

        # `parallel` is the max concurrent (task × model) units; the
        # scheduler spreads work across models and caps concurrency there,
        # so e.g. parallel==1 runs one unit at a time (model-by-model for a
        # single task definition).
        if task_retry_attempts:
            return await run_task_retry_attempts(
                initial_options,
                parallel,
                task_retry_attempts=task_retry_attempts,
                debug_errors=debug_errors,
                feed=feed,
            )

        return await run_multiple(
            initial_options, parallel, debug_errors=debug_errors, feed=feed
        )

    finally:
        # shutdown sandbox environments
        try:
            await sandbox_manager.shutdown()
        except BaseException as ex:
            log.warning(
                f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
            )

        # clean up cached S3 sessions to prevent "Unclosed connector" warnings
        try:
            await cleanup_s3_sessions()
        except Exception as ex:
            log.warning(f"Error cleaning up S3 sessions: {exception_message(ex)}")


class _Wake:
    """One-shot wake signal that can be re-armed (set on completion / injection).

    Safe under cooperative scheduling: the only await is on ``wait()``; the
    re-arm assignment afterwards runs without a yield point, so a concurrent
    ``set()`` can't be lost between waking and re-arming.
    """

    def __init__(self) -> None:
        self._event = anyio.Event()

    def set(self) -> None:
        self._event.set()

    async def wait(self) -> None:
        await self._event.wait()
        self._event = anyio.Event()


def _empty_feed() -> PreparedFeed:
    """A feed that supplies nothing — turns the dispatcher into a fixed-set run."""

    async def drain() -> list[TaskRunOptions]:
        return []

    async def next() -> list[TaskRunOptions] | None:
        return None

    def set_wake(_: Callable[[], None]) -> None:
        pass

    return PreparedFeed(drain=drain, next=next, set_wake=set_wake)


class TaskRunResult(NamedTuple):
    log: EvalLog | None
    """The task's log, or ``None`` if it was cancelled before producing one."""

    cancel_type: CancelType
    """How the task was cancelled (``None`` if it ran to completion)."""


async def _run_task(options: TaskRunOptions, can_retry: bool = False) -> TaskRunResult:
    """Run one task in its own cancel scope so cancelling it can't affect siblings.

    Returns the task's :class:`EvalLog` (``None`` if it was cancelled before
    producing one) together with the ``CancelType`` it was cancelled with, so a
    caller managing retries can distinguish a retry/abort request from an
    ordinary error. ``can_retry`` is surfaced to the task (via ``TaskCancel``) so
    it knows whether requesting a retry will be honoured. Re-raises (after
    logging) the rare error that escapes a task — e.g. a failure during the final
    log write.
    """
    result: EvalLog | None = None
    cancel_type: CancelType = None
    try:
        with trace_action(
            log, "Run Task", f"task: {options.task.name} ({options.model})"
        ):
            # a per-task group so a task cancelling itself doesn't cancel siblings
            async with anyio.create_task_group() as task_tg:
                task_cancel = TaskCancel(
                    can_retry=can_retry, cancel_task=lambda _: None
                )

                def cancel_task(
                    type: CancelType,
                    cancel_tg: TaskGroup = task_tg,
                    tc: TaskCancel = task_cancel,
                ) -> None:
                    nonlocal cancel_type
                    cancel_type = type
                    tc.cancel_type = type
                    if type:
                        cancel_tg.cancel_scope.cancel()

                task_cancel.cancel_task = cancel_task

                async def run() -> None:
                    nonlocal result
                    result = await task_run(options, task_cancel=task_cancel)

                task_tg.start_soon(run)
    except Exception as ex:
        # errors generally don't escape from tasks (the exception being if an
        # error occurs during the final write of the log)
        log.error(
            f"Task '{options.task.name}' encountered an error during finalisation: {inner_exception(ex)}"
        )
        raise
    return TaskRunResult(result, cancel_type)


# multiple mode -- run multiple logical tasks with bounded, model-balanced
# concurrency. The task set may be fixed (``feed is None``) or open (a feed
# supplies more while the run is in progress); a fixed set is just a run whose
# feed is immediately exhausted, so both share one dispatcher.
async def run_multiple(
    tasks: list[TaskRunOptions],
    parallel: int,
    debug_errors: bool = False,
    feed: PreparedFeed | None = None,
) -> list[EvalLog]:
    """Run tasks with bounded, model-balanced concurrency.

    The set may be fixed (``feed is None``) or open: ``feed.drain()``
    (non-blocking) yields tasks enqueued since the last cycle and ``feed.next()``
    (blocking) yields the next batch, returning ``None`` when the source is
    exhausted. The run completes when nothing is pending, nothing is in flight,
    and the feed is exhausted (immediately so for a fixed set). A cancelled task
    ends the run.
    """
    feed = feed or _empty_feed()

    # model-balancing state (grows as tasks are injected). Keyed by the Model
    # object (identity), not str(model): a provider may rewrite its model name
    # mid-run (e.g. vLLM resolving a "base:adapter" LoRA spec to "base" on the
    # first generate()), which would make the decrement key differ from the
    # increment key and raise KeyError at finalisation. The connection pool that
    # balancing spreads load across belongs to the Model instance, not its name,
    # so identity is the right key; eval_resolve_tasks shares one Model object
    # across all of a model's tasks. (Relies on Model being identity-hashable —
    # a plain class, not a frozen dataclass with __eq__.)
    model_counts: dict[Model, int] = {}

    def note_models(options: list[TaskRunOptions]) -> None:
        for t in options:
            model_counts.setdefault(t.model, 0)

    # pending (index, task) pairs: initial tasks keep their original order and
    # injected tasks are appended in arrival order, so results sort stably
    note_models(tasks)
    pending: list[tuple[int, TaskRunOptions]] = list(enumerate(tasks))
    next_index = len(tasks)
    results: list[tuple[int, EvalLog]] = []
    in_flight = 0
    cancelled = False
    source_done = False

    # woken on each task completion and on each injection (enqueue)
    wake = _Wake()
    feed.set_wake(wake.set)

    def add(options: list[TaskRunOptions]) -> None:
        nonlocal next_index
        note_models(options)
        pending.extend((next_index + i, opts) for i, opts in enumerate(options))
        next_index += len(options)
        display().update_task_count(len(options))

    def pick_balanced() -> tuple[int, TaskRunOptions]:
        # among models that have pending tasks, pick the least-used one (keeps as
        # many different models running concurrently as possible)
        models_with_pending = {opts.model for _, opts in pending}
        model = min(models_with_pending, key=lambda m: model_counts[m])
        item = next(p for p in pending if p[1].model is model)
        pending.remove(item)
        return item

    async with display().task_screen(task_specs(tasks), parallel=True) as screen:
        init_task_screen(screen)
        try:
            async with anyio.create_task_group() as tg:

                async def run_one(idx: int, options: TaskRunOptions) -> None:
                    nonlocal in_flight, cancelled
                    result: EvalLog | None = None
                    try:
                        result = (await _run_task(options)).log
                    finally:
                        in_flight -= 1
                        model_counts[options.model] -= 1
                        if result is not None:
                            results.append((idx, result))
                        if result is None or result.status == "cancelled":
                            cancelled = True
                        wake.set()

                while True:
                    # pick up tasks buffered since the last cycle (non-blocking)
                    injected = await feed.drain()
                    if injected:
                        add(injected)

                    # dispatch up to the concurrency cap (model-balanced)
                    while not cancelled and in_flight < parallel and pending:
                        idx, options = pick_balanced()
                        model_counts[options.model] += 1
                        in_flight += 1
                        tg.start_soon(run_one, idx, options)

                    if cancelled:
                        break

                    # work still queued or running: wait for a completion or a
                    # new injection, then re-evaluate
                    if pending or in_flight > 0:
                        await wake.wait()
                        continue

                    # fully idle: ask the source for more (may block) and finish
                    # when it is exhausted
                    if source_done:
                        break
                    more = await feed.next()
                    if more is None:
                        source_done = True
                    else:
                        add(more)
        # exceptions can escape when debug_errors is True and that's okay
        except ExceptionGroup as ex:
            if debug_errors:
                raise ex.exceptions[0]
            else:
                raise
        except anyio.get_cancelled_exc_class():
            pass
        finally:
            clear_task_screen()

    # sort results by index and return just the values
    return [r for _, r in sorted(results)]


class PendingTask(NamedTuple):
    idx: int
    options: TaskRunOptions
    retries_remaining: int


# run multiple logical tasks with bounded, model-balanced concurrency and
# per-task retries, optionally fed additional tasks while in progress (a live
# TaskSource-driven run). Shares run_multiple's central-dispatch design and adds
# retries: a task that errors (or requests a retry) is re-queued under its
# original index — a fresh log entry, completed samples reused — until its
# retries are exhausted. (run_multiple is the retries==0 baseline kept until this
# path is fully proven; this function is meant to subsume it.)
async def run_task_retry_attempts(
    tasks: list[TaskRunOptions],
    parallel: int,
    task_retry_attempts: int,
    debug_errors: bool = False,
    feed: PreparedFeed | None = None,
) -> list[EvalLog]:
    """Run tasks with bounded, model-balanced concurrency and per-task retries.

    Like :func:`run_multiple`, the set may be fixed (``feed is None``) or open (a
    feed supplies more while the run is in progress). A task whose log comes back
    with an error — or which requests a retry via its ``TaskCancel`` — is
    re-queued (reusing completed samples) until ``task_retry_attempts`` is
    exhausted; an abort or external cancellation is never retried.
    """
    feed = feed or _empty_feed()

    # model-balancing state (grows as tasks are injected). Keyed by the Model
    # object (identity), not str(model): a provider may rewrite its model name
    # mid-run (e.g. vLLM resolving a "base:adapter" LoRA spec to "base" on the
    # first generate()), which would make the decrement key differ from the
    # increment key and raise KeyError at finalisation. The connection pool that
    # balancing spreads load across belongs to the Model instance, not its name,
    # so identity is the right key; eval_resolve_tasks shares one Model object
    # across all of a model's tasks. (Relies on Model being identity-hashable —
    # a plain class, not a frozen dataclass with __eq__.)
    model_counts: dict[Model, int] = {}

    def note_models(options: list[TaskRunOptions]) -> None:
        for t in options:
            model_counts.setdefault(t.model, 0)

    # pending tasks: initial tasks keep their original order and injected tasks
    # are appended in arrival order, so results sort stably. A retry re-queues
    # under the same index, overwriting the failed attempt's result.
    note_models(tasks)
    pending: list[PendingTask] = [
        PendingTask(idx=i, options=opts, retries_remaining=task_retry_attempts)
        for i, opts in enumerate(tasks)
    ]
    next_index = len(tasks)
    results: dict[int, EvalLog] = {}
    in_flight = 0
    cancelled = False
    source_done = False

    # woken on each task completion and on each injection (enqueue)
    wake = _Wake()
    feed.set_wake(wake.set)

    def add(options: list[TaskRunOptions]) -> None:
        nonlocal next_index
        note_models(options)
        pending.extend(
            PendingTask(
                idx=next_index + i, options=opts, retries_remaining=task_retry_attempts
            )
            for i, opts in enumerate(options)
        )
        next_index += len(options)
        display().update_task_count(len(options))

    def pick_balanced() -> PendingTask:
        # among models that have pending tasks, pick the least-used one (keeps as
        # many different models running concurrently as possible)
        models_with_pending = {p.options.model for p in pending}
        model = min(models_with_pending, key=lambda m: model_counts[m])
        item = next(p for p in pending if p.options.model is model)
        pending.remove(item)
        return item

    async with display().task_screen(task_specs(tasks), parallel=True) as screen:
        init_task_screen(screen)
        try:
            async with anyio.create_task_group() as tg:

                async def run_one(item: PendingTask) -> None:
                    nonlocal in_flight, cancelled
                    options = item.options
                    run = await _run_task(options, can_retry=item.retries_remaining > 0)
                    result = run.log

                    # decide whether to retry: on an error or an explicit retry
                    # request, but never on an abort or external (ctrl+c)
                    # cancellation (which ends the whole run)
                    retry = False
                    if result is None or result.status == "cancelled":
                        cancelled = True
                    elif run.cancel_type == "retry":
                        log.info(
                            f"Task '{options.task.name}' was cancelled with retry "
                            f"requested — {item.retries_remaining} retries remaining"
                        )
                        retry = True
                    elif run.cancel_type == "abort":
                        log.info(
                            f"Task '{options.task.name}' was cancelled with abort requested"
                        )
                    elif result.status == "error":
                        retry = True
                    retry = retry and item.retries_remaining > 0

                    # build the requeued task before releasing the in-flight slot:
                    # reinit is async, and were the slot freed first the dispatcher
                    # could observe an idle run mid-reinit and finish early
                    retry_item: PendingTask | None = None
                    if retry and result is not None:
                        # build sample_source from the failed log so completed
                        # samples are reused on retry (mirrors legacy eval_set retry)
                        failed_log_info = EvalLogInfo(
                            name=options.logger.location,
                            type="file",
                            size=0,
                            mtime=None,
                            task=options.task.name,
                            task_id=options.logger.eval.task_id,
                            suffix=None,
                        )
                        sample_source = eval_log_sample_source(
                            result,
                            failed_log_info,
                            options.task.dataset,
                            eval_checkpoints_dir_from_config(
                                options.logger.location,
                                options.checkpoint,
                                options.eval_checkpoint,
                            ),
                        )

                        # reinit logger for a fresh eval entry
                        await options.logger.reinit()

                        retry_attempt = task_retry_attempts - item.retries_remaining + 1
                        retry_display_name = (
                            f"{options.task.name} "
                            f"(retry {retry_attempt} of {task_retry_attempts})"
                        )
                        retry_item = PendingTask(
                            idx=item.idx,
                            options=replace(
                                options,
                                sample_source=sample_source,
                                display_name=retry_display_name,
                            ),
                            retries_remaining=item.retries_remaining - 1,
                        )

                    # finalize atomically (no awaits below) so the dispatcher sees
                    # a consistent (in_flight, pending) snapshot
                    in_flight -= 1
                    model_counts[options.model] -= 1
                    if result is not None:
                        results[item.idx] = result
                    if retry_item is not None:
                        pending.append(retry_item)
                        log.info(
                            f"Retrying task '{options.task.name}' ({options.model}) "
                            f"— {retry_item.retries_remaining} retries remaining"
                        )
                    wake.set()

                while True:
                    # pick up tasks buffered since the last cycle (non-blocking)
                    injected = await feed.drain()
                    if injected:
                        add(injected)

                    # dispatch up to the concurrency cap (model-balanced)
                    while not cancelled and in_flight < parallel and pending:
                        item = pick_balanced()
                        model_counts[item.options.model] += 1
                        in_flight += 1
                        tg.start_soon(run_one, item)

                    if cancelled:
                        break

                    # work still queued or running (incl. pending retries): wait
                    # for a completion or a new injection, then re-evaluate
                    if pending or in_flight > 0:
                        await wake.wait()
                        continue

                    # fully idle: ask the source for more (may block) and finish
                    # when it is exhausted
                    if source_done:
                        break
                    more = await feed.next()
                    if more is None:
                        source_done = True
                    else:
                        add(more)
        # exceptions can escape when debug_errors is True and that's okay
        except ExceptionGroup as ex:
            if debug_errors:
                raise ex.exceptions[0]
            else:
                raise
        except anyio.get_cancelled_exc_class():
            pass
        finally:
            clear_task_screen()

    # sort results by index and return just the values
    return [v for _, v in sorted(results.items())]


def resolve_task_sample_ids(
    task: str, sample_id: str | int | list[str] | list[int] | list[str | int] | None
) -> str | int | list[str] | list[int] | list[str | int] | None:
    def collect_for_task(sample: str | int) -> str | int | None:
        if isinstance(sample, str):
            scoped = sample.split(":", maxsplit=1)
            if len(scoped) > 1:
                if scoped[0].lower() == task.lower():
                    return scoped[1]
                else:
                    return None
            else:
                return sample
        else:
            return sample

    if sample_id is not None:
        if isinstance(sample_id, list):
            ids: list[int | str] = []
            for id in sample_id:
                collect = collect_for_task(id)
                if collect is not None:
                    ids.append(collect)
            return ids

        else:
            collect = collect_for_task(sample_id)
            if collect is not None:
                return collect
            else:
                return []

    else:
        return sample_id


class SandboxManager:
    """Starts sandbox environments incrementally and tears them all down.

    Tasks injected into a live run arrive in batches, so startup must be
    callable repeatedly — :meth:`start` initializes only sandboxenvs not already
    started and accumulates their cleanups; :meth:`shutdown` runs every
    accumulated cleanup once, at the end of the run.
    """

    def __init__(
        self,
        config: EvalConfig,
        cleanup: bool,
    ) -> None:
        self._config = config
        self._cleanup = cleanup
        self._started: Set[TaskSandboxEnvironment] = set()
        self._cleanups: list[
            tuple[TaskCleanup, SandboxEnvironmentConfigType | None, str]
        ] = []

    async def start(self, tasks: list[ResolvedTask]) -> None:
        # find unique sandboxenvs not already started
        sandboxenvs: Set[TaskSandboxEnvironment] = set()
        for task in tasks:
            # resolve each sample and add to sandboxenvs
            resolved_task_sample_ids = resolve_task_sample_ids(
                task.task.name, self._config.sample_id
            )
            dataset = slice_dataset(
                task.task.dataset, self._config.limit, resolved_task_sample_ids
            )
            for sample in dataset:
                sandbox = await resolve_sandbox_for_task_and_sample(
                    task.sandbox, task.task, sample
                )
                if (
                    sandbox is not None
                    and sandbox not in self._started
                    and sandbox not in sandboxenvs
                ):
                    sandboxenvs.add(sandbox)

        if not sandboxenvs:
            return

        # initialiase sandboxenvs (track cleanups)
        with display().suspend_task_app():
            for sandboxenv in sandboxenvs:
                # find type
                sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)

                # run startup
                task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
                with chdir(sandboxenv.run_dir), environ_vars(dict(sandboxenv.env)):
                    await task_init("startup", sandboxenv.sandbox.config)

                # track as started and append cleanup method
                self._started.add(sandboxenv)
                task_cleanup = cast(
                    TaskCleanup, getattr(sandboxenv_type, "task_cleanup")
                )
                self._cleanups.append(
                    (task_cleanup, sandboxenv.sandbox.config, sandboxenv.run_dir)
                )

            # provide some space above task display
            print("")

    async def shutdown(self) -> None:
        with anyio.CancelScope(shield=True):
            for cleanup_jobs in self._cleanups:
                try:
                    cleanup_fn, config, task_run_dir = cleanup_jobs
                    with chdir(task_run_dir):
                        await cleanup_fn("shutdown", config, self._cleanup)
                except BaseException as ex:
                    log.warning(
                        f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                    )


async def startup_sandbox_environments(
    tasks: list[ResolvedTask],
    config: EvalConfig,
    cleanup: bool,
) -> Callable[[], Awaitable[None]]:
    manager = SandboxManager(config, cleanup)
    await manager.start(tasks)
    return manager.shutdown


def task_specs(tasks: list[TaskRunOptions]) -> list[TaskSpec]:
    return [
        TaskSpec(
            task_display_name(task.task.name),
            ModelName(task.model),
            plan_agent_name(resolve_plan(task.task, task.solver)),
        )
        for task in tasks
    ]


def ensure_unique_ids(dataset: Dataset) -> None:
    """
    Validates that all samples in the dataset have unique IDs.

    Raises a error if duplicates are found.

    Args:
        dataset (Datatset): The dataset

    Raises:
        PrerequisiteError: If duplicate IDs are found in the dataset.
    """
    seen_ids: set[int | str | None] = set()
    seen_str_ids: dict[str, int | str] = {}
    for sample in dataset:
        if sample.id in seen_ids:
            raise PrerequisiteError(
                f"The dataset contains duplicate sample ids (duplicate id: {sample.id}). Please ensure each sample has a unique id."
            )
        # sample ids are also keyed by their str() form downstream (.eval log
        # member names, score reduction grouping, buffer database), so e.g.
        # int 1 and str "1" cannot coexist even though they're distinct values
        if sample.id is not None:
            str_id = str(sample.id)
            if str_id in seen_str_ids:
                other = seen_str_ids[str_id]
                raise PrerequisiteError(
                    f"The dataset contains sample ids {other!r} ({type(other).__name__}) "
                    f"and {sample.id!r} ({type(sample.id).__name__}) which share the same "
                    f"string representation '{str_id}'. Sample ids must be unique when "
                    f"converted to strings."
                )
            seen_str_ids[str_id] = sample.id
        seen_ids.add(sample.id)
