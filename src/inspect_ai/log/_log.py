import abc
import asyncio
import os
import sys
import traceback
from logging import LogRecord
from types import TracebackType
from typing import Any, Literal, Type, cast

import click
import tenacity
from pydantic import BaseModel, ConfigDict, Field
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


class EvalConfig(BaseModel):
    limit: int | tuple[int, int] | None = Field(default=None)
    """Sample limit (number of samples or range of samples)."""

    epochs: int | None = Field(default=None)
    """Number of epochs to run samples over."""

    max_messages: int | None = Field(default=None)
    """Maximum messages to allow in a chat conversation."""

    max_samples: int | None = Field(default=None)
    """Maximum number of samples to run in parallel."""

    max_subprocesses: int | None = Field(default=None)
    """Maximum number of subprocesses to run concurrently."""

    toolenv_cleanup: bool | None = Field(default=None)
    """Cleanup tool environments after task completes."""

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

    score: Score | None = Field(default=None)
    """Score for sample."""

    metadata: dict[str, Any]
    """Additional sample metadata."""


class EvalPlanStep(BaseModel):
    solver: str
    """Name of solver."""

    params: dict[str, Any] = Field(default={})
    """Parameters used to instantiate solver."""


class EvalScorer(BaseModel):
    name: str
    """Scorer name."""

    params: dict[str, Any] = Field(default={})
    """Parameters specified when creating scorer."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional scorer metadata."""


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


class EvalResults(BaseModel):
    scorer: EvalScorer | None = Field(default=None)
    """Scorer used to compute results"""

    metrics: dict[str, EvalMetric] = Field(default={})
    """Metrics computed."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional results metadata."""


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

    tool_environment: tuple[str, str | None] | None = Field(default=None)
    """Tool environment type and optional config file."""

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


LoggingLevel = Literal["debug", "http", "tools", "info", "warning", "error", "critical"]
"""Logging level."""


class LoggingMessage(BaseModel):
    level: LoggingLevel
    """Logging level."""

    message: str
    """Log message."""

    created: float
    """Message created time."""

    @staticmethod
    def from_log_record(record: LogRecord) -> "LoggingMessage":
        """Create a LoggingMesssage from a LogRecord.

        Args:
          record (LogRecord): LogRecord to convert.

        Returns:
          LoggingMessage for LogRecord

        """
        return LoggingMessage(
            level=cast(LoggingLevel, record.levelname.lower()),
            message=record.getMessage(),
            created=record.created * 1000,
        )


class EvalLog(BaseModel):
    version: int = Field(default=1)
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
