"""Score metrics recomputation functionality."""

from inspect_ai._eval.task.results import eval_results
from inspect_ai.scorer._metric import SampleScore, Score

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

    # Build scores from sample.scores for all samples
    scores = []
    for sample in log.samples:
        if sample.scores is not None:
            sample_score_dict = {}
            for score_name, score in sample.scores.items():
                # Handle dict-valued scores by breaking them into separate entries
                if isinstance(score.value, dict):
                    for key, value in score.value.items():
                        scalar_score = Score(
                            value=value,
                            answer=score.answer,
                            explanation=score.explanation,
                            metadata=score.metadata,
                        )
                        sample_score_dict[key] = SampleScore(
                            score=scalar_score,
                            sample_id=sample.id,
                            sample_metadata=sample.metadata,
                        )
                else:
                    sample_score_dict[score_name] = SampleScore(
                        score=score,
                        sample_id=sample.id,
                        sample_metadata=sample.metadata,
                    )
            scores.append(sample_score_dict)

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
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
