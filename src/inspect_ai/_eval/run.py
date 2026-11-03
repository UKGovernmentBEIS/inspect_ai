"""One eval run: configuring its tasks, sandbox setup, and the scheduling loop.

The scheduler's state (the run's :class:`RunTasks`, its :class:`SetupCache`)
is used only from the run's event loop and changed without locks: code on one
event loop does not interleave between ``await`` points, so a method that does
not await (``RunTasks.enqueue``, ``start`` and ``end``, the dispatcher's
``prepare_front_of_queue`` and ``start_prepared_tasks``, the setup cache's
bookkeeping) changes it as one step.
"""

import functools
import itertools
import logging
import os
import weakref
from collections import Counter
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
    cast,
)

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._util._async import Wake, unwrap_exception_group
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
    remove_dispatch_waker,
    task_dispatch_paused,
    wait_task_dispatch,
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
from inspect_ai.model._model import ModelName, ensure_model_controller
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
from .task.enqueue import (
    ConfiguredTask,
    ResolveTasksFn,
    RunTasks,
    TaskRecord,
    clear_run_tasks,
    register_run_tasks,
)
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
from .task.setup_cache import SetupCache
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
    resolve_added_tasks: ResolveTasksFn,
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
    """Run the tasks of one eval run, including the tasks added while it runs.

    Makes the run's :class:`RunTasks` the active one (so ``enqueue_task``
    reaches it), starts up the seed tasks, runs the scheduling loop
    (:class:`TaskDispatcher`) until no task is left, then shuts the run's
    sandbox environments down once. ``parallel`` is the launch limit on
    concurrent (task × model) units; ``resolve_added_tasks`` resolves added
    tasks against the run's models and config.
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
    changed = Wake()
    sandboxes = SandboxManager(
        eval_config,
        cleanup=eval_config.sandbox_cleanup is not False,
        on_setup_done=changed.set,
    )
    startup = TaskStartup(settings, sandboxes, task_names=list(eval_set_tasks or []))
    run_tasks = RunTasks(
        run_id,
        resolve_added_tasks,
        startup.configure,
        startup.prepare,
        changed=changed,
        sequence_order=parallel == 1,
    )
    token = register_run_tasks(run_tasks)
    try:
        # entered with the run's tasks active, so code a setup runs can add tasks
        async with sandboxes:
            seed = await run_tasks.create(tasks)
            run_tasks.enqueue(seed)
            await startup.start_seed(seed)
            # setups from here on run beside the task display
            sandboxes.collect_output = True
            dispatcher = TaskDispatcher(
                run_tasks,
                sandboxes.setups,
                sandboxes.apply_provider_state,
                parallel=parallel,
                retries=task_retry_attempts or 0,
                next_tasks=task_source.next_tasks if task_source else None,
                debug_errors=debug_errors,
            )
            return await dispatcher.run()
    finally:
        # a task that outlives the run keeps its RunTasks in its context
        run_tasks.close()
        clear_run_tasks(token)
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
        apply_provider_state: Callable[[], None],
    ) -> ConfiguredTask:
        """Configure one task of the run: validate it and resolve its settings.

        Eval-level settings are resolved against a shallow copy of the task, so
        repeated ``eval()`` calls on the same ``Task`` do not keep them (nested
        state such as the dataset is still shared). Runs in the task's run
        directory, as does creating each attempt's logger (which records the
        git revision and paths relative to it); ``chdir`` is process-wide, so
        nothing here may await.

        Args:
            resolved_task: The task as resolved against the run's models.
            task_names: Every task name known to the run (``task:id`` sample
                selectors).
            startup_sandboxes: Starts the sandboxes of samples a
                ``SampleSource`` adds while the task runs (``None`` if it adds
                none).
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

        def selected_samples() -> Dataset:
            return slice_dataset(
                task.dataset,
                config.limit,
                config.sample_id,
                dynamic=task.sample_source is not None,
            )

        spec = TaskSpec(
            task_display_name(task.name),
            ModelName(resolved_task.model),
            plan_agent_name(resolve_plan(task, self.solver)),
        )
        return ConfiguredTask(
            resolved_task, spec, options, new_logger, selected_samples
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


NextTasksFn = Callable[[], Awaitable[list[Task] | None]]
"""Asked for more tasks when the run is idle (``TaskSource.next_tasks``)."""

SampleSandboxSetup = Callable[[Iterable[Sample]], Awaitable[None]]
"""Sets up the sandboxes some of a task's samples need, from inside the task."""


@dataclass
class TaskStartup:
    """Configures the tasks of one run and prepares them to start.

    Both happen as a task is added, before its record is queued, so an
    invalid task raises to whoever added it. Configuring is synchronous;
    preparing is asynchronous: its model's controller, and the sandbox configs
    its selected samples use.
    """

    settings: TaskSettings
    sandboxes: "SandboxManager"
    task_names: list[str]
    """Every task name known to the run, for ``task:id`` sample selectors: the
    enclosing eval set's (a retry runs only some of them), then each task's
    as it is added, so an added task sees the tasks before it."""

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
                t,
                [*self.task_names, *names],
                self._sample_setup(t),
                self.sandboxes.apply_provider_state,
            )
            for t in group
        ]
        self.task_names.extend(names)
        return configured

    async def prepare(
        self, configured: ConfiguredTask
    ) -> tuple[TaskSandboxEnvironment, ...]:
        """Prepare a task to start; the sandbox configs its selected samples use.

        Creates the model's controller as the task is added, so ``ctl
        config`` can retune ``max_connections`` during a long sandbox setup.
        """
        if not self.settings.run_samples:
            return ()
        resolved_task = configured.resolved
        await ensure_model_controller(
            resolved_task.model,
            resolved_task.task.config.merge(
                GenerateConfigArgs(**self.settings.generate_config)
            ),
        )
        return await self.sandboxes.resolve(
            resolved_task, configured.selected_samples()
        )

    async def start_seed(self, seed: list[TaskRecord]) -> None:
        """Set up the seed's sandboxes and create its loggers, before the task display opens.

        Setups run one at a time with their output streamed to the terminal,
        and any failure raises before a log exists. Then each seed task's
        first logger is created, so a log's ``created`` time (which names its
        file) follows the setups; it is initialised as the task starts.
        """
        await self.sandboxes.setup_seed(
            dict.fromkeys(key for record in seed for key in record.setup_keys)
        )
        for record in seed:
            assert record.configured is not None
            record.logger = record.configured.new_logger()

    def _sample_setup(self, resolved_task: ResolvedTask) -> SampleSandboxSetup | None:
        """Sets up the sandboxes of samples the task's ``SampleSource`` adds."""
        if not self.settings.run_samples or resolved_task.task.sample_source is None:
            return None
        return functools.partial(self.sandboxes.setup_for_samples, resolved_task)


def ensure_sample_ids(dataset: Dataset) -> None:
    """Give samples without an id their 1-based position, then check ids are unique."""
    for id, sample in enumerate(dataset):
        if sample.id is None:
            sample.id = id + 1
    ensure_unique_ids(dataset)


class TaskRunResult(NamedTuple):
    log: EvalLog | None
    """The task's log; ``None`` only if an operator abandoned the attempt
    before it registered with the control channel (it wrote no log of its
    own)."""

    cancel_type: CancelType
    """How the task was cancelled (``None`` if it ran to completion)."""


async def _run_task(
    options: TaskRunOptions,
    *,
    retry: bool,
    can_retry: bool,
    on_log: Callable[[EvalLog], None] = lambda log: None,
) -> TaskRunResult:
    """Open an attempt's log and run the task in its own cancel scope.

    The scope keeps cancelling the task from affecting its siblings. Returns
    the task's log (``None`` if an operator abandoned the attempt before it
    registered) and the ``CancelType`` it was cancelled with, so the
    dispatcher can tell a retry/abort request from an ordinary error. A
    run-level cancellation raises. ``retry`` says whether the attempt is a
    retry (see :func:`open_log`); ``can_retry`` is surfaced to the task
    through ``TaskCancel``.

    An attempt left without a log by an error opening its log or escaping
    ``task_run`` (a failure to write the log itself) or by its own abort or
    retry request
    (which cancels its scope, possibly mid-write) gets an errored header log
    (``TaskLogger.header_log``), so the dispatcher ends or retries only this
    task. The failed write is re-raised when ``debug_errors`` is set.

    Once the scope has exited the outcome is decided: a later retry request
    is ignored, and only an abort of an errored attempt still applies (it
    stops the retry). The run's ``TaskSource`` gets ``task_complete`` after
    the scope has exited (for every attempt except a failed write), so it
    runs whether or not the task was cancelled; an exception it raises ends
    the run. ``on_log`` gets the attempt's log before that callback runs, so
    a cancellation of the run while it awaits keeps the log.
    """
    result: EvalLog | None = None
    cancel_type: CancelType = None
    scope_exited = False
    try:
        with trace_action(
            log, "Run Task", f"task: {options.task.name} ({options.model})"
        ):
            # a per-task group so a task cancelling itself doesn't cancel
            # siblings; abort/retry cancel task_scope, which encloses only
            # task_run
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
                    # after task_run the outcome is decided: only an abort of
                    # an errored attempt still applies (it stops the retry)
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
                    nonlocal result, scope_exited
                    write_failed = False
                    with task_scope:
                        try:
                            await open_log(options.logger, retry=retry)
                            result = await task_run(options, task_cancel=task_cancel)
                        except TaskRetryAbandonedError:
                            # an operator-requested outcome, not a task error
                            # (caught inside the trace action so it is not
                            # traced as one): no log, and the previous
                            # attempt's stays the task's final state
                            return
                        except Exception as ex:
                            # errors generally don't escape from task_run: this
                            # is a failure to open or write the log itself (or
                            # a retry's checkpoint copy). Rather than tear down
                            # the run, record an errored log, which the
                            # dispatcher and eval_set() retry.
                            if options.debug_errors:
                                raise
                            inner = inner_exception(ex)
                            log.error(
                                f"Task '{options.task.name}' encountered an error "
                                f"while starting or writing its log: {inner}"
                            )
                            # its location is where the write was going: the
                            # file may be missing or partial
                            result = options.logger.header_log(
                                eval_error(
                                    inner, type(inner), inner, inner.__traceback__
                                )
                            )
                            write_failed = True
                    scope_exited = True
                    if write_failed:
                        return
                    # task_scope swallows only its own cancellation, so no
                    # log here means the task's abort/retry interrupted it
                    if result is None:
                        assert cancel_type in ("abort", "retry")
                        cancel_ex = TerminateTaskError(
                            f"Task cancelled by user ({cancel_type})"
                        )
                        result = options.logger.header_log(
                            eval_error(cancel_ex, TerminateTaskError, cancel_ex, None)
                        )
                    on_log(result)
                    try:
                        await notify_task_source(options, result)
                    except Exception as ex:
                        ex.add_note(
                            "Raised by TaskSource.task_complete() for task "
                            f"'{options.task.name}'."
                        )
                        raise

                task_tg.start_soon(run)
    finally:
        # Startup can fail before log_finish owns teardown. Release the
        # cached prior on every exit without removing a written destination.
        with anyio.CancelScope(shield=True):
            try:
                await options.logger.recorder.close_seed_source(options.logger.eval)
            except Exception as ex:
                log.warning(f"Error closing prior log source: {exception_message(ex)}")
    return TaskRunResult(result, cancel_type)


class TaskDispatcher:
    """The scheduling loop of one eval run.

    Starts the queued records with bounded, model-balanced concurrency as
    they can start, and when nothing is queued or running asks the
    ``TaskSource`` for more (``next_tasks()``) until there is nothing left.
    A record can start once its setups are requested (see
    :meth:`prepare_front_of_queue`) and they are done, or failed: a
    record whose setup is still running keeps its place but does not hold
    back a later one. A record whose setup failed starts like any other and
    its attempt ends with that error, so it has a log, hooks and a
    ``TaskSource`` notification.

    A task whose log comes back with an error, or which requests a retry
    through its ``TaskCancel``, is retried in its slot (reusing its completed
    samples) until its retries are exhausted, after setting up again whatever
    failed. An abort is never retried and resolves to an errored log; a
    cancellation of the run is never retried and ends dispatch.
    """

    def __init__(
        self,
        tasks: RunTasks,
        setups: "SetupCache[Any]",
        apply_provider_state: Callable[[], None],
        *,
        parallel: int,
        retries: int,
        next_tasks: NextTasksFn | None,
        debug_errors: bool,
    ) -> None:
        self.tasks = tasks
        self.setups = setups
        """Sets up the run's sandbox configs."""
        self.apply_provider_state = apply_provider_state
        """Sets the run's sandbox provider state in the current context."""
        self.parallel = parallel
        """The launch ``max_tasks`` (``ctl config --max-tasks`` overrides it live)."""
        self.retries = retries
        """How many times a task is retried after an attempt that fails."""
        self.next_tasks = next_tasks
        """Asked for more tasks when nothing is queued or running: the
        ``TaskSource``'s ``next_tasks()`` (``None`` once it returns nothing)."""
        self.debug_errors = debug_errors

    async def run(self) -> list[EvalLog]:
        """Run the queued tasks and every task added while the run is in progress.

        Returns the logs in the order of :attr:`RunTasks.records`. A cancellation
        of the run (Ctrl-C) wherever the loop is returns the logs written so
        far.
        """
        try:
            async with _run_task_screen(task_specs(self.tasks.queued)) as screen:
                init_task_screen(screen)
                try:
                    add_dispatch_waker(self.tasks.changed.set)
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
                    remove_dispatch_waker(self.tasks.changed.set)
                    remove_task_dispatcher(self.stats)
                    clear_task_screen()
        finally:
            # a cancelled or failed run leaves records unfinished: those
            # interrupted while running released their loggers in run_one
            self.tasks.close()
        return self.tasks.results()

    async def loop(self, tg: TaskGroup) -> None:
        """Start the queued tasks as they can start, then ask for more or finish.

        Each pass recomputes, from the run's tasks as they are now, two
        stages: prepare the front of the queue (request its sandbox setups),
        then start prepared tasks while a slot is free. Starting tasks moves
        the front of the queue, so the pass repeats before sleeping. With
        nothing to start it sleeps until something changes while tasks are
        queued or running, and otherwise asks the ``TaskSource`` for more,
        finishing once it has nothing more.

        :meth:`RunTasks.wait_for_change` wakes it: the run's tasks change
        (a task added, started, ended, or cancelled while waiting), a setup
        ends, or ``inspect ctl`` changes a setting that decides what can
        start (pause, resume, ``max_tasks``). A cancellation of the run
        reaches the loop where it awaits.
        """
        while True:
            if self.setups.fatal is not None:
                raise self.setups.fatal
            self.prepare_front_of_queue()
            if self.start_prepared_tasks(tg):
                continue
            if self.tasks.running or self.tasks.queued:
                await self.tasks.wait_for_change()
            elif not await self.add_tasks_from_source():
                break
        # nothing is queued, running or coming: a late add raises
        self.tasks.close()

    async def add_tasks_from_source(self) -> bool:
        """Ask the ``TaskSource`` for its next batch and add it.

        Returns whether the source was asked: ``False`` once it has returned
        nothing, after which it is not asked again. Its batch is queued ahead
        of any tasks added (with ``enqueue_task``) while ``next_tasks()`` ran,
        as it was asked for before them (see :meth:`RunTasks.add_ahead`).
        """
        if self.next_tasks is None:
            return False
        more = await self.next_tasks()
        if more:
            await self.tasks.add_ahead(more)
        else:
            self.next_tasks = None
        return True

    def prepare_front_of_queue(self) -> None:
        """Request the sandbox setups of the queued records that will start soonest.

        Those are the first ``max_tasks`` (read live) unpaused queued records,
        so a queued task's sandboxes (often billed cloud resources) are not
        created long before a slot can be free for it; the front moves as
        records start, and follows ``ctl config --max-tasks``. A record behind
        the front whose configs all have a job already (none, or shared with
        an earlier record) holds them at once: that sets up nothing new, and
        it can start as soon as they are done.

        Waiting setups that no queued or running record holds any more (those
        of a task cancelled before it started) are dropped.
        """
        limit = effective_max_tasks(self.parallel)
        unpaused = [r for r in self.tasks.queued if not _dispatch_paused(r)]
        for i, record in enumerate(unpaused):
            if record.setups is None and (
                i < limit or self.setups.has_jobs(record.setup_keys)
            ):
                record.setups = self.setups.request(record.setup_keys)
        self.setups.drop_waiting(
            key
            for record in [*self.tasks.queued, *self.tasks.running]
            if record.setups is not None
            for key in record.setup_keys
        )

    def start_prepared_tasks(self, tg: TaskGroup) -> bool:
        """Start prepared records while a slot is free; whether any started.

        A record is prepared once its setups are done or failed. Each start
        takes :meth:`earliest_of_least_busy_model`, against ``max_tasks``
        read live.
        """
        running_before = len(self.tasks.running)
        while len(self.tasks.running) < effective_max_tasks(self.parallel):
            record = self.earliest_of_least_busy_model()
            if record is None:
                break
            self.start_in_background(tg, record)
        return len(self.tasks.running) > running_before

    def earliest_of_least_busy_model(self) -> TaskRecord | None:
        """The prepared record to start next, or ``None`` if there is none.

        Of the unpaused queued records whose setups are done or failed, the
        earliest whose model has the fewest running records, so as many
        models as possible run at once. Ties go to queue order, so at a
        launch limit of 1 a sequence-ordered queue keeps all of a task's
        model fan-outs together (while every setup they need is done).
        """
        prepared = [
            r for r in self.tasks.queued if not _dispatch_paused(r) and r.can_start
        ]
        if not prepared:
            return None
        running = Counter(r.model for r in self.tasks.running)
        fewest = min(running[r.model] for r in prepared)
        return next(r for r in prepared if running[r.model] == fewest)

    def start_in_background(self, tg: TaskGroup, record: TaskRecord) -> None:
        """Start running a record's attempts, with the run's provider state."""
        self.tasks.start(record)
        # tasks inherit the loop's context: the latest provider state
        self.apply_provider_state()
        tg.start_soon(self.run_one, record)

    async def run_one(self, record: TaskRecord) -> None:
        """Run a record's attempts in its slot, then end it.

        A failed attempt is retried while retries remain (see
        :func:`wants_retry`), reusing its completed samples. A retry waits
        while a pause holds the task, then whatever of the record's setups
        failed is set up again, ahead of the setups waiting; it keeps the
        slot meanwhile.
        """
        configured = record.configured
        assert configured is not None
        logger = record.logger or configured.new_logger()
        record.logger = None
        sample_source: EvalSampleSource | None = None
        try:
            for attempt in itertools.count(1):
                retries_left = self.retries - (attempt - 1)
                if attempt > 1:
                    # a pause holds a retry back, as it holds a queued task
                    await wait_task_dispatch(
                        record.task_id, model=dispatch_model_name(record.model)
                    )
                    await self.set_up_again(record)
                options = self.attempt_options(
                    configured.options(logger), record, attempt, sample_source
                )
                run = await _run_task(
                    options,
                    retry=attempt > 1,
                    can_retry=retries_left > 0,
                    on_log=functools.partial(setattr, record, "log"),
                )
                if run.log is None:
                    # abandoned before it registered: its never-started log
                    # entry goes; the task keeps its previous attempt's log
                    await logger.discard()
                    break
                record.log = run.log
                if not wants_retry(run.cancel_type, run.log, record, retries_left):
                    # unwind the task runner's retry-pending mark (a no-op if a
                    # cancel stamp during the log write already cleared it)
                    clear_eval_retry_pending(run.log.eval.eval_id)
                    await _release_unfinished(logger)
                    break
                # until the retry registers, this attempt is the task's
                # latest: the mark stops task-keyed directives reading it as
                # finished
                mark_eval_retry_pending(run.log.eval.eval_id)
                sample_source = retry_sample_source(options, run.log)
                log.info(
                    f"Retrying task '{record.task}' ({record.model}) "
                    f"— {retries_left - 1} retries remaining"
                )
        except BaseException:
            # the run failed or was cancelled: the attempt's files are kept
            await _release_unfinished(logger)
            raise
        self.tasks.end(record)

    async def set_up_again(self, record: TaskRecord) -> None:
        """Set up whatever of a record's setups failed, ahead of those waiting.

        A failed setup's job was forgotten, so requesting the record's
        configs again adds a job for it; the others are done already. Waits
        until every job is done (or has failed again, which the next attempt
        then ends with), then sets the run's provider state in the attempt's
        context, so the retry sees the state its redone setups left (the
        context it started with predates them).
        """
        record.setups = self.setups.request(record.setup_keys, first=True)
        for job in record.setups:
            await job.done.wait()
        self.apply_provider_state()

    def attempt_options(
        self,
        options: TaskRunOptions,
        record: TaskRecord,
        attempt: int,
        sample_source: EvalSampleSource | None,
    ) -> TaskRunOptions:
        """A record's run options for one attempt.

        ``sample_source`` is where a retry reads the failed attempt's
        completed samples (``None``: the task's own).
        """
        return replace(
            options,
            setup_failure=record.failure,
            sample_source=(
                options.sample_source if sample_source is None else sample_source
            ),
            display_name=(
                None
                if attempt == 1
                else f"{record.task} (retry {attempt - 1} of {self.retries})"
            ),
        )

    def stats(self) -> TaskDispatcherStats:
        """The view ``inspect ctl config`` shows of this dispatcher."""
        return TaskDispatcherStats(
            launch=self.parallel,
            in_flight=len(self.tasks.running),
            pending=len(self.tasks.queued),
        )


async def open_log(logger: TaskLogger, *, retry: bool) -> None:
    """Create the log entry of an attempt's logger.

    A retry reinitialises the failed attempt's logger for a fresh entry; a
    first attempt initialises its new (or seed) logger.
    """
    if retry:
        await logger.reinit()
    else:
        await logger.init()


async def _release_unfinished(logger: TaskLogger) -> None:
    """Release a logger whose attempt ended without finishing its log.

    Its destination file and realtime buffer are kept: they hold the samples
    saved so far, for a retry or for recovery.
    """
    if not logger.finished:
        with anyio.CancelScope(shield=True):
            await logger.discard(keep_destination=True, keep_buffer=True)


def _dispatch_paused(record: TaskRecord) -> bool:
    """Whether a pause latch holds the record back from starting.

    The model name is passed to the latch because a task that has not started
    has no EvalState for the latch to resolve its model from.
    """
    return task_dispatch_paused(record.task_id, model=dispatch_model_name(record.model))


def wants_retry(
    cancel_type: CancelType, task_log: EvalLog, record: TaskRecord, retries_left: int
) -> bool:
    """Whether a finished attempt of a record should be retried.

    It is retried after an error or its own retry request while retries
    remain (``retries_left`` counts this attempt's retry), unless a ctl
    drain/cancel has abandoned its retry. An attempt the run's cancellation
    ended is never retried. An abort, a drain or a graceful sample
    resolution (``score``/``error``) is a user cancel and is never retried,
    even when its log has an error status.
    """
    if task_log.status == "cancelled":
        return False
    task = record.task
    match cancel_type:
        case "retry":
            log.info(
                f"Task '{task}' was cancelled with retry requested — "
                f"{retries_left} retries remaining"
            )
            retry = True
        case "abort":
            log.info(f"Task '{task}' was cancelled with abort requested")
            retry = False
        case "drain":
            log.info(
                f"Task '{task}' was drained — in-flight samples finished "
                "naturally, queued samples abandoned"
            )
            retry = False
        case None:
            retry = task_log.status == "error"
        case resolution:
            log.info(
                f"Task '{task}' was cancelled with sample resolution '{resolution}'"
            )
            retry = False
    if not retry or retries_left == 0:
        return False
    if task_retry_abandoned(record.task_id):
        log.info(
            f"Task '{task}' retry abandoned by operator — task ends with this "
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
    whoever needs it: the seed before the run starts, a queued task, a
    `SampleSource` adding samples to a running task. Each config's
    ``task_cleanup`` runs once, when the run ends.

    Providers may keep state in ContextVars that ``task_init`` sets and
    ``sample_init`` / ``task_cleanup`` read (Modal, E2B, Daytona, k8s). Each
    ``task_init`` runs in a child task started from the context taken on
    entry, with the run's provider state so far set. The ContextVars it sets
    are added to the run's provider state, which each task starts with (the
    latest value of each wins), and its config's ``task_cleanup`` runs with
    the state as it was right after it. Provider state is therefore per run,
    not per config: a provider resolves config-specific values from the
    config ``sample_init`` gets.

    The manager also binds the run's sandbox lifecycle state (the registries
    a provider's ``task_cleanup`` reads) on entry, before any task of the run
    is spawned, and releases it on exit.
    """

    def __init__(
        self, config: EvalConfig, *, cleanup: bool, on_setup_done: Callable[[], None]
    ) -> None:
        """Create the run's sandbox manager.

        Args:
            config: The eval config (sample selection, ``max_sandboxes``,
                ``sandbox_prebuilt``).
            cleanup: Whether ``task_cleanup`` removes what setup created.
            on_setup_done: Called as each config's setup ends.
        """
        self._config = config
        self._cleanup = cleanup
        self.setups: SetupCache[TaskSandboxEnvironment] = SetupCache(
            self._init_one, on_done=on_setup_done
        )
        self.collect_output = False
        """Collect setup output (shown if the setup fails) instead of letting it
        through to the terminal: set once the task display is open."""
        self._cleanups: list[_TaskCleanup] = []
        self._state: ProviderState = {}
        self._exit_stack = AsyncExitStack()
        self._context: Context
        """The context setups and cleanups start from (taken on entry)."""
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
        # exits first, cancelling a setup still in progress
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
                        functools.partial(cleanup, job), job.state, self._context
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
        if not sandboxenvs:
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

        A config first seen in an added sample gets the same ``task_init`` as
        the seed's before the sample runs; configs already set up are a no-op.
        """
        await self.setups.ensure(await self.resolve(task, samples))

    async def resolve(
        self, task: ResolvedTask, samples: Iterable[Sample]
    ) -> tuple[TaskSandboxEnvironment, ...]:
        """The sandbox configs ``samples`` of ``task`` use; registers their limiters.

        The configs are in sample order, each once; sandbox-less samples are
        skipped.
        The limiter of each sandbox type is registered here, before any setup,
        so a ``ctl config --max-sandboxes`` retune reaches a type whose tasks
        are still waiting. Full resolution reads the sandbox config (and, for
        docker configs with metadata interpolation, spawns a subprocess) per
        sample. Metadata-less samples resolve deterministically per spec, so
        those resolutions are cached; samples with metadata must always fully
        resolve (their config may interpolate it into a per-sample init
        environment).
        """
        # a dict keeps the first occurrence of each, in sample order
        sandboxenvs: dict[TaskSandboxEnvironment, None] = {}
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
                sandboxenvs[sandboxenv] = None
        for sandbox_type in {env.sandbox.type for env in sandboxenvs}:
            await ensure_sandbox_limiter(
                registry_find_sandboxenv(sandbox_type),
                sandbox_type,
                self._config.max_sandboxes,
            )
        return tuple(sandboxenvs)

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
            await _in_child_task(init, state, self._context, done=started)
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
    context: Context,
    done: Callable[[ProviderState], None] = lambda changes: None,
) -> None:
    """Run ``fn`` in a child task started from ``context`` with ``state`` set.

    The child's ContextVar writes stay out of the caller's context; ``done``
    gets the ones ``fn`` made, in the child, as soon as ``fn`` returns (a
    cancellation can still reach the caller after that, and what ``fn`` did
    must not be lost). An exception from ``fn`` is re-raised as it is, not
    wrapped in a group.
    """
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
        done(
            {
                var: value
                for var, value in copy_context().items()
                if base.get(var, _UNSET) is not value
            }
        )

    async with anyio.create_task_group() as tg:
        context.copy().run(tg.start_soon, run)
    if error is not None:
        raise error


def _set_provider_state(state: ProviderState) -> None:
    """Set provider ContextVars in the current context, for the tasks it starts."""
    for var, value in state.items():
        var.set(value)


@asynccontextmanager
async def _run_task_screen(tasks: list[TaskSpec]) -> AsyncIterator[TaskScreen]:
    """Open the display's task screen for a run that absorbs cancellation.

    A cancellation of the run body is absorbed, and the run returns the logs
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


def task_specs(records: list[TaskRecord]) -> list[TaskSpec]:
    """The task display's rows for records that have not ended."""
    specs: list[TaskSpec] = []
    for record in records:
        assert record.configured is not None
        specs.append(record.configured.spec)
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
