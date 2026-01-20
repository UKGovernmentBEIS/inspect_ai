"""Taxonomy definitions for EvalLog field classification.

This module defines the sensitivity and informativeness levels for classifying
EvalLog fields, enabling secure log publication by clearly identifying which
fields contain sensitive data and which are critical for analysis.
"""

from enum import Enum

from pydantic import BaseModel


class Sensitivity(str, Enum):
    """Sensitivity level for a field.

    Indicates how sensitive the data in a field is from a privacy/security
    perspective.
    """

    LOW = "low"
    """Non-sensitive data (versions, IDs, timestamps, configuration options)."""

    MEDIUM = "medium"
    """Potentially identifying data (file paths, hostnames, project structure)."""

    HIGH = "high"
    """Sensitive data (credentials, user inputs, model outputs, personal data)."""


class Informativeness(str, Enum):
    """Informativeness level for a field.

    Indicates how valuable a field is for understanding and analyzing
    evaluation results.
    """

    LOW = "low"
    """Limited analytical value (internal IDs, format versions)."""

    MEDIUM = "medium"
    """Useful for some analyses (configuration, timing, resource usage)."""

    HIGH = "high"
    """Critical for understanding results (scores, model outputs, errors)."""


class FieldClassification(BaseModel, frozen=True):
    """Classification of a field's sensitivity and informativeness.

    Used to categorize EvalLog fields to support decisions about which fields
    to include when publishing or sharing evaluation logs.
    """

    sensitivity: Sensitivity
    """How sensitive the data in this field is."""

    informativeness: Informativeness
    """How useful this field is for analysis."""

    rationale: str = ""
    """Explanation for why this classification was assigned."""

    may_contain_user_data: bool = False
    """Whether this field may contain user-provided data."""

    may_contain_model_output: bool = False
    """Whether this field may contain model-generated content."""

    may_contain_credentials: bool = False
    """Whether this field may contain API keys, tokens, or other credentials."""


# Default classification for unknown fields - conservative defaults
DEFAULT_FIELD_CLASSIFICATION = FieldClassification(
    sensitivity=Sensitivity.HIGH,
    informativeness=Informativeness.LOW,
    rationale="Unknown field - defaulting to high sensitivity for safety",
)

# =============================================================================
# DEFAULT_TAXONOMY: Comprehensive field classifications for EvalLog
# =============================================================================
# Field paths use type-qualified dot notation:
# - EvalLog.field - direct field on EvalLog
# - EvalSpec.field - field on nested EvalSpec type
# - EvalSample.messages[] - list elements
# - *.metadata.* - dynamic dict keys (wildcard matching)
# =============================================================================

DEFAULT_TAXONOMY: dict[str, FieldClassification] = {
    # =========================================================================
    # EvalLog top-level fields
    # =========================================================================
    "EvalLog.version": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Log format version number, purely technical",
    ),
    "EvalLog.status": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Evaluation completion status, critical for understanding results",
    ),
    "EvalLog.eval": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Contains EvalSpec with mixed sensitivity fields",
    ),
    "EvalLog.plan": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Solver plan with config, may contain custom params",
    ),
    "EvalLog.results": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Aggregate scores and metrics, critical for analysis",
    ),
    "EvalLog.stats": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Timing and usage statistics",
    ),
    "EvalLog.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Error details may expose internal paths and state",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalLog.invalidated": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Boolean flag indicating sample invalidation",
    ),
    "EvalLog.samples": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Contains full conversation data and user inputs",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "EvalLog.reductions": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Reduced sample scores, aggregate data",
    ),
    # =========================================================================
    # EvalSpec fields
    # =========================================================================
    "EvalSpec.eval_set_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Internal identifier for eval set",
    ),
    "EvalSpec.eval_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Unique evaluation identifier",
    ),
    "EvalSpec.run_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Unique run identifier",
    ),
    "EvalSpec.created": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Timestamp of evaluation creation",
    ),
    "EvalSpec.task": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Task name, needed for analysis",
    ),
    "EvalSpec.task_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Unique task identifier",
    ),
    "EvalSpec.task_version": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Task version for reproducibility",
    ),
    "EvalSpec.task_file": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="File path may expose project structure",
    ),
    "EvalSpec.task_display_name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Human-readable task name",
    ),
    "EvalSpec.task_registry_name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Registry identifier for task",
    ),
    "EvalSpec.task_attribs": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Task decorator attributes, may contain custom config",
    ),
    "EvalSpec.task_args": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Task invocation arguments, may contain custom values",
    ),
    "EvalSpec.task_args_passed": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Explicitly passed task arguments",
    ),
    "EvalSpec.solver": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Solver name, important for analysis",
    ),
    "EvalSpec.solver_args": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Solver arguments, may contain custom config",
    ),
    "EvalSpec.solver_args_passed": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Explicitly passed solver arguments",
    ),
    "EvalSpec.tags": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="User-defined tags, may contain identifying info",
        may_contain_user_data=True,
    ),
    "EvalSpec.dataset": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Dataset info including location which may be sensitive",
    ),
    "EvalSpec.sandbox": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Sandbox environment spec, may include config paths",
    ),
    "EvalSpec.model": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Model name, critical for analysis",
    ),
    "EvalSpec.model_generate_config": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Generation parameters like temperature, top_p",
    ),
    "EvalSpec.model_base_url": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="API endpoint, usually hostname but could contain tokens",
    ),
    "EvalSpec.model_args": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="Model args filtered by model_args_for_log(), may have custom config",
    ),
    "EvalSpec.model_roles": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Model role configurations",
    ),
    "EvalSpec.config": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Evaluation configuration options",
    ),
    "EvalSpec.revision": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Git revision info, useful for reproducibility",
    ),
    "EvalSpec.packages": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Package versions for reproducibility",
    ),
    "EvalSpec.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Arbitrary user-provided metadata",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalSpec.scorers": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Scorer configurations, important for understanding results",
    ),
    "EvalSpec.metrics": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Metric configurations",
    ),
    # =========================================================================
    # EvalConfig fields
    # =========================================================================
    "EvalConfig.limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Sample limit configuration",
    ),
    "EvalConfig.sample_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Specific sample IDs to evaluate",
    ),
    "EvalConfig.sample_shuffle": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Shuffle configuration",
    ),
    "EvalConfig.epochs": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Number of epochs",
    ),
    "EvalConfig.epochs_reducer": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Reducer for aggregating scores",
    ),
    "EvalConfig.approval": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="Approval policy config, may contain custom settings",
    ),
    "EvalConfig.fail_on_error": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Error handling configuration",
    ),
    "EvalConfig.continue_on_fail": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Error handling configuration",
    ),
    "EvalConfig.retry_on_error": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Retry configuration",
    ),
    "EvalConfig.message_limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Message limit per sample",
    ),
    "EvalConfig.token_limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Token limit per sample",
    ),
    "EvalConfig.time_limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Time limit per sample",
    ),
    "EvalConfig.working_limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Working time limit per sample",
    ),
    "EvalConfig.max_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Parallelism configuration",
    ),
    "EvalConfig.max_tasks": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Parallelism configuration",
    ),
    "EvalConfig.max_subprocesses": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Parallelism configuration",
    ),
    "EvalConfig.max_sandboxes": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Parallelism configuration",
    ),
    "EvalConfig.sandbox_cleanup": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Sandbox cleanup configuration",
    ),
    "EvalConfig.log_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Logging configuration",
    ),
    "EvalConfig.log_realtime": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Logging configuration",
    ),
    "EvalConfig.log_images": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Logging configuration",
    ),
    "EvalConfig.log_buffer": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Logging configuration",
    ),
    "EvalConfig.log_shared": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Logging configuration",
    ),
    "EvalConfig.score_display": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Display configuration",
    ),
    # =========================================================================
    # EvalSample fields
    # =========================================================================
    "EvalSample.id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Sample identifier, needed for analysis",
    ),
    "EvalSample.epoch": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Epoch number for the sample",
    ),
    "EvalSample.input": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Task input, may contain sensitive user data",
        may_contain_user_data=True,
    ),
    "EvalSample.choices": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Multiple choice options from dataset",
    ),
    "EvalSample.target": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Expected answer from dataset",
    ),
    "EvalSample.sandbox": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="Sandbox environment spec",
    ),
    "EvalSample.files": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="File paths for sample",
    ),
    "EvalSample.setup": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Setup script content",
    ),
    "EvalSample.messages": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Full conversation history with model",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "EvalSample.output": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Model output for the sample",
        may_contain_model_output=True,
    ),
    "EvalSample.scores": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Evaluation scores, critical for analysis",
    ),
    "EvalSample.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Arbitrary sample metadata",
        may_contain_user_data=True,
    ),
    "EvalSample.store": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Runtime state, may contain arbitrary data",
        may_contain_user_data=True,
    ),
    "EvalSample.events": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Detailed event trace with all interactions",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "EvalSample.model_usage": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Token usage statistics",
    ),
    "EvalSample.started_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Sample start timestamp",
    ),
    "EvalSample.completed_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Sample completion timestamp",
    ),
    "EvalSample.total_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Total sample runtime",
    ),
    "EvalSample.working_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Active working time",
    ),
    "EvalSample.uuid": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Unique sample identifier",
    ),
    "EvalSample.invalidation": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Invalidation provenance data",
    ),
    "EvalSample.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Error details may expose internal state",
        may_contain_user_data=True,
        may_contain_credentials=True,  # Often errors occur because of invalid credentials
    ),
    "EvalSample.error_retries": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Retry error history",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalSample.attachments": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Attachment content, may include sensitive data",
        may_contain_user_data=True,
    ),
    "EvalSample.limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Sample limit that was reached",
    ),
    # =========================================================================
    # EvalSampleSummary fields (subset of EvalSample, same classifications)
    # =========================================================================
    "EvalSampleSummary.id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Sample identifier",
    ),
    "EvalSampleSummary.epoch": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Epoch number",
    ),
    "EvalSampleSummary.input": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Task input (truncated)",
        may_contain_user_data=True,
    ),
    "EvalSampleSummary.choices": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Multiple choice options",
        may_contain_user_data=True,
    ),
    "EvalSampleSummary.target": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Expected answer (truncated)",
        may_contain_user_data=True,
    ),
    "EvalSampleSummary.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Sample metadata (thinned)",
        may_contain_user_data=True,
    ),
    "EvalSampleSummary.scores": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Evaluation scores",
    ),
    "EvalSampleSummary.model_usage": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Token usage",
    ),
    "EvalSampleSummary.started_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Start timestamp",
    ),
    "EvalSampleSummary.completed_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Completion timestamp",
    ),
    "EvalSampleSummary.total_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Total runtime",
    ),
    "EvalSampleSummary.working_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Working time",
    ),
    "EvalSampleSummary.uuid": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Unique identifier",
    ),
    "EvalSampleSummary.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Error message",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalSampleSummary.limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Limit type string",
    ),
    "EvalSampleSummary.retries": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Number of retries",
    ),
    "EvalSampleSummary.completed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Completion status",
    ),
    "EvalSampleSummary.message_count": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Number of messages",
    ),
    # =========================================================================
    # EvalPlan fields
    # =========================================================================
    "EvalPlan.name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Plan name",
    ),
    "EvalPlan.steps": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Solver steps with params",
    ),
    "EvalPlan.finish": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Final step configuration",
    ),
    "EvalPlan.config": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Generation configuration",
    ),
    # =========================================================================
    # EvalPlanStep fields
    # =========================================================================
    "EvalPlanStep.solver": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Solver name",
    ),
    "EvalPlanStep.params": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Solver parameters, may contain custom values",
    ),
    "EvalPlanStep.params_passed": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Explicitly passed parameters",
    ),
    # =========================================================================
    # EvalResults fields
    # =========================================================================
    "EvalResults.total_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Total sample count",
    ),
    "EvalResults.completed_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Completed sample count",
    ),
    "EvalResults.early_stopping": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Early stopping summary",
    ),
    "EvalResults.scores": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Evaluation scores list",
    ),
    "EvalResults.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Results metadata, arbitrary user data",
        may_contain_user_data=True,
    ),
    # =========================================================================
    # EvalScore fields
    # =========================================================================
    "EvalScore.name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Score name",
    ),
    "EvalScore.scorer": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Scorer name",
    ),
    "EvalScore.reducer": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Reducer name",
    ),
    "EvalScore.scored_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Number of scored samples",
    ),
    "EvalScore.unscored_samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Number of unscored samples",
    ),
    "EvalScore.params": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Scorer parameters",
    ),
    "EvalScore.metrics": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Computed metrics",
    ),
    "EvalScore.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Scorer metadata, may contain user data",
        may_contain_user_data=True,
    ),
    # =========================================================================
    # EvalMetric fields
    # =========================================================================
    "EvalMetric.name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Metric name",
    ),
    "EvalMetric.value": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Metric value, critical for analysis",
    ),
    "EvalMetric.params": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Metric parameters",
    ),
    "EvalMetric.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Metric metadata",
        may_contain_user_data=True,
    ),
    # =========================================================================
    # EvalStats fields
    # =========================================================================
    "EvalStats.started_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Evaluation start time",
    ),
    "EvalStats.completed_at": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Evaluation completion time",
    ),
    "EvalStats.model_usage": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Aggregate model token usage",
    ),
    # =========================================================================
    # EvalDataset fields
    # =========================================================================
    "EvalDataset.name": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Dataset name",
    ),
    "EvalDataset.location": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Dataset path or URL, may expose project structure",
    ),
    "EvalDataset.samples": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Number of samples in dataset",
    ),
    "EvalDataset.sample_ids": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="List of sample IDs",
    ),
    "EvalDataset.shuffled": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Whether dataset was shuffled",
    ),
    # =========================================================================
    # EvalRevision fields
    # =========================================================================
    "EvalRevision.type": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Revision type",
    ),
    "EvalRevision.origin": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="Git origin, may expose internal URLs",
    ),
    "EvalRevision.commit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Git commit hash",
    ),
    "EvalRevision.dirty": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Whether working tree was dirty",
    ),
    # =========================================================================
    # EvalError fields
    # =========================================================================
    "EvalError.message": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Error message may contain sensitive paths or data",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalError.traceback": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Stack trace exposes internal code paths and state",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "EvalError.traceback_ansi": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.LOW,
        rationale="ANSI-formatted traceback",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    # =========================================================================
    # EvalSampleLimit fields
    # =========================================================================
    "EvalSampleLimit.type": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Type of limit encountered",
    ),
    "EvalSampleLimit.limit": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Limit value",
    ),
    # =========================================================================
    # Score fields
    # =========================================================================
    "Score.value": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Score value, critical for analysis",
    ),
    "Score.answer": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Model answer being scored",
        may_contain_model_output=True,
    ),
    "Score.explanation": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.HIGH,
        rationale="Score explanation, may contain model output references",
        may_contain_model_output=True,
    ),
    "Score.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Score metadata, arbitrary data",
        may_contain_user_data=True,
    ),
    # =========================================================================
    # ChatMessage fields
    # =========================================================================
    "ChatMessage.id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Message identifier",
    ),
    "ChatMessage.role": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Message role (system/user/assistant/tool)",
    ),
    "ChatMessage.content": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Message content, contains conversation data",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "ChatMessage.source": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Message source indicator",
    ),
    "ChatMessage.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Message metadata",
        may_contain_user_data=True,
    ),
    "ChatMessage.tool_calls": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Tool calls with arguments and results",
        may_contain_model_output=True,
    ),
    "ChatMessage.tool_call_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Tool call identifier",
    ),
    "ChatMessage.function": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Function name for tool messages",
    ),
    "ChatMessage.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Tool error information",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    # =========================================================================
    # ModelOutput fields
    # =========================================================================
    "ModelOutput.model": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Model name",
    ),
    "ModelOutput.choices": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Model response choices",
        may_contain_model_output=True,
    ),
    "ModelOutput.usage": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Token usage statistics",
    ),
    "ModelOutput.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Model error information",
        may_contain_credentials=True,
    ),
    "ModelOutput.stop_reason": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Why generation stopped",
    ),
    # =========================================================================
    # Event base fields (shared by all events)
    # =========================================================================
    "BaseEvent.uuid": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event identifier",
    ),
    "BaseEvent.span_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Span identifier",
    ),
    "BaseEvent.timestamp": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event timestamp",
    ),
    "BaseEvent.working_start": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Working time when event occurred",
    ),
    "BaseEvent.metadata": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Event metadata, arbitrary data",
        may_contain_user_data=True,
    ),
    "BaseEvent.pending": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event pending status",
    ),
    # =========================================================================
    # ModelEvent fields
    # =========================================================================
    "ModelEvent.event": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event type identifier",
    ),
    "ModelEvent.model": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Model name",
    ),
    "ModelEvent.role": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Model role",
    ),
    "ModelEvent.input": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Input messages to model",
        may_contain_user_data=True,
    ),
    "ModelEvent.tools": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Available tool definitions",
    ),
    "ModelEvent.tool_choice": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Tool choice directive",
    ),
    "ModelEvent.config": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Generation config for this call",
    ),
    "ModelEvent.output": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Model output",
        may_contain_model_output=True,
    ),
    "ModelEvent.retries": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Number of API retries",
    ),
    "ModelEvent.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Error during model call",
        may_contain_credentials=True,
    ),
    "ModelEvent.cache": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Cache read/write indicator",
    ),
    "ModelEvent.call": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Raw API call data",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "ModelEvent.completed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Completion timestamp",
    ),
    "ModelEvent.working_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Working time for call",
    ),
    # =========================================================================
    # ToolEvent fields
    # =========================================================================
    "ToolEvent.event": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event type identifier",
    ),
    "ToolEvent.type": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Tool call type",
    ),
    "ToolEvent.id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Tool call identifier",
    ),
    "ToolEvent.function": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.HIGH,
        rationale="Function name called",
    ),
    "ToolEvent.arguments": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Tool call arguments",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "ToolEvent.view": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom view of tool input",
        may_contain_user_data=True,
    ),
    "ToolEvent.result": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Tool call result",
        may_contain_user_data=True,
    ),
    "ToolEvent.truncated": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Truncation indicator",
    ),
    "ToolEvent.error": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Tool error information",
        may_contain_user_data=True,
        may_contain_credentials=True,
    ),
    "ToolEvent.events": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Nested events (deprecated)",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
    "ToolEvent.completed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Completion timestamp",
    ),
    "ToolEvent.working_time": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Working time for tool call",
    ),
    "ToolEvent.agent": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Agent name if handoff",
    ),
    "ToolEvent.failed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Whether tool call failed",
    ),
    "ToolEvent.message_id": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Associated message ID",
    ),
    # =========================================================================
    # SandboxEvent fields
    # =========================================================================
    "SandboxEvent.event": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Event type identifier",
    ),
    "SandboxEvent.action": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Sandbox action type",
    ),
    "SandboxEvent.cmd": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Command executed in sandbox",
        may_contain_user_data=True,
    ),
    "SandboxEvent.options": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.LOW,
        rationale="Execution options",
    ),
    "SandboxEvent.file": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="File path for read/write operations",
    ),
    "SandboxEvent.input": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Input to command or file write",
        may_contain_user_data=True,
    ),
    "SandboxEvent.result": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Exit code for exec",
    ),
    "SandboxEvent.output": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.HIGH,
        rationale="Command or file read output",
        may_contain_user_data=True,
    ),
    "SandboxEvent.completed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Completion timestamp",
    ),
    # =========================================================================
    # ModelUsage fields
    # =========================================================================
    "ModelUsage.input_tokens": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Input token count",
    ),
    "ModelUsage.output_tokens": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Output token count",
    ),
    "ModelUsage.total_tokens": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Total token count",
    ),
    "ModelUsage.input_tokens_cache_read": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Cached input tokens",
    ),
    "ModelUsage.input_tokens_cache_write": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.LOW,
        rationale="Tokens written to cache",
    ),
    "ModelUsage.reasoning_tokens": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Reasoning token count",
    ),
    # =========================================================================
    # GenerateConfig fields
    # =========================================================================
    "GenerateConfig.max_tokens": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Max tokens setting",
    ),
    "GenerateConfig.temperature": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Temperature setting",
    ),
    "GenerateConfig.top_p": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Top-p setting",
    ),
    "GenerateConfig.top_k": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Top-k setting",
    ),
    "GenerateConfig.stop_seqs": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Stop sequences",
    ),
    "GenerateConfig.seed": FieldClassification(
        sensitivity=Sensitivity.LOW,
        informativeness=Informativeness.MEDIUM,
        rationale="Random seed for reproducibility",
    ),
}

# =============================================================================
# Wildcard patterns for dynamic fields (metadata, store, args dicts)
# =============================================================================
# These patterns match fields that can have arbitrary keys
# =============================================================================

DYNAMIC_FIELD_PATTERNS: dict[str, FieldClassification] = {
    # All metadata fields are high sensitivity - they can contain arbitrary user data
    "*.metadata.*": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Arbitrary user-provided metadata values",
        may_contain_user_data=True,
    ),
    # Store fields can contain arbitrary runtime state
    "*.store.*": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Arbitrary runtime state values",
        may_contain_user_data=True,
    ),
    # Args fields may contain custom parameters
    "EvalSpec.task_args.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom task argument values",
    ),
    "EvalSpec.task_args_passed.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom passed task argument values",
    ),
    "EvalSpec.solver_args.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom solver argument values",
    ),
    "EvalSpec.solver_args_passed.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom passed solver argument values",
    ),
    "EvalSpec.model_args.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom model argument values",
    ),
    # Params fields may contain custom configuration
    "*.params.*": FieldClassification(
        sensitivity=Sensitivity.MEDIUM,
        informativeness=Informativeness.MEDIUM,
        rationale="Custom parameter values",
    ),
    # Attachments can contain arbitrary content
    "*.attachments.*": FieldClassification(
        sensitivity=Sensitivity.HIGH,
        informativeness=Informativeness.MEDIUM,
        rationale="Attachment content, may contain sensitive data",
        may_contain_user_data=True,
        may_contain_model_output=True,
    ),
}
