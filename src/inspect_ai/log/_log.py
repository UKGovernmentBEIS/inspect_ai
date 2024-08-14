import abc
import asyncio
import logging
import os
import re
import sys
import traceback
from logging import LogRecord
from types import TracebackType
from typing import Any, Literal, Type, cast

import click
import tenacity
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from pydantic_core import to_jsonable_python
from rich.console import Console, RenderableType
from rich.traceback import Traceback

from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.error import exception_message
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.scorer import Score
from inspect_ai.scorer._metric import SampleScore

SCORER_PLACEHOLDER = "88F74D2C"


class EvalConfig(BaseModel):
    limit: int | tuple[int, int] | None = Field(default=None)
    """Sample limit (number of samples or range of samples)."""

    epochs: int | None = Field(default=None)
    """Number of epochs to run samples over."""

    epochs_reducer: list[str] | None = Field(default=None)
    """Reducers for aggregating per-sample scores."""

    max_messages: int | None = Field(default=None)
    """Maximum messages to allow in a chat conversation."""

    max_samples: int | None = Field(default=None)
    """Maximum number of samples to run in parallel."""

    max_tasks: int | None = Field(default=None)
    """Maximum number of tasks to run in parallel."""

    max_subprocesses: int | None = Field(default=None)
    """Maximum number of subprocesses to run concurrently."""

    sandbox_cleanup: bool | None = Field(default=None)
    """Cleanup sandbox environments after task completes."""

    log_samples: bool | None = Field(default=None)
    """Log detailed information on each sample."""

    log_images: bool | None = Field(default=None)
    """Log base64 encoded versions of images."""

    log_buffer: int | None = Field(default=None)
    """Number of samples to buffer before writing log file."""


class EvalSample(BaseModel):
    id: int | str
    """Unique id for sample."""

    epoch: int
    """Epoch number for sample."""

    input: str | list[ChatMessage]
    """Sample input."""

    choices: list[str] | None = Field(default=None)
    """Sample choices."""

    target: str | list[str]
    """Sample target value(s)"""

    messages: list[ChatMessage]
    """Chat conversation history for sample."""

    output: ModelOutput
    """Model output from sample."""

    @property
    def score(self) -> Score | None:
        """Score for sample (deprecated)."""
        logging.warning(
            "The 'score' field is deprecated. Access sample scores through 'scores' instead."
        )
        return list(self.scores.values())[0] if self.scores else None

    scores: dict[str, Score] | None = Field(default=None)
    """Scores for sample."""

    metadata: dict[str, Any]
    """Additional sample metadata."""

    @model_validator(mode="before")
    @classmethod
    def convert_score_to_scores(
        cls: Type["EvalSample"], values: dict[str, Any]
    ) -> dict[str, Any]:
        if "score" in values:
            # There cannot be a scorers property too
            if "scores" in values:
                raise TypeError(
                    "Unexpected value `scores` present when `score` has already been specified."
                )

            # Convert the scorer to the new schema
            score = values["score"]
            values["scores"] = {SCORER_PLACEHOLDER: score}

            # Get rid of the 'scorer' property
            del values["score"]

        return values


class EvalPlanStep(BaseModel):
    solver: str
    """Name of solver."""

    params: dict[str, Any] = Field(default={})
    """Parameters used to instantiate solver."""


class EvalPlan(BaseModel):
    name: str = Field(default="plan")
    """Plan name."""

    steps: list[EvalPlanStep] = Field(default=[])
    """Steps in plan."""

    finish: EvalPlanStep | None = Field(default=None)
    """Step to always run at the end."""

    config: GenerateConfig = Field(default=GenerateConfig())
    """Generation config."""


class EvalMetric(BaseModel):
    name: str
    """Metric name."""

    value: int | float
    """Metric value."""

    options: dict[str, Any] = Field(default={})
    """Options specified when creating metric."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata associated with metric."""


class EvalScore(BaseModel):
    name: str
    """Score name."""

    scorer: str
    """Scorer name."""

    reducer: str | None = Field(default=None)
    """Reducer name."""

    params: dict[str, Any] = Field(default={})
    """Parameters specified when creating scorer."""

    metrics: dict[str, EvalMetric] = Field(default=[])
    """Metrics computed for this scorer."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional scorer metadata."""


class EvalSampleReductions(BaseModel):
    scorer: str
    """Name the of scorer"""

    reducer: str | None = Field(default=None)
    """Name the of reducer"""

    samples: list[SampleScore]
    """List of reduced scores"""


class EvalResults(BaseModel):
    @property
    def scorer(self) -> EvalScore | None:
        """Scorer used to compute results (deprecated)."""
        logging.warning(
            "The 'scorer' field is deprecated. Use 'scorers' instead.",
        )
        return self.scores[0] if self.scores else None

    @property
    def metrics(self) -> dict[str, EvalMetric]:
        """Metrics computed (deprecated)."""
        logging.warning(
            "The 'metrics' field is deprecated. Access metrics through 'scorers' instead."
        )
        return self.scores[0].metrics if self.scores else {}

    scores: list[EvalScore] = Field(default=[])
    """Scorers used to compute results"""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional results metadata."""

    sample_reductions: list[EvalSampleReductions] | None = Field(default=None)
    """List of per sample scores reduced across epochs"""

    @model_validator(mode="before")
    @classmethod
    def convert_scorer_to_scorers(
        cls: Type["EvalResults"], values: dict[str, Any]
    ) -> dict[str, Any]:
        if "scorer" in values:
            # There cannot be a scorers property too
            if "scores" in values:
                raise TypeError(
                    "Unexpected value `scores` present when `scorer` has already been specified."
                )

            # Gather metrics
            if "metrics" in values:
                metrics = values["metrics"]
                del values["metrics"]
            # Convert the scorer to the new schema
            score = values["scorer"]
            if metrics:
                score["metrics"] = metrics
            score["scorer"] = score["name"]
            values["scores"] = [score]

            # Get rid of the 'scorer' property
            del values["scorer"]

        return values


class EvalDataset(BaseModel):
    name: str | None = Field(default=None)
    """Dataset name."""

    location: str | None = Field(default=None)
    """Dataset location (file path or remote URL)"""

    samples: int | None = Field(default=None)
    """Number of samples in the dataset."""

    shuffled: bool | None = Field(default=None)
    """Was the dataset shuffled after reading."""


class EvalRevision(BaseModel):
    type: Literal["git"]
    """Type of revision (currently only "git")"""

    origin: str
    """Revision origin server"""

    commit: str
    """Revision commit."""


class EvalSpec(BaseModel):
    task: str
    """Task name."""

    task_version: int = Field(default=0)
    """Task version."""

    task_file: str | None = Field(default=None)
    """Task source file."""

    task_id: str = Field(default="")
    """Unique task id."""

    run_id: str = Field(default="")
    """Unique run id"""

    created: str
    """Time created."""

    dataset: EvalDataset
    """Dataset used for eval."""

    sandbox: tuple[str, str | None] | None = Field(default=None)
    """Sandbox environment type and optional config file."""

    model: str
    """Model used for eval."""

    model_base_url: str | None = Field(default=None)
    """Optional override of model base url"""

    task_attribs: dict[str, Any] = Field(default={})
    """Attributes of the @task decorator."""

    task_args: dict[str, Any] = Field(default={})
    """Arguments used for invoking the task."""

    model_args: dict[str, Any] = Field(default={})
    """Model specific arguments."""

    config: EvalConfig
    """Configuration values for eval."""

    revision: EvalRevision | None = Field(default=None)
    """Source revision of eval."""

    packages: dict[str, str] = Field(default={})
    """Package versions for eval."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional eval metadata."""

    # allow field model_args
    model_config = ConfigDict(protected_namespaces=())


class EvalError(BaseModel):
    message: str
    """Error message."""

    traceback: str
    """Error traceback."""

    traceback_ansi: str
    """Error traceback with ANSI color codes."""


def eval_error(
    exception: BaseException,
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> EvalError:
    # get text traceback
    traceback_text = "\n".join(
        traceback.format_exception(exc_type, exc_value, exc_traceback)
    )

    with open(os.devnull, "w") as f:
        console = Console(record=True, file=f, legacy_windows=True)
        console.print(rich_traceback(exc_type, exc_value, exc_traceback))
        traceback_ansi = console.export_text(styles=True)

    # return error
    return EvalError(
        message=exception_message(exception),
        traceback=traceback_text,
        traceback_ansi=traceback_ansi,
    )


def rich_traceback(
    exc_type: Type[Any], exc_value: BaseException, exc_traceback: TracebackType | None
) -> RenderableType:
    rich_tb = Traceback.from_exception(
        exc_type=exc_type,
        exc_value=exc_value,
        traceback=exc_traceback,
        suppress=[click, asyncio, tenacity, sys.modules[PKG_NAME]],
        show_locals=False,
    )
    return rich_tb


class EvalStats(BaseModel):
    started_at: str = Field(default="")
    """Evaluation start time."""

    completed_at: str = Field(default="")
    """Evaluation completion time."""

    model_usage: dict[str, ModelUsage] = Field(default={})
    """Model token usage for evaluation."""

    # allow field model_usage
    model_config = ConfigDict(protected_namespaces=())


LoggingLevel = Literal[
    "debug", "http", "sandbox", "info", "warning", "error", "critical"
]
"""Logging level."""


class LoggingMessage(BaseModel):
    name: str | None = Field(default=None)
    """Logger name (e.g. 'httpx')"""

    level: LoggingLevel
    """Logging level."""

    message: str
    """Log message."""

    created: float
    """Message created time."""

    filename: str = Field(default="unknown")
    """Logged from filename."""

    module: str = Field(default="unknown")
    """Logged from module."""

    lineno: int = Field(default=0)
    """Logged from line number."""

    args: JsonValue = Field(default=None)
    """Extra arguments passed to log function."""

    @staticmethod
    def from_log_record(record: LogRecord) -> "LoggingMessage":
        """Create a LoggingMesssage from a LogRecord.

        Args:
          record (LogRecord): LogRecord to convert.

        Returns:
          LoggingMessage for LogRecord

        """
        return LoggingMessage(
            # don't include full file paths (as the filename is also below),
            # we just want to use this to capture e.g. 'httpx', 'openai', etc.
            name=record.name
            if re.match(r"^[\w_]+$", record.name) is not None
            else None,
            level=cast(LoggingLevel, record.levelname.lower()),
            message=record.getMessage(),
            created=record.created * 1000,
            filename=str(record.filename),
            module=str(record.module),
            lineno=record.lineno or 0,
            # serialize anything we can from the additional arguments
            args=to_jsonable_python(record.args, fallback=lambda _x: None)
            if record.args
            else None,
        )

    @model_validator(mode="before")
    @classmethod
    def convert_log_levels(
        cls: Type["LoggingMessage"], values: dict[str, Any]
    ) -> dict[str, Any]:
        if "level" in values:
            level = values["level"]
            if level == "tools":
                values["level"] = "sandbox"

        return values


class EvalLog(BaseModel):
    version: int = Field(default=2)
    """Eval log file format version."""

    status: Literal["started", "success", "cancelled", "error"] = Field(
        default="started"
    )
    """Status of evaluation (did it succeed or fail)."""

    eval: EvalSpec
    """Eval identity and configuration."""

    plan: EvalPlan = Field(default=EvalPlan())
    """Eval plan (solvers and config)"""

    results: EvalResults | None = None
    """Eval results (scores and metrics)."""

    stats: EvalStats = Field(default=EvalStats())
    """Eval stats (runtime, model usage)"""

    error: EvalError | None = Field(default=None)
    """Error that halted eval (if status=="error")"""

    samples: list[EvalSample] | None = Field(default=None)
    """Samples processed by eval."""

    logging: list[LoggingMessage] = Field(default=[])
    """Logging message captured during eval."""

    @model_validator(mode="after")
    def populate_scorer_name_for_samples(self) -> "EvalLog":
        if self.samples and self.results and self.results.scores:
            scorer_name = self.results.scores[0].name
            for sample in self.samples:
                if sample.scores and SCORER_PLACEHOLDER in sample.scores:
                    sample.scores[scorer_name] = sample.scores[SCORER_PLACEHOLDER]
                    del sample.scores[SCORER_PLACEHOLDER]

        return self


LogEvent = Literal["plan", "sample", "score", "results", "scorer", "logging"]


class Recorder(abc.ABC):
    @abc.abstractmethod
    def log_start(self, eval: EvalSpec) -> str: ...

    @abc.abstractmethod
    def log_event(
        self,
        spec: EvalSpec,
        type: LogEvent,
        data: EvalSample | EvalPlan | EvalResults | LoggingMessage,
        flush: bool = False,
    ) -> None:
        pass

    @abc.abstractmethod
    def log_cancelled(self, eval: EvalSpec, stats: EvalStats) -> EvalLog: ...

    @abc.abstractmethod
    def log_success(self, eval: EvalSpec, stats: EvalStats) -> EvalLog: ...

    @abc.abstractmethod
    def log_failure(
        self, eval: EvalSpec, stats: EvalStats, error: EvalError
    ) -> EvalLog: ...

    @abc.abstractmethod
    def read_log(self, location: str) -> EvalLog: ...

    @abc.abstractmethod
    def write_log(self, location: str, log: EvalLog) -> None: ...

    @abc.abstractmethod
    def read_latest_log(self) -> EvalLog: ...
