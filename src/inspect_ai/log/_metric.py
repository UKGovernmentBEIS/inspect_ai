"""Score metrics recomputation functionality."""

from inspect_ai._eval.task.results import eval_results
from inspect_ai.scorer._metric import SampleScore

from ._log import EvalLog


def recompute_metrics(log: EvalLog) -> None:
    """Recompute aggregate metrics after score edits.

    Args:
        log: The evaluation log to recompute metrics for

    Raises:
        ValueError: If log is missing required data for recomputation
    """
    # Import here to avoid circular imports
    from inspect_ai._eval.score import (
        metrics_from_log_header,
        reducers_from_log_header,
        resolve_scorers,
    )

    if log.samples is None:
        raise ValueError("Log contains no samples")

    # Extract scores from all samples
    scores = []
    for sample in log.samples:
        if sample.scores:
            sample_scores = {}
            for score_name, score in sample.scores.items():
                sample_scores[score_name] = SampleScore(
                    score=score, sample_id=sample.id, sample_metadata=sample.metadata
                )
            scores.append(sample_scores)

    reducers = reducers_from_log_header(log)
    metrics = metrics_from_log_header(log)
    scorers = resolve_scorers(log)

    # Recompute
    results, reductions = eval_results(
        samples=len(log.samples),
        scores=scores,
        reducers=reducers,
        scorers=scorers,
        metrics=metrics,
        early_stopping=log.results.early_stopping if log.results else None,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
