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
    var,
)
from inspect_ai.scorer._metric import (
    MetricDeprecated,
    MetricProtocol,
    SampleScore,
    metric_create,
)
from inspect_ai.scorer._metrics import grouped
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
        assert (
            log.results.scores[1].metrics["nested_dict_metric_key1"].name
            == "nested_dict_metric_key1"
        )

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
        assert (
            log.results.scores[1].metrics["nested_list_metric_0"].name
            == "nested_list_metric_0"
        )

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


def test_clustered_stderr():
    metric = stderr(cluster="my_cluster")
    se = metric(
        [
            SampleScore(score=Score(value=i), sample_metadata={"my_cluster": i % 4})
            for i in range(20)
        ]
    )
    assert round(se, 3) == 0.645


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
