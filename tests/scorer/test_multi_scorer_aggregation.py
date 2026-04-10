from inspect_ai._eval.task.results import eval_results
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import TaskState


def _make_fixed_scorer(value: float):
    """Create a scorer that always returns a fixed value."""

    @scorer(metrics=[mean()])
    def fixed_score():
        async def score(state: TaskState, target: Target):
            return Score(value=value, answer=state.output.completion)

        return score

    return fixed_score()


def _resolve_names(scorers: list) -> list[str]:
    """Resolve unique scorer names the same way task_run() does."""
    names: list[str] = []
    for s in scorers:
        names.append(unique_scorer_name(s, names))
    return names


def test_aggregate_scores_distinguish_scorers() -> None:
    """Each scorer instance must produce a distinct aggregate mean."""
    s1 = _make_fixed_scorer(1.0)
    s2 = _make_fixed_scorer(5.0)
    s3 = _make_fixed_scorer(9.0)

    scorer_names = _resolve_names([s1, s2, s3])

    # Build sample scores as they would appear after scoring
    sample_scores: list[dict[str, SampleScore]] = [
        {
            name: SampleScore(
                score=Score(value=val, answer="x"),
                sample_id="1",
                scorer="fixed_score",
            )
            for name, val in zip(scorer_names, [1.0, 5.0, 9.0])
        }
    ]

    results, _ = eval_results(
        samples=1,
        scores=sample_scores,
        reducers=None,
        scorers=[s1, s2, s3],
        metrics=None,
        scorer_names=scorer_names,
    )

    assert results.scores is not None
    assert len(results.scores) == 3

    means = [s.metrics["mean"].value for s in results.scores]
    assert means[0] == 1.0, f"Expected 1.0, got {means[0]}"
    assert means[1] == 5.0, f"Expected 5.0, got {means[1]}"
    assert means[2] == 9.0, f"Expected 9.0, got {means[2]}"


def test_reducer_consistent_across_scorers() -> None:
    """The reducer must remain consistent across multiple scorer instances."""
    from inspect_ai.scorer._reducer import mean_score

    s1 = _make_fixed_scorer(1.0)
    s2 = _make_fixed_scorer(2.0)

    scorer_names = _resolve_names([s1, s2])

    # Two epochs worth of scores
    sample_scores: list[dict[str, SampleScore]] = [
        {
            name: SampleScore(
                score=Score(value=float(i + 1), answer="x"),
                sample_id="1",
                scorer="fixed_score",
            )
            for name in scorer_names
        }
        for i in range(2)
    ]

    results, _ = eval_results(
        samples=2,
        scores=sample_scores,
        reducers=mean_score(),
        scorers=[s1, s2],
        metrics=None,
        scorer_names=scorer_names,
    )

    assert results.scores is not None
    assert len(results.scores) == 2

    # Both scorers should produce valid results without reducer corruption
    for score_result in results.scores:
        assert "mean" in score_result.metrics
        assert score_result.metrics["mean"].value is not None
