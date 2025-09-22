"""Score metrics recomputation functionality."""

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
    )
    from inspect_ai._eval.task.results import eval_results
    from inspect_ai._util.registry import (
        REGISTRY_PARAMS,
        RegistryInfo,
        registry_create,
        set_registry_info,
    )
    from inspect_ai.scorer import Scorer

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

    scorers: list[Scorer] = []

    # Extract scorer info from existing results and create scorers with real metrics
    if log.results and log.results.scores:
        for score_result in log.results.scores:
            # Create a minimal scorer function
            def scorer_func() -> None:
                pass

            scorer_func.__name__ = score_result.name

            # Try to get real metric functions from registry by name
            metrics_list = []
            if score_result.metrics:
                for metric_name in score_result.metrics.keys():
                    try:
                        metric = registry_create("metric", metric_name)
                        metrics_list.append(metric)
                    except Exception:
                        # Create a proper metric function as fallback
                        def fallback(scores: list[SampleScore]) -> float:
                            return 0.0

                        fallback.__name__ = metric_name
                        metrics_list.append(fallback)

            registry_info = RegistryInfo(
                type="scorer",
                name=score_result.name,
                metadata={"metrics": metrics_list},
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
        metrics=metrics,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions
