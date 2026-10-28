import functools
import logging
import os
import weakref
from collections import Counter
from contextlib import ExitStack, asynccontextmanager
from contextvars import ContextVar, copy_context
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
    Set,
    cast,
)

import anyio
from anyio.abc import TaskGroup
from typing_extensions import Unpack

from inspect_ai._eval.task.constants import TASK_ALL_PARAMS_ATTR
from inspect_ai._util._async import unwrap_exception_group
from inspect_ai._util.environ import environ_vars
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
from inspect_ai._util.exception import TaskRetryAbandonedError
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
    eval_log_sample_source,
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
    sandboxes = SandboxManager(eval_config, eval_config.sandbox_cleanup is not False)
    start_up = GroupStartup(settings, sandboxes, parallel, list(eval_set_tasks or []))
    dispatcher = TaskDispatcher(
        queue,
        start_up,
        parallel=parallel,
        task_retry_attempts=task_retry_attempts or 0,
        source=task_source,
        debug_errors=debug_errors,
    )
    try:
        # own the run's sandbox lifecycle state before any task starts
        sandboxes.open()
        return await dispatcher.run(await start_up(tasks))
    finally:
        try:
            await sandboxes.shutdown()
        except BaseException as ex:
            log.warning(
                f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
            )

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
        startup_sandboxes: Callable[[list[Sample]], Awaitable[None]] | None,
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
            startup_sandboxes: Starts the sandboxes of samples a
                ``SampleSource`` adds while the task runs.

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

            # reject options that assume a fixed sample set for a SampleSource
            # task here, before its logger exists, so the error surfaces
            # pre-run rather than as a task error log
            if task.sample_source is not None:
                # early stopping managers register the seed only (samples the
                # source adds are never registered) and samples they halt
                # complete without notifying the source — a source blocked
                # awaiting completions would hang the task
                if task.early_stopping is not None:
                    raise PrerequisiteError(
                        "early_stopping is not currently supported for "
                        "tasks whose dataset is a SampleSource."
                    )
                # a range limit selects seed samples by position, but samples
                # the source adds have no position
                if isinstance(config.limit, tuple):
                    raise PrerequisiteError(
                        "A range --limit (start,end) is not supported for "
                        "tasks whose dataset is a SampleSource (added "
                        "samples have no dataset position); use a plain "
                        "numeric --limit to cap total samples."
                    )

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

            # policies given to eval() override the task's (the eval config
            # already reflects them); otherwise the config records the task's
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
            startup_sandboxes=startup_sandboxes,
            input_media_policy=resolved_task.input_media_policy,
        )


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

        In order: sample ids, model controllers (created eagerly so ``ctl
        config`` can retune ``max_connections`` during a long sandbox start-up),
        the sandbox environments of the selected samples (those not already
        started), configuration, then logger init. A group starts up whole,
        before any of it runs: a sandbox's ``task_init`` changes the process's
        working directory and environment while it runs, a failure must fail
        the run before any of the group runs, and each log's ``created`` time
        (which names its file) follows the sandbox start-up.

        At a launch limit of 1 the group is ordered by sequence: the scheduling
        loop breaks ties in queue order, so all of a task's model fan-outs run
        before the next task's (the order passing the tasks to ``eval()``
        gives). The group's loggers belong to this call until it returns: if
        it fails or is cancelled, they are discarded.
        """
        if self.parallel == 1:
            group = sorted(group, key=lambda t: t.sequence)
        self.task_names = self.task_names + [
            name for name in resolved_task_names(group) if name not in self.task_names
        ]
        for resolved_task in group:
            dataset = resolved_task.task.dataset
            for id, sample in enumerate(dataset):
                if sample.id is None:
                    sample.id = id + 1
            ensure_unique_ids(dataset)
        if self.settings.run_samples:
            for resolved_task in group:
                await ensure_model_controller(
                    resolved_task.model,
                    resolved_task.task.config.merge(
                        GenerateConfigArgs(**self.settings.generate_config)
                    ),
                )
            if any(t.has_sandbox for t in group):
                await self.sandboxes.start(group, self.task_names)
        options = [
            self.settings.task_options(t, self.task_names, self._startup_sandboxes(t))
            for t in group
        ]
        try:
            for task_options in options:
                await task_options.logger.init()
        except BaseException:
            with anyio.CancelScope(shield=True):
                for task_options in options:
                    await task_options.logger.discard()
            raise
        return options

    def _startup_sandboxes(
        self, resolved_task: ResolvedTask
    ) -> Callable[[list[Sample]], Awaitable[None]] | None:
        """Start-up of the sandboxes of samples a ``SampleSource`` adds mid-run."""
        if self.settings.run_samples and resolved_task.task.sample_source is not None:
            return functools.partial(self.sandboxes.start_for_samples, resolved_task)
        return None


class TaskRunResult(NamedTuple):
    log: EvalLog | None
    """The task's log, or ``None`` if it was cancelled before producing one."""

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

    Returns the task's :class:`EvalLog` (``None`` if it was cancelled before
    producing one) together with the ``CancelType`` it was cancelled with, so a
    caller managing retries can distinguish a retry/abort request from an
    ordinary error. ``can_retry`` is surfaced to the task (via ``TaskCancel``) so
    it knows whether requesting a retry will be honoured. The rare error that
    escapes a task — a failure to write the log itself (e.g. the ``log_start()``
    header flush) — is converted into an errored :class:`EvalLog` so the
    dispatcher can retry the task rather than tearing down the run; it is
    re-raised only when ``debug_errors`` is set.
    """
    result: EvalLog | None = None
    cancel_type: CancelType = None
    abandoned = False
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
                        cancel_tg.cancel_scope.cancel()

                task_cancel.cancel_task = cancel_task

                async def run() -> None:
                    nonlocal result, abandoned
                    try:
                        result = await task_run(options, task_cancel=task_cancel)
                    except TaskRetryAbandonedError:
                        # abandoned at attempt start (a drain/cancel stamped
                        # the retry-abandoned registry between the
                        # dispatcher's pick and the attempt registering).
                        # Caught here, inside the trace action, so an
                        # operator-requested outcome is not traced as a task
                        # error with a stacktrace; the sentinel is returned
                        # below. Writing an errored EvalLog would supersede
                        # the errored prior attempt's log, which must remain
                        # the task's final state.
                        abandoned = True

                task_tg.start_soon(run)
        if abandoned:
            return TaskRunResult(None, None, abandoned=True)
    except Exception as ex:
        # errors generally don't escape from tasks -- the exception is a
        # failure to write the log itself (e.g. the log_start() header flush,
        # or the log_finish() of an already-errored task, when log storage is
        # unreachable) or of a retry's checkpoint startup copy, which runs
        # before the log's first write. propagating would tear down the
        # entire run (and all sibling tasks) for one task's failed write, so
        # record an errored EvalLog instead: the dispatcher re-queues errored
        # tasks and eval_set() retries them once storage recovers.
        if options.debug_errors:
            raise
        inner = inner_exception(ex)
        log.error(
            f"Task '{options.task.name}' encountered an error while starting "
            f"or writing its log: {inner}"
        )
        # location points at the log file the write was destined for — it may
        # not exist (a failed log_start() header flush, or a retry's failed
        # checkpoint startup copy) or may hold a partial log (a failed
        # error-status log_finish())
        result = EvalLog(
            status="error",
            eval=options.logger.eval,
            error=eval_error(inner, type(inner), inner, inner.__traceback__),
            location=options.logger.location,
        )
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
"""Starts up a group of tasks (:class:`GroupStartup`)."""


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
    """

    def __init__(
        self,
        queue: RunQueue,
        start_up: StartUpFn,
        *,
        parallel: int,
        task_retry_attempts: int,
        source: TaskSource | None,
        debug_errors: bool,
    ) -> None:
        self.queue = queue
        self.start_up_group = start_up
        self.parallel = parallel
        """The launch ``max_tasks`` (``ctl config --max-tasks`` overrides it live)."""
        self.task_retry_attempts = task_retry_attempts
        self.source = source
        self.debug_errors = debug_errors
        self.in_flight = 0
        self.model_counts: Counter[Model] = Counter()
        """Running attempts per model. Keyed by the ``Model`` object, not its
        name: a provider may rewrite its model name mid-run (e.g. vLLM resolving
        a LoRA spec on the first generate), and the connection pool that
        balancing spreads load across belongs to the instance."""
        self.results: dict[int, EvalLog] = {}
        self.next_index = 0
        self.cancelled = False
        """An attempt ended cancelled (the run was cancelled): start no more."""
        self.source_done = False
        self.starting_up = False
        """The loop is starting up an added group or awaiting ``next_tasks()``
        (see :meth:`run`)."""

    async def run(self, seed: list[TaskRunOptions]) -> list[EvalLog]:
        """Run the seed and every task added while the run is in progress.

        Returns the logs in queue order: the seed, then added tasks in the
        order they became ready (a retry keeps its task's position).

        A cancellation of the run that lands while tasks run or the loop waits
        is absorbed: the running tasks write cancelled logs and the run returns
        them. One that lands while the loop starts up an added group or awaits
        ``next_tasks()`` propagates: the tasks it interrupts have no log yet,
        so a run that returned normally would look complete.
        """
        self.add(seed, added=False)
        try:
            async with _run_task_screen(
                task_specs(seed), absorb_cancel=lambda: not self.starting_up
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
        """Start ready attempts while there is capacity; when idle, add more or finish."""
        while not self.cancelled:
            await self.start_up(self.queue.take("when_free"))
            await self.drop_abandoned_retries()
            self.start_ready(tg)
            if self.cancelled:
                break
            if self.queue.ready or self.in_flight:
                await self.queue.wake.wait()
            elif not await self.add_when_idle():
                # no await before returning: an addition accepted after this
                # point would never run
                self.queue.close()
                break

    async def add_when_idle(self) -> bool:
        """Add more work once nothing is ready or running; ``False`` if there is none.

        In order: tasks added with ``when_free`` since this cycle took them (so
        nothing overtakes them), then ``after_batch`` tasks, then the
        ``TaskSource``'s next batch, asked until it first returns nothing.
        Tasks added while ``next_tasks()`` runs follow its batch.
        """
        group = self.queue.take("when_free") or self.queue.take("after_batch")
        if group:
            await self.start_up(group)
        elif self.source is not None and not self.source_done:
            # left set if next_tasks() is cancelled, so the cancellation
            # propagates (see run)
            self.starting_up = True
            more = await self.source.next_tasks()
            self.starting_up = False
            if more:
                await self.start_up(self.queue.resolve(more))
            else:
                self.source_done = True
        else:
            return False
        return True

    async def start_up(self, group: list[ResolvedTask]) -> None:
        """Start up an added group and make it ready."""
        if not group:
            return
        # left set if the start-up fails, so a cancellation propagates (see run)
        self.starting_up = True
        options = await self.start_up_group(group)
        self.starting_up = False
        self.add(options, added=True)

    def add(self, options: list[TaskRunOptions], *, added: bool) -> None:
        """Make started-up tasks ready; ``added`` ones grow the task display's count."""
        self.queue.ready.extend(
            Attempt(self.next_index + i, task_options, self.task_retry_attempts)
            for i, task_options in enumerate(options)
        )
        self.next_index += len(options)
        # lets the model pause directives validate against tasks that have not
        # started (which have no EvalState to check)
        note_dispatch_models([dispatch_model_name(o.model) for o in options])
        if added:
            display().update_task_count(len(options))

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
        """Start ready attempts while there is capacity under ``max_tasks``.

        The limit is read live for each attempt (a ``ctl config --max-tasks``
        set fires the dispatch waker). A method of its own so the loop keeps
        no reference to the last attempt it started, which would keep that
        task's ``Task`` and dataset alive after it finishes.
        """
        while (
            not self.cancelled
            and self.in_flight < effective_max_tasks(self.parallel)
            and self.queue.ready
        ):
            attempt = pick_balanced(self.queue.ready, self.model_counts)
            if attempt is None:
                # every ready attempt is paused; a resume fires the dispatch waker
                return
            self.queue.ready.remove(attempt)
            self.model_counts[attempt.options.model] += 1
            self.in_flight += 1
            tg.start_soon(self.run_one, attempt)

    async def run_one(self, attempt: Attempt) -> None:
        """Run one attempt in its slot, then settle its log, its retry and its slot."""
        options = attempt.options
        retry: Attempt | None = None
        try:
            run = await _run_task(options, can_retry=attempt.retries_remaining > 0)
            if run.abandoned:
                # its never-started log entry goes; the task keeps its previous
                # attempt's errored log (already in the results)
                await options.logger.discard()
                self.finish(attempt, None, None)
                return
            if run.log is None or run.log.status == "cancelled":
                self.cancelled = True
            elif wants_retry(run, run.log, attempt):
                # before the slot is freed: the loop must not see an idle run
                # while the retry's logger reinitialises
                retry = await self.next_attempt(attempt, run.log)
        except BaseException:
            # the run failed or was cancelled while the attempt ran or while its
            # retry's logger reinitialised
            with anyio.CancelScope(shield=True):
                if not options.logger.finished:
                    await options.logger.discard(
                        keep_destination=True, keep_buffer=True
                    )
            raise
        if retry is None:
            if run.log is not None:
                # unwind the task runner's retry-pending mark (a no-op if a
                # cancel stamp during the log write already cleared it)
                clear_eval_retry_pending(run.log.eval.eval_id)
            if not options.logger.finished:
                with anyio.CancelScope(shield=True):
                    await options.logger.discard(
                        keep_destination=True, keep_buffer=True
                    )
        self.finish(attempt, run.log, retry)

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
        self, attempt: Attempt, task_log: EvalLog | None, retry: Attempt | None
    ) -> None:
        """Free the attempt's slot, record its log and queue its retry.

        No await, so the loop never sees the freed slot without the retry.
        """
        options = attempt.options
        self.in_flight -= 1
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
        """The view ``inspect ctl config`` shows of this dispatcher."""
        return TaskDispatcherStats(
            launch=self.parallel,
            in_flight=self.in_flight,
            pending=len(self.queue.ready),
        )


def pick_balanced(ready: list[Attempt], model_counts: Counter[Model]) -> Attempt | None:
    """The next attempt to start, or ``None`` if every ready attempt is paused.

    Among attempts not held by a pause latch, the earliest one whose model has
    the fewest running attempts, so as many models as possible run at once.
    Ties go to queue order, so at a launch limit of 1 a sequence-ordered queue
    keeps all of a task's model fan-outs together. The model name is passed to
    the latch because a task that has not started has no EvalState for the
    latch to resolve its model from.
    """
    candidates = [
        a
        for a in ready
        if not task_dispatch_paused(
            a.options.logger.eval.task_id, model=dispatch_model_name(a.options.model)
        )
    ]
    if not candidates:
        return None
    fewest = min(model_counts[a.options.model] for a in candidates)
    return next(a for a in candidates if model_counts[a.options.model] == fewest)


def wants_retry(run: TaskRunResult, task_log: EvalLog, attempt: Attempt) -> bool:
    """Whether a finished, not cancelled, attempt should be retried.

    It is retried after an error or its own retry request while retries
    remain, unless a ctl drain/cancel has abandoned its retry. An abort, a
    drain or a graceful sample resolution (``score``/``error``) is a user
    cancel and is never retried, even when its log has an error status.
    """
    name = attempt.options.task.name
    match run.cancel_type:
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
"""ContextVars a sandbox provider's ``task_init`` set, with the values it left."""


class _TaskCleanup(NamedTuple):
    """A started sandbox config's ``task_cleanup`` and what it runs with."""

    cleanup: TaskCleanup
    config: SandboxEnvironmentConfigType | None
    run_dir: str
    state: ProviderState
    """The provider state right after the config's ``task_init``."""


class SandboxManager:
    """Starts sandbox environments incrementally and tears them all down.

    Tasks added to a running eval — and samples a `SampleSource` adds to a
    live task — arrive in groups, so startup must be callable repeatedly:
    :meth:`start` / :meth:`start_for_samples` initialize only sandboxenvs not
    already started and accumulate their cleanups; :meth:`shutdown` runs every
    accumulated cleanup once, at the end of the run.

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
    files). :meth:`open` binds a fresh scope in the calling context before any
    task of the run is spawned, so a `task_init` that runs late — for an added
    task, or in a `SampleSource` feeder task, a sibling of the samples —
    registers on the object every task inherited rather than in its own
    context; :meth:`shutdown` releases the scope, so a later run in the same
    process starts clean.
    """

    def __init__(
        self,
        config: EvalConfig,
        cleanup: bool,
    ) -> None:
        self._config = config
        self._cleanup = cleanup
        self._started: Set[TaskSandboxEnvironment] = set()
        self._cleanups: list[_TaskCleanup] = []
        self._state: ProviderState = {}
        self._init_lock = anyio.Lock()
        self._lifecycle: ExitStack | None = None
        # keyed by task, then spec: resolution folds in per-task state
        # (run_dir), so a spec-only key would leak one task's resolution to
        # another. Weak on the task, so a finished task's Task and dataset are
        # not kept alive until the run ends
        self._resolved_no_metadata: weakref.WeakKeyDictionary[
            Task, dict[SandboxEnvironmentSpec, TaskSandboxEnvironment]
        ] = weakref.WeakKeyDictionary()

    def open(self) -> None:
        """Own the run's sandbox lifecycle state from the calling context.

        Call before any task or sample of the run is spawned (and whether or
        not any initial sample has a sandbox — the first sandbox may arrive
        with an added task or sample). :meth:`shutdown` releases it.
        """
        if self._lifecycle is None:
            self._lifecycle = ExitStack()
            self._lifecycle.enter_context(sandbox_lifecycle_scope())

    async def start(self, tasks: list[ResolvedTask], task_names: list[str]) -> None:
        """Start the sandboxenvs of `tasks`' selected samples.

        `task_names` is every task name known to the run so far (not just
        `tasks`), so `task:id` sample selectors resolve here exactly as they do
        when the tasks run.
        """
        # find unique sandboxenvs to start
        sandboxenvs: Set[TaskSandboxEnvironment] = set()
        for task in tasks:
            resolved_task_sample_ids = resolve_task_sample_ids(
                task.task.name, self._config.sample_id, task_names
            )
            dataset = slice_dataset(
                task.task.dataset,
                self._config.limit,
                resolved_task_sample_ids,
                dynamic=task.task.sample_source is not None,
            )
            sandboxenvs |= await self._resolve_sandboxenvs(task, dataset)

        await self._start_sandboxenvs(sandboxenvs)

    async def start_for_samples(
        self, task: ResolvedTask, samples: list[Sample]
    ) -> None:
        """Initialize the sandboxenvs of samples added to a live task.

        The counterpart of :meth:`start` for samples a `SampleSource` adds
        while its task runs: a sandbox config first seen in an added sample
        (including the task-level config when the seed dataset was empty)
        gets the same `task_init` startup as seed configs — up-front image
        build/pull, fail-fast validation, and a registered `task_cleanup` —
        before the sample runs. Configs already started are a no-op.
        """
        await self._start_sandboxenvs(await self._resolve_sandboxenvs(task, samples))

    async def _resolve_sandboxenvs(
        self, task: ResolvedTask, samples: Iterable[Sample]
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
        resolved = self._resolved_no_metadata.setdefault(task.task, {})
        for sample in samples:
            sandboxenv: TaskSandboxEnvironment | None = None
            cache_key: SandboxEnvironmentSpec | None = None
            if not sample.metadata:
                spec = await resolve_sandbox(task.sandbox, sample, task.task.name)
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
        self, sandboxenvs: Set[TaskSandboxEnvironment]
    ) -> None:
        """Run `task_init` for new sandboxenvs; set provider state in the caller.

        Serialized on a lock with the started-set re-checked under it, so
        concurrent callers (e.g. two live tasks adding samples at once)
        can't double-init the same sandboxenv. The pre-lock filter lets a
        caller whose configs are all already started return without waiting
        out another caller's (possibly minutes-long) image pull — safe
        because the started set only ever grows.
        """
        sandboxenvs = {env for env in sandboxenvs if env not in self._started}
        if sandboxenvs:
            async with self._init_lock:
                await self._init_sandboxenvs(sandboxenvs)
        _set_provider_state(self._state)

    async def _init_sandboxenvs(self, sandboxenvs: Set[TaskSandboxEnvironment]) -> None:
        """Run ``task_init`` for each sandboxenv not started meanwhile (under the lock)."""
        sandboxenvs = {env for env in sandboxenvs if env not in self._started}
        if sandboxenvs:
            set_sandbox_prebuilt(self._config.sandbox_prebuilt is True)

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

                    # run startup, from the state earlier task_inits left (so a
                    # provider's get-or-create finds it)
                    task_init = cast(TaskInit, getattr(sandboxenv_type, "task_init"))
                    _set_provider_state(self._state)
                    with chdir(sandboxenv.run_dir), environ_vars(dict(sandboxenv.env)):
                        state = await _provider_state_of(
                            task_init, "startup", sandboxenv.sandbox.config
                        )

                    # track as started and append cleanup method
                    self._started.add(sandboxenv)
                    self._state.update(state)
                    task_cleanup = cast(
                        TaskCleanup, getattr(sandboxenv_type, "task_cleanup")
                    )
                    self._cleanups.append(
                        _TaskCleanup(
                            task_cleanup,
                            sandboxenv.sandbox.config,
                            sandboxenv.run_dir,
                            dict(self._state),
                        )
                    )

                # provide some space above task display ("none" has no task
                # display and must keep stdout machine-readable, e.g. --json)
                if display_type() != "none":
                    print("")

    async def shutdown(self) -> None:
        """Run every accumulated `task_cleanup`, then release the lifecycle state.

        The final cleanup of the run: it also covers samples whose own
        cleanup was deferred by an interruption, since their provider state is
        on the scope this manager owns.
        """

        async def cleanup(job: _TaskCleanup) -> None:
            _set_provider_state(job.state)
            await job.cleanup("shutdown", job.config, self._cleanup)

        with anyio.CancelScope(shield=True):
            try:
                for job in self._cleanups:
                    try:
                        with chdir(job.run_dir):
                            async with (
                                unwrap_exception_group(),
                                anyio.create_task_group() as tg,
                            ):
                                tg.start_soon(cleanup, job)
                    except BaseException as ex:
                        log.warning(
                            f"Error occurred shutting down sandbox environments: {exception_message(ex)}"
                        )
            finally:
                if self._lifecycle is not None:
                    self._lifecycle.close()
                    self._lifecycle = None


async def _provider_state_of(
    task_init: TaskInit, task_name: str, config: SandboxEnvironmentConfigType | None
) -> ProviderState:
    """Run a provider's ``task_init`` in a child task; return the ContextVars it set.

    Only what ``task_init`` itself sets is kept, not a copy of the caller's
    whole context, which would keep the caller's state (its task display,
    a running task's settings) alive and visible to ``task_cleanup``.
    """
    base = copy_context()
    state: ProviderState = {}

    async def run() -> None:
        await task_init(task_name, config)
        state.update(
            (var, value)
            for var, value in copy_context().items()
            if base.get(var, _UNSET) is not value
        )

    try:
        async with anyio.create_task_group() as tg:
            tg.start_soon(run)
    except BaseExceptionGroup as group:
        # the task group wraps the one task's exception
        if len(group.exceptions) == 1:
            raise group.exceptions[0] from group.exceptions[0].__cause__
        raise
    return state


_UNSET = object()


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
