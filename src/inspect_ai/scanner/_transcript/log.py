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
    def log(self) -> Column:
        """Location that the log file was read from."""
        return Column("log")

    # ===== Eval Info columns =====

    @property
    def eval_created(self) -> Column:
        """Time eval was created."""
        return Column("eval_created")

    @property
    def eval_tags(self) -> Column:
        """Tags associated with evaluation run."""
        return Column("eval_tags")

    @property
    def eval_metadata(self) -> Column:
        """Additional eval metadata."""
        return Column("eval_metadata")

    # ===== Eval Task columns =====

    @property
    def task_name(self) -> Column:
        """Task name."""
        return Column("task_name")

    @property
    def task_args(self) -> Column:
        """Task arguments."""
        return Column("task_args")

    @property
    def solver(self) -> Column:
        """Solver name."""
        return Column("solver")

    @property
    def solver_args(self) -> Column:
        """Arguments used for invoking the solver."""
        return Column("solver_args")

    # ===== Eval Model columns =====

    @property
    def model(self) -> Column:
        """Model used for eval."""
        return Column("model")

    @property
    def generate_config(self) -> Column:
        """Generate config specified for model instance."""
        return Column("generate_config")

    @property
    def model_roles(self) -> Column:
        """Model roles."""
        return Column("model_roles")

    # ===== Sample columns =====

    @property
    def id(self) -> Column:
        """Unique id for sample."""
        return Column("id")

    @property
    def epoch(self) -> Column:
        """Epoch number for sample."""
        return Column("epoch")

    @property
    def sample_metadata(self) -> Column:
        """Sample metadata."""
        return Column("sample_metadata")

    @property
    def score(self) -> Column:
        """Headline score value."""
        return Column("score")

    @property
    def total_tokens(self) -> Column:
        """Total tokens used for sample."""
        return Column("total_tokens")

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
        """Error that halted the sample."""
        return Column("error")

    @property
    def limit(self) -> Column:
        """Limit that halted the sample."""
        return Column("limit")


# Singleton instance for the DSL
log_metadata = LogMetadata()
