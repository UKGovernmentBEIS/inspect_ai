from importlib import metadata as importlib_metadata
from typing import Any, Literal, cast

from shortuuid import uuid

from inspect_ai._display.core.display import TaskDisplayMetric
from inspect_ai._eval.task.util import slice_dataset
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.git import git_context
from inspect_ai._util.path import cwd_relative_path
from inspect_ai._util.registry import (
    registry_log_name,
    registry_params,
)
from inspect_ai.dataset import Dataset
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
)
from inspect_ai.log._log import (
    EvalLog,
    EvalMetricDefinition,
    EvalSampleReductions,
    EvalSampleSummary,
    EvalScorer,
    eval_config_defaults,
)
from inspect_ai.log._model import model_args_for_log, model_roles_to_model_roles_config
from inspect_ai.log._recorders import Recorder
from inspect_ai.log._recorders.buffer import SampleBufferDatabase
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._transcript import Event
from inspect_ai.model import (
    GenerateConfig,
    Model,
    ModelName,
)
from inspect_ai.model._model import model_usage
from inspect_ai.scorer._metric import MetricSpec
from inspect_ai.scorer._scorer import ScorerSpec
from inspect_ai.solver._plan import Plan
from inspect_ai.solver._solver import Solver, SolverSpec
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


class TaskLogger:
    def __init__(
        self,
        task_name: str,
        task_version: int,
        task_file: str | None,
        task_registry_name: str | None,
        task_id: str | None,
        run_id: str,
        solver: SolverSpec | None,
        tags: list[str] | None,
        model: Model,
        model_roles: dict[str, Model] | None,
        dataset: Dataset,
        scorer: list[ScorerSpec] | None,
        metrics: list[MetricSpec] | dict[str, list[MetricSpec]] | None,
        sandbox: SandboxEnvironmentSpec | None,
        task_attribs: dict[str, Any],
        task_args: dict[str, Any],
        model_args: dict[str, Any],
        eval_config: EvalConfig,
        metadata: dict[str, Any] | None,
        recorder: Recorder,
    ) -> None:
        # determine versions
        git = git_context()
        revision = (
            EvalRevision(type="git", origin=git.origin, commit=git.commit)
            if git
            else None
        )
        packages = {PKG_NAME: importlib_metadata.version(PKG_NAME)}

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
            run_id=run_id,
            created=iso_now(),
            task=f"{task_name}",
            task_id=task_id if task_id else uuid(),
            task_version=task_version,
            task_file=task_file,
            task_registry_name=task_registry_name,
            task_attribs=task_attribs,
            task_args=task_args,
            solver=solver.solver if solver else None,
            tags=tags,
            solver_args=solver.args if solver else None,
            model=str(ModelName(model)),
            model_generate_config=model.config,
            model_base_url=model.api.base_url,
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
        )

        # stack recorder and location
        self.recorder = recorder

        # number of samples logged
        self._samples_completed = 0

        # size of flush buffer (how many samples we buffer before hitting storage)
        self.flush_buffer = eval_config.log_buffer or recorder.default_log_buffer()
        self.flush_pending: list[tuple[str | int, int]] = []

        # sample buffer db
        self._buffer_db: SampleBufferDatabase | None = None

    async def init(self) -> None:
        self._location = await self.recorder.log_init(self.eval)
        if self.eval.config.log_realtime is not False:
            self._buffer_db = SampleBufferDatabase(
                location=self._location,
                log_images=self.eval.config.log_images is not False,
                log_shared=self.eval.config.log_shared,
            )

    @property
    def location(self) -> str:
        return self._location

    @property
    def samples_completed(self) -> int:
        return self._samples_completed

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
        # log the sample
        await self.recorder.log_sample(self.eval, sample)

        # mark complete
        if self._buffer_db is not None:
            self._buffer_db.complete_sample(sample.summary())

        # flush if requested
        if flush:
            self.flush_pending.append((sample.id, sample.epoch))
            if len(self.flush_pending) >= self.flush_buffer:
                # flush to disk
                await self.recorder.flush(self.eval)

                # notify the event db it can remove these
                if self._buffer_db is not None:
                    self._buffer_db.remove_samples(self.flush_pending)

                # Clear
                self.flush_pending.clear()

        # track sucessful samples logged
        if sample.error is None:
            self._samples_completed += 1

    def update_metrics(self, metrics: list[TaskDisplayMetric]) -> None:
        if self._buffer_db is not None:
            self._buffer_db.update_metrics(metrics)

    async def log_finish(
        self,
        status: Literal["success", "cancelled", "error"],
        stats: EvalStats,
        results: EvalResults | None = None,
        reductions: list[EvalSampleReductions] | None = None,
        error: EvalError | None = None,
    ) -> EvalLog:
        # finish and get log
        log = await self.recorder.log_finish(
            self.eval, status, stats, results, reductions, error
        )

        # cleanup the events db
        if self._buffer_db is not None:
            self._buffer_db.cleanup()

        # return log
        return log


async def log_start(
    logger: TaskLogger,
    plan: Plan,
    config: GenerateConfig,
) -> None:
    def eval_plan_step(solver: Solver) -> EvalPlanStep:
        return EvalPlanStep(
            solver=registry_log_name(solver), params=registry_params(solver)
        )

    eval_plan = EvalPlan(
        name=plan.name,
        steps=[eval_plan_step(solver) for solver in plan.steps],
        finish=eval_plan_step(plan.finish) if plan.finish else None,
        config=config,
    )
    if plan.finish:
        eval_plan.steps.append(eval_plan_step(plan.finish))

    await logger.log_start(eval_plan)


def collect_eval_data(stats: EvalStats) -> None:
    # collect stats
    stats.completed_at = iso_now()
    stats.model_usage = model_usage()


def resolve_eval_metrics(
    metrics: list[MetricSpec] | dict[str, list[MetricSpec]] | None,
) -> list[EvalMetricDefinition] | dict[str, list[EvalMetricDefinition]] | None:
    if metrics is None:
        return None
    elif isinstance(metrics, list):
        return [EvalMetricDefinition(name=m.metric, options=m.args) for m in metrics]
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
