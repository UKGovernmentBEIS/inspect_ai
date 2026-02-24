from logging import getLogger
from types import TracebackType
from typing import Any, Literal, Type, TypedDict

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    model_validator,
)
from shortuuid import uuid

from inspect_ai._util.constants import DESERIALIZING
from inspect_ai._util.dateutil import UtcDatetimeStr
from inspect_ai._util.error import EvalError, exception_message
from inspect_ai._util.hash import base57_id_hash
from inspect_ai._util.json import to_json_str_safe
from inspect_ai._util.logger import warn_once
from inspect_ai._util.metadata import MT, metadata_as
from inspect_ai._util.rich import format_traceback
from inspect_ai.approval._policy import ApprovalPolicyConfig
from inspect_ai.event._timeline import Timeline
from inspect_ai.log._edit import ProvenanceData
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._model_config import ModelConfig
from inspect_ai.scorer import Score
from inspect_ai.util._early_stopping import EarlyStoppingSummary
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec
from inspect_ai.util._store import Store
from inspect_ai.util._store_model import SMT

from ..event._event import Event
from ._util import thin_input, thin_metadata, thin_target, thin_text

logger = getLogger(__name__)

EvalStatus = Literal["started", "success", "cancelled", "error"]
"""Status of an evaluation run."""

SCORER_PLACEHOLDER = "88F74D2C"


class EvalConfigDefaults(TypedDict):
    epochs: int
    epochs_reducer: list[str]
    fail_on_error: bool
    continue_on_fail: bool
    sandbox_cleanup: bool
    log_samples: bool
    log_realtime: bool
    log_images: bool
    score_display: bool


def eval_config_defaults() -> EvalConfigDefaults:
    return {
        "epochs": 1,
        "epochs_reducer": ["mean"],
        "fail_on_error": True,
        "continue_on_fail": False,
        "sandbox_cleanup": True,
        "log_samples": True,
        "log_realtime": True,
        "log_images": True,
        "score_display": True,
    }


class EvalConfig(BaseModel):
    """Configuration used for evaluation."""

    limit: int | tuple[int, int] | None = Field(default=None)
    """Sample limit (number of samples or range of samples)."""

    sample_id: str | int | list[str] | list[int] | list[str | int] | None = Field(
        default=None
    )
    """Evaluate specific sample(s)."""

    sample_shuffle: bool | int | None = Field(default=None)
    """Shuffle order of samples."""

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

    continue_on_fail: bool | None = Field(default=None)
    """Continue eval even if the `fail_on_error` condition is met.

    `True` to continue running and only fail at the end if the `fail_on_error` condition is met.
    `False` to fail eval immediately when the `fail_on_error` condition is met (default).
    """

    retry_on_error: int | None = Field(default=None)
    """Number of times to retry samples if they encounter errors."""

    message_limit: int | None = Field(default=None)
    """Maximum messages to allow per sample."""

    token_limit: int | None = Field(default=None)
    """Maximum tokens usage per sample."""

    time_limit: int | None = Field(default=None)
    """Maximum clock time per sample."""

    working_limit: int | None = Field(default=None)
    """Meximum working time per sample."""

    cost_limit: float | None = Field(default=None)
    """Maximum cost (in dollars) per sample."""

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

    log_realtime: bool | None = Field(default=None)
    """Log events in realtime (enables live viewing of samples in inspect view)."""

    log_images: bool | None = Field(default=None)
    """Log base64 encoded versions of images."""

    log_buffer: int | None = Field(default=None)
    """Number of samples to buffer before writing log file."""

    log_shared: int | None = Field(default=None)
    """Interval (in seconds) for syncing sample events to log directory."""

    score_display: bool | None = Field(default=None)
    """Display scoring metrics realtime."""

    @property
    def max_messages(self) -> int | None:
        """Deprecated max_messages property."""
        return self.message_limit

    @model_validator(mode="before")
    @classmethod
    def convert_max_messages_to_message_limit(
        cls: Type["EvalConfig"], values: Any
    ) -> Any:
        """Migrate deprecated max_messages property."""
        if not isinstance(values, dict):
            return values
        max_messages = values.get("max_messages", None)
        if max_messages:
            values["message_limit"] = max_messages
        return values


class EvalSampleLimit(BaseModel):
    """Limit encountered by sample."""

    type: Literal[
        "context", "time", "working", "message", "token", "cost", "operator", "custom"
    ]
    """The type of limit"""

    limit: float
    """The limit value"""


class EvalSampleSummary(BaseModel):
    """Summary information (including scoring) for a sample."""

    id: int | str
    """Unique id for sample."""

    epoch: int
    """Epoch number for sample."""

    input: str | list[ChatMessage]
    """Sample input (text inputs only)."""

    choices: list[str] | None = Field(default=None)
    """Sample choices."""

    target: str | list[str]
    """Sample target value(s)"""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Sample metadata (only fields < 1k; strings truncated to 1k)."""

    scores: dict[str, Score] | None = Field(default=None)
    """Scores for sample (only metadata fields < 1k; strings truncated to 1k)."""

    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """Model token usage for sample."""

    started_at: UtcDatetimeStr | None = Field(default=None)
    """Time sample started."""

    completed_at: UtcDatetimeStr | None = Field(default=None)
    """Time sample completed."""

    total_time: float | None = Field(default=None)
    """Total time that the sample was running."""

    working_time: float | None = Field(default=None)
    """Time spent working (model generation, sandbox calls, etc.)"""

    uuid: str | None = Field(default=None)
    """Globally unique identifier for sample run (exists for samples created in Inspect >= 0.3.70)"""

    error: str | None = Field(default=None)
    """Error that halted sample."""

    limit: str | None = Field(default=None)
    """Limit that halted the sample"""

    retries: int | None = Field(default=None)
    """Number of retries for the sample."""

    completed: bool = Field(default=False)
    """Is the sample complete."""

    message_count: int | None = Field(default=None)
    """Number of messages in the sample conversation."""

    @model_validator(mode="after")
    def thin_data(self) -> "EvalSampleSummary":
        # thin input
        self.input = thin_input(self.input)

        # thin target
        self.target = thin_target(self.target)

        # thin metadata
        self.metadata = thin_metadata(self.metadata)

        # thin score explanations and metadata
        if self.scores is not None:
            self.scores = {
                key: Score(
                    value=score.value,
                    answer=thin_text(score.answer)
                    if score.answer is not None
                    else None,
                    explanation=thin_text(score.explanation)
                    if score.explanation is not None
                    else None,
                    metadata=thin_metadata(score.metadata)
                    if score.metadata is not None
                    else None,
                )
                for key, score in self.scores.items()
            }
        return self

    # allow field model_usage
    model_config = ConfigDict(protected_namespaces=())


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

    messages: list[ChatMessage] = Field(default_factory=list)
    """Chat conversation history for sample."""

    output: ModelOutput = Field(default_factory=ModelOutput)
    """Model output from sample."""

    scores: dict[str, Score] | None = Field(default=None)
    """Scores for sample."""

    metadata: dict[str, Any] = Field(default_factory=dict)
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

    def store_as(self, model_cls: Type[SMT], instance: str | None = None) -> SMT:
        """Pydantic model interface to the store.

        Args:
          model_cls: Pydantic model type (must derive from StoreModel)
          instance: Optional instances name for store (enables multiple instances
            of a given StoreModel type within a single sample)

        Returns:
          StoreModel: model_cls bound to sample store data.
        """
        # un-namespace names for creation
        data = {
            k.replace(f"{model_cls.__name__}:", "", 1): v for k, v in self.store.items()
        }

        # since we are reading from the log provide a fully detached store
        data["store"] = Store()

        # provide instance if specified
        if instance is not None:
            data["instance"] = instance

        # create the model
        return model_cls.model_validate(data)

    events: list[Event] = Field(default_factory=list)
    """Events that occurred during sample execution."""

    timelines: list[Timeline] | None = Field(default=None)
    """Custom timelines for this sample."""

    model_usage: dict[str, ModelUsage] = Field(default_factory=dict)
    """Model token usage for sample."""

    started_at: UtcDatetimeStr | None = Field(default=None)
    """Time sample started."""

    completed_at: UtcDatetimeStr | None = Field(default=None)
    """Time sample completed."""

    total_time: float | None = Field(default=None)
    """Total time that the sample was running."""

    working_time: float | None = Field(default=None)
    """Time spent working (model generation, sandbox calls, etc.)"""

    uuid: str | None = Field(default=None)
    """Globally unique identifier for sample run (exists for samples created in Inspect >= 0.3.70)"""

    invalidation: ProvenanceData | None = Field(default=None)
    """Provenance data for invalidation."""

    error: EvalError | None = Field(default=None)
    """Error that halted sample."""

    error_retries: list[EvalError] | None = Field(default=None)
    """Errors that were retried for this sample."""

    attachments: dict[str, str] = Field(default_factory=dict)
    """Attachments referenced from messages and events.

    Resolve attachments for a sample (replacing attachment://* references with
    attachment content) by passing `resolve_attachments=True` to log reading functions.
    """

    limit: EvalSampleLimit | None = Field(default=None)
    """The limit that halted the sample"""

    def summary(self) -> EvalSampleSummary:
        """Summary of sample.

        The summary excludes potentially large fields like messages, output,
        events, store, and metadata so that it is always fast to load.

        If there are images, audio, or video in the input, they are
        replaced with a placeholder.

        Returns:
           Summary of sample.
        """
        return EvalSampleSummary(
            id=self.id,
            epoch=self.epoch,
            input=self.input,
            choices=self.choices,
            target=self.target,
            metadata=self.metadata,
            scores=self.scores,
            model_usage=self.model_usage,
            started_at=self.started_at,
            completed_at=self.completed_at,
            total_time=self.total_time,
            working_time=self.working_time,
            uuid=self.uuid,
            error=self.error.message if self.error is not None else None,
            limit=f"{self.limit.type}" if self.limit is not None else None,
            retries=len(self.error_retries) if self.error_retries is not None else None,
            completed=True,
            message_count=len(self.messages),
        )

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
    def migrate_deprecated(cls: Type["EvalSample"], values: Any) -> Any:
        if not isinstance(values, dict):
            return values
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

        return migrate_values(values)

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

    params_passed: dict[str, Any] = Field(default_factory=dict)
    """Parameters explicitly passed to the eval plan."""

    @model_validator(mode="before")
    @classmethod
    def read_params(cls: Type["EvalPlanStep"], values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        if "params_passed" not in values:
            values["params_passed"] = values.get("params", {})
        return values


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

    scored_samples: int | None = Field(default=None)
    """Number of samples scored by this scorer."""

    unscored_samples: int | None = Field(default=None)
    """Number of samples not scored by this scorer."""

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

    Will be equal to total_samples except when --fail-on-error is enabled
    or when there is early stopping.
    """

    early_stopping: EarlyStoppingSummary | None = Field(default=None)
    """Early stopping summary (if an early stopping manager was present)."""

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
    def convert_scorer_to_scorers(cls: Type["EvalResults"], values: Any) -> Any:
        if not isinstance(values, dict):
            return values
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

    sample_ids: list[str] | list[int] | list[str | int] | None = Field(default=None)
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

    dirty: bool | None = Field(default=None)
    """Working tree has uncommitted changes or untracked files."""


class EvalSpec(BaseModel):
    """Eval target and configuration."""

    eval_set_id: str | None = Field(default=None)
    """Globally unique id for eval set (if any)."""

    eval_id: str = Field(default_factory=str)
    """Globally unique id for eval."""

    run_id: str = Field(default_factory=str)
    """Unique run id"""

    created: UtcDatetimeStr
    """Time created."""

    task: str
    """Task name."""

    task_id: str = Field(default_factory=str)
    """Unique task id."""

    task_version: int | str = Field(default=0)
    """Task version."""

    task_file: str | None = Field(default=None)
    """Task source file."""

    task_display_name: str | None = Field(default=None)
    """Task display name."""

    task_registry_name: str | None = Field(default=None)
    """Task registry name."""

    task_attribs: dict[str, Any] = Field(default_factory=dict)
    """Attributes of the @task decorator."""

    task_args: dict[str, Any] = Field(default_factory=dict)
    """Arguments used for invoking the task (including defaults)."""

    task_args_passed: dict[str, Any] = Field(default_factory=dict)
    """Arguments explicitly passed by caller for invoking the task."""

    solver: str | None = Field(default=None)
    """Solver name."""

    solver_args: dict[str, Any] | None = Field(default=None)
    """Arguments used for invoking the solver."""

    solver_args_passed: dict[str, Any] | None = Field(default=None)
    """Arguments explicitly passed by caller for invoking the solver."""

    tags: list[str] | None = Field(default=None)
    """Tags associated with evaluation run."""

    dataset: EvalDataset
    """Dataset used for eval."""

    sandbox: SandboxEnvironmentSpec | None = Field(default=None)
    """Sandbox environment type and optional config file."""

    model: str
    """Model used for eval."""

    model_generate_config: GenerateConfig = Field(default_factory=GenerateConfig)
    """Generate config specified for model instance."""

    model_base_url: str | None = Field(default=None)
    """Optional override of model base url"""

    model_args: dict[str, Any] = Field(default_factory=dict)
    """Model specific arguments."""

    model_roles: dict[str, ModelConfig] | None = Field(default=None)
    """Model roles."""

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
        list[EvalMetricDefinition | dict[str, list[EvalMetricDefinition]]]
        | dict[str, list[EvalMetricDefinition]]
        | None
    ) = Field(default=None)
    """metrics and args for this eval"""

    # allow field model_args
    model_config = ConfigDict(protected_namespaces=())

    def model_post_init(self, __context: Any) -> None:
        # check if deserializing
        is_deserializing = isinstance(__context, dict) and __context.get(
            DESERIALIZING, False
        )

        # Generate eval_id if needed
        if self.eval_id == "":
            if is_deserializing:
                # we want the eval_id to be stable across reads of the eval log so we compose it
                # as a hash that matches the size/apperance of shortuuid-based uuids
                self.eval_id = base57_id_hash(self.run_id + self.task_id + self.created)
            else:
                self.eval_id = uuid()

    @model_validator(mode="before")
    @classmethod
    def read_sandbox_spec(cls: Type["EvalSpec"], values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        return migrate_values(values)


def migrate_values(values: dict[str, Any]) -> dict[str, Any]:
    if "sandbox" in values:
        sandbox = values.get("sandbox")
        if isinstance(sandbox, list):
            values["sandbox"] = SandboxEnvironmentSpec(
                type=sandbox[0], config=sandbox[1]
            )
    if "task_args_passed" not in values:
        values["task_args_passed"] = values.get("task_args", {})
    if "solver_args_passed" not in values:
        values["solver_args_passed"] = values.get("solver_args", {})
    return values


def eval_error(
    exception: BaseException,
    exc_type: Type[Any],
    exc_value: BaseException,
    exc_traceback: TracebackType | None,
) -> EvalError:
    traceback_text, traceback_ansi = format_traceback(
        exc_type, exc_value, exc_traceback
    )

    return EvalError(
        message=exception_message(exception),
        traceback=traceback_text,
        traceback_ansi=traceback_ansi,
    )


class EvalStats(BaseModel):
    """Timing and usage statistics."""

    started_at: UtcDatetimeStr | Literal[""] = Field(default_factory=str)
    """Evaluation start time. Empty string if eval interrupted before start time set."""

    completed_at: UtcDatetimeStr | Literal[""] = Field(default_factory=str)
    """Evaluation completion time. Empty string if eval interrupted before completion."""

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

    status: EvalStatus = Field(default="started")
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

    invalidated: bool = Field(default=False)
    """Whether any samples were invalidated."""

    samples: list[EvalSample] | None = Field(default=None)
    """Samples processed by eval."""

    reductions: list[EvalSampleReductions] | None = Field(default=None)
    """Reduced sample values"""

    location: str = Field(default_factory=str, exclude=True)
    """Location that the log file was read from."""

    etag: str | None = Field(default=None, exclude=True)
    """ETag from S3 for conditional writes."""

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
    def resolve_sample_reductions(cls: Type["EvalLog"], values: Any) -> Any:
        if not isinstance(values, dict):
            return values
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

    def __repr__(self) -> str:
        return to_json_str_safe(
            self.model_dump(
                exclude={"samples", "reductions"},
                exclude_none=True,
                fallback=lambda _: None,
            )
        )


def sort_samples(samples: list[EvalSample]) -> None:
    # convert into string zfilled so order is preserved
    samples.sort(
        key=lambda sample: (
            sample.epoch,
            (sample.id if isinstance(sample.id, str) else str(sample.id).zfill(20)),
        )
    )
