from typing import Any

from inspect_ai import Task, eval, score
from inspect_ai._util.constants import PKG_NAME
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Metric, Score, accuracy, includes, match, metric
from inspect_ai.scorer._metric import MetricType, metric_create

# declare some metrics using the various forms supported (function,
# function returning Metric, class deriving from Metric) as well
# as using implicit and explicit names


@metric
def accuracy1(correct: str = "C") -> Metric:
    def metric(scores: list[Score]) -> int | float:
        return 1

    return metric


@metric(name="accuracy2")
def acc_fn(correct: str = "C") -> Metric:
    def metric(scores: list[Score]) -> int | float:
        return 1

    return metric


@metric
class Accuracy3(Metric):
    def __init__(self, correct: str = "C") -> None:
        self.correct = correct

    def __call__(self, scores: list[Score]) -> int | float:
        return 1


@metric(name="accuracy4")
class AccuracyNamedCls(Metric):
    def __init__(self, correct: str = "C") -> None:
        self.correct = correct

    def __call__(self, scores: list[Score]) -> int | float:
        return 1


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


def test_extra_metrics() -> None:
    # check that we get the extra metrics and de-duping works
    def check_log(log):
        assert log.results and (
            list(log.results.metrics.keys())
            == [
                "accuracy",
                "bootstrap_std",
                "accuracy1",
                "Accuracy3",
            ]
        )

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=match(),
        metrics=[accuracy(), accuracy1(), Accuracy3()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log)

    # eval log w/ different scorer (that still uses accuracy)
    log = score(log, scorer=includes())
    check_log(log)


def registry_assert(metric: Metric | MetricType, name: str) -> None:
    info = registry_info(metric)
    assert info.name == name


def metric_create_assert(name: str, **kwargs: Any) -> None:
    metric = metric_create(name, **kwargs)
    assert metric([]) == 1
