import logging
from importlib import metadata as importlib_metadata
from typing import TYPE_CHECKING, Any, cast

import anyio
from shortuuid import uuid

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._eval.task.util import slice_dataset
from inspect_ai._util.background import run_in_background
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.dateutil import iso_now
from inspect_ai._util.git import git_context
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import (
    registry_log_name,
    registry_package_name,
    registry_params,
)
from inspect_ai.dataset import Dataset
from inspect_ai.event._event import Event
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalError,
    EvalPlan,
    EvalPlanStep,
    EvalResults,
    EvalRevision,
    EvalSample,
    EvalSpec,
    EvalStats,
    EvalStatus,
)
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalScorer,
    eval_config_defaults,
)
from inspect_ai.log._recorders import Recorder
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.model import (
    GenerateConfig,
    Model,
    ModelName,
)
from inspect_ai.model._model import model_usage, role_usage
from inspect_ai.model._model_config import (
    model_args_for_log,
    model_roles_to_model_roles_config,
)
from inspect_ai.scorer._metric import MetricSpec
from inspect_ai.scorer._scorer import ScorerSpec
from inspect_ai.solver._constants import SOLVER_ALL_PARAMS_ATTR
from inspect_ai.solver._plan import Plan
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.viewer import ViewerConfig

logger = logging.getLogger(__name__)

_STALE_FLUSH_INTERVAL: float = 60

if TYPE_CHECKING:
    from inspect_ai.log._recorders.buffer.history import SampleHistory


def resolve_revision() -> EvalRevision | None:
    git = git_context()
    return (
        EvalRevision(type="git", origin=git.origin, commit=git.commit, dirty=git.dirty)
        if git
        else None
    )


def resolve_external_registry_package_version(
    task_registry_name: str | None,
) -> tuple[str, str] | None:
    if task_registry_name is None:
        return None

    package_name = registry_package_name(task_registry_name)

    is_external = package_name != PKG_NAME
    if package_name is None or not is_external:
        return None

    try:
        package_version = importlib_metadata.version(package_name)
    except importlib_metadata.PackageNotFoundError:
        logger.warning(f"Could not resolve version for {package_name=}")
        return None

    return package_name, package_version


def _is_high_throughput(sample_count: int) -> bool:
    """Detect high-throughput runs that benefit from reduced logging overhead."""
    return sample_count >= 1000


class TaskLogger:
    def __init__(
        self,
        task_name: str,
        task_version: int | str,
        task_file: str | None,
        task_registry_name: str | None,
        task_display_name: str | None,
        task_id: str | None,
        eval_set_id: str | None,
        run_id: str,
        solver: SolverSpec | None,
        tags: list[str] | None,
        model: Model,
        model_roles: dict[str, Model] | None,
        dataset: Dataset,
        scorer: list[ScorerSpec] | None,
        metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
        | dict[str, list[MetricSpec]]
        | None,
        sandbox: SandboxEnvironmentSpec | None,
        task_attribs: dict[str, Any],
        task_args: dict[str, Any],
        task_args_passed: dict[str, Any],
        model_args: dict[str, Any],
        eval_config: EvalConfig,
        metadata: dict[str, Any] | None,
        viewer: ViewerConfig | None,
        recorder: Recorder,
        header_only: bool,
    ) -> None:
        packages = {
            PKG_NAME: importlib_metadata.version(PKG_NAME),
        }
        revision = resolve_revision()
        resolved_registry = resolve_external_registry_package_version(
            task_registry_name
        )
        if resolved_registry:
            external_package, external_package_version = resolved_registry
            packages[external_package] = external_package_version

        # redact authentication oriented model_args
        model_args = model_args_for_log(model_args)

        # cwd_relative_path for sandbox config
        if sandbox and isinstance(sandbox.config, str):
            sandbox = SandboxEnvironmentSpec(
                sandbox.type, cwd_relative_path(sandbox.config)
            )

        # ensure that the dataset has sample ids and record them
        sample_ids = cast(
            list[int | str],
            [
                sample.id
                for sample in slice_dataset(
                    dataset, eval_config.limit, eval_config.sample_id
                )
            ],
        )

        # total samples accounting for slicing and epochs
        epochs = eval_config.epochs if eval_config.epochs else 1
        total_samples = len(sample_ids) * epochs

        # high-throughput runs still get a larger flush buffer (fewer main
        # eval-log flushes), but we no longer force `log_realtime` or
        # `score_display` off. Realtime logging is now cheap: sample completion
        # logs directly from resident memory instead of reading every event
        # back out of the buffer DB (see `log_sample` in run.py), and the
        # WAL/persistent-connection buffer DB removed the read/write contention
        # that motivated disabling it (#3173). Score-display recompute is
        # throttled and was measured to be negligible at high sample counts.
        high_throughput = _is_high_throughput(total_samples)

        # write defaults for unspecified config
        for name, value in eval_config_defaults().items():
            if getattr(eval_config, name, None) is None:
                setattr(eval_config, name, value)

        # resolve scorers
        eval_scorers = resolve_eval_scorers(scorer)

        # resolve metrics
        eval_metrics = resolve_eval_metrics(metrics)

        # create eval spec
        self.eval = EvalSpec(
            eval_set_id=eval_set_id,
            run_id=run_id,
            created=iso_now(),
            task=f"{task_name}",
            task_id=task_id if task_id else uuid(),
            task_version=task_version,
            task_file=task_file,
            task_registry_name=task_registry_name,
            task_display_name=task_display_name,
            task_attribs=task_attribs,
            task_args=task_args,
            task_args_passed=task_args_passed,
            solver=solver.solver if solver else None,
            tags=tags,
            solver_args=solver.args if solver else None,
            solver_args_passed=solver.args_passed if solver else None,
            model=f"{ModelName(model).api}/{model.name}",
            model_generate_config=model.config,
            model_base_url=model.explicit_base_url,
            model_roles=model_roles_to_model_roles_config(model_roles),
            dataset=EvalDataset(
                name=dataset.name,
                location=cwd_relative_path(dataset.location),
                samples=len(dataset),
                sample_ids=sample_ids,
                shuffled=dataset.shuffled,
            ),
            scorers=eval_scorers,
            metrics=eval_metrics,
            sandbox=sandbox,
            model_args=model_args,
            config=eval_config,
            revision=revision,
            packages=packages,
            metadata=metadata,
            viewer=viewer,
        )

        # stack recorder and location
        self.recorder = recorder
        self.header_only = header_only

        # number of samples logged
        self._samples_completed = 0

        # size of flush buffer (how many samples we buffer before hitting storage)
        self.flush_buffer = eval_config.log_buffer or recorder.default_log_buffer(
            total_samples, high_throughput
        )
        if high_throughput and eval_config.log_buffer is None:
            eval_config.log_buffer = self.flush_buffer
        self.flush_pending: list[tuple[str | int, int]] = []
        self._init_stale_flush_state()

        # sample buffer db
        self._buffer_db: SampleBufferDatabase | None = None

    def _init_stale_flush_state(self) -> None:
        self._flush_lock = anyio.Lock()
        self._flush_pending_lock = anyio.Lock()
        self._stale_flush_cancel_scope: anyio.CancelScope | None = None
        self._stale_flush_stopped: anyio.Event | None = None
        self._stale_flush_stops: set[anyio.Event] = set()
        self._stale_flush_generation = 0
        self._stale_flush_interval = _STALE_FLUSH_INTERVAL

    async def init(self) -> None:
        self._bump_created_past_existing_logs()
        self._location = await self.recorder.log_init(self.eval)

        if self.eval.config.log_realtime is False:
            return

        self._buffer_db = SampleBufferDatabase(
            location=self._location,
            log_images=self.eval.config.log_images is not False,
            log_shared=self.eval.config.log_shared,
        )

    async def reinit(self) -> None:
        """Reset this logger for a retry attempt with a fresh eval entry."""
        await self._stop_stale_flush_timer()
        self.eval = self.eval.model_copy(update=dict(eval_id=uuid(), created=iso_now()))
        self._samples_completed = 0
        self.flush_pending = []
        self._buffer_db = None
        await self.init()

    def _bump_created_past_existing_logs(self) -> None:
        """Bump `eval.created` past any existing log at the would-be path.

        File recorders compute the log filename from `eval.created` (down
        to a second), `task`, `task_id`, and `model`. Two logs that share
        all of those collide on the filesystem; we walk `created` forward
        until the computed path doesn't already exist.
        """
        log_file_path = getattr(self.recorder, "_log_file_path", None)
        if log_file_path is None:
            return
        from datetime import datetime, timedelta, timezone

        from inspect_ai._util.file import filesystem

        max_attempts = 60
        for _ in range(max_attempts):
            path = log_file_path(self.eval)
            if not filesystem(path).exists(path):
                return
            dt = datetime.fromisoformat(self.eval.created) + timedelta(seconds=1)
            bumped = dt.astimezone(timezone.utc).isoformat(timespec="seconds")
            self.eval = self.eval.model_copy(update=dict(created=bumped))
        raise RuntimeError(
            f"Could not find a unique log filename for task {self.eval.task!r} "
            f"(task_id={self.eval.task_id}) after {max_attempts} attempts; "
            f"last tried {log_file_path(self.eval)!r}."
        )

    @property
    def location(self) -> str:
        return self._location

    @property
    def samples_completed(self) -> int:
        return self._samples_completed

    @property
    def buffer_db(self) -> SampleBufferDatabase | None:
        return self._buffer_db

    async def log_start(self, plan: EvalPlan) -> None:
        await self.recorder.log_start(self.eval, plan)
        await self.recorder.flush(self.eval)

    async def start_sample(self, sample: EvalSampleSummary) -> None:
        if self._buffer_db is not None:
            self._buffer_db.start_sample(sample)

    def log_sample_event(self, id: str | int, epoch: int, event: Event) -> None:
        # log the sample event
        if self._buffer_db is not None:
            self._buffer_db.log_events([SampleEvent(id=id, epoch=epoch, event=event)])

    def remove_sample(self, id: str | int, epoch: int) -> None:
        if self._buffer_db is not None:
            self._buffer_db.remove_samples([(id, epoch)])

    async def complete_sample(self, sample: EvalSample, *, flush: bool) -> None:
        await self.recorder.log_sample(self.eval, sample)
        await self._finalize_sample(sample, flush=flush)

    async def complete_sample_streaming(
        self, sample: EvalSample, history: "SampleHistory", *, flush: bool
    ) -> None:
        await self.recorder.log_sample_streaming(self.eval, sample, history)
        await self._finalize_sample(sample, flush=flush)

    async def _finalize_sample(self, sample: EvalSample, *, flush: bool) -> None:
        if self._buffer_db is not None:
            self._buffer_db.complete_sample(sample.summary())

        if flush:
            async with self._flush_pending_lock:
                was_empty = not self.flush_pending
                self.flush_pending.append((sample.id, sample.epoch))
                threshold_reached = len(self.flush_pending) >= self.flush_buffer

            if threshold_reached:
                await self._stop_stale_flush_timer()
                await self._flush_pending_samples()
            elif was_empty:
                await self._start_stale_flush_timer_if_needed()

        if sample.error is None:
            self._samples_completed += 1

    async def _flush_pending_samples(
        self, *, stale_flush_generation: int | None = None
    ) -> None:
        reschedule_stale_flush = False
        async with self._flush_lock:
            async with self._flush_pending_lock:
                pending = list(self.flush_pending)
                if not pending:
                    return

            await self.recorder.flush(self.eval)

            async with self._flush_pending_lock:
                if self._buffer_db is not None:
                    self._buffer_db.remove_samples(pending)

                # Items appended during the flush are at the tail; drop the flushed prefix.
                del self.flush_pending[: len(pending)]
                current_generation = self._stale_flush_generation
                reschedule_stale_flush = bool(self.flush_pending) and (
                    stale_flush_generation is None
                    or stale_flush_generation == current_generation
                )

        if reschedule_stale_flush:
            await self._arm_stale_flush_timer(generation=stale_flush_generation)

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        if self._buffer_db is not None:
            self._buffer_db.update_metrics(metrics)

    async def _start_stale_flush_timer_if_needed(self) -> None:
        await self._arm_stale_flush_timer()

    async def _arm_stale_flush_timer(self, *, generation: int | None = None) -> None:
        async with self._flush_pending_lock:
            if generation is not None and generation != self._stale_flush_generation:
                return

            should_start = 0 < len(self.flush_pending) < self.flush_buffer
            already_started = self._stale_flush_cancel_scope is not None
            if not should_start or already_started:
                return

            cancel_scope = anyio.CancelScope()
            stopped = anyio.Event()
            current_generation = self._stale_flush_generation
            self._stale_flush_cancel_scope = cancel_scope
            self._stale_flush_stopped = stopped
            self._stale_flush_stops.add(stopped)

        try:
            run_in_background(
                self._stale_flush_after_delay,
                cancel_scope,
                stopped,
                current_generation,
            )
        except Exception:
            async with self._flush_pending_lock:
                if self._stale_flush_cancel_scope is cancel_scope:
                    self._stale_flush_cancel_scope = None
                    self._stale_flush_stopped = None
                self._stale_flush_stops.discard(stopped)
            stopped.set()
            raise

    async def _stop_stale_flush_timer(self) -> None:
        async with self._flush_pending_lock:
            self._stale_flush_generation += 1
            if self._stale_flush_cancel_scope is not None:
                self._stale_flush_cancel_scope.cancel()
                self._stale_flush_cancel_scope = None
                self._stale_flush_stopped = None
            stopped_events = list(self._stale_flush_stops)

        for stopped in stopped_events:
            await stopped.wait()

    async def cleanup(self) -> None:
        await self._stop_stale_flush_timer()
        if self._buffer_db is not None:
            self._buffer_db.cleanup()
            self._buffer_db = None

    async def _clear_stale_flush_timer(
        self, cancel_scope: anyio.CancelScope, stopped: anyio.Event
    ) -> None:
        async with self._flush_pending_lock:
            if self._stale_flush_cancel_scope is cancel_scope:
                self._stale_flush_cancel_scope = None
                self._stale_flush_stopped = None

    async def _stale_flush_after_delay(
        self,
        cancel_scope: anyio.CancelScope,
        stopped: anyio.Event,
        generation: int,
    ) -> None:
        try:
            with cancel_scope:
                await anyio.sleep(self._stale_flush_interval)
                await self._clear_stale_flush_timer(cancel_scope, stopped)
                try:
                    with anyio.CancelScope(shield=True):
                        await self._flush_pending_samples(
                            stale_flush_generation=generation
                        )
                except Exception as ex:
                    logger.warning("Stale eval log flush failed: %s", ex, exc_info=ex)
                    await self._arm_stale_flush_timer(generation=generation)
        finally:
            async with self._flush_pending_lock:
                self._stale_flush_stops.discard(stopped)
            stopped.set()

    async def log_finish(
        self,
        status: EvalStatus,
        stats: EvalStats,
        results: EvalResults | None = None,
        reductions: list[EvalSampleReductions] | None = None,
        error: EvalError | None = None,
    ) -> EvalLog:
        await self._stop_stale_flush_timer()

        # finish and get log
        log = await self.recorder.log_finish(
            self.eval, status, stats, results, reductions, error, self.header_only
        )

        # cleanup the events db
        if self._buffer_db is not None:
            self._buffer_db.cleanup()
            self._buffer_db = None

        # return log
        return log


def plan_to_eval_plan(plan: Plan, config: GenerateConfig) -> EvalPlan:
    def eval_plan_step(solver: Solver) -> EvalPlanStep:
        return EvalPlanStep(
            solver=registry_log_name(solver),
            params=getattr(solver, SOLVER_ALL_PARAMS_ATTR, {}),
            params_passed=registry_params(solver),
        )

    eval_plan = EvalPlan(
        name=plan.name,
        steps=[eval_plan_step(solver) for solver in plan.steps],
        finish=eval_plan_step(plan.finish) if plan.finish else None,
        config=config,
    )
    if plan.finish:
        eval_plan.steps.append(eval_plan_step(plan.finish))
    return eval_plan


async def log_start(
    logger: TaskLogger,
    plan: Plan,
    config: GenerateConfig,
) -> None:
    eval_plan = plan_to_eval_plan(plan, config)
    await logger.log_start(eval_plan)


def collect_eval_data(stats: EvalStats) -> None:
    from inspect_ai.log._log import ConnectionLimitChange
    from inspect_ai.util._concurrency import adaptive_controllers

    # collect stats
    stats.completed_at = iso_now()
    stats.model_usage = model_usage()
    stats.role_usage = role_usage()

    # capture adaptive-connections controller history. The tuple's second
    # element is the controller's display name (model name), NOT the underlying
    # connection_key (which often contains an api_key) — see _set_limit.
    history: list[ConnectionLimitChange] = []
    for controller in adaptive_controllers():
        for ts, model, old, new, reason in controller.history:
            history.append(
                ConnectionLimitChange(
                    timestamp=ts,
                    model=model,
                    old_limit=old,
                    new_limit=new,
                    reason=reason,  # type: ignore[arg-type]
                )
            )
    history.sort(key=lambda e: e.timestamp)
    stats.connection_limit_history = history


def resolve_eval_metrics(
    metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
    | dict[str, list[MetricSpec]]
    | None,
) -> (
    list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
    | dict[str, list[EvalMetricDefinition]]
    | None
):
    if metrics is None:
        return None
    elif isinstance(metrics, list):
        result: list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]] = []
        for metric_item in metrics:
            if isinstance(metric_item, dict):
                # It's a dict of metric groups
                result.append(
                    {
                        k: [
                            EvalMetricDefinition(name=v.metric, options=v.args)
                            for v in metric_list
                        ]
                        for k, metric_list in metric_item.items()
                    }
                )
            else:
                # It's a direct MetricSpec
                result.append(
                    EvalMetricDefinition(
                        name=metric_item.metric, options=metric_item.args
                    )
                )
        return result
    else:
        return {
            k: [
                EvalMetricDefinition(name=v.metric, options=v.args) for v in metric_list
            ]
            for k, metric_list in metrics.items()
        }


def resolve_eval_scorers(scorers: list[ScorerSpec] | None) -> list[EvalScorer] | None:
    if scorers is None:
        return None
    else:
        results = []
        for scorer in scorers:
            results.append(
                EvalScorer(
                    name=scorer.scorer,
                    metrics=resolve_scorer_metrics(scorer.metrics),
                    options=scorer.args,
                    metadata=scorer.metadata,
                )
            )
        return results


def resolve_scorer_metrics(
    metrics: list[MetricSpec | dict[str, list[MetricSpec]]]
    | dict[str, list[MetricSpec]]
    | None,
) -> (
    list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
    | dict[str, list[EvalMetricDefinition]]
    | None
):
    if metrics is None:
        return None
    elif isinstance(metrics, list):
        resolved_metrics: list[
            EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]
        ] = []
        for metric_item in metrics:
            if isinstance(metric_item, MetricSpec):
                resolved_metrics.append(
                    EvalMetricDefinition(
                        name=metric_item.metric, options=metric_item.args
                    )
                )
            elif isinstance(metric_item, dict):
                resolved_metrics.append(
                    {
                        metric_group: [
                            EvalMetricDefinition(
                                name=metric_spec.metric, options=metric_spec.args
                            )
                            for metric_spec in metric_specs
                        ]
                        for metric_group, metric_specs in metric_item.items()
                    }
                )
            else:
                raise TypeError(f"Unexpected item in list: {metric_item}")
        return resolved_metrics
    else:
        return {
            metric_group: [
                EvalMetricDefinition(name=metric_spec.metric, options=metric_spec.args)
                for metric_spec in metric_specs
            ]
            for metric_group, metric_specs in metrics.items()
        }
