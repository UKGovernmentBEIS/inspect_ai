"""One eval run: configuring its tasks, sandbox setup, and the scheduling loop.

The scheduler's state (the run's task records and queue, its
:class:`SetupCache`, the dispatcher's slot and model counts) is used only from
the run's event loop and changed without locks: code on one event loop does
not interleave between ``await`` points, so a method that does not await
(``RunQueue.put``, ``TaskDispatcher.start`` and ``settle``, the setup cache's
bookkeeping) changes it as one step.
"""

import functools
import logging
import os
import weakref
from collections import Counter, deque
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import Context, ContextVar, copy_context
from copy import copy
from dataclasses import dataclass, replace
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    NamedTuple,
    Protocol,
    cast,
)

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._util._async import Wake, run_cancelled, unwrap_exception_group
from inspect_ai._util.file import cleanup_s3_sessions
from inspect_ai._util.task import task_display_name
from inspect_ai._util.trace import trace_action
from inspect_ai.util._anyio import inner_exception
from inspect_ai.util._checkpoint import CheckpointConfig

if TYPE_CHECKING:
    from inspect_sentinel._integration import Sentinels

from inspect_ai._control.eval_state import (
    clear_eval_retry_pending,
    mark_eval_retry_pending,
)
from inspect_ai._control.max_tasks import (
    QueuedTask,
    TaskDispatcherStats,
    WaitingFor,
    effective_max_tasks,
    register_task_dispatcher,
    remove_task_dispatcher,
)
from inspect_ai._control.pause import (
    add_dispatch_waker,
    dispatch_model_name,
    note_dispatch_models,
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
from inspect_ai._eval.task.scan import Scanners
from inspect_ai._sentinel._config import resolve_sentinel_root, sentinel_config
from inspect_ai._util.error import PrerequisiteError, exception_message
from inspect_ai._util.exception import TaskRetryAbandonedError, TerminateTaskError
from inspect_ai._util.path import chdir
from inspect_ai.approval._policy import ApprovalPolicy, config_from_approval_policies
from inspect_ai.dataset._dataset import Dataset, Sample
from inspect_ai.log import EvalConfig, EvalError, EvalLog
from inspect_ai.log._file import EvalLogInfo
from inspect_ai.log._log import eval_error
from inspect_ai.log._recorders import Recorder
from inspect_ai.model import GenerateConfigArgs
from inspect_ai.model._model import Model, ModelName, ensure_model_controller
from inspect_ai.review._policy import ReviewPolicy, config_from_review_policies
from inspect_ai.scorer._metric import to_metric_specs
from inspect_ai.scorer._reducer import ScoreReducer, reducer_log_names
from inspect_ai.scorer._reducer.registry import validate_reducer
from inspect_ai.scorer._scorer import as_scorer_spec
from inspect_ai.solver._solver import Solver, SolverSpec
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
from inspect_ai.util._sandbox.setup import SandboxSetup, sandbox_setup_scope

from .loader import (
    as_solver_spec,
    solver_from_spec,
)
from .task.enqueue import ConfiguredTask, RunQueue, TaskRecord, TaskRecordState
from .task.log import TaskLogger
from .task.resolved import ResolvedTask, resolved_task_names
from .task.run import (
    EvalSampleSource,
    TaskRunOptions,
    eval_log_sample_source,
    notify_task_source,
    plan_agent_name,
    resolve_plan,
    task_run,
)
from .task.sandbox import (
    TaskSandboxEnvironment,
    ensure_sandbox_limiter,
    resolve_sandbox,
    resolve_sandbox_for_task_and_sample,
)
from .task.setup_cache import SetupCache, SetupFailure
from .task.task import Task
from .task.task_source import TaskSource
from .task.util import resolve_task_sample_ids, slice_dataset, task_run_dir

log = logging.getLogger(__name__)


async def eval_run(
    eval_set_id: str | None,
    run_id: str,
    tasks: list[ResolvedTask],
    parallel: int,
    eval_config: EvalConfig,
    eval_checkpoint: CheckpointConfig | None,
    recorder: Recorder,
    header_only: bool,
    queue: RunQueue,
    epochs_reducer: list[ScoreReducer] | None = None,
    approval: list[ApprovalPolicy] | None = None,
    review: list[ReviewPolicy] | None = None,
    sentinel: "Sentinels | None" = None,
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
    eval_set_tasks: list[str] | None = None,
    **kwargs: Unpack[GenerateConfigArgs],
) -> list[EvalLog]:
    """Run the tasks of one eval run, including the tasks added to ``queue``.

    Starts up the seed tasks, runs the scheduling loop (:class:`TaskDispatcher`)
    until no task is left, then shuts the run's sandbox environments down once.
    ``parallel`` is the launch limit on concurrent (task × model) units.
    """
    if isinstance(solver, Solver):
        eval_solver, eval_solver_spec = solver, as_solver_spec(solver)
    elif isinstance(solver, SolverSpec):
        eval_solver, eval_solver_spec = solver_from_spec(solver), solver
    else:
        eval_solver, eval_solver_spec = None, None
    settings = TaskSettings(
        eval_set_id=eval_set_id,
        run_id=run_id,
        eval_config=eval_config,
        eval_checkpoint=eval_checkpoint,
        # before any task changes the working directory
        eval_wd=os.getcwd(),
        recorder=recorder,
        header_only=header_only,
        solver=eval_solver,
        solver_spec=eval_solver_spec,
        scanner=scanner,
        scan_id=scan_id,
        tags=tags,
        metadata=metadata,
        epochs_reducer=epochs_reducer,
        approval=approval,
        review=review,
        sentinel=sentinel,
        debug_errors=debug_errors,
        run_samples=run_samples,
        score=score,
        task_source=task_source,
        generate_config=kwargs,
    )
    try:
        async with SandboxManager(
            eval_config, cleanup=eval_config.sandbox_cleanup is not False
        ) as sandboxes:
            startup = TaskStartup(
                settings, sandboxes, task_names=list(eval_set_tasks or [])
            )
            queue.open(
                startup.configure,
                retries=task_retry_attempts or 0,
                sequence_order=parallel == 1,
            )
            seed = queue.add(tasks)
            queue.enqueue(seed)
            await startup.start_seed(seed)
            # setups from here on run beside the task display
            sandboxes.collect_output = True
            dispatcher = TaskDispatcher(
                queue,
                startup,
                parallel=parallel,
                source=task_source,
                debug_errors=debug_errors,
            )
            return await dispatcher.run(seed)
    finally:
        # clean up cached S3 sessions to prevent "Unclosed connector" warnings
        try:
            await cleanup_s3_sessions()
        except Exception as ex:
            log.warning(f"Error cleaning up S3 sessions: {exception_message(ex)}")


# Task settings that an eval-level value (from eval() or the CLI) overrides;
# when there is none, the task's value fills in the eval config
_TASK_OVERRIDABLE = (
    "epochs",
    "message_limit",
    "turn_limit",
    "time_limit",
    "working_limit",
    "cost_limit",
    "fail_on_error",
    "continue_on_fail",
    "score_on_error",
)


@dataclass(frozen=True)
class TaskSettings:
    """The run-wide inputs every task of one run is configured with."""

    eval_set_id: str | None
    run_id: str
    eval_config: EvalConfig
    eval_checkpoint: CheckpointConfig | None
    eval_wd: str
    recorder: Recorder
    header_only: bool
    solver: Solver | None
    solver_spec: SolverSpec | None
    scanner: "Scanners | None"
    scan_id: str | None
    tags: list[str] | None
    metadata: dict[str, Any] | None
    epochs_reducer: list[ScoreReducer] | None
    approval: list[ApprovalPolicy] | None
    review: list[ReviewPolicy] | None
    sentinel: "Sentinels | None"
    debug_errors: bool
    run_samples: bool
    score: bool
    task_source: TaskSource | None
    generate_config: GenerateConfigArgs

    def configure(
        self,
        resolved_task: ResolvedTask,
        task_names: list[str],
        startup_sandboxes: "SampleSandboxSetup | None",
        apply_provider_state: Callable[[], None] | None,
    ) -> ConfiguredTask:
        """Configure one task of the run: validate it and resolve its settings.

        Eval-level settings are resolved against a shallow copy of the task, so
        repeated ``eval()`` calls on the same ``Task`` do not keep them (nested
        state such as the dataset, config and reducer list is still shared, so
        it must not be changed in place). Runs in the task's run directory, as
        does creating each attempt's logger (which records the git revision
        and paths relative to it); ``chdir`` is process-wide, so nothing here
        may await.

        Args:
            resolved_task: The task as resolved against the run's models.
            task_names: Every task name known to the run (``task:id`` sample
                selectors).
            startup_sandboxes: Starts the sandboxes of samples a
                ``SampleSource`` adds while the task runs.
            apply_provider_state: Sets the run's provider state in such a
                sample's task.

        Raises:
            PrerequisiteError: If the task can't run with these settings.
        """
        run_dir = task_run_dir(resolved_task.task)
        with chdir(run_dir):
            task = copy(resolved_task.task)
            config = self.eval_config.model_copy()

            # sample_ids can be specified per task
            config.sample_id = resolve_task_sample_ids(
                task.name, config.sample_id, task_names
            )
            if config.sample_id == [] and self.eval_config.sample_id != []:
                log.warning(
                    f"No sample_id selector names task '{task.name}'; "
                    "it will run no samples."
                )
            _check_sample_source_options(task, config)
            self._apply_eval_settings(task, config)
            sentinel_root = (
                resolve_sentinel_root(task.sentinel)
                if task.sentinel is not None
                else None
            )
            tags = list(set(self.tags or []) | set(task.tags or [])) or None

        new_logger = functools.partial(
            _new_logger,
            run_dir,
            task_name=task.name,
            task_version=task.version,
            task_file=resolved_task.task_file,
            task_registry_name=resolved_task.task.registry_name,
            task_display_name=resolved_task.task.display_name,
            task_description=task.description,
            task_id=resolved_task.id,
            eval_set_id=self.eval_set_id,
            run_id=self.run_id,
            solver=self.solver_spec,
            tags=tags,
            model=resolved_task.model,
            model_roles=resolved_task.model_roles,
            dataset=task.dataset,
            scorer=(
                [as_scorer_spec(scorer) for scorer in task.scorer]
                if task.scorer is not None
                else None
            ),
            metrics=(
                to_metric_specs(task.metrics) if task.metrics is not None else None
            ),
            headline_metric=task.headline_metric,
            sandbox=resolved_task.sandbox,
            task_attribs=task.attribs,
            task_args=getattr(task, TASK_ALL_PARAMS_ATTR, resolved_task.task_args),
            task_args_passed=resolved_task.task_args,
            model_args=resolved_task.model.model_args,
            eval_config=config,
            metadata=((self.metadata or {}) | (task.metadata or {})) or None,
            viewer=task.viewer,
            recorder=self.recorder,
            header_only=self.header_only,
            dynamic_dataset=task.sample_source is not None,
        )

        def options(logger: TaskLogger) -> TaskRunOptions:
            return TaskRunOptions(
                task=task,
                model=resolved_task.model,
                model_roles=resolved_task.model_roles,
                sandbox=resolved_task.sandbox,
                checkpoint=resolved_task.checkpoint,
                eval_checkpoint=self.eval_checkpoint,
                logger=logger,
                eval_wd=self.eval_wd,
                config=config,
                sentinel=sentinel_root,
                solver=self.solver,
                scanner=self.scanner,
                scan_id=self.scan_id,
                tags=tags,
                run_samples=self.run_samples,
                score=self.score,
                debug_errors=self.debug_errors,
                sample_source=resolved_task.sample_source,
                kwargs=self.generate_config,
                initial_model_usage=resolved_task.initial_model_usage,
                initial_role_usage=resolved_task.initial_role_usage,
                task_source=self.task_source,
                startup_sandboxes=startup_sandboxes,
                apply_provider_state=apply_provider_state,
                input_media_policy=resolved_task.input_media_policy,
            )

        return ConfiguredTask(resolved_task, options, new_logger)

    def _apply_eval_settings(self, task: Task, config: EvalConfig) -> None:
        """Resolve eval-level settings against the task's own, in place.

        A setting given to ``eval()`` (already in ``config``) overrides the
        task's; otherwise the task's value is recorded in ``config``.
        """
        for name in _TASK_OVERRIDABLE:
            if getattr(config, name) is None:
                setattr(config, name, getattr(task, name))
            else:
                setattr(task, name, getattr(config, name))

        # the token limit and its metering type travel as a unit
        if config.token_limit is None:
            config.token_limit = task.token_limit
            config.token_limit_type = task.token_limit_type
        else:
            task.token_limit = config.token_limit
            task.token_limit_type = config.token_limit_type

        if self.epochs_reducer is not None:
            task.epochs_reducer = self.epochs_reducer
        else:
            config.epochs_reducer = reducer_log_names(task.epochs_reducer)
        if task.epochs and task.epochs_reducer:
            for reducer in task.epochs_reducer:
                validate_reducer(task.epochs, reducer)
        if self.approval:
            task.approval = self.approval
        elif task.approval:
            config.approval = config_from_approval_policies(task.approval)
        if self.review:
            task.review = self.review
        elif task.review:
            config.review = config_from_review_policies(task.review)
        if self.sentinel is not None:
            task.sentinel = self.sentinel
        elif task.sentinel is not None:
            config.sentinel = sentinel_config(task.sentinel)


def _new_logger(run_dir: str, **kwargs: Any) -> TaskLogger:
    """A logger for a new attempt of a task (see :meth:`TaskSettings.configure`)."""
    with chdir(run_dir):
        return TaskLogger(**kwargs)


def _check_sample_source_options(task: Task, config: EvalConfig) -> None:
    """Reject options that assume a fixed sample set, for a ``SampleSource`` task.

    Checked before the task's logger exists, so the error surfaces before the
    run rather than as a task error log.

    Raises:
        PrerequisiteError: If such an option is set.
    """
    if task.sample_source is None:
        return
    # early stopping managers register the seed only (samples the source adds
    # are never registered) and samples they halt complete without notifying
    # the source; a source blocked awaiting completions would hang the task
    if task.early_stopping is not None:
        raise PrerequisiteError(
            "early_stopping is not currently supported for "
            "tasks whose dataset is a SampleSource."
        )
    # a range limit selects seed samples by position, but samples the source
    # adds have no position
    if isinstance(config.limit, tuple):
        raise PrerequisiteError(
            "A range --limit (start,end) is not supported for "
            "tasks whose dataset is a SampleSource (added "
            "samples have no dataset position); use a plain "
            "numeric --limit to cap total samples."
        )


SampleSandboxSetup = Callable[[Iterable[Sample]], Awaitable[None]]
"""Sets up the sandboxes some of a task's samples need, from inside the task."""


@dataclass
class TaskStartup:
    """Configures the tasks of one run and readies them to start.

    Configuration is synchronous, so a task is configured when its record is
    created (an invalid task raises to whoever added it). Readying a task is
    asynchronous: its model's controller, and the sandbox configs its
    selected samples use, which the run's :class:`SetupCache` then sets up.
    """

    settings: TaskSettings
    sandboxes: "SandboxManager"
    task_names: list[str]
    """Every task name known to the run, for ``task:id`` sample selectors: the
    enclosing eval set's (a retry runs only some of them), then each task's
    as it is added, so an added task sees the tasks before it."""

    @property
    def setups(self) -> "SetupCache[TaskSandboxEnvironment]":
        return self.sandboxes.setups

    def configure(self, group: list[ResolvedTask]) -> list[ConfiguredTask]:
        """Configure tasks added together.

        Raises:
            PrerequisiteError: If a task can't run with the run's settings
                (duplicate sample ids, unsupported options).
        """
        names = [
            name for name in resolved_task_names(group) if name not in self.task_names
        ]
        for resolved_task in group:
            ensure_sample_ids(resolved_task.task.dataset)
        configured = [
            self.settings.configure(
                t, [*self.task_names, *names], *self._added_samples(t)
            )
            for t in group
        ]
        self.task_names.extend(names)
        return configured

    async def prepare(
        self, resolved_task: ResolvedTask
    ) -> frozenset[TaskSandboxEnvironment]:
        """Ready a task to start; the sandbox configs its selected samples use.

        Creates the model's controller eagerly, so ``ctl config`` can retune
        ``max_connections`` during a long sandbox setup, and registers the
        ``ctl`` limiter of each sandbox type the task uses.
        """
        await ensure_model_controller(
            resolved_task.model,
            resolved_task.task.config.merge(
                GenerateConfigArgs(**self.settings.generate_config)
            ),
        )
        if not self.settings.run_samples:
            return frozenset()
        return await self.sandboxes.resolve(
            resolved_task,
            self.sandboxes.selected_samples(resolved_task, self.task_names),
        )

    def apply_provider_state(self) -> None:
        self.sandboxes.apply_provider_state()

    async def start_seed(self, seed: list[TaskRecord]) -> None:
        """Ready the seed before the task display opens, failing fast.

        Every seed's sandboxes are set up first, one at a time with their
        output streamed to the terminal, and any failure raises before a log
        exists. Then each seed's first logger is created and initialised (so
        a log's ``created`` time, which names its file, follows the setups);
        if that fails or is cancelled, the loggers are discarded.
        """
        keys: set[TaskSandboxEnvironment] = set()
        for record in seed:
            assert record.configured is not None
            record.setup_keys = await self.prepare(record.configured.resolved)
            keys |= record.setup_keys
        await self.sandboxes.setup_seed(keys)
        try:
            for record in seed:
                assert record.configured is not None
                record.logger = record.configured.new_logger()
                await record.logger.init()
        except BaseException:
            with anyio.CancelScope(shield=True):
                for record in seed:
                    if record.logger is not None:
                        await record.logger.discard()
                        record.logger = None
            raise

    def _added_samples(
        self, resolved_task: ResolvedTask
    ) -> tuple[SampleSandboxSetup | None, Callable[[], None] | None]:
        """What samples a task's ``SampleSource`` adds need: setup, provider state."""
        if not self.settings.run_samples or resolved_task.task.sample_source is None:
            return None, None
        return (
            functools.partial(self.sandboxes.setup_for_samples, resolved_task),
            self.sandboxes.apply_provider_state,
        )


def ensure_sample_ids(dataset: Dataset) -> None:
    """Give samples without an id their 1-based position, then check ids are unique."""
    for id, sample in enumerate(dataset):
        if sample.id is None:
            sample.id = id + 1
    ensure_unique_ids(dataset)


class TaskRunResult(NamedTuple):
    log: EvalLog | None
    """The task's log, or ``None`` if a run-level cancellation (e.g. ctrl+c)
    ended it before it produced one."""

    cancel_type: CancelType
    """How the task was cancelled (``None`` if it ran to completion)."""

    abandoned: bool = False
    """An operator abandoned the attempt before it registered with the control
    channel (``TaskRunOptions.abandoned``): it wrote no log of its own."""


async def _run_task(options: TaskRunOptions, can_retry: bool = False) -> TaskRunResult:
    """Run one task in its own cancel scope so cancelling it can't affect siblings.

    Returns the task's :class:`EvalLog` (``None`` if a run-level cancellation
    ended it before it produced one) together with the ``CancelType`` it was
    cancelled with, so a caller managing retries can distinguish a
    retry/abort request from an ordinary error. ``can_retry`` is surfaced to
    the task (via ``TaskCancel``) so it knows whether requesting a retry will
    be honoured. The rare error that escapes ``task_run`` — a failure to
    write the log itself (e.g. the ``log_start()`` header flush) — is
    converted into an errored :class:`EvalLog` so the dispatcher can retry
    the task rather than tearing down the run; it is re-raised only when
    ``debug_errors`` is set.

    A task's own abort or retry request cancels its scope, which can also
    interrupt the task's error-log write (it is not shielded, so an abort
    can end a stuck error-log write) or the awaits after its final log
    write, and leave no log. That attempt is reported with an errored
    :class:`EvalLog` naming the cancel, so the dispatcher ends (or retries)
    only this task instead of reading a missing log as a run-level
    cancellation. Like the log of a failed write, it holds the attempt's
    header, plan and stats but no results or samples (see
    ``TaskLogger.header_log``). Its file keeps what the task wrote:
    normally the ``started`` header of the interrupted write, or the final
    log when the cancel landed after the write. (An abort that interrupts a
    success-log write instead goes through the task's cancellation handler,
    which writes the abort's error log under a shield, so a hung
    success-log write is not ended by it.)

    Once the task's scope has exited, the attempt's outcome is decided: a
    later retry request (e.g. a cancel dialog answered while
    ``task_complete`` runs) is ignored, so it cannot re-run a finished
    task. Only an abort of an attempt that ended in error is still
    recorded, so it stops the dispatcher from retrying that attempt.

    The run's ``TaskSource`` (if any) gets ``task_complete`` with the log of
    each attempt that ``task_run`` finished or that the task's abort or
    retry request interrupted (the errored log above), but not the log of
    a failed write. It is called after the task's cancel scope has exited,
    in the task's context, so it runs to completion whether or not the task
    was cancelled. An exception it raises is not a task error: it ends the
    run, as an exception from ``next_tasks()`` does.
    """
    result: EvalLog | None = None
    cancel_type: CancelType = None
    abandoned = False
    scope_exited = False
    try:
        with trace_action(
            log, "Run Task", f"task: {options.task.name} ({options.model})"
        ):
            # a per-task group so a task cancelling itself doesn't cancel
            # siblings. A task's abort/retry request cancels task_scope, which
            # encloses only task_run, so the TaskSource is notified after it
            # (see run below) in the task's context but outside the cancel.
            async with anyio.create_task_group() as task_tg:
                task_scope = anyio.CancelScope()
                task_cancel = TaskCancel(
                    can_retry=can_retry, cancel_task=lambda _: None
                )

                def cancel_task(
                    type: CancelType,
                    scope: anyio.CancelScope = task_scope,
                    tc: TaskCancel = task_cancel,
                ) -> None:
                    nonlocal cancel_type
                    # a dismissed cancel dialog passes None: no request, and
                    # it must not clear one already made
                    if type is None:
                        return
                    # after task_run the attempt's outcome is decided: only an
                    # abort of an attempt that ended in error still applies
                    # (it stops the dispatcher's retry). A retry would re-run
                    # the finished task, and any other request would
                    # misreport how it ended
                    if scope_exited and not (
                        type == "abort"
                        and result is not None
                        and result.status == "error"
                    ):
                        return
                    cancel_type = type
                    tc.cancel_type = type
                    # samples parked at the pause gate observe the stamped
                    # cancel through their escape predicate — wake them so a
                    # graceful resolution reaches the queue-exit abandon
                    # check (cancel escalates over pause)
                    wake_pause_waiters()
                    # only abort/retry tear the task's scope down. score/error
                    # are graceful sample resolutions: the caller interrupts
                    # in-flight samples, queued samples are abandoned (they
                    # check the stamped cancel_type as they leave the queue),
                    # and the task runs to natural completion.
                    if type in ("abort", "retry"):
                        scope.cancel()

                task_cancel.cancel_task = cancel_task

                async def run() -> None:
                    nonlocal result, abandoned, scope_exited
                    write_failed = False
                    with task_scope:
                        try:
                            result = await task_run(options, task_cancel=task_cancel)
                        except TaskRetryAbandonedError:
                            # an operator-requested outcome, not a task error:
                            # caught inside the trace action so it is not
                            # traced with a stacktrace. No errored log is
                            # written: the task's previous attempt's log must
                            # stay its final state.
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
                            log.error(
                                f"Task '{options.task.name}' encountered an error "
                                f"while starting or writing its log: {inner}"
                            )
                            # location points at the log file the write was
                            # destined for — it may not exist (a failed
                            # log_start() header flush, or a retry's failed
                            # checkpoint startup copy) or may hold a partial
                            # log (a failed error-status log_finish())
                            result = options.logger.header_log(
                                eval_error(
                                    inner, type(inner), inner, inner.__traceback__
                                )
                            )
                            write_failed = True
                    scope_exited = True
                    if abandoned or write_failed:
                        return
                    # task_scope swallows only its own cancellation (a
                    # run-level one propagates), so no log here means the
                    # task's abort/retry request interrupted it
                    if result is None:
                        assert cancel_type in ("abort", "retry")
                        cancel_ex = TerminateTaskError(
                            f"Task cancelled by user ({cancel_type})"
                        )
                        result = options.logger.header_log(
                            eval_error(cancel_ex, TerminateTaskError, cancel_ex, None)
                        )
                    try:
                        await notify_task_source(options, result)
                    except Exception as ex:
                        ex.add_note(
                            "Raised by TaskSource.task_complete() for task "
                            f"'{options.task.name}'."
                        )
                        raise

                task_tg.start_soon(run)
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
    return TaskRunResult(result, cancel_type)


class Startup(Protocol):
    """What the scheduling loop needs to prepare tasks (:class:`TaskStartup`)."""

    @property
    def setups(self) -> "SetupCache[Any]": ...

    async def prepare(self, resolved_task: ResolvedTask) -> frozenset[Any]: ...

    def apply_provider_state(self) -> None: ...


class TaskDispatcher:
    """The scheduling loop of one eval run.

    Starts the queue's records with bounded, model-balanced concurrency as
    they can start, and when nothing is queued or running adds more
    (``after_batch`` tasks, then the ``TaskSource``'s ``next_tasks()``) until
    there is nothing left. A record can start once it is prepared (the
    sandbox configs its samples use are resolved) and those configs are set
    up by the run's :class:`SetupCache`: a record whose setup is still running
    keeps its place but does not hold back a later one that can start. When
    every setup is done (the seed, tasks without sandboxes, configs set up
    earlier), records start in queue order.

    A task whose log comes back with an error, or which requests a retry
    through its ``TaskCancel``, is retried (reusing its completed samples)
    until its retries are exhausted; the retry goes to the back of the queue.
    An abort is never retried and resolves to an errored log; a cancellation
    of the run is never retried and ends dispatch.

    A record whose sandboxes could not be prepared or set up starts at once,
    beside the task slots: its attempt ends with that error right after it
    starts, so it has a log, hooks and a ``TaskSource`` notification like any
    failed task, and its retry sets up again.
    """

    def __init__(
        self,
        queue: RunQueue,
        startup: Startup,
        *,
        parallel: int,
        source: TaskSource | None,
        debug_errors: bool,
    ) -> None:
        self.queue = queue
        self.startup = startup
        self.setups = startup.setups
        self.parallel = parallel
        """The launch ``max_tasks`` (``ctl config --max-tasks`` overrides it live)."""
        self.source = source
        self.debug_errors = debug_errors
        self.running = 0
        """Records with an attempt running."""
        self.in_slots = 0
        """Attempts running in task slots (counted against ``max_tasks``)."""
        self.model_counts: Counter[Model] = Counter()
        """Attempts running in task slots, per model. Keyed by the ``Model``
        object, not its name: a provider may rewrite its model name mid-run
        (e.g. vLLM resolving a LoRA spec on the first generate), and the
        connection pool that balancing spreads load across belongs to the
        instance."""
        self.stopped = False
        """An attempt ended cancelled (the run was cancelled): start no more."""
        self.source_done = False
        """The ``TaskSource``'s ``next_tasks()`` returned nothing."""
        self.awaiting_source = False
        """The loop is awaiting ``next_tasks()`` (see :meth:`absorbs_cancel`)."""
        self.cancel_absorbed = False
        """The task screen absorbed a cancellation of the run."""
        self.unprepared: deque[TaskRecord] = deque()
        """Queued records not prepared yet, in queue order."""
        self.unprepared_wake = Wake()
        self.prefetched: set[TaskRecord] = set()
        """Queued records whose setups have been requested for this attempt."""
        self.fatal: BaseException | None = None
        """A ``KeyboardInterrupt`` or ``SystemExit`` raised by a setup."""
        self.tg: TaskGroup | None = None
        """The task group attempts run in, while the run is in progress."""

    async def run(self, seed: list[TaskRecord]) -> list[EvalLog]:
        """Run the seed and every task added while the run is in progress.

        Returns the logs in queue order: the seed, then added tasks in the
        order the loop took them (a retry keeps its task's position).
        """
        try:
            async with _run_task_screen(
                task_specs(seed), absorb_cancel=self.absorbs_cancel
            ) as screen:
                init_task_screen(screen)
                try:
                    add_dispatch_waker(self.queue.wake.set)
                    register_task_dispatcher(self)
                    # exceptions can escape when debug_errors is True
                    async with (
                        unwrap_exception_group("first" if self.debug_errors else None),
                        anyio.create_task_group() as tg,
                    ):
                        self.tg = tg
                        preparer = anyio.CancelScope()
                        tg.start_soon(self.prepare_records, preparer)
                        reporter = _start_throughput_reporter(tg)
                        await self.loop(tg)
                        preparer.cancel()
                        reporter.cancel()
                finally:
                    self.tg = None
                    remove_dispatch_waker(self.queue.wake.set)
                    remove_task_dispatcher(self)
                    clear_task_screen()
        finally:
            await self.end_unfinished()
        return self.queue.results()

    async def end_unfinished(self) -> None:
        """End the records left when dispatch stops (a cancelled or failed run).

        Records that never started release the loggers they held; those whose
        attempt a failed run interrupted keep the log they have. After a
        cancellation the screen absorbed, setups still running are cut short.
        """
        if self.cancel_absorbed:
            self.setups.cancel_running()
        for record in self.queue.close():
            if record.logger is not None:
                await _release_queued(record.logger, record.attempt)
            record.end(None)
        for record in self.queue.records:
            if record.state is not TaskRecordState.ENDED:
                record.end(None)

    async def loop(self, tg: TaskGroup) -> None:
        """Start records while there is capacity; when idle, add more or finish."""
        while not self.stopped:
            if self.fatal is not None:
                raise self.fatal
            self.take(self.queue.take("when_free"))
            self.fill_slots(tg)
            if self.stopped:
                break
            if self.queue.queued or self.running:
                await self.queue.wake.wait()
            elif not await self.add_when_idle():
                break

    def absorbs_cancel(self) -> bool:
        """Whether a cancellation of the run returns the logs so far (Ctrl-C).

        It does unless the loop is awaiting ``next_tasks()`` or a queued
        record is being prepared or set up (setup requested and not done):
        that work is interrupted and those tasks have no log yet, so a run
        that returned normally would look complete. Records waiting for a
        slot, a pause or their turn for setup end without a log, as unstarted
        tasks always have.
        """
        self.cancel_absorbed = not self.awaiting_source and not any(
            self.being_prepared(record) for record in self.queue.queued
        )
        return self.cancel_absorbed

    def being_prepared(self, record: TaskRecord) -> bool:
        """Whether a queued record is being prepared, or its setup is running."""
        return not self.can_start(record) and (
            record.setup_keys is None or record in self.prefetched
        )

    async def add_when_idle(self) -> bool:
        """Add more work once nothing is queued or running; ``False`` if there is none.

        In order: tasks added with ``when_free`` since this cycle took them (so
        nothing overtakes them), then ``after_batch`` tasks, then the
        ``TaskSource``'s next batch, asked until it first returns nothing.
        Tasks added while ``next_tasks()`` runs follow its batch. A cancellation
        of the run landing in ``next_tasks()`` leaves ``awaiting_source`` set,
        so it propagates (see :meth:`absorbs_cancel`).
        """
        records = self.queue.take("when_free") or self.queue.take("after_batch")
        if records:
            self.take(records)
        elif self.source is not None and not self.source_done:
            self.awaiting_source = True
            more = await self.source.next_tasks()
            self.awaiting_source = False
            if more:
                self.take(self.queue.add(self.queue.resolve(more)))
            else:
                self.source_done = True
        else:
            return not self.queue.close_if_idle(self.running)
        return True

    def take(self, records: list[TaskRecord]) -> None:
        """Queue added records to start, and grow the task display's count."""
        if not records:
            return
        self.queue.enqueue(records)
        self.unprepared.extend(records)
        self.unprepared_wake.set()
        # lets the model pause directives validate against tasks that have not
        # started (which have no EvalState to check)
        note_dispatch_models([dispatch_model_name(r.model) for r in records])
        display().update_task_count(len(records))

    async def prepare_records(self, scope: anyio.CancelScope) -> None:
        """Prepare queued records one at a time, in queue order, until ``scope`` ends."""
        with scope:
            while True:
                while not self.unprepared:
                    await self.unprepared_wake.wait()
                record = self.unprepared.popleft()
                if record.state is TaskRecordState.QUEUED:
                    await self.prepare(record)
                    self.queue.wake.set()

    async def prepare(self, record: TaskRecord) -> None:
        """Resolve a record's sandbox configs; a failure ends its next attempt."""
        assert record.configured is not None
        try:
            keys = await self.startup.prepare(record.configured.resolved)
        except Exception as ex:
            if self.debug_errors:
                raise
            failure = SetupFailure.of(ex)
        except anyio.get_cancelled_exc_class() as ex:
            if run_cancelled():
                raise
            failure = SetupFailure.of(
                RuntimeError(f"Sandbox resolution raised {ex!r}.")
            )
        else:
            record.setup_keys = keys
            return
        if record.state is TaskRecordState.QUEUED:
            record.setup_failure = failure

    def can_start(self, record: TaskRecord) -> bool:
        """Whether a queued record can start: its sandboxes are set up, or failed."""
        return record.setup_failure is not None or (
            record.setup_keys is not None and self.setups.done(record.setup_keys)
        )

    def fill_slots(self, tg: TaskGroup) -> None:
        """Start records into free slots (:meth:`pick`), then request setups ahead."""
        while (record := self.pick()) is not None:
            self.start_attempt(tg, record)
        self.prefetch_setups()

    def prefetch_setups(self) -> None:
        """Request the setups of the next ``max_tasks`` queued records that can start.

        ``max_tasks`` is read live. Paused records and records whose setup
        failed are passed over. The oldest record that cannot start yet has
        its setups marked as needed now.
        """
        window = [
            r
            for r in self.queue.queued
            if r.setup_failure is None and not _dispatch_paused(r)
        ][: effective_max_tasks(self.parallel)]
        for record in window:
            if record.setup_keys is not None and record not in self.prefetched:
                self.prefetched.add(record)
                self.setups.prefetch(
                    record.setup_keys, functools.partial(self.setup_done, record)
                )
        head = next((r for r in window if not self.can_start(r)), None)
        if head is not None and head.setup_keys is not None:
            self.setups.need(head.setup_keys)

    def setup_done(self, record: TaskRecord, failure: SetupFailure | None) -> None:
        """A setup a queued record waits for ended: it may start, or must fail.

        A ``KeyboardInterrupt`` or ``SystemExit`` the setup raised is not a
        failure of the record: the loop raises it.
        """
        if failure is not None and not isinstance(failure.error, Exception):
            self.fatal = failure.error
        elif (
            failure is not None
            and record.state is TaskRecordState.QUEUED
            and record.setup_failure is None
        ):
            record.setup_failure = failure
        self.queue.wake.set()

    def pick(self) -> TaskRecord | None:
        """The next record to start (see :func:`pick_balanced`).

        Candidates are the unpaused records that can start, ahead of the first
        one not prepared yet: preparing is quick and runs in queue order, so
        waiting for it keeps the start order deterministic when every setup is
        done. A record whose setup is running is passed over, and one whose
        setup failed needs no slot.
        """
        candidates: list[TaskRecord] = []
        for record in self.queue.queued:
            if _dispatch_paused(record):
                continue
            if record.setup_keys is None and record.setup_failure is None:
                break
            if self.can_start(record):
                candidates.append(record)
        failed = next((r for r in candidates if r.setup_failure is not None), None)
        if failed is not None:
            return failed
        if self.in_slots >= effective_max_tasks(self.parallel):
            return None
        return pick_balanced(candidates, self.model_counts)

    def start_attempt(self, tg: TaskGroup, record: TaskRecord) -> None:
        """Start a record's attempt, with the run's provider state."""
        self.queue.queued.remove(record)
        self.prefetched.discard(record)
        record.state = TaskRecordState.RUNNING
        in_slot = record.setup_failure is None
        if in_slot:
            self.in_slots += 1
            self.model_counts[record.model] += 1
        self.running += 1
        # tasks inherit the loop's context: the latest provider state
        self.startup.apply_provider_state()
        tg.start_soon(self.run_one, record, in_slot)

    async def run_one(self, record: TaskRecord, in_slot: bool) -> None:
        """Run one attempt of a record, then settle it."""
        logger, record.logger = record.logger, None
        if logger is None:
            assert record.configured is not None
            logger = record.configured.new_logger()
        try:
            await open_log(logger, retry=record.attempt > 1)
        except Exception as ex:
            if self.debug_errors:
                raise
            self.fail_attempt(record, in_slot, logger, ex)
            return
        options = self.attempt_options(record, logger)
        retry = False
        try:
            run = await _run_task(options, can_retry=record.retries_remaining > 0)
            if run.abandoned:
                # its never-started log entry goes; the task keeps its previous
                # attempt's errored log
                await logger.discard()
                self.settle(record, in_slot, None)
                return
            if run.log is None or run.log.status == "cancelled":
                self.stopped = True
            else:
                retry = wants_retry(run.cancel_type, run.log, record)
        except BaseException:
            # the run failed or was cancelled while the attempt ran
            await _release_unfinished(logger)
            raise
        if retry:
            assert run.log is not None
            # reinitialised for a fresh log entry when the retry starts
            record.logger = logger
            self.settle(record, in_slot, run.log, Retry(begin_retry(options, run.log)))
        else:
            if run.log is not None:
                # unwind the task runner's retry-pending mark (a no-op if a
                # cancel stamp during the log write already cleared it)
                clear_eval_retry_pending(run.log.eval.eval_id)
            await _release_unfinished(logger)
            self.settle(record, in_slot, run.log)

    def fail_attempt(
        self, record: TaskRecord, in_slot: bool, logger: TaskLogger, error: Exception
    ) -> None:
        """End an attempt whose log entry could not be created, as a failed write does.

        It gets an errored header log (with no location: nothing was written)
        and its retries apply.
        """
        log.error(
            f"Task '{record.task}' could not create its log: {exception_message(error)}"
        )
        retry = record.retries_remaining > 0
        if not retry and record.log is not None:
            clear_eval_retry_pending(record.log.eval.eval_id)
        header = logger.header_log(_eval_error(error))
        self.settle(record, in_slot, header, Retry(None) if retry else None)

    def attempt_options(self, record: TaskRecord, logger: TaskLogger) -> TaskRunOptions:
        """The run options of a record's next attempt."""
        assert record.configured is not None
        options = replace(
            record.configured.options(logger),
            setup_failure=record.setup_failure,
            abandoned=lambda: record.abandoned,
        )
        if record.retry_source is not None:
            options = replace(options, sample_source=record.retry_source)
        if record.attempt == 1:
            return options
        retries = record.attempt - 1 + record.retries_remaining
        return replace(
            options,
            display_name=f"{record.task} (retry {record.attempt - 1} of {retries})",
        )

    def settle(
        self,
        record: TaskRecord,
        in_slot: bool,
        task_log: EvalLog | None,
        retry: "Retry | None" = None,
    ) -> None:
        """Free an attempt's slot and record its log; queue its retry or end the record.

        ``retry`` is ``None`` when the attempt is not retried. A retry goes to
        the back of the queue, behind tasks added with ``when_free`` that the
        loop has not taken yet, so also behind follow-ups the attempt's own
        callbacks returned.
        """
        self.running -= 1
        if in_slot:
            self.in_slots -= 1
            self.model_counts[record.model] -= 1
        if task_log is not None:
            record.log = task_log
        if retry is None or record.abandoned:
            record.end(None)
        else:
            record.state = TaskRecordState.QUEUED
            if retry.sample_source is not None:
                record.retry_source = retry.sample_source
            record.attempt += 1
            record.retries_remaining -= 1
            # a setup failure is reported now; the retry sets up again
            record.setup_failure = None
            if record.setup_keys is None:
                self.unprepared.append(record)
                self.unprepared_wake.set()
            self.take(self.queue.take("when_free"))
            self.queue.queued.append(record)
            log.info(
                f"Retrying task '{record.task}' ({record.model}) "
                f"— {record.retries_remaining} retries remaining"
            )
        self.queue.wake.set()

    def stats(self) -> TaskDispatcherStats:
        """The view ``inspect ctl config`` shows of this dispatcher.

        In flight counts the records running (a record whose setup failed runs
        beside the slots, so this can briefly exceed ``max_tasks``). Pending
        counts every record waiting to start, including added ones the loop
        has not taken yet (``after_batch`` ones waiting for the run to be
        idle).
        """
        return TaskDispatcherStats(
            launch=self.parallel,
            in_flight=self.running,
            pending=len(self.queue.unstarted()),
        )

    def queued_tasks(self) -> list[QueuedTask]:
        """The records waiting to start, for ``inspect ctl task queued``."""
        return [self._queued_task(record) for record in self.queue.unstarted()]

    def queued_task(self, task_id: str) -> QueuedTask | None:
        """The record of ``task_id`` if it is waiting to start."""
        record = self._find_queued(task_id)
        return self._queued_task(record) if record is not None else None

    def cancel_queued(self, task_id: str) -> None:
        """End the record of ``task_id``, waiting to start, without running it.

        It is not retried: a first attempt leaves no log, a retry keeps the
        failed attempt's log. Its sandbox setup, if one is running, runs on
        (and is cleaned up at the end of the run).
        """
        record = self._find_queued(task_id)
        if record is not None:
            record.abandoned = True
            self._remove_queued(record)

    def abandon_retry(self, task_id: str) -> None:
        """Stop a task from being retried (a ctl drain/cancel between attempts).

        A queued retry ends at once, keeping the failed attempt's log; a
        running attempt is not retried, and one that has not yet registered
        with the control channel ends before it does.
        """
        record = self._find_queued(task_id) or next(
            (r for r in self.queue.records if r.task_id == task_id), None
        )
        if record is None or record.state is TaskRecordState.ENDED:
            return
        record.abandoned = True
        if record.state is TaskRecordState.QUEUED:
            self._remove_queued(record)

    def _queued_task(self, record: TaskRecord) -> QueuedTask:
        return QueuedTask(
            task_id=record.task_id,
            task=record.task,
            model=dispatch_model_name(record.model),
            attempt=record.attempt,
            waiting_for=self._waiting_for(record),
        )

    def _waiting_for(self, record: TaskRecord) -> WaitingFor:
        if record.idx is None:
            if record.start_policy == "after_batch":
                return "after_batch"
            return "next_tasks" if self.awaiting_source else "added"
        if _dispatch_paused(record):
            return "paused"
        if record.setup_failure is not None:
            return "failed setup"
        if record.setup_keys is None:
            return "sandbox resolution"
        if not self.setups.done(record.setup_keys):
            return "sandbox setup" if record in self.prefetched else "setup turn"
        return "slot"

    def _find_queued(self, task_id: str) -> TaskRecord | None:
        return next((r for r in self.queue.unstarted() if r.task_id == task_id), None)

    def _remove_queued(self, record: TaskRecord) -> None:
        """End a record that will not start, releasing the logger it held."""
        self.queue.remove(record)
        self.prefetched.discard(record)
        if record.logger is not None:
            assert self.tg is not None
            self.tg.start_soon(_release_queued, record.logger, record.attempt)
        if record.idx is not None and record.attempt == 1:
            # counted in the task display's total, but will never run
            display().update_task_count(-1)
        record.end(None)
        self.queue.wake.set()


class Retry(NamedTuple):
    """The retry of a failed attempt (see :meth:`TaskDispatcher.settle`)."""

    sample_source: EvalSampleSource | None
    """Where it reads the completed samples of the failed attempt (``None``:
    where the failed attempt read them)."""


async def open_log(logger: TaskLogger, *, retry: bool) -> None:
    """Create the log entry of an attempt's logger, if it has none yet.

    A new logger is initialised and a retry's (the failed attempt's) is
    reinitialised for a fresh entry; a seed's first logger already has one.
    If that fails, the logger is released (a retry's previous log stays) and
    the error raised.
    """
    try:
        if logger.location == "":
            await logger.init()
        elif retry:
            await logger.reinit()
    except BaseException:
        with anyio.CancelScope(shield=True):
            await logger.discard(keep_destination=True)
        raise


def begin_retry(options: TaskRunOptions, failed: EvalLog) -> EvalSampleSource | None:
    """Mark a failed attempt's retry as pending; where the retry reads its samples.

    Until the retry registers its own EvalState, the failed attempt is the
    task's latest: the mark stops task-keyed directives reading its
    ``completed_at`` as "task finished" (the task runner set it ahead of its
    log write; this confirms it).
    """
    mark_eval_retry_pending(failed.eval.eval_id)
    return retry_sample_source(options, failed)


async def _release_queued(logger: TaskLogger, attempt: int) -> None:
    """Release the logger a record held for an attempt that will not start.

    A seed's first logger has written nothing and is discarded; a retry's is
    the failed attempt's, whose log stays.
    """
    if attempt == 1:
        with anyio.CancelScope(shield=True):
            await logger.discard()
    else:
        await _release_unfinished(logger)


def _eval_error(ex: BaseException) -> EvalError:
    return eval_error(ex, type(ex), ex, ex.__traceback__)


async def _release_unfinished(logger: TaskLogger) -> None:
    """Release a logger whose attempt ended without finishing its log.

    Its destination file and realtime buffer are kept: they hold the samples
    saved so far, for a retry or for recovery.
    """
    if not logger.finished:
        with anyio.CancelScope(shield=True):
            await logger.discard(keep_destination=True, keep_buffer=True)


def pick_balanced(
    ready: list[TaskRecord], model_counts: Counter[Model]
) -> TaskRecord | None:
    """The next record to start, or ``None`` if there is none.

    The earliest record whose model has the fewest running attempts, so as
    many models as possible run at once. Ties go to queue order, so at a
    launch limit of 1 a sequence-ordered queue keeps all of a task's model
    fan-outs together (while every setup they need is done).
    """
    if not ready:
        return None
    fewest = min(model_counts[r.model] for r in ready)
    return next(r for r in ready if model_counts[r.model] == fewest)


def _dispatch_paused(record: TaskRecord) -> bool:
    """Whether a pause latch holds the record back from starting.

    The model name is passed to the latch because a task that has not started
    has no EvalState for the latch to resolve its model from.
    """
    return task_dispatch_paused(record.task_id, model=dispatch_model_name(record.model))


def wants_retry(cancel_type: CancelType, task_log: EvalLog, record: TaskRecord) -> bool:
    """Whether a finished, not cancelled, attempt should be retried.

    It is retried after an error or its own retry request while retries
    remain, unless a ctl drain/cancel has abandoned its retry. An abort, a
    drain or a graceful sample resolution (``score``/``error``) is a user
    cancel and is never retried, even when its log has an error status.
    """
    name = record.task
    match cancel_type:
        case "retry":
            log.info(
                f"Task '{name}' was cancelled with retry requested — "
                f"{record.retries_remaining} retries remaining"
            )
            retry = True
        case "abort":
            log.info(f"Task '{name}' was cancelled with abort requested")
            retry = False
        case "drain":
            log.info(
                f"Task '{name}' was drained — in-flight samples finished "
                "naturally, queued samples abandoned"
            )
            retry = False
        case None:
            retry = task_log.status == "error"
        case resolution:
            log.info(
                f"Task '{name}' was cancelled with sample resolution '{resolution}'"
            )
            retry = False
    if not retry or record.retries_remaining == 0:
        return False
    if record.abandoned:
        log.info(
            f"Task '{name}' retry abandoned by operator — task ends with this "
            "attempt's error log"
        )
        return False
    return True


def retry_sample_source(
    options: TaskRunOptions, failed: EvalLog
) -> EvalSampleSource | None:
    """Where the retry of a failed attempt reads its completed samples from.

    The failed attempt's log file whenever a flush reached it, finished or
    not: it holds the seeded prior samples plus every completion flushed
    since (an unfinished one sits under a ``started`` header, which the
    retry's ``reinit()`` leaves in place). An attempt that wrote nothing (its
    prior-log seed or ``log_start`` flush failed) keeps the source it ran with.
    Decided from recorder state, with no filesystem probe.
    """
    if not options.logger.destination_written:
        log.info(
            f"Task '{options.task.name}' wrote no log for this attempt; retrying "
            "with the prior attempt's sample source"
        )
        return options.sample_source
    location = options.logger.location
    return eval_log_sample_source(
        failed,
        EvalLogInfo(
            name=location,
            type="file",
            size=0,
            mtime=None,
            task=options.task.name,
            task_id=options.logger.eval.task_id,
            suffix=None,
        ),
        options.task.dataset,
        eval_checkpoints_dir_from_config(
            location, options.checkpoint, options.eval_checkpoint
        ),
    )


def _start_throughput_reporter(tg: TaskGroup) -> anyio.CancelScope:
    """Start the run's periodic ``[Throughput]`` trace reporter.

    See design/model-throughput.md §4. Returns its cancel scope: dispatch ends
    by returning while the task group waits for its children, so the reporter
    must then be cancelled. The reporter is observability only, so a failure
    in it is logged, never raised into the run.
    """
    scope = anyio.CancelScope()

    async def report() -> None:
        from inspect_ai.model._throughput import report_throughput_periodically

        with scope:
            try:
                await report_throughput_periodically()
            except Exception as ex:
                log.warning(f"Throughput reporter failed: {ex}")

    tg.start_soon(report)
    return scope


ProviderState = dict[ContextVar[Any], Any]
"""ContextVars a sandbox provider set, with the values it left."""

_UNSET = object()

# characters of a failed sandbox setup's output shown with its error
_SETUP_OUTPUT_SHOWN = 4000


class _TaskCleanup(NamedTuple):
    """A started sandbox config's ``task_cleanup`` and what it runs with."""

    cleanup: TaskCleanup
    config: SandboxEnvironmentConfigType | None
    run_dir: str
    state: ProviderState
    """The provider state right after the config's ``task_init``."""


class SandboxManager:
    """Sets up the run's sandbox configs and tears them all down at its end.

    Use as an async context manager around the run. Each sandbox config is set
    up once (its provider's ``task_init``) by the run's :class:`SetupCache`,
    whoever needs it: the seed before the run starts, a queued task ahead of
    its turn, a `SampleSource` adding samples to a running task. Each config's
    ``task_cleanup`` runs once, when the run ends.

    Providers may keep state in ContextVars that ``task_init`` sets and
    ``sample_init`` / ``task_cleanup`` read (Modal, E2B, Daytona, k8s). Each
    ``task_init`` runs in a child task started from the context taken when
    the manager was entered, with the run's provider state so far set (so a
    provider's get-or-create finds it). The ContextVars it sets are recorded:
    they are added to the run's provider state, which the scheduling loop
    sets in its own context before it starts each task (the latest value of
    each winning, as when every ``task_init`` ran in that context), and its
    config's ``task_cleanup`` runs with the state as it was right after it.
    So a cleanup sees its own state even after a later ``task_init`` of the
    same provider set the ContextVar again, and nothing of the task that
    asked for the setup.

    The manager also owns the run's sandbox lifecycle state (the registries
    a provider's `task_cleanup` reads: running containers, generated config
    files), bound in the calling context on entry, before any task of the run
    is spawned, so every setup and every task registers on the same object.
    It is released on exit, so a later run in the same process starts clean.
    """

    def __init__(self, config: EvalConfig, *, cleanup: bool) -> None:
        """Create the run's sandbox manager.

        Args:
            config: The eval config (sample selection, ``max_sandboxes``,
                ``sandbox_prebuilt``).
            cleanup: Whether ``task_cleanup`` removes what setup created.
        """
        self._config = config
        self._cleanup = cleanup
        self.setups: SetupCache[TaskSandboxEnvironment] = SetupCache(self._init_one)
        self.collect_output = False
        """Collect setup output (shown if the setup fails) instead of letting it
        through to the terminal: set once the task display is open."""
        self._cleanups: list[_TaskCleanup] = []
        self._state: ProviderState = {}
        self._exit_stack = AsyncExitStack()
        self._context = copy_context()
        # keyed by task, then spec: resolution folds in per-task state
        # (run_dir), so a spec-only key would leak one task's resolution to
        # another. Weak on the task, so a finished task's Task and dataset are
        # not kept alive until the run ends
        self._resolved_no_metadata: weakref.WeakKeyDictionary[
            Task, dict[SandboxEnvironmentSpec, TaskSandboxEnvironment]
        ] = weakref.WeakKeyDictionary()

    async def __aenter__(self) -> "SandboxManager":
        self._exit_stack.enter_context(sandbox_lifecycle_scope())
        set_sandbox_prebuilt(self._config.sandbox_prebuilt is True)
        # setups and cleanups run from here, so they see neither the state of
        # the task that asked for them nor (cleanups) what later setups set
        self._context = copy_context()
        self._exit_stack.push_async_callback(self._cleanup_all)
        # exits first: setups still in progress when the run ends are cancelled
        await self._exit_stack.enter_async_context(self.setups)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self._exit_stack.__aexit__(exc_type, exc, tb)

    async def _cleanup_all(self) -> None:
        """Run every accumulated `task_cleanup`.

        The final cleanup of the run: it also covers samples whose own cleanup
        was deferred by an interruption, since their provider state is on the
        scope this manager owns. A failing cleanup is logged and the others
        still run.
        """

        async def cleanup(job: _TaskCleanup) -> None:
            with sandbox_setup_scope(SandboxSetup(job.run_dir)):
                await job.cleanup("shutdown", job.config, self._cleanup)

        with anyio.CancelScope(shield=True):
            for job in self._cleanups:
                try:
                    await _in_child_task(
                        functools.partial(cleanup, job),
                        job.state,
                        context=self._context,
                    )
                except BaseException as ex:
                    log.warning(
                        f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                    )

    def apply_provider_state(self) -> None:
        """Set the run's provider state in the current context (for tasks it starts)."""
        _set_provider_state(self._state)

    async def setup_seed(self, sandboxenvs: Iterable[TaskSandboxEnvironment]) -> None:
        """Set up sandbox configs now (the seed's, before the task display opens).

        Their output goes to the terminal; the first failure raises.
        """
        sandboxenvs = list(sandboxenvs)
        if self.setups.done(sandboxenvs):
            return
        # one at a time, so none starts after a failure
        for sandboxenv in sandboxenvs:
            await self.setups.ensure([sandboxenv])
        # space above the task display ("none" has none and must keep stdout
        # machine-readable, e.g. --json)
        if display_type() != "none":
            print("")

    async def setup_for_samples(
        self, task: ResolvedTask, samples: Iterable[Sample]
    ) -> None:
        """Set up the sandbox configs of samples a `SampleSource` adds to a task.

        A config first seen in an added sample (including the task-level config
        when the seed dataset was empty) gets the same `task_init` setup as
        seed configs (up-front image build/pull, fail-fast validation, a
        registered `task_cleanup`) before the sample runs; configs already set
        up are a no-op. Each added sample starts with the run's provider state
        as it is then (see ``TaskRunOptions.apply_provider_state``).
        """
        await self.setups.ensure(await self.resolve(task, samples))

    def selected_samples(
        self, task: ResolvedTask, task_names: list[str]
    ) -> Iterable[Sample]:
        """The samples of `task` that the eval's sample selection runs.

        `task_names` is every task name known to the run so far, so `task:id`
        sample selectors resolve here exactly as they do when the task runs.
        """
        return slice_dataset(
            task.task.dataset,
            self._config.limit,
            resolve_task_sample_ids(task.task.name, self._config.sample_id, task_names),
            dynamic=task.task.sample_source is not None,
        )

    async def resolve(
        self, task: ResolvedTask, samples: Iterable[Sample]
    ) -> frozenset[TaskSandboxEnvironment]:
        """The sandbox configs ``samples`` of ``task`` use; registers their limiters.

        Each sample's config is deduped and sandbox-less samples are skipped.
        The limiter of each sandbox type is registered here, before any setup,
        so a ``ctl config --max-sandboxes`` retune reaches a type whose tasks
        are still waiting. Full resolution reads the sandbox config (and, for
        docker configs with metadata interpolation, spawns a subprocess) per
        sample. Metadata-less samples resolve deterministically per spec, so
        those resolutions are cached; samples with metadata must always fully
        resolve (their config may interpolate it into a per-sample init
        environment).
        """
        sandboxenvs: set[TaskSandboxEnvironment] = set()
        resolved = self._resolved_no_metadata.setdefault(task.task, {})
        for sample in samples:
            sandboxenv: TaskSandboxEnvironment | None = None
            cache_key: SandboxEnvironmentSpec | None = None
            if not sample.metadata:
                spec = await resolve_sandbox(
                    task.sandbox,
                    sample,
                    task.task.name,
                    task_dir=task_run_dir(task.task),
                )
                if spec is None:
                    continue
                cache_key = spec
                sandboxenv = resolved.get(cache_key)
            if sandboxenv is None:
                sandboxenv = await resolve_sandbox_for_task_and_sample(
                    task.sandbox, task.task, sample
                )
                if sandboxenv is not None and cache_key is not None:
                    resolved[cache_key] = sandboxenv
            if sandboxenv is not None:
                sandboxenvs.add(sandboxenv)
        for sandbox_type in {env.sandbox.type for env in sandboxenvs}:
            await ensure_sandbox_limiter(
                registry_find_sandboxenv(sandbox_type),
                sandbox_type,
                self._config.max_sandboxes,
            )
        return frozenset(sandboxenvs)

    async def _init_one(self, sandboxenv: TaskSandboxEnvironment) -> None:
        """Set up one sandbox config: its provider's `task_init` (a setup job).

        As soon as `task_init` returns, its cleanup is recorded (to run with
        the provider state it started from plus what it set) and what it set
        is added to the run's provider state, even if a cancellation then
        lands.
        """
        sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)
        task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
        task_cleanup = cast(TaskCleanup, getattr(sandboxenv_type, "task_cleanup"))
        setup = SandboxSetup(
            sandboxenv.run_dir,
            dict(sandboxenv.env),
            output=[] if self.collect_output else None,
        )
        state = self._state

        async def init() -> None:
            with sandbox_setup_scope(setup):
                await task_init("startup", sandboxenv.sandbox.config)

        def started(changes: ProviderState) -> None:
            self._cleanups.append(
                _TaskCleanup(
                    task_cleanup,
                    sandboxenv.sandbox.config,
                    sandboxenv.run_dir,
                    state | changes,
                )
            )
            self._state = self._state | changes

        try:
            await _in_child_task(init, state, done=started, context=self._context)
        except Exception as ex:
            if setup.output:
                ex.add_note(
                    "Output of the sandbox setup:\n"
                    + "".join(setup.output)[-_SETUP_OUTPUT_SHOWN:]
                )
            raise


async def _in_child_task(
    fn: Callable[[], Awaitable[None]],
    state: ProviderState,
    done: Callable[[ProviderState], None] = lambda changes: None,
    context: Context | None = None,
) -> ProviderState:
    """Run ``fn`` in a child task with ``state`` set; return the ContextVars it set.

    The child starts from a copy of ``context`` (default: the caller's).

    The child's ContextVar writes stay out of the caller's context, so only
    what ``fn`` itself sets is kept, rather than a copy of the caller's whole
    context, which would keep the caller's state (its task display, a running
    task's settings) alive and visible to a later ``task_cleanup``. ``done``
    gets them in the child, as soon as ``fn`` returns: a cancellation can
    still be raised in the caller after that (asyncio raises one that arrived
    while ``fn`` shielded its work), and what ``fn`` did must not be lost.

    An exception from ``fn`` is re-raised in the caller as it is: a task group
    would wrap it in a group, and would drop a ``CancelledError`` that is not
    the group's own.
    """
    changes: ProviderState = {}
    error: BaseException | None = None

    async def run() -> None:
        nonlocal error
        _set_provider_state(state)
        base = copy_context()
        try:
            await fn()
        except BaseException as ex:
            error = ex
            return
        changes.update(
            (var, value)
            for var, value in copy_context().items()
            if base.get(var, _UNSET) is not value
        )
        done(changes)

    async with anyio.create_task_group() as tg:
        (context or copy_context()).copy().run(tg.start_soon, run)
    if error is not None:
        raise error
    return changes


def _set_provider_state(state: ProviderState) -> None:
    """Set provider ContextVars in the current context, for the tasks it starts."""
    for var, value in state.items():
        var.set(value)


@asynccontextmanager
async def _run_task_screen(
    tasks: list[TaskSpec], absorb_cancel: Callable[[], bool]
) -> AsyncIterator[TaskScreen]:
    """Open the display's task screen for a run that absorbs cancellation.

    A cancellation of the run body is absorbed when ``absorb_cancel()`` says
    so at that point, and the run returns the logs it has. Trio raises that
    cancellation again at every checkpoint inside the cancelled scope, so a
    display whose teardown awaits (the rich display's update-loop task group)
    raises it again; that one is absorbed too. A cancellation of the body
    that is not absorbed, from the teardown of a body that was not cancelled,
    or from the display's setup, propagates.
    """
    body_cancelled = False
    try:
        async with display().task_screen(tasks, parallel=True) as screen:
            try:
                yield screen
            except anyio.get_cancelled_exc_class():
                if not absorb_cancel():
                    raise
                body_cancelled = True
    except anyio.get_cancelled_exc_class():
        if not body_cancelled:
            raise


def task_specs(seed: list[TaskRecord]) -> list[TaskSpec]:
    """The task display's rows for the seed (whose records have their loggers)."""
    specs: list[TaskSpec] = []
    for record in seed:
        assert record.configured is not None and record.logger is not None
        options = record.configured.options(record.logger)
        specs.append(
            TaskSpec(
                task_display_name(options.task.name),
                ModelName(options.model),
                plan_agent_name(resolve_plan(options.task, options.solver)),
            )
        )
    return specs


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
