import functools
import logging
import os
from contextlib import ExitStack, asynccontextmanager
from contextvars import Context, copy_context
from copy import copy
from dataclasses import replace
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    NamedTuple,
    Set,
    cast,
)

import anyio
from typing_extensions import Unpack

from inspect_ai._control.eval_state import (
    clear_eval_retry_pending,
    get_eval_state,
    latest_eval_for_task,
    mark_eval_retry_pending,
    task_retry_abandoned,
)
from inspect_ai._control.max_tasks import (
    TaskDispatcherStats,
    effective_max_tasks,
    register_task_dispatcher,
    remove_task_dispatcher,
)
from inspect_ai._control.pause import (
    add_dispatch_waker,
    dispatch_model_name,
    remove_dispatch_waker,
    task_dispatch_paused,
    wake_pause_waiters,
)
from inspect_ai._display import display
from inspect_ai._display.core.active import (
    clear_task_screen,
    init_task_screen,
)
from inspect_ai._display.core.display import (
    CancelType,
    TaskCancel,
    TaskScreen,
    TaskSpec,
)
from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._eval.task.scan import Scanners
from inspect_ai._sentinel._config import (
    SentinelProxy,
    Sentinels,
    resolve_sentinel_root,
    sentinel_config,
)
from inspect_ai._util._async import unwrap_exception_group
from inspect_ai._util.error import PrerequisiteError, exception_message
from inspect_ai._util.exception import TaskRetryAbandonedError, TerminateTaskError
from inspect_ai._util.file import cleanup_s3_sessions
from inspect_ai._util.path import chdir
from inspect_ai._util.task import task_display_name
from inspect_ai._util.trace import trace_action
from inspect_ai.approval._policy import ApprovalPolicy, config_from_approval_policies
from inspect_ai.dataset._dataset import Dataset, Sample
from inspect_ai.log import EvalConfig, EvalLog
from inspect_ai.log._file import EvalLogInfo
from inspect_ai.log._recorders import Recorder
from inspect_ai.model import GenerateConfigArgs
from inspect_ai.model._model import Model, ModelName, ensure_model_controller
from inspect_ai.review._policy import ReviewPolicy, config_from_review_policies
from inspect_ai.scorer._metric import to_metric_specs
from inspect_ai.scorer._reducer import ScoreReducer, reducer_log_names
from inspect_ai.scorer._reducer.registry import validate_reducer
from inspect_ai.scorer._scorer import as_scorer_spec
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._checkpoint import CheckpointConfig
from inspect_ai.util._checkpoint._layout import (
    eval_checkpoints_dir_from_config,
)
from inspect_ai.util._display import display_type
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironmentConfigType,
    SandboxEnvironmentSpec,
    TaskCleanup,
    TaskInit,
    set_sandbox_prebuilt,
)
from inspect_ai.util._sandbox.lifecycle import sandbox_lifecycle_scope
from inspect_ai.util._sandbox.registry import registry_find_sandboxenv
from inspect_ai.util._sandbox.setup import task_init_env

from .loader import (
    as_solver_spec,
    solver_from_spec,
)
from .task.enqueue import RunQueue, TaskRecord, creator_model_scope
from .task.log import TaskLogger
from .task.resolved import ResolvedTask
from .task.run import (
    EvalSampleSource,
    TaskRunOptions,
    bound_log_write,
    eval_log_sample_source,
    notify_task_source,
    plan_agent_name,
    resolve_plan,
    task_run,
    unwritten_task_log,
)
from .task.sandbox import (
    SandboxSetupBindings,
    TaskSandboxEnvironment,
    ensure_sandbox_limiter,
    resolve_sandbox,
    resolve_sandbox_for_task_and_sample,
)
from .task.task import Task
from .task.task_source import TaskSource
from .task.util import resolve_task_sample_ids, task_run_dir

log = logging.getLogger(__name__)


async def eval_run(
    eval_set_id: str | None,
    run_id: str,
    queue: RunQueue,
    tasks: list[ResolvedTask],
    parallel: int,
    eval_config: EvalConfig,
    eval_checkpoint: CheckpointConfig | None,
    recorder: Recorder,
    header_only: bool,
    epochs_reducer: list[ScoreReducer] | None = None,
    approval: list[ApprovalPolicy] | None = None,
    review: list[ReviewPolicy] | None = None,
    sentinel: Sentinels | None = None,
    sentinel_proxy: SentinelProxy | None = None,
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
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    """Run the seed `tasks` and every task added to `queue`, under one dispatcher.

    Opens `queue` with this run's task configuration, adds the seed and runs
    the dispatcher until every task has ended. Returns the log of each task
    that has one, in result order.
    """
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

    # manage sandbox environments incrementally (each task's attempt sets up
    # what its samples need), tearing them all down once at the end of the run
    sandbox_manager = SandboxManager(
        eval_config,
        eval_config.sandbox_cleanup is not False,
        launch_dir=eval_wd,
    )

    def configure_task(
        resolved_tasks: list[ResolvedTask], task_names: list[str]
    ) -> list[TaskRunOptions]:
        """Configure tasks for the run, without awaiting.

        Applies the eval-level overrides, runs the configuration checks,
        resolves each task's `task:id` sample selectors against `task_names`
        and constructs its logger, whose log starts with the task's attempt.
        Raises on a configuration error.
        """
        # ensure sample ids
        for resolved_task in resolved_tasks:
            # add sample ids to dataset if they aren't there (start at 1 not 0)
            task = resolved_task.task
            for id, sample in enumerate(task.dataset):
                if sample.id is None:
                    sample.id = id + 1

            # Ensure sample ids are unique
            ensure_unique_ids(task.dataset)

        # create run tasks
        task_run_options: list[TaskRunOptions] = []
        for resolved_task in resolved_tasks:
            # the logger's constructor reads the git context and relative
            # paths against the process directory; nothing here awaits, so no
            # other coroutine sees the change
            with chdir(task_run_dir(resolved_task.task)):
                # tasks can provide their epochs, message_limit,
                # token_limit, time_limit, and fail_on_error so broadcast these
                # into the eval config (so long as they aren't overriding a
                # value specified from eval() or the CLI)
                # Resolve eval-level overrides against a per-run task view so
                # repeated eval() calls on the same Task do not retain them.
                # The copy is shallow: it guards only the direct attribute
                # rebinds below — nested state (dataset, config, reducer list
                # contents) is still shared, so don't write to it in place.
                task = copy(resolved_task.task)
                task_eval_config = eval_config.model_copy()

                # sample_ids can be specified per task
                task_eval_config.sample_id = resolve_task_sample_ids(
                    resolved_task.task.name, task_eval_config.sample_id, task_names
                )
                if task_eval_config.sample_id == [] and eval_config.sample_id != []:
                    log.warning(
                        f"No sample_id selector names task '{task.name}'; "
                        "it will run no samples."
                    )

                # reject options that assume a fixed sample set for a
                # SampleSource-driven task — here, before the task's logger
                # is created, so the config error surfaces pre-run rather
                # than as a task error log
                if task.sample_source is not None:
                    # early stopping managers register the seed only (samples
                    # the source adds are never registered) and samples they
                    # halt complete without notifying the source — a source
                    # blocked awaiting completions would hang the task
                    if task.early_stopping is not None:
                        raise PrerequisiteError(
                            "early_stopping is not currently supported for "
                            "tasks whose dataset is a SampleSource."
                        )
                    # a range limit selects seed samples by position, but
                    # samples the source adds have no position — there is no
                    # coherent way to apply it
                    if isinstance(task_eval_config.limit, tuple):
                        raise PrerequisiteError(
                            "A range --limit (start,end) is not supported for "
                            "tasks whose dataset is a SampleSource (added "
                            "samples have no dataset position); use a plain "
                            "numeric --limit to cap total samples."
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

                # sample concurrency
                if task_eval_config.max_samples is None:
                    task_eval_config.max_samples = task.max_samples
                else:
                    task.max_samples = task_eval_config.max_samples

                # sample message limit
                if task_eval_config.message_limit is None:
                    task_eval_config.message_limit = task.message_limit
                else:
                    task.message_limit = task_eval_config.message_limit

                # sample token limit (limit and metering type travel as a unit)
                if task_eval_config.token_limit is None:
                    task_eval_config.token_limit = task.token_limit
                    task_eval_config.token_limit_type = task.token_limit_type
                else:
                    task.token_limit = task_eval_config.token_limit
                    task.token_limit_type = task_eval_config.token_limit_type

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

                # approval
                if approval:
                    # override task (eval_config already reflects approval)
                    task.approval = approval
                elif task.approval:
                    # use task (eval_config needs to be updated to reflect it)
                    task_eval_config.approval = config_from_approval_policies(
                        task.approval
                    )

                # review
                if review:
                    task.review = review
                elif task.review:
                    task_eval_config.review = config_from_review_policies(task.review)

                # sentinel (eval_config already reflects an eval-level one)
                if sentinel is not None:
                    task.sentinel = sentinel
                elif task.sentinel is not None:
                    task_eval_config.sentinel = sentinel_config(task.sentinel)
                sentinel_root = (
                    resolve_sentinel_root(task.sentinel)
                    if task.sentinel is not None
                    else None
                )

                # merge eval-level and task-level tags
                merged_tags = list(set(tags or []) | set(task.tags or [])) or None

                # create and track the logger
                logger = TaskLogger(
                    task_name=task.name,
                    task_version=task.version,
                    task_file=resolved_task.task_file,
                    task_registry_name=resolved_task.task.registry_name,
                    task_display_name=resolved_task.task.display_name,
                    task_description=task.description,
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
                    headline_metric=task.headline_metric,
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
                    dynamic_dataset=task.sample_source is not None,
                    prior_created=resolved_task.sample_source.prior_created
                    if resolved_task.sample_source is not None
                    else None,
                )

                # each attempt sets up its seed samples' sandboxes, and a
                # SampleSource task's feeder those of the samples it adds;
                # the dict caches this task's metadata-free resolutions
                startup_sandboxes: (
                    Callable[[Iterable[Sample]], Awaitable[None]] | None
                ) = None
                if run_samples:
                    startup_sandboxes = functools.partial(
                        sandbox_manager.start_for_samples, resolved_task, {}
                    )

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
                        sentinel=sentinel_root,
                        sentinel_proxy=sentinel_proxy,
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
                        startup_sandboxes=startup_sandboxes,
                        apply_sandbox_bindings=functools.partial(
                            sandbox_manager.bindings.apply,
                            task_dir=task_run_dir(resolved_task.task, eval_wd),
                        ),
                        input_media_policy=resolved_task.input_media_policy,
                    )
                )
        return task_run_options

    try:
        # own the run's sandbox lifecycle state before any task starts
        sandbox_manager.open()

        queue.open(configure_task, task_retry_attempts=task_retry_attempts or 0)

        # create the seed's model controllers before any setup, so `ctl
        # config` can retune max_connections while images build; an added
        # task's controller is created on its model's first generate
        if run_samples:
            await ensure_controllers(tasks, kwargs)
        seed = queue.add(tasks, seed=True) + queue.add_held()

        # `parallel` is the max concurrent (task × model) units; the
        # dispatcher spreads work across models and caps concurrency there,
        # so e.g. parallel==1 runs one unit at a time (model-by-model for a
        # single task definition).
        return await dispatch_tasks(
            queue,
            task_specs(
                [record.options for record in seed if record.options is not None]
            ),
            parallel=parallel,
            task_source=task_source,
            debug_errors=debug_errors,
        )

    finally:
        # nothing more starts, and every record still open ends
        queue.close()
        queue.end_all()

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


async def ensure_controllers(
    tasks: list[ResolvedTask], kwargs: GenerateConfigArgs
) -> None:
    """Create each task model's adaptive-connections controller now.

    Normally created lazily on the first generate. A bad adaptive setting
    raises here.
    """
    for resolved_task in tasks:
        await ensure_model_controller(
            resolved_task.model,
            resolved_task.task.config.merge(GenerateConfigArgs(**kwargs)),
        )


class TaskRunResult(NamedTuple):
    log: EvalLog | None
    """The task's log, or ``None`` if it was abandoned (see ``abandoned``).
    A task's own abort or retry request always leaves a log (see
    :func:`_run_task`); a run-level cancellation (e.g. ctrl+c) propagates
    from :func:`_run_task` or leaves a ``cancelled`` log."""

    cancel_type: CancelType
    """How the task was cancelled (``None`` if it ran to completion)."""

    abandoned: bool = False
    """The attempt was abandoned at start: a task drain/cancel stamped the
    retry-abandoned registry after the dispatcher dequeued this retry but
    before the attempt registered its ``EvalState``. A dedicated field
    (not an overload of ``log`` or ``cancel_type``) because every natural
    return shape misfires in ``run_one``: a ``None``/cancelled-status log
    reads as an external cancellation and ends the whole dispatch loop,
    and an unstamped error log would queue another retry. ``run_one``
    checks it before the external-cancellation branch and maps it to a
    side-effect-free finalize."""


async def _run_task(
    options: TaskRunOptions, task_cancel: TaskCancel, task_scope: anyio.CancelScope
) -> TaskRunResult:
    """Run one task attempt in its own cancel scope so cancelling it can't affect siblings.

    ``task_cancel`` and ``task_scope`` are the attempt's, created by the
    dispatcher when it started the attempt (see :func:`_attempt_cancel`): an
    abort or retry request cancels ``task_scope``, which encloses only
    ``task_run``, so a request made before the attempt runs stops it at
    ``task_run``'s first checkpoint.

    Returns the task's :class:`EvalLog` together with the ``CancelType`` it
    was cancelled with, so a caller managing retries can distinguish a
    retry/abort request from an ordinary error. The rare error that escapes
    ``task_run`` — a failure to start or write the log itself (e.g.
    ``logger.init()`` or the ``log_start()`` header flush) — is converted
    into an errored :class:`EvalLog` so the dispatcher can retry the task
    rather than tearing down the run; it is re-raised only when
    ``debug_errors`` is set. An error escaping ``task_run`` after the final
    log was written (e.g. from an ``on_task_end`` hook) is logged, and the
    written log is the attempt's result.

    A task's own abort or retry request always leaves a log, so the
    dispatcher never reads it as a run-level cancellation. In ``task_run``
    the request cannot interrupt a final log write: the error-log write
    completes first (see ``abort_bounded_write``), and an interrupted success
    write is followed by the cancel handler's shielded write of the abort's
    error log. When the request interrupts ``task_run`` after the write, the
    written log is returned; when it interrupts it before any final log
    write (before or during ``log_start()``), the attempt returns an unwritten
    "Task cancelled by user" log.

    The run's ``TaskSource`` (if any) gets ``task_complete`` once with the
    log each attempt ends with, written or not (a failed log start or write
    included), but not for an attempt abandoned by the retry-abandon stamp,
    which has no log of its own, nor for a preview (``run_samples=False``).
    It is called after the task's cancel scope has exited, in the task's
    context, so a task's abort does not interrupt it. Once that scope has exited the
    attempt's outcome is decided: a later retry request (e.g. a cancel
    dialog answered while ``task_complete`` runs) is ignored, so it cannot
    re-run a finished task; only an abort of an attempt that ended in error
    is still recorded, so it stops the dispatcher from retrying it. An
    exception from the ``task_complete`` callback is not a task error: it is
    logged, and the attempt keeps its written log and is not retried for it
    (see ``notify_task_source``); with ``debug_errors``, or for an error
    adding the tasks it returned, the exception ends the run. A
    cancellation exception that no cancellation of the run caused, raised
    by ``task_complete`` or escaping ``task_run`` (e.g. from an
    ``on_task_end`` hook), ends the run: the task group would otherwise
    absorb it.
    """
    result: EvalLog | None = None
    abandoned = False
    notifying = False
    run_returned = False
    try:
        with trace_action(
            log, "Run Task", f"task: {options.task.name} ({options.model})"
        ):
            # a per-task group so a task cancelling itself doesn't cancel
            # siblings. A task's abort/retry request cancels task_scope, which
            # encloses only task_run, so the TaskSource is notified outside it
            async with anyio.create_task_group() as task_tg:

                async def run() -> None:
                    nonlocal result, abandoned, notifying, run_returned
                    error_after_write = False
                    with task_scope:
                        try:
                            with creator_model_scope(options.model):
                                result = await task_run(
                                    options, task_cancel=task_cancel
                                )
                        except TaskRetryAbandonedError:
                            # abandoned at attempt start (a drain/cancel
                            # stamped the retry-abandoned registry between
                            # the dispatcher's pick and the attempt
                            # registering). Caught here, inside the trace
                            # action, so an operator-requested outcome is not
                            # traced as a task error with a stacktrace; the
                            # sentinel is returned below. Writing an errored
                            # EvalLog would supersede the errored prior
                            # attempt's log, which must remain the task's
                            # final state.
                            abandoned = True
                        except Exception as ex:
                            # errors generally don't escape from task_run --
                            # the exception is a failure to write the log
                            # itself (e.g. the log_start() header flush, or
                            # the log_finish() of an already-errored task,
                            # when log storage is unreachable) or of a
                            # retry's checkpoint startup copy, which runs
                            # before the log's first write. propagating
                            # would tear down the entire run (and all
                            # sibling tasks) for one task's failed write, so
                            # record an errored EvalLog instead: the
                            # dispatcher re-queues errored tasks and
                            # eval_set() retries them once storage recovers.
                            if options.debug_errors:
                                raise
                            inner = inner_exception(ex)
                            if options.logger.finished_log is not None:
                                # once written, the log is the attempt's
                                # result (taken below)
                                error_after_write = True
                                log.error(
                                    f"Task '{options.task.name}' encountered an "
                                    f"error after writing its log: {inner}",
                                    exc_info=ex,
                                )
                            else:
                                log.error(
                                    f"Task '{options.task.name}' encountered an "
                                    f"error while starting or writing its log: "
                                    f"{inner}"
                                )
                                result = unwritten_task_log(options.logger, inner)
                    written_log = options.logger.pop_finished_log()
                    # task_scope swallows only its own cancellation (a
                    # run-level one propagates), so no log here means the
                    # task's abort/retry request interrupted task_run, or an
                    # error escaped it after the write
                    if result is None and not abandoned:
                        assert error_after_write or task_cancel.cancel_type in (
                            "abort",
                            "retry",
                        )
                        if written_log is not None:
                            result = written_log
                        else:
                            result = unwritten_task_log(
                                options.logger,
                                TerminateTaskError(
                                    "Task cancelled by user "
                                    f"({task_cancel.cancel_type})"
                                ),
                            )
                    task_cancel.close(
                        ended_in_error=result is not None and result.status == "error"
                    )
                    if abandoned:
                        run_returned = True
                        return
                    assert result is not None
                    try:
                        notifying = True
                        await notify_task_source(options, result)
                        notifying = False
                    except Exception as ex:
                        ex.add_note(
                            "Raised by TaskSource.task_complete() for task "
                            f"'{options.task.name}'."
                        )
                        raise
                    run_returned = True

                task_tg.start_soon(run)
            if not run_returned:
                source = "TaskSource.task_complete() for task" if notifying else "Task"
                raise RuntimeError(
                    f"{source} '{options.task.name}' raised a cancellation "
                    "that no cancellation of the run caused."
                )
        if abandoned:
            return TaskRunResult(None, None, abandoned=True)
    finally:
        # Startup can fail before log_finish owns teardown. Release the
        # cached prior on every exit without removing a written destination.
        with anyio.CancelScope(shield=True):
            try:
                await options.logger.recorder.close_seed_source(options.logger.eval)
            except Exception as ex:
                log.warning(f"Error closing prior log source: {exception_message(ex)}")
    return TaskRunResult(result, task_cancel.cancel_type)


async def _next_tasks(task_source: TaskSource) -> list[Task] | None:
    """Await ``task_source.next_tasks()`` in a child task.

    A cancellation of the run cancels the call and propagates. A cancellation
    that no cancellation of the run caused (for example from an upstream task
    the source awaits, cancelled on its own) would otherwise be absorbed by
    the task screen, ending the run as if the source had finished, so it is
    raised as a ``RuntimeError`` instead.
    """
    result: list[Task] | None = None
    returned = False

    async def pull() -> None:
        nonlocal result, returned
        # a TaskSource callback runs outside any task attempt
        with creator_model_scope(None):
            result = await task_source.next_tasks()
        returned = True

    async with unwrap_exception_group(), anyio.create_task_group() as tg:
        tg.start_soon(pull)
    if not returned:
        raise RuntimeError(
            "TaskSource.next_tasks() raised a cancellation that no "
            "cancellation of the run caused."
        )
    return result


def _clear_retry_pending(result: EvalLog, task_id: str) -> None:
    """Unwind the retry-pending flag once no retry follows an attempt.

    An attempt that ended before it registered (its log init, prior-log seed
    or log_start failed) has no flag of its own: the flag stands on the
    task's latest registered attempt.
    """
    registered = get_eval_state(result.eval.eval_id)
    if registered is None:
        registered = latest_eval_for_task(task_id)
    if registered is not None:
        clear_eval_retry_pending(registered.eval_id)


def _attempt_cancel(can_retry: bool) -> tuple[TaskCancel, anyio.CancelScope]:
    """A fresh cancel handle and cancel scope for one task attempt.

    The handle's abort and retry requests cancel the scope, which encloses
    only ``task_run``. A scope cancelled before it is entered cancels its body
    at the first checkpoint, so a request made before the attempt runs still
    takes effect.
    """
    task_scope = anyio.CancelScope()
    task_cancel = TaskCancel(can_retry=can_retry, apply=lambda _: None)

    def apply_cancel(type: CancelType) -> None:
        # samples parked at the pause gate observe the stamped cancel through
        # their escape predicate — wake them so a graceful resolution reaches
        # the queue-exit abandon check (cancel escalates over pause)
        wake_pause_waiters()
        # only abort/retry tear the task's scope down. score/error are
        # graceful sample resolutions: the caller interrupts in-flight
        # samples, queued samples are abandoned (they check the stamped
        # cancel_type as they leave the queue), and the task runs to natural
        # completion.
        if type in ("abort", "retry") and not bound_log_write(task_cancel):
            task_scope.cancel()

    task_cancel.apply = apply_cancel
    return task_cancel, task_scope


async def dispatch_tasks(
    queue: RunQueue,
    seed_specs: list[TaskSpec],
    *,
    parallel: int,
    task_source: "TaskSource | None",
    debug_errors: bool,
) -> list[EvalLog]:
    """Run the queue's tasks with bounded, model-balanced concurrency and retries.

    A queued task starts as soon as a ``max_tasks`` slot is free, whenever it
    was added. A task whose log comes back with an error — or which requests
    a retry via its ``TaskCancel`` — is queued again (reusing completed
    samples) until its retries are exhausted; an abort or external
    cancellation is never retried, and an external cancellation ends the run
    (an abort resolves to an errored log and the run continues).

    When nothing is queued or running, ``task_source.next_tasks()`` is awaited
    for more; the run ends when it returns ``None`` or ``[]`` (at once without
    a source). Returns the log of each task that has one, in result order.

    ``seed_specs`` are the display rows of the tasks already queued. The
    dispatcher holds no task options of its own, so an ended task's ``Task``
    and dataset are freed with its record's options.
    """
    # model-balancing state. Keyed by the Model object (identity), not
    # str(model): a provider may rewrite its model name mid-run (e.g. vLLM
    # resolving a "base:adapter" LoRA spec to "base" on the first generate()),
    # which would make the decrement key differ from the increment key. The
    # connection pool that balancing spreads load across belongs to the Model
    # instance, not its name, so identity is the right key; eval_resolve_tasks
    # shares one Model object across all of a model's tasks. (Relies on Model
    # being identity-hashable — a plain class, not a frozen dataclass with
    # __eq__.)
    model_counts: dict[Model, int] = {}
    # attempts counted against max_tasks, and every attempt running
    in_flight = 0
    attempts = 0
    cancelled = False
    source_done = task_source is None

    def record_options(record: TaskRecord) -> TaskRunOptions:
        assert record.options is not None
        return record.options

    def pick_balanced() -> TaskRecord | None:
        # among models that have startable queued tasks (not held by a pause
        # latch — covering both not-yet-started tasks and queued retry
        # attempts of a paused task — and not cancelled while queued, which
        # the uncounted start takes), pick the least-used one (keeps as many
        # different models running concurrently as possible); None when
        # nothing is startable. The model name rides along because a
        # not-yet-started task has no EvalState for the model latch to
        # resolve against — this check is what holds a latched model's
        # undispatched tasks.
        candidates = [
            record
            for record in queue.pending
            if not record.abort_requested
            and not task_dispatch_paused(
                record.task_id,
                model=dispatch_model_name(record_options(record).model),
            )
        ]
        if not candidates:
            return None
        # earliest queued candidate among the least-used models: ties break
        # by queue order (not arbitrary set order), so at a dispatch limit
        # of 1 a sequence-major queue keeps its grouping — all of task N's
        # model fan-outs run before task N+1 — instead of interleaving
        min_count = min(
            model_counts.get(record_options(r).model, 0) for r in candidates
        )
        return next(
            r
            for r in candidates
            if model_counts.get(record_options(r).model, 0) == min_count
        )

    def dispatcher_stats() -> TaskDispatcherStats:
        return TaskDispatcherStats(
            launch=parallel, in_flight=in_flight, pending=len(queue.pending)
        )

    async with _run_task_screen(seed_specs) as screen:
        init_task_screen(screen)
        queue.screen_open = True
        try:
            # registered inside the try so the removes in the finally below
            # always run (a failure in task_screen setup would otherwise
            # leak them into the module-level registries)
            add_dispatch_waker(queue.wake.set)
            register_task_dispatcher(dispatcher_stats)
            # exceptions can escape when debug_errors is True and that's okay
            async with (
                unwrap_exception_group("first" if debug_errors else None),
                anyio.create_task_group() as tg,
            ):
                # Run-scoped periodic [Throughput] trace reporter (see
                # design/model-throughput.md §4). Its own cancel scope: the
                # dispatch loop below exits by `break` while the task group
                # waits for children, so the reporter must be cancelled
                # explicitly then (exceptions/cancellation tear down the
                # whole group, reporter included).
                reporter_scope = anyio.CancelScope()

                async def throughput_reporter() -> None:
                    from inspect_ai.model._throughput import (
                        report_throughput_periodically,
                    )

                    with reporter_scope:
                        # the reporter is observability only — a bug in it
                        # must never propagate into the task group and take
                        # down the run (cancellation passes through: it's a
                        # BaseException, not Exception)
                        try:
                            await report_throughput_periodically()
                        except Exception as ex:
                            log.warning(f"Throughput reporter failed: {ex}")

                tg.start_soon(throughput_reporter)

                def start_attempt(record: TaskRecord, counted: bool) -> None:
                    """Start the record's next attempt, in one synchronous step.

                    A counted attempt holds a ``max_tasks`` slot and its model's
                    count until it ends. The attempt's cancel pair is stored on
                    the record before ``run_one`` runs, so a cancel landing
                    first still reaches it.
                    """
                    nonlocal in_flight, attempts
                    options = record_options(record)
                    queue.pending.remove(record)
                    if counted:
                        in_flight += 1
                        model_counts[options.model] = (
                            model_counts.get(options.model, 0) + 1
                        )
                    attempts += 1
                    record.phase = "attempt"
                    task_cancel, task_scope = _attempt_cancel(
                        can_retry=record.retries_remaining > 0
                    )
                    record.attempt_cancel = task_cancel
                    record.attempt_scope = task_scope
                    if record.abort_requested:
                        task_cancel.request("abort")
                    tg.start_soon(run_one, record, task_cancel, task_scope, counted)

                async def run_one(
                    record: TaskRecord,
                    task_cancel: TaskCancel,
                    task_scope: anyio.CancelScope,
                    counted: bool,
                ) -> None:
                    options = record_options(record)

                    def release() -> None:
                        nonlocal in_flight, attempts
                        attempts -= 1
                        if counted:
                            in_flight -= 1
                            model_counts[options.model] -= 1

                    async def settle(run: TaskRunResult) -> None:
                        """Decide on a retry and publish it, or end the record."""
                        nonlocal cancelled
                        result = run.log

                        # a drain/cancel abandoned this queued retry between the
                        # dispatcher's pick and the attempt registering its
                        # EvalState: side-effect-free finalize — discard the
                        # attempt's never-started log entry (including a header
                        # log_start already flushed), release the slot, end the
                        # record with the errored attempt's log it already holds,
                        # and never set the run-level cancelled flag. Checked
                        # before the external-cancellation branch below (run.log
                        # is None here, which would otherwise end the whole run).
                        if run.abandoned:
                            await options.logger.discard()
                            release()
                            queue.end(record, record.log)
                            return

                        # decide whether to retry: on an error or an explicit retry
                        # request, but never on an abort or external (ctrl+c)
                        # cancellation (which ends the whole run). Contract: an
                        # attempt that ends with no log, or a `cancelled` log, was
                        # ended by a run-level cancellation. A task's own abort or
                        # retry request always leaves an `error` (or, landing after
                        # a successful write, a `success`) log (see _run_task), so
                        # it ends or retries only this task.
                        retry = False
                        if result is None or result.status == "cancelled":
                            cancelled = True
                        elif run.cancel_type == "retry":
                            log.info(
                                f"Task '{options.task.name}' was cancelled with retry "
                                f"requested — {record.retries_remaining} retries remaining"
                            )
                            retry = True
                        elif run.cancel_type == "abort":
                            log.info(
                                f"Task '{options.task.name}' was cancelled with abort requested"
                            )
                        elif run.cancel_type == "drain":
                            # drain interrupts nothing (in-flight samples finished
                            # naturally, queued ones were abandoned) — a user
                            # cancel like abort, so never retried
                            log.info(
                                f"Task '{options.task.name}' was drained — in-flight "
                                "samples finished naturally, queued samples abandoned"
                            )
                        elif run.cancel_type is not None:
                            # a graceful cancel resolution (score/error) — a user
                            # cancel like abort, so never retried even when the
                            # resolved log carries an error status
                            log.info(
                                f"Task '{options.task.name}' was cancelled with "
                                f"sample resolution '{run.cancel_type}'"
                            )
                        elif result.status == "error":
                            retry = True
                        retry = retry and record.retries_remaining > 0

                        # a drain/plain cancel issued while this attempt was
                        # tearing down (or between run_one iterations) stamped
                        # the retry-abandoned registry: skip constructing the
                        # retry entirely — no retry_pending flag, no reinit,
                        # nothing to discard; the attempt's error log is the
                        # record's final log
                        if retry and task_retry_abandoned(options.logger.eval.task_id):
                            log.info(
                                f"Task '{options.task.name}' retry abandoned by "
                                "operator — task ends with this attempt's error log"
                            )
                            retry = False

                        # no retry once dispatch has ended, or once this attempt
                        # (which never registered) was aborted after it returned
                        if retry and (
                            queue.closed or task_cancel.cancel_type == "abort"
                        ):
                            retry = False

                        # build the requeued task before releasing the in-flight slot:
                        # reinit is async, and were the slot freed first the dispatcher
                        # could observe an idle run mid-reinit and finish early
                        retry_options: TaskRunOptions | None = None
                        if retry and result is not None:
                            # from here until the retry attempt registers its own
                            # EvalState, this errored attempt is the task's latest —
                            # flag it so task-keyed directives don't read its
                            # completed_at as "task finished" (see EvalState
                            # .retry_pending). The task runner already flagged it
                            # when it decided the error status (ahead of its log
                            # write); this is the confirming re-mark.
                            mark_eval_retry_pending(result.eval.eval_id)

                            # build sample_source from the failed log so completed
                            # samples are reused on retry (mirrors legacy eval_set
                            # retry). The attempt's destination is the newest
                            # record on disk whenever a flush reached it, finished
                            # or not: it holds the seeded prior set plus every
                            # live completion flushed since. An unfinished one
                            # (log_finish failed) sits under a `started` header,
                            # which reinit() below leaves in place — sample
                            # progress outranks the header it lacks. An attempt
                            # that wrote nothing (its log init, prior-log seed or
                            # log_start flush failed) has nothing newer to offer:
                            # the retry keeps the source this attempt ran with
                            # (the same prior log). Decided from recorder state,
                            # with no filesystem probe on the dispatcher's loop.
                            failed_location = options.logger.location
                            sample_source: EvalSampleSource | None
                            if (
                                options.logger.destination_written
                                and failed_location is not None
                            ):
                                failed_log_info = EvalLogInfo(
                                    name=failed_location,
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
                                        failed_location,
                                        options.checkpoint,
                                        options.eval_checkpoint,
                                    ),
                                )
                            else:
                                log.info(
                                    f"Task '{options.task.name}' wrote no log for this "
                                    "attempt; retrying with the prior attempt's sample "
                                    "source"
                                )
                                sample_source = options.sample_source

                            # release the failed attempt's log entry; the retry's
                            # own attempt starts a fresh one
                            await options.logger.reinit()

                            if queue.closed or task_cancel.cancel_type == "abort":
                                # dispatch ended, or the attempt was aborted,
                                # while reinit() ran: no retry, and the re-mark
                                # above is unwound
                                _clear_retry_pending(
                                    result, options.logger.eval.task_id
                                )
                            else:
                                retry_attempt = (
                                    queue.task_retry_attempts
                                    - record.retries_remaining
                                    + 1
                                )
                                retry_display_name = (
                                    f"{options.task.name} "
                                    f"(retry {retry_attempt} of "
                                    f"{queue.task_retry_attempts})"
                                )
                                retry_options = replace(
                                    options,
                                    sample_source=sample_source,
                                    display_name=retry_display_name,
                                )
                        elif result is not None:
                            # no retry follows — unwind the runner's pre-mark, which
                            # a cancel stamp landing during the log write may have
                            # superseded (a retry abandoned before the pre-mark was
                            # never marked, and one abandoned during the log write
                            # was already cleared by the directive; this is a no-op
                            # then)
                            _clear_retry_pending(result, options.logger.eval.task_id)

                        # Retry source selection needs the recorder's write state.
                        # Once no retry follows, release any unfinished entry even
                        # if startup failed after seeding an entire prior log.
                        if retry_options is None and not options.logger.finished:
                            with anyio.CancelScope(shield=True):
                                await options.logger.discard(
                                    keep_destination=True, keep_buffer=True
                                )

                        # finalize atomically (no awaits below) so the dispatcher sees
                        # a consistent (in_flight, pending) snapshot
                        release()
                        if result is not None:
                            record.log = result
                        if retry_options is not None:
                            record.options = retry_options
                            record.retries_remaining -= 1
                            queue.requeue(record)
                            log.info(
                                f"Retrying task '{options.task.name}' ({options.model}) "
                                f"— {record.retries_remaining} retries remaining"
                            )
                        else:
                            queue.end(record, record.log)

                    # the attempt owns its logger until the record is requeued or
                    # ends: an exception anywhere in the attempt, retry
                    # preparation included, releases an unfinished entry
                    # (keeping its destination and buffer for recovery) and
                    # ends the record before it propagates
                    try:
                        run = await _run_task(options, task_cancel, task_scope)
                        await settle(run)
                    except BaseException:
                        with anyio.CancelScope(shield=True):
                            if not options.logger.finished:
                                await options.logger.discard(
                                    keep_destination=True, keep_buffer=True
                                )
                        queue.end(record, record.log)
                        raise

                try:
                    while True:
                        # end queued retries abandoned by a task drain/cancel
                        # (design/ctl/task-drain.md "Tasks between attempts")
                        # with their stored log — ahead of pick_balanced's
                        # pause filter, so a paused-and-held retry is
                        # droppable too. The directive fired the dispatch
                        # waker, so this runs promptly after the stamp; a
                        # retry still mid-construction when the stamp landed
                        # is covered because its requeue fires the waker and
                        # the next cycle drops it here.
                        for abandoned in [
                            record
                            for record in queue.pending
                            if task_retry_abandoned(record.task_id)
                        ]:
                            queue.end(abandoned, abandoned.log)

                        # start up to the concurrency cap (model-balanced),
                        # re-reading the live `ctl config --max-tasks` override
                        # each iteration (a set fires the dispatch wakers, so a
                        # raise reaches a waiting dispatcher immediately)
                        while not cancelled and in_flight < effective_max_tasks(
                            parallel
                        ):
                            record = pick_balanced()
                            if record is None:
                                # nothing startable (everything queued is held
                                # by a pause latch, or none is queued) — a
                                # resume fires the dispatch waker
                                break
                            start_attempt(record, counted=True)

                        if cancelled:
                            break

                        # a task cancelled while queued starts at once,
                        # outside max_tasks and whether or not a pause holds
                        # it, and aborts before its log starts
                        for record in [r for r in queue.pending if r.abort_requested]:
                            start_attempt(record, counted=False)

                        # work still queued or running (incl. pending retries):
                        # wait for a completion or a new addition, then
                        # re-evaluate
                        if queue.pending or attempts > 0:
                            await queue.wake.wait()
                            continue

                        # fully idle: ask the source for more (may block) and
                        # finish when it is exhausted. Nothing starts while it
                        # blocks: a task added meanwhile starts when it returns,
                        # ahead of the batch it returned
                        if source_done:
                            break
                        assert task_source is not None
                        more = await _next_tasks(task_source)
                        if not more:
                            source_done = True
                        elif queue.closed:
                            log.warning(
                                f"Dropping {len(more)} task(s) returned by the "
                                "task source after the run stopped."
                            )
                        else:
                            queue.add(queue.resolve(more))
                        # the queue holds what it needs: drop the source's
                        # batch so its tasks and datasets can be freed once
                        # they end, while the next call blocks
                        more = None
                finally:
                    # synchronous, before the group joins its attempts: nothing
                    # more starts, and every queued record ends
                    queue.close()
                    queue.end_unstarted()
                    reporter_scope.cancel()
        finally:
            queue.screen_open = False
            remove_dispatch_waker(queue.wake.set)
            remove_task_dispatcher(dispatcher_stats)
            clear_task_screen()

    return queue.logs()


class SandboxManager:
    """Starts sandbox environments incrementally and tears them all down.

    Each task attempt sets up the sandboxes its seed samples need, and a
    `SampleSource` task's feeder those of the samples it adds, so startup is
    called repeatedly: :meth:`start_for_samples` initializes only sandboxenvs
    not already started in the run and accumulates their cleanups;
    :meth:`shutdown` runs every accumulated cleanup once, at the end of the run.

    The manager also owns the run's sandbox lifecycle state (the registries
    a provider's `task_cleanup` reads: running containers, generated config
    files). :meth:`open` binds a fresh scope in the calling context before any
    task of the run is spawned, so a `task_init` that runs in a task's attempt
    or in a `SampleSource` feeder task registers on the object every task
    inherited rather than in its own context; :meth:`shutdown` releases the
    scope.

    :meth:`open` also captures the run's root context, the one every task and
    sample starts from. Each `task_init` runs in a task started from the setup
    chain's context, which starts as the root and which each successful
    `task_init`'s context replaces, so a later setup sees what earlier ones
    bound. The `ContextVar` values each configuration's context binds
    differently from the root are recorded in :attr:`bindings` for its
    samples, and its `task_cleanup` runs in that context.
    """

    def __init__(
        self,
        config: EvalConfig,
        cleanup: bool,
        launch_dir: str,
    ) -> None:
        self._config = config
        self._cleanup = cleanup
        # the directory of a task not loaded from a file, fixed for the run so
        # a setup's bindings and its samples' lookup use the same key
        self._launch_dir = launch_dir
        self._started: Set[TaskSandboxEnvironment] = set()
        self._cleanups: list[
            tuple[TaskCleanup, SandboxEnvironmentConfigType | None, Context]
        ] = []
        self._init_lock = anyio.Lock()
        self._lifecycle: ExitStack | None = None
        self._chain: Context | None = None
        self._bindings: SandboxSetupBindings | None = None

    def open(self) -> None:
        """Own the run's sandbox lifecycle state from the calling context.

        Call before any task or sample of the run is spawned (and whether or
        not any initial sample has a sandbox — the first sandbox may arrive
        with an added task or sample). :meth:`shutdown` releases it.
        """
        if self._lifecycle is None:
            set_sandbox_prebuilt(self._config.sandbox_prebuilt is True)
            self._lifecycle = ExitStack()
            self._lifecycle.enter_context(sandbox_lifecycle_scope())
            root = copy_context()
            self._chain = root
            self._bindings = SandboxSetupBindings(root)

    @property
    def bindings(self) -> SandboxSetupBindings:
        """The provider state each configuration's `task_init` bound."""
        assert self._bindings is not None, "SandboxManager.open() not called"
        return self._bindings

    async def start_for_samples(
        self,
        task: ResolvedTask,
        cache: dict[SandboxEnvironmentSpec, TaskSandboxEnvironment],
        samples: Iterable[Sample],
    ) -> None:
        """Initialize the sandboxenvs of a task's samples before they run.

        Called by a task's attempt for its seed samples and by a
        `SampleSource` task's feeder for the samples it adds: a sandbox config
        not yet started in the run gets its `task_init` startup — up-front
        image build/pull, fail-fast validation, and a registered
        `task_cleanup` — before the samples run. Configs already started are a
        no-op. `cache` holds the task's metadata-free resolutions (see
        :meth:`_resolve_sandboxenvs`); it is the task's own, so it goes with
        the task when the task ends.
        """
        await self._start_sandboxenvs(
            await self._resolve_sandboxenvs(task, samples, cache)
        )

    async def _resolve_sandboxenvs(
        self,
        task: ResolvedTask,
        samples: Iterable[Sample],
        cache: dict[SandboxEnvironmentSpec, TaskSandboxEnvironment],
    ) -> Set[TaskSandboxEnvironment]:
        """Resolve each sample's sandboxenv (deduped; sandbox-less samples skipped).

        Full resolution reads the sandbox config (and, for docker configs with
        metadata interpolation, spawns a subprocess) per sample — meaningful
        when a source adds samples batch after batch. Metadata-less samples
        resolve deterministically per spec, so those resolutions are cached;
        samples with metadata must always fully resolve (their config may
        interpolate it into a per-sample init environment).
        """
        sandboxenvs: Set[TaskSandboxEnvironment] = set()
        for sample in samples:
            sandboxenv: TaskSandboxEnvironment | None = None
            cache_key: SandboxEnvironmentSpec | None = None
            if not sample.metadata:
                spec = await resolve_sandbox(
                    task.sandbox,
                    sample,
                    task.task.name,
                    task_dir=task_run_dir(task.task, self._launch_dir),
                )
                if spec is None:
                    continue
                cache_key = spec
                sandboxenv = cache.get(cache_key)
            if sandboxenv is None:
                sandboxenv = await resolve_sandbox_for_task_and_sample(
                    task.sandbox, task.task, sample, self._launch_dir
                )
                if sandboxenv is not None and cache_key is not None:
                    cache[cache_key] = sandboxenv
            if sandboxenv is not None:
                sandboxenvs.add(sandboxenv)
        return sandboxenvs

    async def _start_sandboxenvs(
        self, sandboxenvs: Set[TaskSandboxEnvironment]
    ) -> None:
        """Run `task_init` for sandboxenvs not already started.

        Serialized on a lock with the started-set re-checked under it, so
        concurrent callers (e.g. two live tasks adding samples at once)
        can't double-init the same sandboxenv. The pre-lock filter lets a
        caller whose configs are all already started return without waiting
        out another caller's (possibly minutes-long) image pull — safe
        because the started set only ever grows.
        """
        sandboxenvs = {env for env in sandboxenvs if env not in self._started}
        if not sandboxenvs:
            return

        async with self._init_lock:
            sandboxenvs = {env for env in sandboxenvs if env not in self._started}
            if not sandboxenvs:
                return

            # initialiase sandboxenvs (track cleanups)
            with display().suspend_task_app():
                for sandboxenv in sandboxenvs:
                    # find type
                    sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)

                    # pre-register the type's resizable concurrency limiter before
                    # task_init (image pulls/builds can take minutes) so a `ctl
                    # limits --max-sandboxes` issued during startup isn't dropped
                    await ensure_sandbox_limiter(
                        sandboxenv_type,
                        sandboxenv.sandbox.type,
                        self._config.max_sandboxes,
                    )

                    # run startup in the setup chain's context; a failed
                    # task_init raises here and registers nothing
                    assert self._chain is not None, "SandboxManager.open() not called"
                    task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
                    task_cleanup = cast(
                        TaskCleanup, getattr(sandboxenv_type, "task_cleanup")
                    )
                    await _run_in_context(
                        self._chain,
                        functools.partial(
                            _task_init_startup,
                            task_init,
                            sandboxenv.sandbox.config,
                            dict(sandboxenv.env),
                        ),
                        on_return=functools.partial(
                            self._register_setup, sandboxenv, task_cleanup
                        ),
                    )

                # provide some space above task display ("none" has no task
                # display and must keep stdout machine-readable, e.g. --json)
                if display_type() != "none":
                    print("")

    def _register_setup(
        self,
        sandboxenv: TaskSandboxEnvironment,
        task_cleanup: TaskCleanup,
        context: Context,
    ) -> None:
        """Record a successful `task_init`: its context, bindings and cleanup."""
        self._chain = context
        self.bindings.record(sandboxenv, context)
        self._started.add(sandboxenv)
        self._cleanups.append((task_cleanup, sandboxenv.sandbox.config, context))

    async def shutdown(self) -> None:
        """Run every accumulated `task_cleanup`, then release the lifecycle state.

        The final cleanup of the run: it also covers samples whose own
        cleanup was deferred by an interruption, since their provider state is
        on the scope this manager owns.
        """
        with anyio.CancelScope(shield=True):
            try:
                for cleanup_jobs in self._cleanups:
                    try:
                        cleanup_fn, config, context = cleanup_jobs
                        await _run_in_context(
                            context,
                            functools.partial(
                                cleanup_fn, "shutdown", config, self._cleanup
                            ),
                        )
                    except BaseException as ex:
                        log.warning(
                            f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                        )
            finally:
                if self._lifecycle is not None:
                    self._lifecycle.close()
                    self._lifecycle = None


async def _task_init_startup(
    task_init: TaskInit,
    config: SandboxEnvironmentConfigType | None,
    env: dict[str, str],
) -> None:
    """Run a startup `task_init` with its `task_init_environment` values.

    The values are set in the setup state that Docker's `task_init` reads,
    inside the child task `_run_in_context` starts, and reset before its
    context is recorded as the setup's bindings.
    """
    with task_init_env(env):
        await task_init("startup", config)


async def _run_in_context(
    context: Context,
    func: Callable[[], Awaitable[None]],
    on_return: Callable[[Context], None] | None = None,
) -> None:
    """Await `func` in a child task started from a copy of `context`.

    The caller's context is unchanged, and an exception from `func` raises
    bare, including a cancellation raised inside `func` that no enclosing
    scope requested (the task group would otherwise absorb it, and the caller
    would return as if `func` had completed). `on_return` gets the child's
    context, holding what `func` bound, as soon as `func` returns and in the
    child, so a cancellation of the caller while the task group joins cannot
    lose it.
    """
    completed = False
    cancelled: BaseException | None = None

    async def run() -> None:
        nonlocal completed, cancelled
        try:
            await func()
        except anyio.get_cancelled_exc_class() as ex:
            cancelled = ex
            raise
        completed = True
        if on_return is not None:
            on_return(copy_context())

    async with unwrap_exception_group(), anyio.create_task_group() as tg:
        # anyio's start_soon gives the child a copy of the current context
        context.copy().run(tg.start_soon, run)

    if not completed:
        if cancelled is not None:
            raise cancelled
        raise RuntimeError("sandbox setup call ended without completing")


@asynccontextmanager
async def _run_task_screen(tasks: list[TaskSpec]) -> AsyncIterator[TaskScreen]:
    """Open the display's task screen for a run that absorbs cancellation.

    A cancellation of the run body is absorbed, so the run returns the logs
    it has. Trio raises that cancellation again at every checkpoint inside
    the cancelled scope, so a display whose teardown awaits (the rich
    display's update-loop task group) raises it again; that one is absorbed
    too. A cancellation from the teardown of a body that was not cancelled,
    or from the display's setup, propagates.
    """
    body_cancelled = False
    try:
        async with display().task_screen(tasks, parallel=True) as screen:
            try:
                yield screen
            except anyio.get_cancelled_exc_class():
                body_cancelled = True
    except anyio.get_cancelled_exc_class():
        if not body_cancelled:
            raise


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
