import asyncio
import os
import sys
import traceback
from logging import getLogger
from types import TracebackType
from typing import Any, Literal, Tuple, Type, TypedDict

import click
import tenacity
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)
from rich.console import Console, RenderableType
from rich.traceback import Traceback

from inspect_ai._util.constants import CONSOLE_DISPLAY_WIDTH, PKG_NAME
from inspect_ai._util.error import EvalError, exception_message
from inspect_ai._util.logger import warn_once
from inspect_ai.approval._policy import ApprovalPolicyConfig
from inspect_ai.dataset._dataset import MT, metadata_as
from inspect_ai.model import ChatMessage, GenerateConfig, ModelOutput, ModelUsage
from inspect_ai.scorer import Score
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._store import Store
from inspect_ai.util._store_model import SMT

from ._transcript import Event

logger = getLogger(__name__)

SCORER_PLACEHOLDER = "88F74D2C"


class EvalConfigDefaults(TypedDict):
    epochs: int
    epochs_reducer: list[str]
    fail_on_error: bool
    sandbox_cleanup: bool
    log_samples: bool
    log_images: bool
    score_display: bool


def eval_config_defaults() -> EvalConfigDefaults:
    return {
        "epochs": 1,
        "epochs_reducer": ["mean"],
        "fail_on_error": True,
        "sandbox_cleanup": True,
        "log_samples": True,
        "log_images": True,
        "score_display": True,
    }


class EvalConfig(BaseModel):
    """Configuration used for evaluation."""

    limit: int | tuple[int, int] | None = Field(default=None)
    """Sample limit (number of samples or range of samples)."""

    sample_id: str | int | list[str | int] | None = Field(default=None)
    """Evaluate specific sample(s)."""

    epochs: int | None = Field(default=None)
    """Number of epochs to run samples over."""

    epochs_reducer: list[str] | None = Field(default=None)
    """Reducers for aggregating per-sample scores."""

    approval: ApprovalPolicyConfig | None = Field(default=None)
    """Approval policy for tool use."""

    fail_on_error: bool | float | None = Field(default=None)
    """Fail eval when sample errors occur.

    `True` to fail on first sample error (default); `False` to never
    fail on sample errors; Value between 0 and 1 to fail if a proportion
    of total samples fails. Value greater than 1 to fail eval if a count
    of samples fails.
    """

    message_limit: int | None = Field(default=None)
    """Maximum messages to allow per sample."""

    token_limit: int | None = Field(default=None)
    """Maximum tokens usage per sample."""

    time_limit: int | None = Field(default=None)
    """Maximum clock time per sample."""

    working_limit: int | None = Field(default=None)
    """Meximum working time per sample."""

    max_samples: int | None = Field(default=None)
    """Maximum number of samples to run in parallel."""

    max_tasks: int | None = Field(default=None)
    """Maximum number of tasks to run in parallel."""

    max_subprocesses: int | None = Field(default=None)
    """Maximum number of subprocesses to run concurrently."""

    max_sandboxes: int | None = Field(default=None)
    """Maximum number of sandboxes to run concurrently."""

    sandbox_cleanup: bool | None = Field(default=None)
    """Cleanup sandbox environments after task completes."""

    log_samples: bool | None = Field(default=None)
    """Log detailed information on each sample."""

    log_images: bool | None = Field(default=None)
    """Log base64 encoded versions of images."""

    log_buffer: int | None = Field(default=None)
    """Number of samples to buffer before writing log file."""

    score_display: bool | None = Field(default=None)
    """Display scoring metrics realtime."""

    @property
    def max_messages(self) -> int | None:
        """Deprecated max_messages property."""
        return self.message_limit

    @model_validator(mode="before")
    @classmethod
    def convert_max_messages_to_message_limit(
        cls: Type["EvalConfig"], values: dict[str, Any]
    ) -> dict[str, Any]:
        """Migrate deprecated max_messages property."""
        max_messages = values.get("max_messages", None)
        if max_messages:
            values["message_limit"] = max_messages
        return values


class EvalSampleLimit(BaseModel):
    """Limit encontered by sample."""

    type: Literal[
        "context", "time", "working", "message", "token", "operator", "custom"
    ]
    """The type of limit"""

    limit: int
    """The limit value"""


class EvalSample(BaseModel):
    """Sample from evaluation task."""

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

    sandbox: SandboxEnvironmentSpec | None = Field(default=None)
    """Sandbox environment type and optional config file."""

    files: list[str] | None = Field(default=None)
    """Files that go along with the sample (copied to SandboxEnvironment)"""

    setup: str | None = Field(default=None)
    """Setup script to run for sample (run within default SandboxEnvironment)."""

    messages: list[ChatMessage]
    """Chat conversation history for sample."""

    output: ModelOutput
    """Model output from sample."""

    scores: dict[str, Score] | None = Field(default=None)
    """Scores for sample."""

    metadata: dict[str, Any]
    """Additional sample metadata."""

    def metadata_as(self, metadata_cls: Type[MT]) -> MT:
        """Pydantic model interface to metadata.

        Args:
          metadata_cls: Pydantic model type

        Returns:
          BaseModel: Instance of metadata_cls bound to sample metadata.
        """
        return metadata_as(self.metadata, metadata_cls)

    store: dict[str, Any] = Field(default_factory=dict)
    """State at end of sample execution."""

    def store_as(self, model_cls: Type[SMT]) -> SMT:
        """Pydantic model interface to the store.

        Args:
          model_cls: Pydantic model type (must derive from StoreModel)

        Returns:
          StoreModel: Instance of model_cls bound to sample store data.
        """
        return model_cls(store=Store(self.store))

    events: list[Event] = Field(default_factory=list)
    """Events that occurred during sample execution."""

    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """Model token usage for sample."""

    total_time: float | None = Field(default=None)
    """Total time that the sample was running."""

    working_time: float | None = Field(default=None)
    """Time spent working (model generation, sandbox calls, etc.)"""

    uuid: str | None = Field(default=None)
    """Globally unique identifier for sample run (exists for samples created in Inspect >= 0.3.70)"""

    error: EvalError | None = Field(default=None)
    """Error that halted sample."""

    attachments: dict[str, str] = Field(default_factory=dict)
    """Attachments referenced from messages and events.

    Resolve attachments for a sample (replacing attachment://* references with
    attachment content) by passing `resolve_attachments=True` to log reading functions.
    """

    limit: EvalSampleLimit | None = Field(default=None)
    """The limit that halted the sample"""

    # deprecated properties

    @property
    def score(self) -> Score | None:
        """Score for sample (deprecated)."""
        warn_once(
            logger,
            "The 'score' field is deprecated. Access sample scores through 'scores' instead.",
        )

        return list(self.scores.values())[0] if self.scores else None

    @property
    def transcript(self) -> "EvalEvents":
        """Transcript of sample events (deprecated)."""
        warn_once(
            logger,
            "EvalSample 'transcript' field is deprecated. Please use 'events' and 'attachments' fields instead.",
        )
        return EvalEvents(events=self.events, content=self.attachments)

    @model_validator(mode="before")
    @classmethod
    def migrate_deprecated(
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

        if "transcript" in values:
            # promote 'transcript' up to 'events' and 'attachments'
            eval_events = EvalEvents(**values["transcript"])
            values["events"] = eval_events.events
            values["attachments"] = eval_events.content

            # get rid of transcript (property accessor w/ deprecation
            # warning will handle this)
            del values["transcript"]

        return values

    # allow field model_usage
    model_config = ConfigDict(protected_namespaces=())


class EvalEvents(BaseModel):
    events: list[Event] = Field(default_factory=list)
    """List of events."""

    content: dict[str, str] = Field(default_factory=dict)
    """Content references."""


class EvalPlanStep(BaseModel):
    """Solver step."""

    solver: str
    """Name of solver."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Parameters used to instantiate solver."""


class EvalPlan(BaseModel):
    """Plan (solvers) used in evaluation."""

    name: str = Field(default="plan")
    """Plan name."""

    steps: list[EvalPlanStep] = Field(default=[])
    """Steps in plan."""

    finish: EvalPlanStep | None = Field(default=None)
    """Step to always run at the end."""

    config: GenerateConfig = Field(default=GenerateConfig())
    """Generation config."""


class EvalMetric(BaseModel):
    """Metric for evaluation score."""

    name: str
    """Metric name."""

    value: int | float
    """Metric value."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Params specified when creating metric."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional metadata associated with metric."""


class EvalScore(BaseModel):
    """Score for evaluation task."""

    name: str
    """Score name."""

    scorer: str
    """Scorer name."""

    reducer: str | None = Field(default=None)
    """Reducer name."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Parameters specified when creating scorer."""

    metrics: dict[str, EvalMetric] = Field(default_factory=dict)
    """Metrics computed for this scorer."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional scorer metadata."""


class EvalSampleScore(Score):
    """Score and sample_id scored."""

    sample_id: str | int | None = Field(default=None)
    """Sample ID."""


class EvalSampleReductions(BaseModel):
    """Score reductions."""

    scorer: str
    """Name the of scorer"""

    reducer: str | None = Field(default=None)
    """Name the of reducer"""

    samples: list[EvalSampleScore]
    """List of reduced scores"""


class EvalResults(BaseModel):
    """Scoring results from evaluation."""

    total_samples: int = Field(default=0)
    """Total samples in eval (dataset samples * epochs)"""

    completed_samples: int = Field(default=0)
    """Samples completed without error.

    Will be equal to total_samples except when --fail-on-error is enabled.
    """

    @property
    def scorer(self) -> EvalScore | None:
        """Scorer used to compute results (deprecated)."""
        warn_once(
            logger,
            "The 'scorer' field is deprecated. Use 'scores' instead.",
        )
        return self.scores[0] if self.scores else None

    @property
    def metrics(self) -> dict[str, EvalMetric]:
        """Metrics computed (deprecated)."""
        warn_once(
            logger,
            "The 'metrics' field is deprecated. Access metrics through 'scores' instead.",
        )
        return self.scores[0].metrics if self.scores else {}

    scores: list[EvalScore] = Field(default=[])
    """Scorers used to compute results"""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional results metadata."""

    _sample_reductions: list[EvalSampleReductions] | None = PrivateAttr(default=None)
    """Private member to hold sample reductions"""

    @property
    def sample_reductions(self) -> list[EvalSampleReductions] | None:
        """List of per sample scores reduced across epochs"""
        warn_once(
            logger,
            "The 'sample_reductions' field is deprecated. Access reductions through the 'reductions' field on EvalLog instead.",
        )
        return self._sample_reductions

    @sample_reductions.setter
    def sample_reductions(self, value: list[EvalSampleReductions] | None) -> None:
        """Set list of per sample scores reduced across epochs"""
        self._sample_reductions = value

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
            else:
                metrics = None
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
    """Dataset used for evaluation."""

    name: str | None = Field(default=None)
    """Dataset name."""

    location: str | None = Field(default=None)
    """Dataset location (file path or remote URL)"""

    samples: int | None = Field(default=None)
    """Number of samples in the dataset."""

    sample_ids: list[int | str] | None = Field(default=None)
    """IDs of samples in the dataset."""

    shuffled: bool | None = Field(default=None)
    """Was the dataset shuffled after reading."""


class EvalMetricDefinition(BaseModel):
    name: str
    """Metric name"""

    options: dict[str, Any] | None = Field(default=None)


class EvalScorer(BaseModel):
    name: str
    """Scorer name"""

    options: dict[str, Any] | None = Field(default=None)
    """Scorer arguments"""

    metrics: (
        list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
        | dict[str, list[EvalMetricDefinition]]
        | None
    ) = Field(default=None)

    metadata: dict[str, Any] | None = Field(default=None)
    """Scorer metadata"""


class EvalRevision(BaseModel):
    """Git revision for evaluation."""

    type: Literal["git"]
    """Type of revision (currently only "git")"""

    origin: str
    """Revision origin server"""

    commit: str
    """Revision commit."""


class EvalSpec(BaseModel):
    """Eval target and configuration."""

    run_id: str = Field(default_factory=str)
    """Unique run id"""

    created: str
    """Time created."""

    task: str
    """Task name."""

    task_id: str = Field(default_factory=str)
    """Unique task id."""

    task_version: int = Field(default=0)
    """Task version."""

    task_file: str | None = Field(default=None)
    """Task source file."""

    task_attribs: dict[str, Any] = Field(default_factory=dict)
    """Attributes of the @task decorator."""

    task_args: dict[str, Any] = Field(default_factory=dict)
    """Arguments used for invoking the task."""

    solver: str | None = Field(default=None)
    """Solver name."""

    solver_args: dict[str, Any] | None = Field(default=None)
    """Arguments used for invoking the solver."""

    tags: list[str] | None = Field(default=None)
    """Tags associated with evaluation run."""

    dataset: EvalDataset
    """Dataset used for eval."""

    sandbox: SandboxEnvironmentSpec | None = Field(default=None)
    """Sandbox environment type and optional config file."""

    model: str
    """Model used for eval."""

    model_base_url: str | None = Field(default=None)
    """Optional override of model base url"""

    model_args: dict[str, Any] = Field(default_factory=dict)
    """Model specific arguments."""

    config: EvalConfig
    """Configuration values for eval."""

    revision: EvalRevision | None = Field(default=None)
    """Source revision of eval."""

    packages: dict[str, str] = Field(default_factory=dict)
    """Package versions for eval."""

    metadata: dict[str, Any] | None = Field(default=None)
    """Additional eval metadata."""

    scorers: list[EvalScorer] | None = Field(default=None)
    """Scorers and args for this eval"""

    metrics: (
        list[EvalMetricDefinition] | dict[str, list[EvalMetricDefinition]] | None
    ) = Field(default=None)
    """metrics and args for this eval"""

    # allow field model_args
    model_config = ConfigDict(protected_namespaces=())


def eval_error(
    exception: BaseException,
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> EvalError:
    # get text traceback
    traceback_text, truncated = truncate_traceback(exc_type, exc_value, exc_traceback)

    if not truncated:
        with open(os.devnull, "w") as f:
            console = Console(record=True, file=f, legacy_windows=True)
            console.print(rich_traceback(exc_type, exc_value, exc_traceback))
            traceback_ansi = console.export_text(styles=True)
    else:
        traceback_ansi = traceback_text

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
        width=CONSOLE_DISPLAY_WIDTH,
    )
    return rich_tb


def truncate_traceback(
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
    max_length: int = 1048576,  # 1MB
) -> Tuple[str, bool]:
    tb_list = traceback.format_exception(exc_type, exc_value, exc_traceback)

    # Keep the front and back of the traceback
    header = tb_list[0]
    error_msg = tb_list[-1]

    # Join the middle parts (stack frames)
    frames = "".join(tb_list[1:-1])

    # It all fits, use it as is
    full_tb = header + frames + error_msg
    if len(full_tb) <= max_length:
        return full_tb, False

    ellipsis = "\n...\n"

    # Minimum header size
    header_size = min(len(header), 1024)

    # Minimum frames size
    frames_size = min(len(frames), 1024)

    # Remaining space for error message
    error_msg_size = max(0, max_length - header_size - frames_size)

    def truncate_middle(text: str, size: int) -> str:
        if len(text) <= size:
            return text
        half = (size - len(ellipsis)) // 2
        return f"{text[:half]}{ellipsis}{text[-half:]}"

    # Truncate each part as needed
    truncated_header = truncate_middle(header, header_size)
    truncated_frames = truncate_middle(frames, frames_size)
    truncated_error = truncate_middle(error_msg, error_msg_size)

    return truncated_header + truncated_frames + truncated_error, True


class EvalStats(BaseModel):
    """Timing and usage statistics."""

    started_at: str = Field(default_factory=str)
    """Evaluation start time."""

    completed_at: str = Field(default_factory=str)
    """Evaluation completion time."""

    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """Model token usage for evaluation."""

    # allow field model_usage
    model_config = ConfigDict(protected_namespaces=())


class EvalLog(BaseModel):
    """Evaluation log."""

    # WARNING: The order of these fields is important for the log file format.
    # Do not change the order of these fields without incrementing the version number,
    # updating the log file read/write functionality (such as read_eval_log),
    # and updating the tests.
    version: int = Field(default=2)
    """Eval log file format version."""

    status: Literal["started", "success", "cancelled", "error"] = Field(
        default="started"
    )
    """Status of evaluation (did it succeed or fail)."""

    eval: EvalSpec
    """Eval identity and configuration."""

    plan: EvalPlan = Field(default_factory=EvalPlan)
    """Eval plan (solvers and config)"""

    results: EvalResults | None = None
    """Eval results (scores and metrics)."""

    stats: EvalStats = Field(default_factory=EvalStats)
    """Eval stats (runtime, model usage)"""

    error: EvalError | None = Field(default=None)
    """Error that halted eval (if status=="error")"""

    samples: list[EvalSample] | None = Field(default=None)
    """Samples processed by eval."""

    reductions: list[EvalSampleReductions] | None = Field(default=None)
    """Reduced sample values"""

    location: str = Field(default_factory=str, exclude=True)
    """Location that the log file was read from."""

    @model_validator(mode="after")
    def populate_scorer_name_for_samples(self) -> "EvalLog":
        if self.samples and self.results and self.results.scores:
            scorer_name = self.results.scores[0].name
            for sample in self.samples:
                if sample.scores and SCORER_PLACEHOLDER in sample.scores:
                    sample.scores[scorer_name] = sample.scores[SCORER_PLACEHOLDER]
                    del sample.scores[SCORER_PLACEHOLDER]

        return self

    @model_validator(mode="before")
    @classmethod
    def resolve_sample_reductions(
        cls: Type["EvalLog"], values: dict[str, Any]
    ) -> dict[str, Any]:
        has_reductions = "reductions" in values
        has_results = values.get("results", None) is not None
        has_sample_reductions = has_results and (
            "sample_reductions" in values["results"]
        )

        if has_sample_reductions and not has_reductions:
            values["reductions"] = values["results"]["sample_reductions"]
        elif has_reductions and (has_results and not has_sample_reductions):
            values["results"]["sample_reductions"] = values["reductions"]
        return values


def sort_samples(samples: list[EvalSample]) -> None:
    # convert into string zfilled so order is preserved
    samples.sort(
        key=lambda sample: (
            sample.epoch,
            (sample.id if isinstance(sample.id, str) else str(sample.id).zfill(20)),
        )
    )
