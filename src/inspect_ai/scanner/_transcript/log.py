"""Typed metadata interface for Inspect log transcripts.

This module provides a typed subclass of Metadata that offers IDE support
and documentation for standard Inspect log fields.
"""

from .metadata import Column, Metadata


class LogMetadata(Metadata):
    """Typed metadata interface for Inspect log transcripts.

    Provides typed properties for standard Inspect log columns while
    preserving the ability to access custom fields through the base
    Metadata class methods.

    Usage:
        from inspect_ai.scanner import log_metadata as m

        # Typed access to standard fields
        filter = m.model == "gpt-4"
        filter = (m.task_name == "math") & (m.epochs > 1)

        # Dynamic access to custom fields still works
        filter = m["custom_field"] > 100
    """

    # ===== ID columns =====

    @property
    def sample_id(self) -> Column:
        """Unique id for sample."""
        return Column("sample_id")

    @property
    def eval_id(self) -> Column:
        """Globally unique id for eval."""
        return Column("eval_id")

    @property
    def eval_set_id(self) -> Column:
        """Globally unique id for eval set (if any)."""
        return Column("eval_set_id")

    @property
    def run_id(self) -> Column:
        """Unique run id"""
        return Column("run_id")

    @property
    def task_id(self) -> Column:
        """Unique task id."""
        return Column("task_id")

    # ===== Eval Log Path =====

    @property
    def log(self) -> Column:
        """Location that the log file was read from."""
        return Column("log")

    # ===== Eval Info columns =====

    @property
    def created(self) -> Column:
        """Time created."""
        return Column("created")

    @property
    def tags(self) -> Column:
        """Tags associated with evaluation run."""
        return Column("tags")

    @property
    def git_origin(self) -> Column:
        """Revision origin server"""
        return Column("git_origin")

    @property
    def git_commit(self) -> Column:
        """Revision commit."""
        return Column("git_commit")

    @property
    def packages(self) -> Column:
        """Package versions for eval."""
        return Column("packages")

    @property
    def metadata(self) -> Column:
        """Additional eval metadata."""
        return Column("metadata")

    # ===== Eval Task columns =====

    @property
    def task_name(self) -> Column:
        """Task name."""
        return Column("task_name")

    @property
    def task_display_name(self) -> Column:
        """Task display name."""
        return Column("task_display_name")

    @property
    def task_version(self) -> Column:
        """Task version."""
        return Column("task_version")

    @property
    def task_file(self) -> Column:
        """Task source file."""
        return Column("task_file")

    @property
    def task_attribs(self) -> Column:
        """Attributes of the @task decorator."""
        return Column("task_attribs")

    @property
    def solver(self) -> Column:
        """Solver name."""
        return Column("solver")

    @property
    def solver_args(self) -> Column:
        """Arguments used for invoking the solver."""
        return Column("solver_args")

    @property
    def sandbox_type(self) -> Column:
        """Sandbox environment type."""
        return Column("sandbox_type")

    @property
    def sandbox_config(self) -> Column:
        """Sandbox environment configuration."""
        return Column("sandbox_config")

    # ===== Eval Model columns =====

    @property
    def model(self) -> Column:
        """Model used for eval."""
        return Column("model")

    @property
    def model_base_url(self) -> Column:
        """Optional override of model base url"""
        return Column("model_base_url")

    @property
    def model_args(self) -> Column:
        """Model specific arguments."""
        return Column("model_args")

    @property
    def model_generate_config(self) -> Column:
        """Generate config specified for model instance."""
        return Column("model_generate_config")

    @property
    def model_roles(self) -> Column:
        """Model roles."""
        return Column("model_roles")

    # ===== Eval Dataset columns =====

    @property
    def dataset_name(self) -> Column:
        """Dataset name."""
        return Column("dataset_name")

    @property
    def dataset_location(self) -> Column:
        """Dataset location (file path or remote URL)"""
        return Column("dataset_location")

    @property
    def dataset_samples(self) -> Column:
        """Number of samples in the dataset."""
        return Column("dataset_samples")

    @property
    def dataset_sample_ids(self) -> Column:
        """IDs of samples in the dataset."""
        return Column("dataset_sample_ids")

    @property
    def dataset_shuffled(self) -> Column:
        """Was the dataset shuffled after reading."""
        return Column("dataset_shuffled")

    # ===== Eval Configuration columns =====

    @property
    def epochs(self) -> Column:
        """Number of epochs to run samples over."""
        return Column("epochs")

    @property
    def epochs_reducer(self) -> Column:
        """Reducers for aggregating per-sample scores."""
        return Column("epochs_reducer")

    @property
    def approval(self) -> Column:
        """Approval policy for tool use."""
        return Column("approval")

    @property
    def message_limit(self) -> Column:
        """Maximum messages to allow per sample."""
        return Column("message_limit")

    @property
    def token_limit(self) -> Column:
        """Maximum tokens usage per sample."""
        return Column("token_limit")

    @property
    def time_limit(self) -> Column:
        """Maximum clock time per sample."""
        return Column("time_limit")

    @property
    def working_limit(self) -> Column:
        """Maximum working time per sample."""
        return Column("working_limit")

    # ===== Eval Results columns =====

    @property
    def status(self) -> Column:
        """Status of evaluation (did it succeed or fail)."""
        return Column("status")

    @property
    def error_message(self) -> Column:
        """Error message if evaluation failed."""
        return Column("error_message")

    @property
    def error_traceback(self) -> Column:
        """Error traceback if evaluation failed."""
        return Column("error_traceback")

    @property
    def total_samples(self) -> Column:
        """Total samples in eval (dataset samples * epochs)"""
        return Column("total_samples")

    @property
    def completed_samples(self) -> Column:
        """Samples completed without error."""
        return Column("completed_samples")

    @property
    def score_headline_name(self) -> Column:
        """Name of the headline scorer."""
        return Column("score_headline_name")

    @property
    def score_headline_metric(self) -> Column:
        """Headline metric name."""
        return Column("score_headline_metric")

    @property
    def score_headline_value(self) -> Column:
        """Headline metric value."""
        return Column("score_headline_value")

    @property
    def score_headline_stderr(self) -> Column:
        """Headline metric standard error."""
        return Column("score_headline_stderr")

    # ===== Sample Summary columns =====

    @property
    def id(self) -> Column:
        """Unique id for sample."""
        return Column("id")

    @property
    def epoch(self) -> Column:
        """Epoch number for sample."""
        return Column("epoch")

    @property
    def input(self) -> Column:
        """Sample input (text inputs only)."""
        return Column("input")

    @property
    def target(self) -> Column:
        """Sample target value(s)"""
        return Column("target")

    @property
    def model_usage(self) -> Column:
        """Model token usage for sample."""
        return Column("model_usage")

    @property
    def total_time(self) -> Column:
        """Total time that the sample was running."""
        return Column("total_time")

    @property
    def working_time(self) -> Column:
        """Time spent working (model generation, sandbox calls, etc.)."""
        return Column("working_time")

    @property
    def error(self) -> Column:
        """Error that halted sample."""
        return Column("error")

    @property
    def limit(self) -> Column:
        """Limit that halted the sample"""
        return Column("limit")

    @property
    def retries(self) -> Column:
        """Number of retries for the sample."""
        return Column("retries")

    # Note: Dynamic columns like task_arg_*, metadata_*, score_* are accessed
    # through the base class __getattr__ and __getitem__ methods


# Singleton instance for the DSL
log_metadata = LogMetadata()
