import math

import anyio

from inspect_ai import Task, eval
from inspect_ai._eval.task.results import eval_results
from inspect_ai._util.content import ContentText
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.model._model import ModelName
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import Score, Target, mean, model_graded_qa, scorer
from inspect_ai.scorer._metric import SampleScore
from inspect_ai.scorer._multi import multi_scorer
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


def test_multi_scorer_can_be_used_as_task_scorer() -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        scorer=multi_scorer(
            [_make_fixed_scorer(1.0), _make_fixed_scorer(0.0)],
            reducer="mean",
        ),
    )

    log = eval(task, model="mockllm/model", display="none")[0]

    assert log.results
    assert log.results.scores is not None
    assert len(log.results.scores) == 1
    assert log.results.scores[0].name == "multi_scorer"
    assert log.results.scores[0].metrics["mean"].value == 0.5


def test_multi_scorer_can_wrap_model_graded_scorers() -> None:
    grader_models = [
        get_model(
            "mockllm/grader1",
            custom_outputs=[
                ModelOutput.from_content(
                    "mockllm/grader1", [ContentText(text="GRADE: C")]
                )
            ],
        ),
        get_model(
            "mockllm/grader2",
            custom_outputs=[
                ModelOutput.from_content(
                    "mockllm/grader2", [ContentText(text="GRADE: C")]
                )
            ],
        ),
    ]
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        scorer=multi_scorer(
            scorers=[model_graded_qa(model=model) for model in grader_models],
            reducer="mode",
        ),
    )

    log = eval(task, model="mockllm/model", display="none")[0]

    assert log.results
    assert log.results.scores is not None
    assert len(log.results.scores) == 1
    assert log.results.scores[0].name == "multi_scorer"
    assert log.results.scores[0].metrics["accuracy"].value == 1.0


def test_multi_scorer_all_none_returns_unscored() -> None:
    # Regression: when every sub-scorer returns None (which the Scorer
    # protocol permits), multi_scorer filtered to an empty list and the
    # reducer crashed with IndexError on scores[0]. It should instead
    # yield the unscored NaN sentinel.
    async def none_scorer(state: TaskState, target: Target) -> None:
        return None

    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=0,
        epoch=0,
        input=[],
        messages=[],
    )
    combined = multi_scorer([none_scorer, none_scorer], reducer="mean")
    result = anyio.run(combined, state, Target(""))
    assert isinstance(result, Score)
    assert isinstance(result.value, float) and math.isnan(result.value)
