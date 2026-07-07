import math
from typing import Any, Callable, cast

import pytest
from pydantic import BaseModel

from inspect_ai import Task, eval, score
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    Metric,
    Score,
    Scorer,
    Value,
    accuracy,
    includes,
    match,
    mean,
    metric,
    scorer,
    std,
    value_to_float,
    var,
)
from inspect_ai.scorer._metric import (
    MetricDeprecated,
    MetricProtocol,
    SampleScore,
    metric_create,
)
from inspect_ai.scorer._metrics import aggregate, grouped
from inspect_ai.scorer._metrics.std import stderr
from inspect_ai.scorer._target import Target
from inspect_ai.solver._task_state import TaskState

# declare some metrics using the various forms supported (function,
# function returning Metric, class deriving from Metric) as well
# as using implicit and explicit names


@metric
def accuracy1(correct: str = "C") -> Metric:
    def metric(scores: list[SampleScore]) -> int | float:
        return 1

    return metric


@metric(name="accuracy2")
def acc_fn(correct: str = "C") -> Metric:
    def metric(scores: list[SampleScore]) -> int | float:
        return 1

    return metric


@metric
class Accuracy3(MetricDeprecated):
    def __init__(self, correct: str = "C") -> None:
        self.correct = correct

    def __call__(self, scores: list[Score]) -> int | float:
        return 1


@metric(name="accuracy4")
class AccuracyNamedCls(MetricProtocol):
    def __init__(self, correct: str = "C") -> None:
        self.correct = correct

    def __call__(self, scores: list[SampleScore]) -> int | float:
        return 1


@metric
def list_metric() -> Metric:
    def metric(scores: list[SampleScore]) -> Value:
        return [1, 2, 3]

    return metric


@metric
def deprecated_metric() -> Metric:
    def metric(scores: list[Score]) -> Value:
        return len(scores)

    return metric


@metric
def dict_metric() -> Metric:
    def metric(scores: list[SampleScore]) -> Value:
        return {"one": 1, "two": 2, "three": 3}

    return metric


def test_metric_registry() -> None:
    registry_assert(accuracy1, "accuracy1")
    registry_assert(acc_fn, "accuracy2")
    registry_assert(Accuracy3, "Accuracy3")
    registry_assert(AccuracyNamedCls, "accuracy4")


def test_metric_call() -> None:
    registry_assert(accuracy1(), "accuracy1")
    registry_assert(acc_fn(), "accuracy2")
    registry_assert(Accuracy3(), "Accuracy3")
    registry_assert(AccuracyNamedCls(), "accuracy4")


def test_metric_create() -> None:
    metric_create_assert("accuracy1", correct="C")
    metric_create_assert("accuracy1", correct="C")
    metric_create_assert("Accuracy3", correct="C")
    metric_create_assert("accuracy4", correct="C")


def test_inspect_metrics() -> None:
    registry_assert(accuracy, f"{PKG_NAME}/accuracy")
    registry_assert(accuracy(), f"{PKG_NAME}/accuracy")


def test_deprecated_metric() -> None:
    def check_log(log):
        assert log.results and (
            list(log.results.scores[0].metrics.keys()) == ["deprecated_metric"]
        )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=match(),
        metrics=[deprecated_metric()],
    )

    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


def test_list_metric() -> None:
    def check_log(log):
        assert log.results and (
            list(log.results.scores[0].metrics.keys())
            == ["list_metric-1", "list_metric-2", "list_metric-3"]
        )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=match(),
        metrics=[list_metric()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


def test_dict_metric() -> None:
    def check_log(log):
        assert log.results and (
            list(log.results.scores[0].metrics.keys()) == ["one", "two", "three"]
        )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=match(),
        metrics=[dict_metric()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


def test_alternative_metrics() -> None:
    # check that we get the alternative metrics
    def check_log(log):
        assert log.results and (
            list(log.results.scores[0].metrics.keys())
            == [
                "accuracy",
                "accuracy1",
                "Accuracy3",
                "std",
            ]
        )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=match(),
        metrics=[accuracy(), accuracy1(), Accuracy3(), std()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)

    # eval log w/ different scorer (that still uses accuracy)
    log = score(log, scorers=[includes()])
    check_log(log)


@metric
def complex_metric() -> Metric:
    def metric(scores: list[SampleScore]) -> int | float:
        total = 0.0
        for complex_score in scores:
            if isinstance(complex_score.score.value, dict):
                total = (
                    total
                    + cast(int, complex_score.score.value["one"])
                    + cast(int, complex_score.score.value["two"])
                    + cast(int, complex_score.score.value["three"])
                )
        return total

    return metric


@scorer(
    metrics=[
        {"one": [mean()], "two": [mean(), std()], "three": [mean(), std()]},
        complex_metric(),
    ]
)
def complex_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"one": 1, "two": 2, "three": 3})

    return score


def test_complex_metrics() -> None:
    def check_log(log):
        assert len(log.results.scores) == 4
        assert log.results.scores[0].name == "complex_scorer"
        assert log.results.scores[0].metrics["complex_metric"].value == 6

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=complex_scorer(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


@scorer(
    metrics=[
        {"*": [mean()]},
    ]
)
def wildcard_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"one": 1, "two": 2, "three": 3})

    return score


def test_wildcard() -> None:
    def check_log(log):
        assert len(log.results.scores) == 4
        assert log.results.scores[1].name == "one"
        assert log.results.scores[1].metrics["mean"].value == 1

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=wildcard_scorer(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


def registry_assert(metric: Metric | Callable[..., Metric], name: str) -> None:
    info = registry_info(metric)
    assert info.name == name


def metric_create_assert(name: str, **kwargs: Any) -> None:
    metric = metric_create(name, **kwargs)
    assert metric([]) == 1


def test_accuracy_handles_empty_scores() -> None:
    # An empty score list must not raise; mirror the std()/var() convention of
    # returning 0 for insufficient data instead of a ZeroDivisionError.
    assert accuracy()([]) == 0.0


@metric
def nested_dict_metric(correct: str = "C") -> Metric:
    def metric(scores: list[SampleScore]) -> Value:
        return {"key1": 1.0, "key2": 2.0}

    return metric


@scorer(
    metrics=[
        {"*": [nested_dict_metric()]},
    ]
)
def nested_dict_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"one": 1, "two": 2, "three": 3})

    return score


def test_nested_dict_metrics() -> None:
    def check_log(log):
        assert len(log.results.scores) == 4
        assert log.results.scores[1].name == "one"
        assert len(log.results.scores[1].metrics.values()) == 2
        m = log.results.scores[1].metrics["nested_dict_metric_key1"]
        assert m.name == "key1"
        assert m.group == "nested_dict_metric"

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=nested_dict_scorer(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


@metric
def nested_list_metric(correct: str = "C") -> Metric:
    def metric(scores: list[SampleScore]) -> Value:
        return [1.0, 2.0]

    return metric


@scorer(
    metrics=[
        {"*": [nested_list_metric()]},
    ]
)
def nested_list_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"one": 1, "two": 2, "three": 3})

    return score


def test_nested_list_metrics() -> None:
    def check_log(log):
        assert len(log.results.scores) == 4
        assert log.results.scores[1].name == "one"
        assert len(log.results.scores[1].metrics.values()) == 2
        m = log.results.scores[1].metrics["nested_list_metric_0"]
        assert m.name == "0"
        assert m.group == "nested_list_metric"

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=nested_list_scorer(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)


def test_variance():
    metric = var()
    result = metric(scores=[SampleScore(score=Score(value=i)) for i in range(10)])
    assert round(result, 3) == 9.167
    assert metric([SampleScore(score=Score(value=4))]) == 0.0


def test_stderr():
    metric = stderr()
    se = metric([SampleScore(score=Score(value=i)) for i in range(10)])
    assert round(se, 3) == 0.957


def test_mean_numeric():
    metric = mean()
    result = metric([SampleScore(score=Score(value=i)) for i in range(10)])
    assert result == 4.5


def test_mean_label_vocabulary():
    # Regression: mean() previously used Score.as_float(), which calls
    # float("C") and raises ValueError on the framework's own CORRECT /
    # INCORRECT / PARTIAL / NOANSWER labels -- even though accuracy() (and
    # std/var/stderr) map them via value_to_float(). A scorer emitting these
    # labels with [accuracy(), mean()] attached would crash at metric time.
    # mean() now shares the same value-to-float vocabulary as its siblings.
    metric = mean()
    result = metric(
        [
            SampleScore(score=Score(value="C")),
            SampleScore(score=Score(value="I")),
            SampleScore(score=Score(value="P")),
            SampleScore(score=Score(value="N")),
        ]
    )
    # C=1.0, I=0, P=0.5, N=0 -> mean 0.375
    assert result == 0.375


def test_mean_custom_to_float():
    metric = mean(to_float=value_to_float(correct="win"))
    result = metric(
        [
            SampleScore(score=Score(value="win")),
            SampleScore(score=Score(value="win")),
        ]
    )
    assert result == 1.0


def test_clustered_stderr():
    metric = stderr(cluster="my_cluster")
    se = metric(
        [
            SampleScore(score=Score(value=i), sample_metadata={"my_cluster": i % 4})
            for i in range(20)
        ]
    )
    assert round(se, 3) == 0.645


def test_clustered_stderr_single_cluster():
    # Regression: with a single cluster, cluster_count / (cluster_count - 1)
    # divides by zero. Should return 0.0 (mirroring the non-clustered n < 2
    # guard) rather than NaN/inf.
    metric = stderr(cluster="my_cluster")
    se = metric(
        [
            SampleScore(score=Score(value=v), sample_metadata={"my_cluster": "only"})
            for v in [1.0, 0.0, 1.0]
        ]
    )
    assert se == 0.0


def test_grouped_mean_single():
    metric = grouped(mean(), group_key="group")
    result = metric(
        [
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=4), sample_metadata={"group": "A"}),
        ]
    )
    assert result["A"] == 2.0
    assert result["all"] == 2.0


def test_grouped_mean_multiple():
    metric = grouped(mean(), group_key="group")
    result = metric(
        [
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=4), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=2), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=6), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=10), sample_metadata={"group": "B"}),
        ]
    )
    assert result["A"] == 2.0
    assert result["B"] == 6.0
    assert result["all"] == 4.0


def test_grouped_mean_error():
    metric = grouped(mean(), group_key="group")
    with pytest.raises(ValueError):
        metric(
            [
                SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
                SampleScore(score=Score(value=1)),
                SampleScore(score=Score(value=4), sample_metadata={"group": "A"}),
                SampleScore(score=Score(value=2), sample_metadata={"group": "B"}),
                SampleScore(score=Score(value=6), sample_metadata={"group": "B"}),
                SampleScore(score=Score(value=10), sample_metadata={"group": "B"}),
            ]
        )


def test_grouped_accuracy():
    metric = grouped(accuracy(), group_key="group")
    result = metric(
        [
            SampleScore(score=Score(value="C"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "B"}),
        ]
    )

    assert result["A"] == 0.25
    assert result["B"] == 0.75
    assert result["all"] == 0.5


def test_grouped_accuracy_groups():
    metric = grouped(accuracy(), group_key="group", all="groups")
    result = metric(
        [
            SampleScore(score=Score(value="I"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "C"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "C"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
        ]
    )

    assert result["A"] == 0.0
    assert result["B"] == 0.5
    assert result["C"] == 0.5
    assert result["D"] == 1.0
    assert result["all"] == 0.5


def test_no_all():
    metric = grouped(accuracy(), group_key="group", all=False)
    result = metric(
        [
            SampleScore(score=Score(value="I"), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value="I"), sample_metadata={"group": "C"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "C"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
            SampleScore(score=Score(value="C"), sample_metadata={"group": "D"}),
        ]
    )

    assert all(key in result for key in ["A", "B", "C", "D"])
    assert "all" not in result


def test_grouped_all_label_collision():
    # Regression: when a group's name collides with all_label (default "all"),
    # the per-group metric was silently overwritten by the aggregate. Now this
    # should raise so the user knows to pick a different all_label.
    metric = grouped(accuracy(), group_key="category")
    with pytest.raises(ValueError, match="all_label"):
        metric(
            [
                SampleScore(
                    score=Score(value="C"), sample_metadata={"category": "easy"}
                ),
                SampleScore(
                    score=Score(value="I"), sample_metadata={"category": "all"}
                ),
            ]
        )


def test_custom_all():
    metric = grouped(mean(), group_key="group", all_label="custom_all")
    result = metric(
        [
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=4), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=2), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=6), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=10), sample_metadata={"group": "B"}),
        ]
    )
    assert result["A"] == 2.0
    assert result["B"] == 6.0
    assert result["custom_all"] == 4.0


def test_custom_name_template():
    metric = grouped(
        mean(),
        group_key="group",
        name_template="mean_{group_name}",
        all_label="mean_all",
    )
    result = metric(
        [
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=1), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=4), sample_metadata={"group": "A"}),
            SampleScore(score=Score(value=2), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=6), sample_metadata={"group": "B"}),
            SampleScore(score=Score(value=10), sample_metadata={"group": "B"}),
        ]
    )
    assert result["mean_A"] == 2.0
    assert result["mean_B"] == 6.0
    assert result["mean_all"] == 4.0


class Metadata(BaseModel, frozen=True):
    name: str
    age: int


def test_sample_score_metadata_as():
    score = SampleScore(
        score=Score(value=1), sample_metadata=Metadata(name="jim", age=42).model_dump()
    )
    metadata = score.sample_metadata_as(Metadata)
    assert metadata is not None
    assert metadata.name == "jim"
    assert metadata.age == 42


def _scorer_info_for_dict_metrics() -> Any:
    from inspect_ai._eval.task.results import ScorerInfo

    return ScorerInfo(name="test_scorer", metrics={"one": [mean()], "two": [mean()]})


def test_dict_metric_unscored_samples_mixed():
    # NaN-at-root samples should be skipped and counted as unscored;
    # metrics computed only over the dict-shaped subset.
    from inspect_ai._eval.task.results import scorers_from_metric_dict

    sample_scores = [
        SampleScore(score=Score(value={"one": 1, "two": 2}), sample_id=1),
        SampleScore(score=Score(value=float("nan")), sample_id=2),
        SampleScore(score=Score(value={"one": 3, "two": 4}), sample_id=3),
        SampleScore(score=Score.unscored(explanation="no result"), sample_id=4),
    ]

    results = scorers_from_metric_dict(
        scorer_name="test_scorer",
        scorer_info=_scorer_info_for_dict_metrics(),
        sample_scores=sample_scores,
        metrics={"one": [mean()], "two": [mean()]},
    )

    assert len(results) == 2
    by_name = {r.name: r for r in results}
    assert by_name["one"].scored_samples == 2
    assert by_name["one"].unscored_samples == 2
    assert by_name["one"].metrics["mean"].value == 2.0
    assert by_name["two"].scored_samples == 2
    assert by_name["two"].unscored_samples == 2
    assert by_name["two"].metrics["mean"].value == 3.0


def test_dict_metric_first_sample_unscored():
    # Regression: when the FIRST sample is NaN-at-root, the dict-key
    # globbing must still find a dict-shaped sample to read keys from.
    from inspect_ai._eval.task.results import scorers_from_metric_dict

    sample_scores = [
        SampleScore(score=Score(value=float("nan")), sample_id=1),
        SampleScore(score=Score(value={"one": 5, "two": 6}), sample_id=2),
        SampleScore(score=Score(value={"one": 1, "two": 2}), sample_id=3),
    ]

    # Use a glob pattern to exercise resolve_glob_metric_keys
    results = scorers_from_metric_dict(
        scorer_name="test_scorer",
        scorer_info=_scorer_info_for_dict_metrics(),
        sample_scores=sample_scores,
        metrics={"*": [mean()]},
    )

    assert len(results) == 2
    by_name = {r.name: r for r in results}
    assert by_name["one"].scored_samples == 2
    assert by_name["one"].unscored_samples == 1
    assert by_name["one"].metrics["mean"].value == 3.0
    assert by_name["two"].scored_samples == 2
    assert by_name["two"].unscored_samples == 1
    assert by_name["two"].metrics["mean"].value == 4.0


def test_dict_metric_all_samples_unscored():
    # When every sample is NaN-at-root, no key-globbing happens, every
    # metric value is NaN, and unscored_samples equals the sample count.
    import math

    from inspect_ai._eval.task.results import scorers_from_metric_dict

    sample_scores = [
        SampleScore(score=Score.unscored(), sample_id=1),
        SampleScore(score=Score.unscored(), sample_id=2),
        SampleScore(score=Score.unscored(), sample_id=3),
    ]

    # Pass literal (non-glob) keys so resolution is unambiguous.
    results = scorers_from_metric_dict(
        scorer_name="test_scorer",
        scorer_info=_scorer_info_for_dict_metrics(),
        sample_scores=sample_scores,
        metrics={"one": [mean()], "two": [mean()]},
    )

    assert len(results) == 2
    for r in results:
        assert r.scored_samples == 0
        assert r.unscored_samples == 3
        assert math.isnan(r.metrics["mean"].value)


def test_aggregate_mean():
    metric = aggregate("element_acc", agg=mean())
    result = metric(
        [
            SampleScore(score=Score(value={"element_acc": 1, "action_f1": 0.5})),
            SampleScore(score=Score(value={"element_acc": 1, "action_f1": 0.6})),
            SampleScore(score=Score(value={"element_acc": 4, "action_f1": 0.7})),
        ]
    )
    assert result == 2.0


def test_aggregate_selects_key():
    # Different keys over the same scores should give different aggregates.
    scores = [
        SampleScore(score=Score(value={"a": 1, "b": 10})),
        SampleScore(score=Score(value={"a": 3, "b": 30})),
    ]
    assert aggregate("a", agg=mean())(scores) == 2.0
    assert aggregate("b", agg=mean())(scores) == 20.0


def test_aggregate_stderr_composes():
    # stderr() should work as the inner aggregator.
    se = aggregate("x", agg=stderr())(
        [SampleScore(score=Score(value={"x": i, "y": -i})) for i in range(20)]
    )
    expected = stderr()([SampleScore(score=Score(value=i)) for i in range(20)])
    assert se == expected


def test_aggregate_missing_key_error_by_default():
    metric = aggregate("element_acc", agg=mean())
    with pytest.raises(ValueError, match="is missing"):
        metric(
            [
                SampleScore(score=Score(value={"element_acc": 1})),
                SampleScore(score=Score(value={"action_f1": 0.5})),
            ]
        )


def test_aggregate_missing_key_skip():
    metric = aggregate("element_acc", agg=mean(), on_missing="skip")
    result = metric(
        [
            SampleScore(score=Score(value={"element_acc": 1})),
            SampleScore(score=Score(value={"action_f1": 0.5})),  # skipped
            SampleScore(score=Score(value={"element_acc": 3})),
        ]
    )
    assert result == 2.0


def test_aggregate_missing_key_zero():
    metric = aggregate("element_acc", agg=mean(), on_missing="zero")
    result = metric(
        [
            SampleScore(score=Score(value={"element_acc": 3})),
            SampleScore(score=Score(value={"action_f1": 0.5})),  # treated as 0.0
            SampleScore(score=Score(value={"element_acc": 3})),
        ]
    )
    assert result == 2.0


def test_aggregate_non_dict_value_raises():
    metric = aggregate("element_acc", agg=mean())
    with pytest.raises(ValueError, match="non-dict"):
        metric(
            [
                SampleScore(score=Score(value={"element_acc": 1})),
                SampleScore(score=Score(value=1.0)),  # scalar, not a dict
            ]
        )


def test_aggregate_explicit_to_float_applied():
    # An explicit to_float lets string grades flow into mean() (which expects
    # numerics). value_to_float maps "C"->1.0 and "I"->0.0.
    result = aggregate("verdict", agg=mean(), to_float=value_to_float())(
        [
            SampleScore(score=Score(value={"verdict": "C"})),
            SampleScore(score=Score(value={"verdict": "I"})),
            SampleScore(score=Score(value={"verdict": "C"})),
            SampleScore(score=Score(value={"verdict": "C"})),
        ]
    )
    assert result == 0.75


def test_aggregate_passthrough_respects_inner_to_float():
    # With the default to_float=None, the raw value passes straight through to
    # the inner metric, so the inner metric's OWN converter applies. Here a
    # custom value_to_float on accuracy() maps "pass"->1.0 / "fail"->0.0;
    # aggregate must not pre-convert and bypass it.
    inner = accuracy(to_float=value_to_float(correct="pass", incorrect="fail"))
    result = aggregate("verdict", agg=inner)(
        [
            SampleScore(score=Score(value={"verdict": "pass"})),
            SampleScore(score=Score(value={"verdict": "fail"})),
            SampleScore(score=Score(value={"verdict": "pass"})),
            SampleScore(score=Score(value={"verdict": "pass"})),
        ]
    )
    assert result == 0.75


def test_aggregate_none_value_treated_as_missing_error():
    # A present-but-None value is treated the same as a missing key
    # (matches inspect_evals.utils.metrics.mean_of).
    metric = aggregate("element_acc", agg=mean())
    with pytest.raises(ValueError, match="is None"):
        metric(
            [
                SampleScore(score=Score(value={"element_acc": 1})),
                SampleScore(score=Score(value={"element_acc": None})),
            ]
        )


def test_aggregate_none_value_treated_as_missing_skip():
    result = aggregate("element_acc", agg=mean(), on_missing="skip")(
        [
            SampleScore(score=Score(value={"element_acc": 1})),
            SampleScore(score=Score(value={"element_acc": None})),  # skipped
            SampleScore(score=Score(value={"element_acc": 3})),
        ]
    )
    assert result == 2.0


def test_aggregate_none_value_treated_as_missing_zero():
    result = aggregate("element_acc", agg=mean(), on_missing="zero")(
        [
            SampleScore(score=Score(value={"element_acc": 3})),
            SampleScore(score=Score(value={"element_acc": None})),  # treated as 0.0
            SampleScore(score=Score(value={"element_acc": 3})),
        ]
    )
    assert result == 2.0


def test_aggregate_all_skipped_returns_nan():
    # When skip filters every sample, return NaN rather than calling agg([])
    # (which most built-in metrics raise on).
    result = aggregate("element_acc", agg=mean(), on_missing="skip")(
        [
            SampleScore(score=Score(value={"action_f1": 0.5})),
            SampleScore(score=Score(value={"action_f1": 0.6})),
        ]
    )
    assert isinstance(result, float) and math.isnan(result)


def test_aggregate_skips_nan_values():
    # A per-key NaN is unscored: skipped regardless of on_missing (which is
    # at its "error" default here), so the aggregate is the mean of the
    # non-NaN values rather than NaN. Matches dict-metric expansion.
    result = aggregate("x", agg=mean())(
        [
            SampleScore(score=Score(value={"x": 1})),
            SampleScore(score=Score(value={"x": float("nan")})),
            SampleScore(score=Score(value={"x": 3})),
        ]
    )
    assert result == 2.0


def test_aggregate_all_nan_returns_nan():
    result = aggregate("x", agg=mean())(
        [
            SampleScore(score=Score(value={"x": float("nan")})),
            SampleScore(score=Score(value={"x": float("nan")})),
        ]
    )
    assert isinstance(result, float) and math.isnan(result)


def test_aggregate_nan_skipped_under_zero():
    # NaN is distinct from a missing key: even with on_missing="zero" a NaN
    # value is skipped (not coerced to 0.0), so it doesn't drag the mean down.
    result = aggregate("x", agg=mean(), on_missing="zero")(
        [
            SampleScore(score=Score(value={"x": 2})),
            SampleScore(score=Score(value={"x": float("nan")})),
        ]
    )
    assert result == 2.0


def test_aggregate_invalid_on_missing_raises():
    # Invalid on_missing must fail at construction, not silently behave like
    # "zero" only when a key happens to be missing.
    with pytest.raises(ValueError, match="invalid on_missing"):
        aggregate("x", agg=mean(), on_missing="skpi")  # type: ignore[arg-type]


def test_metrics_return_zero_for_empty_scores() -> None:
    # Every built-in numeric metric must handle an empty score list by
    # returning 0.0 rather than nan (with numpy empty-slice warnings). See the
    # empty-input guards documented in accuracy()/std()/var().
    from inspect_ai.scorer import (
        accuracy,
        bootstrap_stderr,
        mean,
        std,
        stderr,
        var,
    )

    for metric_fn in (
        accuracy(),
        mean(),
        var(),
        std(),
        stderr(),
        bootstrap_stderr(),
    ):
        assert metric_fn([]) == 0.0
