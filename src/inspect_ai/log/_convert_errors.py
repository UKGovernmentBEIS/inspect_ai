"""Convert errored samples to incorrect scores."""

from typing import Any, TYPE_CHECKING

from inspect_ai.scorer._metric import INCORRECT, Score, Value

from ._log import EvalLog

if TYPE_CHECKING:
    from ._metric import recompute_metrics as _recompute_metrics


def convert_errored_samples_to_incorrect(
    log: EvalLog,
    *,
    scorer_name: str | None = None,
    score_value: Value = INCORRECT,
    explanation: str | None = None,
    preserve_error: bool = True,
    recompute: bool = True,
) -> EvalLog:
    """Convert samples with errors to incorrect scores.

    This function modifies samples that have an error set by:
    1. Creating an incorrect score for the sample
    2. Optionally preserving the original error in metadata
    3. Removing the error field from the sample
    4. Recomputing metrics to reflect the changes

    The log with converted samples is returned but not persisted to storage.
    Use `write_eval_log()` to save the modified log.

    Args:
        log: The evaluation log to process
        scorer_name: Scorer name to use for incorrect scores.
            If None, uses first scorer from log.results.scores
        score_value: Score value to assign (default: INCORRECT = "I").
            Can be customized for different scorer types (e.g., 0.0, False)
        explanation: Optional explanation text. If None, uses
            "Sample failed: {error.message}"
        preserve_error: If True, stores original error in score.metadata
        recompute: If True, calls recompute_metrics() after conversion

    Returns:
        EvalLog with errored samples converted to incorrect scores

    Raises:
        ValueError: If log has no samples or no scorers defined

    Example:
        ```python
        from inspect_ai.log import read_eval_log, write_eval_log
        from inspect_ai.log import convert_errored_samples_to_incorrect

        # Read log
        log = read_eval_log("eval.log")

        # Convert errors to incorrect scores
        log = convert_errored_samples_to_incorrect(log)

        # Write back
        write_eval_log(log, "eval.log")
        ```
    """
    # Validate input
    if log.samples is None or len(log.samples) == 0:
        raise ValueError("Log contains no samples")

    if log.results is None or not log.results.scores:
        raise ValueError(
            "Cannot convert errors: log has no scorers defined. "
            "This may indicate the evaluation did not complete scoring."
        )

    # Resolve scorer name
    if scorer_name is None:
        # Use the first scorer from results
        scorer_name = log.results.scores[0].scorer

    # Process each sample
    converted_count = 0
    for sample in log.samples:
        # Only process samples with errors
        if sample.error is None:
            continue

        # Build explanation
        if explanation is None:
            explanation_text = f"Sample failed: {sample.error.message}"
        else:
            explanation_text = explanation

        # Build metadata
        metadata: dict[str, Any] = {"conversion_source": "error"}
        if preserve_error:
            metadata["original_error"] = {
                "message": sample.error.message,
                "traceback": sample.error.traceback,
            }

        # Create incorrect score
        incorrect_score = Score(
            value=score_value,
            answer=None,
            explanation=explanation_text,
            metadata=metadata,
        )

        # Initialize scores dict if needed, then set score
        if sample.scores is None:
            sample.scores = {}
        sample.scores[scorer_name] = incorrect_score

        # Remove error from sample
        sample.error = None

        converted_count += 1

    # Recompute metrics if requested
    if recompute and converted_count > 0:
        from ._metric import recompute_metrics as _recompute_metrics

        _recompute_metrics(log)

    return log
