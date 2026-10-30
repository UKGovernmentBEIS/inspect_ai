import functools
import logging
import os
import weakref
from collections import Counter
from contextlib import ExitStack, asynccontextmanager, nullcontext
from contextvars import Context, ContextVar, copy_context
from copy import copy
from dataclasses import dataclass, replace
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    NamedTuple,
    TypeVar,
    cast,
)

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._util._async import unwrap_exception_group
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
from inspect_ai.log import EvalConfig, EvalLog
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
from .task.enqueue import Attempt, RunQueue
from .task.log import TaskLogger
from .task.resolved import ResolvedTask, resolved_task_names
from .task.run import (
    EvalSampleSource,
    TaskRunOptions,
    TaskSandboxSetup,
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
from .task.task import Task
from .task.task_source import TaskSource
from .task.util import resolve_task_sample_ids, slice_dataset, task_run_dir

log = logging.getLogger(__name__)

T = TypeVar("T")


def setup_in_slot() -> bool:
    """Whether each task starts its own sandboxes, while other tasks run.

    A prototype mode, "slot mode" (``INSPECT_TASK_SETUP_IN_SLOT=1``). By
    default each group of tasks starts its sandboxes before any of it is
    dispatched, and the scheduling loop waits meanwhile. In slot mode a task
    starts its sandboxes once it has started (in ``task_run``, before its
    samples), beside running tasks (see :class:`TaskDispatcher` for where it
    runs meanwhile): provider state reaches only that task, a setup failure
    ends only that task, and setup output is collected for the task.
    """
    return os.environ.get("INSPECT_TASK_SETUP_IN_SLOT") == "1"


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
            eval_config,
            cleanup=eval_config.sandbox_cleanup is not False,
            in_slot=setup_in_slot(),
        ) as sandboxes:
            start_up = GroupStartup(
                settings,
                sandboxes,
                parallel=parallel,
                task_names=list(eval_set_tasks or []),
            )
            dispatcher = TaskDispatcher(
                queue,
                start_up,
                parallel=parallel,
                task_retry_attempts=task_retry_attempts or 0,
                source=task_source,
                debug_errors=debug_errors,
            )
            return await dispatcher.run(await start_up(tasks))
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

    def task_options(
        self,
        resolved_task: ResolvedTask,
        task_names: list[str],
        sandboxes: "TaskSandboxStarts",
    ) -> TaskRunOptions:
        """Configure one task of the run: validate it and create its logger.

        Eval-level settings are resolved against a shallow copy of the task, so
        repeated ``eval()`` calls on the same ``Task`` do not keep them (nested
        state such as the dataset, config and reducer list is still shared, so
        it must not be changed in place). Runs in the task's run directory (the
        logger records the git revision and paths relative to it); ``chdir`` is
        process-wide, so nothing here may await.

        Args:
            resolved_task: The task as resolved against the run's models.
            task_names: Every task name known to the run (``task:id`` sample
                selectors).
            sandboxes: The sandbox start-ups the task runs itself.

        Raises:
            PrerequisiteError: If the task can't run with these settings.
        """
        with chdir(task_run_dir(resolved_task.task)):
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
            logger = TaskLogger(
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
            startup_sandboxes=sandboxes.added_samples,
            sandbox_setup=sandboxes.own_setup,
            input_media_policy=resolved_task.input_media_policy,
        )

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


SampleSandboxStartup = Callable[[Iterable[Sample]], Awaitable[None]]
"""Starts the sandboxes some of a task's samples need, from inside the task."""


class TaskSandboxStarts(NamedTuple):
    """The sandbox start-ups a task runs itself, once it is running."""

    own_setup: TaskSandboxSetup | None
    """The setup of the task's own samples' sandboxes, run before they run (in
    slot mode, for a task with setup to do)."""

    added_samples: SampleSandboxStartup | None
    """For samples a ``SampleSource`` adds while the task runs."""


@dataclass
class GroupStartup:
    """Starts up the groups of tasks of one run (see :meth:`__call__`)."""

    settings: TaskSettings
    sandboxes: "SandboxManager"
    parallel: int
    task_names: list[str]
    """Every task name known to the run, for ``task:id`` sample selectors: the
    enclosing eval set's (a retry runs only some of them), then each group's
    as it starts up, so an added task sees the tasks before it."""

    async def __call__(self, group: list[ResolvedTask]) -> list[TaskRunOptions]:
        """Start up a group of tasks, ready to run.

        Steps: sample ids, model controllers (created eagerly so ``ctl config``
        can retune ``max_connections`` during a long sandbox start-up), the
        group's sandboxes, configuration, logger init. The group starts up
        whole, before any of it runs, so a failure fails the run before any of
        the group runs and each log's ``created`` time (which names its file)
        follows the sandbox start-up. In slot mode the tasks start their own
        sandboxes later; here each task's setup is prepared (if it has setup
        to do) and the sandbox types' ``ctl`` limiters are registered.

        At a launch limit of 1 the group is ordered by sequence: the scheduling
        loop breaks ties in queue order, so all of a task's model fan-outs run
        before the next task's. The group's loggers belong to this call until
        it returns: if it fails or is cancelled, they are discarded.
        """
        if self.parallel == 1:
            group = sorted(group, key=lambda t: t.sequence)
        self.task_names.extend(
            name for name in resolved_task_names(group) if name not in self.task_names
        )
        for resolved_task in group:
            ensure_sample_ids(resolved_task.task.dataset)
        own_setups = (
            await self._prepare_resources(group)
            if self.settings.run_samples
            else [None] * len(group)
        )
        options = [
            self.settings.task_options(
                t, self.task_names, self._sandbox_starts(t, own_setup)
            )
            for t, own_setup in zip(group, own_setups)
        ]
        await _init_loggers(options)
        return options

    async def _prepare_resources(
        self, group: list[ResolvedTask]
    ) -> "list[TaskSandboxes | None]":
        """Model controllers, then the group's sandboxes (in slot mode, each task's setup)."""
        for resolved_task in group:
            await ensure_model_controller(
                resolved_task.model,
                resolved_task.task.config.merge(
                    GenerateConfigArgs(**self.settings.generate_config)
                ),
            )
        if self.sandboxes.in_slot:
            return await self.sandboxes.task_setups(group, self.task_names)
        elif any(t.has_sandbox for t in group):
            await self.sandboxes.start(group, self.task_names)
        return [None] * len(group)

    def _sandbox_starts(
        self, resolved_task: ResolvedTask, own_setup: "TaskSandboxes | None"
    ) -> TaskSandboxStarts:
        if not self.settings.run_samples:
            return TaskSandboxStarts(None, None)
        return TaskSandboxStarts(
            own_setup=own_setup,
            added_samples=(
                functools.partial(self.sandboxes.start_for_samples, resolved_task)
                if resolved_task.task.sample_source is not None
                else None
            ),
        )


async def _init_loggers(options: list[TaskRunOptions]) -> None:
    """Initialise a group's loggers; if that fails or is cancelled, discard them all."""
    try:
        for task_options in options:
            await task_options.logger.init()
    except BaseException:
        with anyio.CancelScope(shield=True):
            for task_options in options:
                await task_options.logger.discard()
        raise


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
    """The attempt was abandoned at start: a task drain/cancel stamped the
    retry-abandoned registry after the dispatcher dequeued this retry but
    before the attempt registered its ``EvalState``. A dedicated field
    (not an overload of ``log`` or ``cancel_type``) because every natural
    return shape misfires in ``run_one``: a ``None``/cancelled-status log
    reads as an external cancellation and ends the whole dispatch loop,
    and an unstamped error log would queue another retry. ``run_one``
    checks it before the external-cancellation branch and maps it to a
    side-effect-free finalize."""


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


StartUpFn = Callable[[list[ResolvedTask]], Awaitable[list[TaskRunOptions]]]
"""Starts up a group of tasks (:class:`GroupStartup`; tests pass a fake)."""


class TaskDispatcher:
    """The scheduling loop of one eval run.

    Starts the queue's ready attempts with bounded, model-balanced concurrency,
    starts up the tasks added to the queue as they arrive, and when nothing is
    ready or running adds more (``after_batch`` tasks, then the ``TaskSource``'s
    ``next_tasks()``) until there is nothing left. A task whose log comes back
    with an error, or which requests a retry through its ``TaskCancel``, is
    retried (reusing its completed samples) until ``task_retry_attempts`` is
    exhausted. An abort is never retried and resolves to an errored log; a
    cancellation of the run is never retried and ends dispatch.

    When each task starts its own sandboxes (slot mode), an attempt with setup
    to do (:func:`needs_setup`) starts in the setup lane instead of a task
    slot. The lane holds one attempt, from its start until it has set up and
    takes a slot, so setups run one at a time, outside the ``max_tasks``
    slots, and no slot waits for another task's setup. The attempt starts as
    any other does (its log, the control channel, ``on_task_start``), so how
    its setup ends is handled as for any started task.
    """

    def __init__(
        self,
        queue: RunQueue,
        group_startup: StartUpFn,
        *,
        parallel: int,
        task_retry_attempts: int,
        source: TaskSource | None,
        debug_errors: bool,
    ) -> None:
        self.queue = queue
        self.group_startup = group_startup
        self.parallel = parallel
        """The launch ``max_tasks`` (``ctl config --max-tasks`` overrides it live)."""
        self.task_retry_attempts = task_retry_attempts
        self.source = source
        self.debug_errors = debug_errors
        self.in_slots = 0
        """Attempts running in task slots (counted against ``max_tasks``)."""
        self.model_counts: Counter[Model] = Counter()
        """Attempts running in task slots, per model. Keyed by the ``Model`` object, not its
        name: a provider may rewrite its model name mid-run (e.g. vLLM resolving
        a LoRA spec on the first generate), and the connection pool that
        balancing spreads load across belongs to the instance."""
        self.results: dict[int, EvalLog] = {}
        self.next_index = 0
        self.cancelled = False
        """An attempt ended cancelled (the run was cancelled): start no more."""
        self.source_done = False
        self.adding = False
        """The loop is starting up added tasks or awaiting ``next_tasks()``
        (see :meth:`run`)."""
        self.starting_up = 0
        """Tasks of the group being started up (counted as pending)."""
        self.lane: _LaneAttempt | None = None
        """The attempt in the setup lane, until it takes a task slot."""

    async def run(self, seed: list[TaskRunOptions]) -> list[EvalLog]:
        """Run the seed and every task added while the run is in progress.

        Returns the logs in queue order: the seed, then added tasks in the
        order they became ready (a retry keeps its task's position).

        A cancellation of the run that lands while tasks run or the loop waits
        is absorbed: the running tasks write cancelled logs and the run returns
        them. One that lands while the loop starts up added tasks or awaits
        ``next_tasks()`` propagates: the tasks it interrupts have no log yet,
        so a run that returned normally would look complete.
        """
        self.make_ready(seed)
        try:
            async with _run_task_screen(
                task_specs(seed), absorb_cancel=lambda: not self.adding
            ) as screen:
                init_task_screen(screen)
                try:
                    add_dispatch_waker(self.queue.wake.set)
                    register_task_dispatcher(self.stats)
                    # exceptions can escape when debug_errors is True
                    async with (
                        unwrap_exception_group("first" if self.debug_errors else None),
                        anyio.create_task_group() as tg,
                    ):
                        reporter = _start_throughput_reporter(tg)
                        await self.loop(tg)
                        reporter.cancel()
                finally:
                    remove_dispatch_waker(self.queue.wake.set)
                    remove_task_dispatcher(self.stats)
                    clear_task_screen()
        finally:
            # attempts that never started (a cancelled or failed run)
            with anyio.CancelScope(shield=True):
                for attempt in self.queue.close():
                    await attempt.options.logger.discard()
        return [log for _, log in sorted(self.results.items())]

    async def loop(self, tg: TaskGroup) -> None:
        """Start ready attempts while there is capacity; when idle, add more or finish.

        Once dispatch stops on a cancelled run, an attempt in the setup lane
        has still started, so it is still given a slot when one frees.
        """
        while not self.cancelled:
            await self.add_group(self.queue.take("when_free"))
            await self.drop_abandoned_retries()
            self.start_ready(tg)
            if self.cancelled:
                break
            if self.queue.ready or self.started:
                await self.queue.wake.wait()
            elif not await self.add_when_idle():
                # no await before returning: an addition accepted after this
                # point would never run
                self.queue.close()
                break
        while self.lane is not None:
            self.start_ready(tg)
            if self.lane is not None:
                await self.queue.wake.wait()

    @property
    def started(self) -> int:
        """Attempts started and not finished: in task slots and in the setup lane."""
        return self.in_slots + (self.lane is not None)

    async def add_when_idle(self) -> bool:
        """Add more work once nothing is ready or running; ``False`` if there is none.

        In order: tasks added with ``when_free`` since this cycle took them (so
        nothing overtakes them), then ``after_batch`` tasks, then the
        ``TaskSource``'s next batch, asked until it first returns nothing.
        Tasks added while ``next_tasks()`` runs follow its batch.
        """
        group = self.queue.take("when_free") or self.queue.take("after_batch")
        if group:
            await self.add_group(group)
        elif self.source is not None and not self.source_done:
            more = await self.while_adding(self.source.next_tasks())
            if more:
                await self.add_group(self.queue.resolve(more))
            else:
                self.source_done = True
        else:
            return False
        return True

    async def add_group(self, group: list[ResolvedTask]) -> None:
        """Start up added tasks, make them ready and grow the task display's count."""
        if not group:
            return
        self.starting_up = len(group)
        try:
            options = await self.while_adding(self.group_startup(group))
        finally:
            self.starting_up = 0
        self.make_ready(options)
        display().update_task_count(len(options))

    async def while_adding(self, adding: Awaitable[T]) -> T:
        """Await a step of adding tasks.

        A cancellation landing in it propagates (see :meth:`run`): the flag is
        left set when the step raises, so the task screen re-raises it.
        """
        self.adding = True
        result = await adding
        self.adding = False
        return result

    def make_ready(self, options: list[TaskRunOptions]) -> None:
        """Queue started-up tasks as ready attempts, in order."""
        self.queue.ready.extend(
            Attempt(self.next_index + i, task_options, self.task_retry_attempts)
            for i, task_options in enumerate(options)
        )
        self.next_index += len(options)
        # lets the model pause directives validate against tasks that have not
        # started (which have no EvalState to check)
        note_dispatch_models([dispatch_model_name(o.model) for o in options])

    async def drop_abandoned_retries(self) -> None:
        """Discard ready retries whose task a ctl drain/cancel abandoned.

        See design/ctl/task-drain.md ("Tasks between attempts"). Runs before
        the pause filter, so a paused retry can be dropped too. Only retries
        can carry a stamped task id, and each carries an eagerly reinitialised,
        never-started log entry.
        """
        for attempt in [
            a
            for a in self.queue.ready
            if task_retry_abandoned(a.options.logger.eval.task_id)
        ]:
            self.queue.ready.remove(attempt)
            await attempt.options.logger.discard()

    def start_ready(self, tg: TaskGroup) -> None:
        """Fill the free task slots under ``max_tasks``, and the setup lane.

        A free slot goes first to the lane's attempt once it has set up, then
        to a ready attempt with no setup to do; the lane, once free, takes a
        ready attempt that has setup to do. Paused attempts are passed over,
        the lane's included (a resume fires the dispatch waker). The limit is
        read live for each slot (a ``ctl config --max-tasks`` set fires the
        waker too). Once dispatch has stopped (``cancelled``), only the lane's
        attempt, which has started, is still given a slot. A method of its
        own so the loop keeps no reference to the last attempt it started,
        which would keep that task's ``Task`` and dataset alive after it
        finishes.
        """
        while True:
            slot_free = self.in_slots < effective_max_tasks(self.parallel)
            lane = self.lane
            if (
                slot_free
                and lane is not None
                and lane.setup_done
                and not _dispatch_paused(lane.attempt)
            ):
                self.lane = None
                self.take_slot(lane.attempt)
                lane.grant_slot()
            elif self.cancelled:
                return
            elif lane is None and (attempt := self.pick(setup=True)):
                self.lane = _LaneAttempt(attempt, self.queue.wake.set)
                self.queue.ready.remove(attempt)
                tg.start_soon(self.run_one, attempt, self.lane)
            elif slot_free and (attempt := self.pick(setup=False)):
                self.queue.ready.remove(attempt)
                self.take_slot(attempt)
                tg.start_soon(self.run_one, attempt, None)
            else:
                return

    def pick(self, *, setup: bool) -> Attempt | None:
        """The next ready attempt that has (or has no) setup to do.

        See :func:`pick_balanced`.
        """
        return pick_balanced(
            [a for a in self.queue.ready if needs_setup(a) == setup],
            self.model_counts,
        )

    def take_slot(self, attempt: Attempt) -> None:
        """Count an attempt as running in a task slot (and against its model)."""
        self.in_slots += 1
        self.model_counts[attempt.options.model] += 1

    async def run_one(self, attempt: Attempt, lane: "_LaneAttempt | None") -> None:
        """Run one attempt, then settle its log, its retry and its slot (or the lane)."""
        options = (
            attempt.options
            if lane is None
            else replace(attempt.options, wait_for_task_slot=lane.wait_for_slot)
        )
        retry: Attempt | None = None
        try:
            run = await _run_task(options, can_retry=attempt.retries_remaining > 0)
            if run.abandoned:
                # its never-started log entry goes; the task keeps its previous
                # attempt's errored log (already in the results)
                await options.logger.discard()
                self.finish(attempt, lane, task_log=None, retry=None)
                return
            if run.log is None or run.log.status == "cancelled":
                self.cancelled = True
            elif wants_retry(run.cancel_type, run.log, attempt):
                # before the slot is freed: the loop must not see an idle run
                # while the retry's logger reinitialises
                retry = await self.next_attempt(attempt, run.log)
        except BaseException:
            # the run failed or was cancelled while the attempt ran or while its
            # retry's logger reinitialised
            await _release_unfinished(options.logger)
            raise
        if retry is None:
            if run.log is not None:
                # unwind the task runner's retry-pending mark (a no-op if a
                # cancel stamp during the log write already cleared it)
                clear_eval_retry_pending(run.log.eval.eval_id)
            await _release_unfinished(options.logger)
        self.finish(attempt, lane, task_log=run.log, retry=retry)

    async def next_attempt(self, attempt: Attempt, failed: EvalLog) -> Attempt:
        """The retry of a failed attempt: a fresh log entry reusing its completed samples."""
        options = attempt.options
        # until the retry registers its own EvalState, the failed attempt is the
        # task's latest: the flag stops task-keyed directives reading its
        # completed_at as "task finished" (the task runner set it ahead of its
        # log write; this confirms it)
        mark_eval_retry_pending(failed.eval.eval_id)
        sample_source = retry_sample_source(options, failed)
        await options.logger.reinit()
        number = self.task_retry_attempts - attempt.retries_remaining + 1
        return attempt._replace(
            options=replace(
                options,
                sample_source=sample_source,
                display_name=(
                    f"{options.task.name} "
                    f"(retry {number} of {self.task_retry_attempts})"
                ),
            ),
            retries_remaining=attempt.retries_remaining - 1,
        )

    def finish(
        self,
        attempt: Attempt,
        lane: "_LaneAttempt | None",
        *,
        task_log: EvalLog | None,
        retry: Attempt | None,
    ) -> None:
        """Free the attempt's slot or the setup lane, record its log, queue its retry.

        No await, so the loop never sees the freed slot without the retry.
        """
        options = attempt.options
        if lane is not None and self.lane is lane:
            # it ended in the lane, before it was given a slot
            self.lane = None
        else:
            self.in_slots -= 1
            self.model_counts[options.model] -= 1
        if task_log is not None:
            self.results[attempt.idx] = task_log
        if retry is not None:
            self.queue.ready.append(retry)
            log.info(
                f"Retrying task '{options.task.name}' ({options.model}) "
                f"— {retry.retries_remaining} retries remaining"
            )
        self.queue.wake.set()

    def stats(self) -> TaskDispatcherStats:
        """The view ``inspect ctl config`` shows of this dispatcher.

        In flight counts the started tasks: those in task slots and the one in
        the setup lane (so it can be one more than ``max_tasks``). Pending
        counts every task waiting to start: ready attempts, tasks being
        started up, and added tasks not yet taken (including ``after_batch``
        ones waiting for the run to be idle).
        """
        return TaskDispatcherStats(
            launch=self.parallel,
            in_flight=self.started,
            pending=len(self.queue.ready) + self.starting_up + self.queue.waiting(),
        )


class _LaneAttempt:
    """The attempt in the setup lane: started, setting up outside the task slots."""

    def __init__(self, attempt: Attempt, wake: Callable[[], None]) -> None:
        self.attempt = attempt
        self.setup_done = False
        """Its setup has finished; it waits for a task slot."""
        self._slot_granted = anyio.Event()
        self._wake = wake

    async def wait_for_slot(self) -> None:
        """Mark the attempt's setup done and wait until the dispatcher grants it a slot."""
        self.setup_done = True
        self._wake()
        await self._slot_granted.wait()

    def grant_slot(self) -> None:
        self._slot_granted.set()


def needs_setup(attempt: Attempt) -> bool:
    """Whether an attempt has sandbox setup to do before its samples can run (slot mode)."""
    setup = attempt.options.sandbox_setup
    return setup is not None and not setup.started()


async def _release_unfinished(logger: TaskLogger) -> None:
    """Release a logger whose attempt ended without finishing its log.

    Its destination file and realtime buffer are kept: they hold the samples
    saved so far, for a retry or for recovery.
    """
    if not logger.finished:
        with anyio.CancelScope(shield=True):
            await logger.discard(keep_destination=True, keep_buffer=True)


def pick_balanced(ready: list[Attempt], model_counts: Counter[Model]) -> Attempt | None:
    """The next attempt to start, or ``None`` if every ready attempt is paused.

    Among attempts not held by a pause latch, the earliest one whose model has
    the fewest running attempts, so as many models as possible run at once.
    Ties go to queue order, so at a launch limit of 1 a sequence-ordered queue
    keeps all of a task's model fan-outs together (in slot mode, a task with
    no setup to do can still start while an earlier one sets up).
    """
    candidates = [a for a in ready if not _dispatch_paused(a)]
    if not candidates:
        return None
    fewest = min(model_counts[a.options.model] for a in candidates)
    return next(a for a in candidates if model_counts[a.options.model] == fewest)


def _dispatch_paused(attempt: Attempt) -> bool:
    """Whether a pause latch holds the attempt back from taking a task slot.

    The model name is passed to the latch because a task that has not started
    has no EvalState for the latch to resolve its model from.
    """
    return task_dispatch_paused(
        attempt.options.logger.eval.task_id,
        model=dispatch_model_name(attempt.options.model),
    )


def wants_retry(cancel_type: CancelType, task_log: EvalLog, attempt: Attempt) -> bool:
    """Whether a finished, not cancelled, attempt should be retried.

    It is retried after an error or its own retry request while retries
    remain, unless a ctl drain/cancel has abandoned its retry. An abort, a
    drain or a graceful sample resolution (``score``/``error``) is a user
    cancel and is never retried, even when its log has an error status.
    """
    name = attempt.options.task.name
    match cancel_type:
        case "retry":
            log.info(
                f"Task '{name}' was cancelled with retry requested — "
                f"{attempt.retries_remaining} retries remaining"
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
    if not retry or attempt.retries_remaining == 0:
        return False
    if task_retry_abandoned(attempt.options.logger.eval.task_id):
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
    """Starts sandbox environments incrementally and tears them all down.

    Use as an async context manager around the run. Tasks added to a running
    eval, and samples a `SampleSource` adds to a live task, arrive in groups,
    so startup is callable repeatedly: :meth:`start`, :meth:`start_for_task` and
    :meth:`start_for_samples` initialize only sandboxenvs not already started
    and accumulate their cleanups, which run once, when the run ends.

    Providers may keep state in ContextVars that ``task_init`` sets and
    ``sample_init`` / ``task_cleanup`` read (Modal, E2B, Daytona, k8s). Each
    ``task_init`` runs in a child task; the ContextVars it sets are recorded
    and set in the caller's context (so the tasks it starts see them, the
    latest value of each winning, as when ``task_init`` ran in the caller's
    context), and each ``task_cleanup`` runs with the state as it was right
    after its own ``task_init``. So a cleanup sees its own state even after a
    later ``task_init`` of the same provider (for an added task) set the
    ContextVar again, and sees nothing of the task that happened to start it.

    The manager also owns the run's sandbox lifecycle state (the registries
    a provider's `task_cleanup` reads: running containers, generated config
    files), bound in the calling context on entry, before any task of the run
    is spawned, so a `task_init` that runs late (for an added task, or in a
    `SampleSource` feeder task) registers on the object every task inherited.
    It is released on exit, so a later run in the same process starts clean.
    """

    def __init__(self, config: EvalConfig, *, cleanup: bool, in_slot: bool) -> None:
        """Create the run's sandbox manager.

        Args:
            config: The eval config (sample selection, ``max_sandboxes``).
            cleanup: Whether ``task_cleanup`` removes what setup created.
            in_slot: Each task starts its own sandboxes once it has started,
                while other tasks run: setup output is collected per task
                (and shown if its setup fails) instead of the task display
                being suspended.
        """
        self._config = config
        self._cleanup = cleanup
        self.in_slot = in_slot
        self._started: set[TaskSandboxEnvironment] = set()
        self._cleanups: list[_TaskCleanup] = []
        self._state: ProviderState = {}
        self._init_lock = anyio.Lock()
        self._lifecycle = ExitStack()
        self._cleanup_context = copy_context()
        # keyed by task, then spec: resolution folds in per-task state
        # (run_dir), so a spec-only key would leak one task's resolution to
        # another. Weak on the task, so a finished task's Task and dataset are
        # not kept alive until the run ends
        self._resolved_no_metadata: weakref.WeakKeyDictionary[
            Task, dict[SandboxEnvironmentSpec, TaskSandboxEnvironment]
        ] = weakref.WeakKeyDictionary()

    async def __aenter__(self) -> "SandboxManager":
        self._lifecycle.enter_context(sandbox_lifecycle_scope())
        # cleanups run from here, so each sees only the provider state as it
        # was right after its own task_init (not what later ones set)
        self._cleanup_context = copy_context()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        """Run every accumulated `task_cleanup`, then release the lifecycle state.

        The final cleanup of the run: it also covers samples whose own cleanup
        was deferred by an interruption, since their provider state is on the
        scope this manager owns. A failing cleanup is logged and the others
        still run.
        """

        async def cleanup(job: _TaskCleanup) -> None:
            with sandbox_setup_scope(SandboxSetup(job.run_dir)):
                await job.cleanup("shutdown", job.config, self._cleanup)

        with anyio.CancelScope(shield=True):
            try:
                for job in self._cleanups:
                    try:
                        await _in_child_task(
                            functools.partial(cleanup, job),
                            job.state,
                            context=self._cleanup_context,
                        )
                    except BaseException as ex:
                        log.warning(
                            f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                        )
            finally:
                self._lifecycle.close()

    async def start(self, tasks: list[ResolvedTask], task_names: list[str]) -> None:
        """Start the sandboxenvs of `tasks`' selected samples.

        `task_names` is every task name known to the run so far (not just
        `tasks`), so `task:id` sample selectors resolve here exactly as they do
        when the tasks run.
        """
        sandboxenvs: set[TaskSandboxEnvironment] = set()
        for task in tasks:
            sandboxenvs |= await self._resolve_sandboxenvs(
                task, self._selected_samples(task, task_names)
            )
        await self._start_sandboxenvs(sandboxenvs, shared=True)

    async def task_setups(
        self, tasks: list[ResolvedTask], task_names: list[str]
    ) -> list["TaskSandboxes | None"]:
        """The setup of each task's own sandboxes, for tasks that start them themselves.

        Resolves the sandboxenvs of each task's selected samples now, as
        :meth:`start` does (a resolution error fails the start-up), so whether
        a task has setup to do is known before it starts. ``None`` for a task
        none of whose selected samples uses a sandbox. Also registers the
        ``ctl`` limiter of each sandbox type the tasks use, so a ``ctl config
        --max-sandboxes`` retune reaches a type whose task is still waiting to
        start.
        """
        setups: list[TaskSandboxes | None] = []
        types: set[str] = set()
        for task in tasks:
            sandboxenvs = await self._resolve_sandboxenvs(
                task, self._selected_samples(task, task_names)
            )
            types |= {env.sandbox.type for env in sandboxenvs}
            setups.append(TaskSandboxes(self, sandboxenvs) if sandboxenvs else None)
        for sandbox_type in types:
            await ensure_sandbox_limiter(
                registry_find_sandboxenv(sandbox_type),
                sandbox_type,
                self._config.max_sandboxes,
            )
        return setups

    async def start_for_task(self, sandboxenvs: set[TaskSandboxEnvironment]) -> None:
        """Start a task's sandboxenvs from inside the task, once it has started.

        For tasks that start their own sandboxes (:class:`TaskSandboxes`). As
        with :meth:`start`, the provider state reaches later tasks too (one
        whose config was already started needs it).
        """
        await self._start_sandboxenvs(sandboxenvs, shared=True)

    def all_started(self, sandboxenvs: set[TaskSandboxEnvironment]) -> bool:
        """Whether every one of `sandboxenvs` has had its `task_init` run."""
        return sandboxenvs <= self._started

    async def start_for_samples(
        self, task: ResolvedTask, samples: Iterable[Sample]
    ) -> None:
        """Start the sandboxenvs of samples a `SampleSource` adds to a running task.

        A config first seen in an added sample (including the task-level config
        when the seed dataset was empty) gets the same `task_init` startup as
        seed configs (up-front image build/pull, fail-fast validation, a
        registered `task_cleanup`) before the sample runs. Configs already
        started are a no-op. The provider state stays with this task and the
        config's cleanup: it is set inside the task, which no other task sees.
        """
        await self._start_sandboxenvs(
            await self._resolve_sandboxenvs(task, samples), shared=False
        )

    def _selected_samples(
        self, task: ResolvedTask, task_names: list[str]
    ) -> Iterable[Sample]:
        """The samples of `task` that the eval's sample selection runs."""
        return slice_dataset(
            task.task.dataset,
            self._config.limit,
            resolve_task_sample_ids(task.task.name, self._config.sample_id, task_names),
            dynamic=task.task.sample_source is not None,
        )

    async def _sandbox_spec(
        self, task: ResolvedTask, sample: Sample
    ) -> SandboxEnvironmentSpec | None:
        return await resolve_sandbox(
            task.sandbox, sample, task.task.name, task_dir=task_run_dir(task.task)
        )

    async def _resolve_sandboxenvs(
        self, task: ResolvedTask, samples: Iterable[Sample]
    ) -> set[TaskSandboxEnvironment]:
        """Resolve each sample's sandboxenv (deduped; sandbox-less samples skipped).

        Full resolution reads the sandbox config (and, for docker configs with
        metadata interpolation, spawns a subprocess) per sample — meaningful
        when a source adds samples batch after batch. Metadata-less samples
        resolve deterministically per spec, so those resolutions are cached;
        samples with metadata must always fully resolve (their config may
        interpolate it into a per-sample init environment).
        """
        sandboxenvs: set[TaskSandboxEnvironment] = set()
        resolved = self._resolved_no_metadata.setdefault(task.task, {})
        for sample in samples:
            sandboxenv: TaskSandboxEnvironment | None = None
            cache_key: SandboxEnvironmentSpec | None = None
            if not sample.metadata:
                spec = await self._sandbox_spec(task, sample)
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
        return sandboxenvs

    async def _start_sandboxenvs(
        self, sandboxenvs: set[TaskSandboxEnvironment], *, shared: bool
    ) -> None:
        """Run `task_init` for new sandboxenvs; set the provider state in the caller.

        ``shared``: what the new `task_init`s set is added to the run's provider
        state, which every later start-up gives its caller.

        One `task_init` at a time, on a lock, with the started set re-checked
        under it, so concurrent callers (e.g. two live tasks adding samples at
        once) can't init the same sandboxenv twice. The check before the lock
        lets a caller whose configs have all started return without waiting
        out another caller's (possibly minutes-long) image pull: the started
        set only grows.
        """
        state = self._state
        if any(env not in self._started for env in sandboxenvs):
            async with self._init_lock:
                state = dict(self._state)
                new = [env for env in sandboxenvs if env not in self._started]
                if new:
                    set_sandbox_prebuilt(self._config.sandbox_prebuilt is True)
                    # a task starting its own sandboxes runs beside a live
                    # task display
                    with (
                        nullcontext() if self.in_slot else display().suspend_task_app()
                    ):
                        for sandboxenv in new:
                            state |= await self._init_one(sandboxenv, state, shared)
                        # space above the task display ("none" has none and must
                        # keep stdout machine-readable, e.g. --json)
                        if not self.in_slot and display_type() != "none":
                            print("")
        _set_provider_state(state)

    async def _init_one(
        self, sandboxenv: TaskSandboxEnvironment, state: ProviderState, shared: bool
    ) -> ProviderState:
        """Run one sandboxenv's `task_init` from ``state``; return what it set.

        As soon as it returns, the sandboxenv is recorded as started, with its
        cleanup (to run with ``state`` plus what it set), and with ``shared``
        what it set is added to the run's provider state: even if the rest of
        the setup then fails or is cancelled.
        """
        sandboxenv_type = registry_find_sandboxenv(sandboxenv.sandbox.type)
        # pre-register the type's resizable concurrency limiter before
        # task_init (image pulls/builds can take minutes) so a `ctl limits
        # --max-sandboxes` issued during startup isn't dropped
        await ensure_sandbox_limiter(
            sandboxenv_type, sandboxenv.sandbox.type, self._config.max_sandboxes
        )
        task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
        setup = SandboxSetup(
            sandboxenv.run_dir,
            dict(sandboxenv.env),
            output=[] if self.in_slot else None,
        )
        task_cleanup = cast(TaskCleanup, getattr(sandboxenv_type, "task_cleanup"))

        def started(changes: ProviderState) -> None:
            self._started.add(sandboxenv)
            self._cleanups.append(
                _TaskCleanup(
                    task_cleanup,
                    sandboxenv.sandbox.config,
                    sandboxenv.run_dir,
                    state | changes,
                )
            )
            if shared:
                self._state = self._state | changes

        with sandbox_setup_scope(setup):
            try:
                # from the state earlier task_inits left, so a provider's
                # get-or-create finds it
                return await _in_child_task(
                    functools.partial(task_init, "startup", sandboxenv.sandbox.config),
                    state,
                    done=started,
                )
            except Exception as ex:
                if setup.output:
                    ex.add_note(
                        "Output of the sandbox setup:\n"
                        + "".join(setup.output)[-_SETUP_OUTPUT_SHOWN:]
                    )
                raise


class TaskSandboxes:
    """The sandboxes a task's own samples use, which the task starts itself.

    A task's :class:`~inspect_ai._eval.task.run.TaskSandboxSetup` in slot
    mode (see :meth:`SandboxManager.task_setups`).
    """

    def __init__(
        self, manager: SandboxManager, sandboxenvs: set[TaskSandboxEnvironment]
    ) -> None:
        self._manager = manager
        self._sandboxenvs = sandboxenvs

    def started(self) -> bool:
        return self._manager.all_started(self._sandboxenvs)

    async def __call__(self) -> None:
        await self._manager.start_for_task(self._sandboxenvs)


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
