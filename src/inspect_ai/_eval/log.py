from importlib import metadata as importlib_metadata
from typing import Any

from shortuuid import uuid

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.datetime import iso_now
from inspect_ai._util.git import git_context
from inspect_ai._util.path import cwd_relative_path
from inspect_ai.dataset import Dataset, Sample
from inspect_ai.log import (
    EvalConfig,
    EvalDataset,
    EvalError,
    EvalLog,
    EvalPlan,
    EvalResults,
    EvalRevision,
    EvalSample,
    EvalSpec,
    EvalStats,
    LoggingMessage,
)
from inspect_ai.log._log import LogEvent, Recorder
from inspect_ai.model import Model, ModelName
from inspect_ai.scorer import Score
from inspect_ai.solver import TaskState


class EvalLogger:
    def __init__(
        self,
        task_name: str,
        task_version: int,
        task_file: str | None,
        task_run_dir: str,
        task_id: str | None,
        run_id: str,
        model: Model,
        dataset: Dataset,
        task_attribs: dict[str, Any],
        task_args: dict[str, Any],
        model_args: dict[str, Any],
        eval_config: EvalConfig,
        recorder: Recorder,
    ) -> None:
        # determine versions
        git = git_context(task_run_dir)
        revision = (
            EvalRevision(type="git", origin=git.origin, commit=git.commit)
            if git
            else None
        )
        packages = {PKG_NAME: importlib_metadata.version(PKG_NAME)}

        # create eval spec
        self.eval = EvalSpec(
            task=f"{task_name}",
            task_version=task_version,
            task_file=task_file,
            task_id=task_id if task_id else uuid(),
            run_id=run_id,
            created=iso_now(),
            model=str(ModelName(model)),
            model_base_url=model.api.base_url,
            dataset=EvalDataset(
                name=dataset.name, location=cwd_relative_path(dataset.location)
            ),
            task_attribs=task_attribs,
            task_args=task_args,
            model_args=model_args,
            config=eval_config,
            revision=revision,
            packages=packages,
        )

        # stack recorder and location
        self.recorder = recorder
        self._location = self.recorder.log_start(self.eval)

    @property
    def location(self) -> str:
        return self._location

    def log_event(
        self,
        type: LogEvent,
        data: EvalSample | EvalPlan | EvalResults | LoggingMessage,
    ) -> None:
        self.recorder.log_event(self.eval, type, data)

    def log_sample(
        self,
        epoch: int,
        sample: Sample,
        state: TaskState,
        score: Score | None,
    ) -> None:
        # log
        self.log_event(
            "sample",
            EvalSample(
                id=sample.id if isinstance(sample.id, int) else str(sample.id),
                epoch=epoch,
                input=sample.input,
                choices=sample.choices,
                target=sample.target,
                metadata=state.metadata if state.metadata else {},
                messages=state.messages,
                output=state.output,
                score=score,
            ),
        )

    def log_plan(self, plan: EvalPlan) -> None:
        self.log_event("plan", plan)

    def log_results(self, results: EvalResults) -> None:
        self.log_event("results", results)

    def log_success(self, stats: EvalStats) -> EvalLog:
        return self.recorder.log_success(self.eval, stats)

    def log_failure(self, stats: EvalStats, error: EvalError) -> EvalLog:
        return self.recorder.log_failure(self.eval, stats, error)
