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
from inspect_ai.scorer._metrics.reliability import (
    align_paired_scores,
    benjamini_hochberg,
    holm_bonferroni,
    mcnemar_from_scores,
    mcnemar_test,
    min_samples_for_delta,
    paired_delta,
    power_for_samples,
    variance_surface,
)
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


_Z_95 = 1.959963984540054  # NormalDist().inv_cdf(0.975)


# ---------------------------------------------------------------------------
# Eval-reliability toolkit: paired delta, multiplicity, power, variance surface.
# ---------------------------------------------------------------------------


def test_paired_delta_matches_hand_computation():
    # a - b = [1, 1, 1, 0]: mean 0.75, sample sd 0.5, se 0.25.
    result = paired_delta([1, 1, 1, 0], [0, 0, 0, 0])
    assert result["delta"] == pytest.approx(0.75)
    assert result["stderr"] == pytest.approx(0.25)
    assert result["n"] == 4.0
    assert result["lower"] == pytest.approx(0.75 - _Z_95 * 0.25)
    assert result["upper"] == pytest.approx(0.75 + _Z_95 * 0.25)
    # z = 0.75 / 0.25 = 3.0 -> two-sided p = 2 * Phi(-3).
    from statistics import NormalDist

    assert result["p_value"] == pytest.approx(2 * NormalDist().cdf(-3.0))


def test_paired_delta_uses_difference_se_not_independent():
    # The correctness point: for positively-correlated paired scores the paired
    # SE (SD of the differences) is far smaller than an independent-samples SE,
    # because shared per-sample difficulty cancels. Here b = a - 0.1 exactly, so
    # the differences are (near) constant and the paired SE collapses to ~0.
    a = [0.9, 0.8, 0.7, 0.6, 0.5]
    b = [0.8, 0.7, 0.6, 0.5, 0.4]
    paired = paired_delta(a, b)
    assert paired["delta"] == pytest.approx(0.1)
    assert paired["stderr"] == pytest.approx(0.0, abs=1e-9)

    # Independent-samples SE of the difference of means would be sqrt(se_a^2+se_b^2),
    # which is strictly positive here — i.e. the naive (wrong) analysis reports a
    # much larger error bar for the same data.
    se_a = stderr()([SampleScore(score=Score(value=v)) for v in a])
    se_b = stderr()([SampleScore(score=Score(value=v)) for v in b])
    independent_se = (se_a**2 + se_b**2) ** 0.5
    assert independent_se == pytest.approx(0.1)  # naive (wrong) error bar
    assert paired["stderr"] < independent_se  # paired ~0 << independent


def test_paired_delta_one_sided_alternatives():
    a = [1, 1, 1, 0]
    b = [0, 0, 0, 0]
    two_sided = paired_delta(a, b, alternative="two-sided")["p_value"]
    greater = paired_delta(a, b, alternative="greater")["p_value"]
    less = paired_delta(a, b, alternative="less")["p_value"]
    assert greater == pytest.approx(two_sided / 2)  # symmetric normal
    assert less == pytest.approx(1.0 - greater)


def test_paired_delta_validates_alignment_and_level():
    with pytest.raises(ValueError):
        paired_delta([1, 2, 3], [1, 2])  # length mismatch
    with pytest.raises(ValueError):
        paired_delta([1, 2], [1, 2], level=1.0)  # level out of range


def test_paired_delta_small_sample_collapses():
    result = paired_delta([1.0], [0.0])
    assert result["delta"] == 1.0
    assert result["lower"] == result["upper"] == 1.0
    assert result["p_value"] == 1.0


def test_paired_delta_clustered_se_exceeds_iid_under_within_cluster_correlation():
    # Two clusters (e.g. prompt templates) of four pairs each. Within a cluster
    # the per-sample differences are identical, so the effective sample size is
    # ~2 clusters, not 8 pairs: the cluster-robust delta SE must exceed the i.i.d.
    # SE and the design effect must be > 1. Mirrors the clustered stderr/ci
    # metrics, but applied to the *difference*.
    a, b, clusters = [], [], []
    for label, d in (("t1", 0.2), ("t2", -0.1)):
        for _ in range(4):
            a.append(d)
            b.append(0.0)
            clusters.append(label)

    iid = paired_delta(a, b)
    clustered = paired_delta(a, b, clusters=clusters)
    assert clustered["delta"] == pytest.approx(iid["delta"])
    assert clustered["stderr_iid"] == pytest.approx(iid["stderr"])
    assert clustered["stderr"] > clustered["stderr_iid"]
    assert clustered["design_effect"] > 1.0
    assert (clustered["upper"] - clustered["lower"]) > (iid["upper"] - iid["lower"])


def test_paired_delta_clusters_validates_length():
    with pytest.raises(ValueError):
        paired_delta([1.0, 0.0, 1.0], [0.0, 0.0, 0.0], clusters=["a", "b"])


def test_mcnemar_exact_matches_binomial_sign_test():
    # 3 vs 0 discordant: exact two-sided p = 2 * P(X <= 0 | Binom(3, 0.5)) = 2/8.
    r = mcnemar_test(3, 0)
    assert r.method == "mcnemar_exact"
    assert r.statistic is None
    assert r.p_value == pytest.approx(2 * (0.5**3))
    assert r.n_discordant == 3
    # Symmetric discordants are maximally non-significant.
    assert mcnemar_test(7, 7, exact=True).p_value == pytest.approx(1.0)
    # No discordant pairs -> nothing to distinguish.
    assert mcnemar_test(0, 0).p_value == 1.0


def test_mcnemar_chi2_with_continuity_correction():
    from math import erfc, sqrt

    r = mcnemar_test(40, 10)  # 50 discordant -> chi-square approximation
    assert r.method == "mcnemar_chi2_cc"
    assert r.statistic == pytest.approx((29.0**2) / 50.0)  # (|40-10|-1)^2 / 50
    assert r.p_value == pytest.approx(erfc(sqrt(r.statistic / 2.0)))
    assert r.p_value < 0.05


def test_mcnemar_from_scores_counts_and_requires_binary():
    a = [1, 1, 1, 0, 1, 0]
    b = [0, 0, 1, 0, 1, 1]
    r = mcnemar_from_scores(a, b)  # A-only: idx 0,1 -> 2 ; B-only: idx 5 -> 1
    assert (r.n_a_only, r.n_b_only) == (2, 1)
    with pytest.raises(ValueError):  # epoch-averaged / non-binary -> use paired_delta
        mcnemar_from_scores([0.5, 1.0, 0.0], [0.0, 1.0, 1.0])
    with pytest.raises(ValueError):
        mcnemar_from_scores([1, 0, 1], [1, 0])


def test_align_paired_scores_orders_by_sample_id():
    a = [
        SampleScore(score=Score(value=1.0), sample_id="s2"),
        SampleScore(score=Score(value=0.0), sample_id="s1"),
    ]
    b = [
        SampleScore(score=Score(value=0.0), sample_id="s1"),
        SampleScore(score=Score(value=1.0), sample_id="s2"),
    ]
    va, vb = align_paired_scores(a, b)
    assert va == [0.0, 1.0]  # ordered s1, s2
    assert vb == [0.0, 1.0]


def test_align_paired_scores_requires_matching_ids():
    a = [SampleScore(score=Score(value=1.0), sample_id="s1")]
    b = [SampleScore(score=Score(value=1.0), sample_id="s2")]
    with pytest.raises(ValueError):
        align_paired_scores(a, b)


def test_holm_bonferroni_known_pset():
    # p = [0.01..0.05]: Holm rejects only the smallest; adjusted = running max of
    # (m - k + 1) * p_(k) = [0.05, 0.08, 0.09, 0.09, 0.09].
    result = holm_bonferroni([0.01, 0.02, 0.03, 0.04, 0.05], alpha=0.05)
    assert result.adjusted == pytest.approx([0.05, 0.08, 0.09, 0.09, 0.09])
    assert result.rejected == [True, False, False, False, False]
    assert result.num_rejected == 1


def test_holm_preserves_input_order():
    # unsorted input -> outputs stay aligned to inputs
    result = holm_bonferroni([0.04, 0.01, 0.05, 0.02, 0.03], alpha=0.05)
    assert result.rejected == [False, True, False, False, False]
    assert result.adjusted[1] == pytest.approx(0.05)


def test_benjamini_hochberg_known_psets():
    # p = [0.01..0.05]: BH rejects all five; q-values all 0.05.
    result = benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05], alpha=0.05)
    assert result.adjusted == pytest.approx([0.05, 0.05, 0.05, 0.05, 0.05])
    assert result.rejected == [True, True, True, True, True]
    # step-up with a middle gap: only the smallest survives.
    result2 = benjamini_hochberg([0.005, 0.04, 0.5], alpha=0.05)
    assert result2.adjusted == pytest.approx([0.015, 0.06, 0.5])
    assert result2.rejected == [True, False, False]


def test_bh_makes_at_least_as_many_discoveries_as_holm():
    pvals = [0.001, 0.012, 0.03, 0.04, 0.2, 0.5]
    holm = holm_bonferroni(pvals)
    bh = benjamini_hochberg(pvals)
    assert bh.num_rejected >= holm.num_rejected  # FDR <= FWER conservativeness


def test_multiple_comparison_validation_and_empty():
    with pytest.raises(ValueError):
        holm_bonferroni([0.1, 1.5])  # p out of range
    with pytest.raises(ValueError):
        benjamini_hochberg([0.1], alpha=0.0)
    assert holm_bonferroni([]).num_rejected == 0
    assert benjamini_hochberg([]).adjusted == []


def test_min_samples_for_delta_textbook_value():
    # Classic: effect size d/sd = 0.5, alpha 0.05 two-sided, power 0.8 -> n ~= 32.
    assert min_samples_for_delta(0.5, 1.0, power=0.8, alpha=0.05) == 32
    # Smaller effects need (quadratically) more samples: halving d -> ~4x n.
    assert min_samples_for_delta(0.25, 1.0) == 126


def test_power_for_samples_inverts_min_samples():
    n = min_samples_for_delta(0.5, 1.0, power=0.8)
    # at the recommended n the power should meet/slightly exceed the target
    assert power_for_samples(n, 0.5, 1.0) >= 0.8
    # one fewer sample falls short
    assert power_for_samples(n - 1, 0.5, 1.0) < 0.8


def test_power_helpers_validate():
    with pytest.raises(ValueError):
        min_samples_for_delta(0.0, 1.0)  # zero effect
    with pytest.raises(ValueError):
        min_samples_for_delta(0.5, 0.0)  # non-positive sd
    with pytest.raises(ValueError):
        power_for_samples(0, 0.5, 1.0)  # n < 1


def test_variance_surface_components():
    scores = [SampleScore(score=Score(value=i)) for i in range(10)]
    surface = variance_surface()(scores)
    # var of 0..9 (ddof=1) = 9.16667; stderr = sd/sqrt(10).
    assert surface["variance"] == pytest.approx(9.166667, abs=1e-5)
    assert surface["stderr"] == pytest.approx(stderr()(scores))
    assert surface["n"] == 10.0
    assert "design_effect" not in surface  # no cluster requested


def test_variance_surface_design_effect_with_cluster():
    # Perfectly correlated within clusters -> clustering inflates the SE, so the
    # design effect exceeds 1 (effectively fewer independent samples).
    scores = [
        SampleScore(score=Score(value=v), sample_metadata={"c": c})
        for c, v in [(0, 1.0), (0, 1.0), (1, 0.0), (1, 0.0), (2, 1.0), (2, 1.0)]
    ]
    surface = variance_surface(cluster="c")(scores)
    assert surface["stderr_clustered"] == pytest.approx(stderr(cluster="c")(scores))
    assert surface["design_effect"] > 1.0
