"""Score editing functionality."""

from inspect_ai.scorer._metric import SampleScore, ScoreEdit

from ._log import EvalLog
from ._transcript import ScoreEditEvent


def edit_score(
    log: EvalLog,
    sample_id: int | str,
    score_name: str,
    edit: ScoreEdit,
    should_recompute_metrics: bool = True,
) -> None:
    """Edit a score in-place.

    Args:
        log: The evaluation log containing the samples and scores
        sample_id: ID of the sample containing the score to edit
        score_name: Name of the score to edit
        edit: The edit to apply to the score
        should_recompute_metrics: Whether to recompute aggregate metrics after editing

    Raises:
        ValueError: If the sample or score cannot be found
    """
    if log.samples is None:
        raise ValueError("Log contains no samples")

    # Find the sample
    sample = None
    for s in log.samples:
        if s.id == sample_id:
            sample = s
            break

    if sample is None:
        raise ValueError(f"Sample with id {sample_id} not found")

    if sample.scores is None:
        raise ValueError(f"Sample {sample_id} has no scores")

    if score_name not in sample.scores:
        raise ValueError(f"Score '{score_name}' not found in sample {sample_id}")

    # Get the score and add edit to its history
    score = sample.scores[score_name]
    score.history.append(edit)

    # Create and append the event to sample's events
    score_edit_event = ScoreEditEvent(score_name=score_name, edit=edit)

    # Add event to sample events (avoiding transcript()._event() as discussed)
    sample.events.append(score_edit_event)

    # Recompute metrics if requested
    if should_recompute_metrics:
        recompute_metrics(log)


def recompute_metrics(log: EvalLog) -> None:
    """Recompute aggregate metrics after score edits.

    Args:
        log: The evaluation log to recompute metrics for

    Raises:
        ValueError: If log is missing required data for recomputation
    """
    # Import here to avoid circular imports
    from inspect_ai._eval.score import metrics_from_log_header, reducers_from_log_header
    from inspect_ai._eval.task.results import eval_results

    if log.samples is None:
        raise ValueError("Log contains no samples")

    # Build scores from sample.scores for all samples
    scores = []
    for sample in log.samples:
        if sample.scores is not None:
            sample_score_dict = {}
            for score_name, score in sample.scores.items():
                sample_score_dict[score_name] = SampleScore(
                    score=score, sample_id=sample.id, sample_metadata=sample.metadata
                )
            scores.append(sample_score_dict)

    # Get reducers and metrics from the log
    reducers = reducers_from_log_header(log)
    metrics = metrics_from_log_header(log)

    # Call eval_results to recompute
    results, reductions = eval_results(
        samples=len(log.samples),
        scores=scores,
        reducers=reducers,
        scorers=None,  # Use None as discussed
        metrics=metrics,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
