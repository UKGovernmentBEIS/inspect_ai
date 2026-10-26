"""Score metrics recomputation functionality."""

from inspect_ai._eval.task.results import eval_results
from inspect_ai.scorer._metric import SampleScore

from ._log import EvalLog
from ._shards._live import check_shards_merged


def recompute_metrics(log: EvalLog) -> None:
    """Recompute aggregate metrics after score edits.

    A merged log (`merge_eval_log_shards()`) is refused while its
    `<name>.shards/` directory still exists, since recomputing would replace
    the reductions its shards recorded; a log with no `location` is not
    checked.

    Args:
        log: The evaluation log to recompute metrics for

    Raises:
        ValueError: If log is missing required data for recomputation
        ShardSetError: The log is a merged log whose shards still exist.
    """
    check_shards_merged(log, "recomputing metrics for")
    recompute_checked_metrics(log)


def recompute_checked_metrics(log: EvalLog) -> None:
    """`recompute_metrics` for a caller that has already run its shard check."""
    # Import here to avoid circular imports
    from inspect_ai._eval.score import (
        metrics_from_log_header,
        reducers_from_log_header,
        resolve_scorers_info,
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
    scorers_info = resolve_scorers_info(log)

    # Recompute
    results, reductions = eval_results(
        samples=len(log.samples),
        scores=scores,
        reducers=reducers,
        scorers=scorers_info,
        metrics=metrics,
        early_stopping=log.results.early_stopping if log.results else None,
        metadata=log.results.metadata if log.results else None,
        # eval-set completeness contract (see EvalResults.logged_samples):
        # recomputing metrics must not make a drained log read complete
        logged_samples=log.results.logged_samples if log.results else None,
        # the count isn't persisted but the per-sample error state is, so
        # recompute it rather than letting eval_results() fall back to
        # len(scores) (which is scorer-order dependent)
        completed_samples=sum(1 for s in log.samples if s.error is None),
        headline_metric=log.eval.headline_metric,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
