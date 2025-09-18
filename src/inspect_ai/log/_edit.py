"""Score editing functionality."""

from inspect_ai.scorer._metric import SampleScore, ScoreEdit

from ._log import EvalLog
from ._transcript import ScoreEditEvent, SpanBeginEvent, SpanEndEvent


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

    sample = next((sample for sample in log.samples if sample.id == sample_id), None)

    if sample is None:
        raise ValueError(f"Sample with id {sample_id} not found")

    if sample.scores is None:
        raise ValueError(f"Sample {sample_id} has no scores")

    if score_name not in sample.scores:
        raise ValueError(f"Score '{score_name}' not found in sample {sample_id}")

    score = sample.scores[score_name]
    score.history.append(edit)

    score_edit_event = ScoreEditEvent(score_name=score_name, edit=edit)

    # Build a map of span_id -> (begin_idx, end_idx) for scorers spans
    span_indexes = {}
    for i, event in enumerate(sample.events):
        if (
            isinstance(event, SpanBeginEvent)
            and event.type == "scorers"
            and event.name == "scorers"
            and event.id
        ):
            span_indexes[event.id] = [i, None]
        elif isinstance(event, SpanEndEvent) and event.id in span_indexes:
            span_indexes[event.id][1] = i

    # Find the last scorers span
    span_id = None
    end_index = None
    if span_indexes:
        last_span_id = max(span_indexes.keys(), key=lambda k: span_indexes[k][1] or -1)
        if span_indexes[last_span_id][1] is not None:
            span_id = last_span_id
            end_index = span_indexes[last_span_id][1]

    score_edit_event.span_id = span_id

    if end_index is not None:
        # Insert before the span end to keep it structurally inside the span
        sample.events.insert(end_index, score_edit_event)
    else:
        sample.events.append(score_edit_event)

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
    from inspect_ai._eval.score import reducers_from_log_header
    from inspect_ai._eval.task.results import eval_results

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
                        from inspect_ai.scorer._metric import Score

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

    # Create scorers with metrics from registry to ensure proper computation
    from inspect_ai._util.registry import (
        REGISTRY_PARAMS,
        RegistryInfo,
        registry_create,
        set_registry_info,
    )
    from inspect_ai.scorer import Scorer

    scorers: list[Scorer] = []

    # Extract scorer info from existing results and create scorers with real metrics
    if log.results and log.results.scores:
        for score_result in log.results.scores:
            # Create a minimal scorer function
            def scorer_func() -> None:
                pass

            scorer_func.__name__ = score_result.name

            # Try to get real metric functions from registry by name
            metrics = []
            if score_result.metrics:
                for metric_name in score_result.metrics.keys():
                    try:
                        metric = registry_create("metric", metric_name)
                        metrics.append(metric)
                    except Exception:
                        # Create a proper metric function as fallback
                        def fallback(scores: list[SampleScore]) -> float:
                            return 0.0

                        fallback.__name__ = metric_name
                        metrics.append(fallback)

            registry_info = RegistryInfo(
                type="scorer", name=score_result.name, metadata={"metrics": metrics}
            )
            set_registry_info(scorer_func, registry_info)
            setattr(scorer_func, REGISTRY_PARAMS, {})
            scorers.append(scorer_func)  # type: ignore[arg-type]

    # Recompute
    results, reductions = eval_results(
        samples=len(log.samples),
        scores=scores,
        reducers=reducers,
        scorers=scorers,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
