"""Task-declared headline metric: declaration, persistence, and resolution."""

import inspect
from typing import Any

import pytest

from inspect_ai import Epochs, Task, eval, score
from inspect_ai.analysis import evals_df
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalMetric,
    EvalResults,
    EvalScore,
    HeadlineMetric,
    headline_metric,
    read_eval_log,
    recompute_metrics,
)
from inspect_ai.log._file import to_overview
from inspect_ai.log._headline import resolve_headline_metric
from inspect_ai.scorer import (
    Metric,
    Score,
    Scorer,
    Target,
    accuracy,
    includes,
    match,
    mean,
    scorer,
    stderr,
)
from inspect_ai.solver import TaskState, generate

# scorer metrics are declared stderr-first so the convention (first metric of
# the first score) picks a metric nobody would want as their headline
METRICS: list[Metric | dict[str, list[Metric]]] = [stderr(), accuracy()]


def headline_task(
    headline_metric: HeadlineMetric | str | None = None, **kwargs: Any
) -> Task:
    return Task(
        dataset=[Sample(input=f"Say hello {i}", target="hello") for i in range(4)],
        scorer=includes(),
        metrics=METRICS,
        headline_metric=headline_metric,
        **kwargs,
    )


def run(headline_metric: HeadlineMetric | str | None = None, **kwargs: Any) -> Any:
    return eval(
        headline_task(headline_metric, **kwargs),
        model="mockllm/model",
        display="none",
    )[0]


def eval_score(
    name: str, metrics: dict[str, float], reducer: str | None = None
) -> EvalScore:
    return EvalScore(
        name=name,
        scorer=name,
        reducer=reducer,
        metrics={k: EvalMetric(name=k, value=v) for k, v in metrics.items()},
    )


# --- declaration and persistence -------------------------------------------


def test_headline_metric_roundtrips_through_eval_log() -> None:
    """`Task(headline_metric=...)` is persisted to `EvalSpec.headline_metric`."""
    declared = HeadlineMetric(score="includes", metric="accuracy")
    log = run(declared)
    assert log.eval.headline_metric == declared
    assert read_eval_log(log.location).eval.headline_metric == declared


def test_headline_metric_partial_declaration_roundtrips() -> None:
    """Unset fields survive the round trip as `None` rather than being filled in."""
    declared = HeadlineMetric(metric="accuracy")
    log = run(declared)
    assert log.eval.headline_metric == declared
    assert log.eval.headline_metric.score is None
    assert log.eval.headline_metric.reducer is None


def test_headline_metric_does_not_shift_positional_args() -> None:
    """`headline_metric` is appended, so it can't capture an existing positional.

    `Task.__init__` accepts every parameter positionally, so inserting a new one
    mid-signature would silently rebind each following argument (e.g. a
    positional `model` landing on `headline_metric`).
    """
    params = list(inspect.signature(Task.__init__).parameters)
    assert params.index("headline_metric") > params.index("viewer")

    positional = Task(None, None, generate(), None, includes(), None, "mockllm/model")
    assert positional.model is not None
    assert positional.headline_metric is None


def test_task_without_headline_metric_persists_as_none() -> None:
    """Tasks that don't declare a headline leave the declaration `None`."""
    log = run()
    assert log.eval.headline_metric is None


# --- resolution against results --------------------------------------------


def test_undeclared_headline_resolves_to_convention() -> None:
    """With no declaration the headline is the first metric of the first score."""
    log = run()
    assert log.results.headline == HeadlineMetric(
        scorer="includes", score="includes", metric="stderr", reducer=None
    )


def test_declared_metric_resolves_and_is_fully_qualified() -> None:
    """A partial declaration is stamped onto results with every field filled in."""
    log = run(HeadlineMetric(metric="accuracy"))
    assert log.results.headline == HeadlineMetric(
        scorer="includes", score="includes", metric="accuracy", reducer=None
    )


def test_reducer_disambiguates_scores_of_the_same_name() -> None:
    """Multiple reducers yield same-named scores; `reducer` picks between them."""
    log = run(
        HeadlineMetric(metric="accuracy", reducer="max"),
        epochs=Epochs(3, ["mean", "max"]),
    )
    assert log.results.headline == HeadlineMetric(
        scorer="includes", score="includes", metric="accuracy", reducer="max"
    )
    # the value really is the max view's, not the mean view's
    max_score = next(s for s in log.results.scores if s.reducer == "max")
    assert log.results.headline is not None
    resolved = resolve_headline_metric(log.results, log.results.headline)
    assert resolved is not None
    assert resolved.metric.value == max_score.metrics["accuracy"].value


def test_metric_selection_skips_scores_lacking_the_metric() -> None:
    """With no scorer named, the first score *containing* the metric is chosen."""
    results = EvalResults(
        scores=[eval_score("sanity", {"mean": 1.0}), eval_score("quality", {"f1": 0.5})]
    )
    resolved = resolve_headline_metric(results, HeadlineMetric(metric="f1"))
    assert resolved is not None
    assert (resolved.score.name, resolved.name) == ("quality", "f1")


def dict_scorer(name: str, value: float) -> Scorer:
    """A scorer whose value is a dict, so its scores are named for its keys."""

    @scorer(name=name, metrics={"quality": [mean()]})
    def build() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value={"quality": value})

        return score

    return build()


def test_dotted_string_addresses_one_value_of_a_dict_scorer() -> None:
    """`"<scorer>.<score>"` is shorthand, expanded only for the string form."""
    assert headline_task("grader.quality").headline_metric == HeadlineMetric(
        scorer="grader", score="quality"
    )
    # splitting on the first dot leaves a dotted score key intact
    assert headline_task("grader.f1.macro").headline_metric == HeadlineMetric(
        scorer="grader", score="f1.macro"
    )
    # a bare string names the scorer alone
    assert headline_task("grader").headline_metric == HeadlineMetric(scorer="grader")


def test_model_scorer_field_is_literal() -> None:
    """Scorer names may contain dots, so the model never splits them.

    `@scorer(name="judge.v2")` is legal and keeps its dot through
    `registry_unqualified_name`, so a shorthand split here would misread it.
    """
    assert HeadlineMetric(scorer="judge.v2").scorer == "judge.v2"
    assert HeadlineMetric(scorer="judge.v2").score is None

    # and model_validate must not mutate the caller's dict
    values = {"scorer": "judge.v2"}
    HeadlineMetric.model_validate(values)
    assert values == {"scorer": "judge.v2"}


@pytest.mark.parametrize(
    "declared",
    [
        "grader_b.quality",
        HeadlineMetric(scorer="grader_b", score="quality"),
        HeadlineMetric(scorer="grader_b"),
    ],
)
def test_scorer_identity_survives_the_round_trip(
    declared: HeadlineMetric | str,
) -> None:
    """Two dict-valued scorers can share a score name; only `scorer` separates them.

    The resolved reference is re-read by every consumer, so dropping the scorer
    from it silently resolved the headline to the wrong scorer's score.
    """
    log = eval(
        Task(
            dataset=[Sample(input="x", target="y")],
            scorer=[dict_scorer("grader_a", 0.1), dict_scorer("grader_b", 0.9)],
            headline_metric=declared,
        ),
        model="mockllm/model",
        display="none",
    )[0]

    assert log.results is not None
    assert log.results.headline == HeadlineMetric(
        scorer="grader_b", score="quality", metric="mean", reducer=None
    )
    for candidate in (log, read_eval_log(log.location)):
        resolved = headline_metric(candidate)
        assert resolved is not None
        assert resolved.score.scorer == "grader_b"
        assert resolved.metric.value == 0.9


def test_resolution_returns_none_when_there_are_no_scores() -> None:
    assert resolve_headline_metric(None, HeadlineMetric(metric="accuracy")) is None
    assert resolve_headline_metric(EvalResults(), HeadlineMetric()) is None
    assert (
        resolve_headline_metric(EvalResults(scores=[eval_score("s", {})]), None) is None
    )


@pytest.mark.parametrize(
    "declared,expected_warning",
    [
        (HeadlineMetric(metric="nope"), "Headline metric 'nope' not found"),
        (HeadlineMetric(score="nope"), "Headline score 'nope' not found"),
        (HeadlineMetric(scorer="nope"), "Headline scorer 'nope' not found"),
        (HeadlineMetric(reducer="nope"), "Headline reducer 'nope' not found"),
    ],
)
def test_unresolvable_declaration_warns_and_falls_back(
    monkeypatch: pytest.MonkeyPatch, declared: HeadlineMetric, expected_warning: str
) -> None:
    """A stale declaration never fails the eval; it warns and uses the convention."""
    from inspect_ai.log import _headline

    warnings: list[str] = []
    monkeypatch.setattr(_headline.logger, "warning", lambda msg: warnings.append(msg))
    # warn_once dedupes globally across the session
    monkeypatch.setattr("inspect_ai._util.logger._warned", [])

    results = EvalResults(scores=[eval_score("includes", {"stderr": 0.1})])
    resolved = resolve_headline_metric(results, declared)

    assert resolved is not None
    assert (resolved.score.name, resolved.name) == ("includes", "stderr")
    assert any(expected_warning in w for w in warnings), warnings


def test_stale_selector_abandons_the_whole_declaration() -> None:
    """A miss falls back to the convention, not to a partially-honored selection.

    Otherwise a declaration naming a scorer that no longer exists would still
    apply its `metric`, silently picking that metric from an unrelated score
    while warning that the first score was used.
    """
    results = EvalResults(
        scores=[
            eval_score("first", {"stderr": 0.1}),
            eval_score("second", {"accuracy": 0.9}),
        ]
    )
    resolved = resolve_headline_metric(
        results, HeadlineMetric(scorer="missing", metric="accuracy")
    )
    assert resolved is not None
    assert (resolved.score.name, resolved.name) == ("first", "stderr")


# --- consumers --------------------------------------------------------------


def test_log_listing_overview_uses_headline() -> None:
    """`to_overview()` powers the viewer's log listing via the manifest."""
    log = run(HeadlineMetric(metric="accuracy"))
    primary = to_overview(log).primary_metric
    assert primary is not None
    assert primary.name == "accuracy"


def test_evals_df_headline_columns_use_headline() -> None:
    log = run(HeadlineMetric(metric="accuracy"))
    row = evals_df(logs=[log.location]).iloc[0]
    assert row.score_headline_name == "includes"
    # a scorer returning a single score names it for itself, so the score
    # column repeats the scorer rather than emptying — it stays usable as a
    # key without coalescing the two columns
    assert row.score_headline_score == "includes"
    assert row.score_headline_metric == "accuracy"
    assert row.score_headline_value == log.results.scores[0].metrics["accuracy"].value
    assert row.score_headline_stderr == log.results.scores[0].metrics["stderr"].value


def test_evals_df_headline_score_distinguishes_dict_scorer_values() -> None:
    """One scorer, several scores: `score_headline_name` alone can't tell them apart.

    `score_headline_name` has always carried the scorer, so it reads `grader`
    for every value that scorer emits; `score_headline_score` carries the value
    key that the headline actually selected.
    """

    @scorer(name="grader", metrics={"coherence": [mean()], "fluency": [mean()]})
    def grader() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value={"coherence": 0.3, "fluency": 0.8})

        return score

    def row(declared: str) -> Any:
        log = eval(
            Task(
                dataset=[Sample(input="hello", target="hello")],
                scorer=grader(),
                headline_metric=declared,
            ),
            model="mockllm/model",
            display="none",
        )[0]
        return evals_df(logs=[log.location]).iloc[0]

    coherence, fluency = row("grader.coherence"), row("grader.fluency")
    assert coherence.score_headline_name == fluency.score_headline_name == "grader"
    assert coherence.score_headline_metric == fluency.score_headline_metric == "mean"
    assert coherence.score_headline_score == "coherence"
    assert fluency.score_headline_score == "fluency"
    assert coherence.score_headline_value == 0.3
    assert fluency.score_headline_value == 0.8


def test_expanded_progress_detail_keeps_colliding_dict_scorers_apart() -> None:
    """The Textual detail groups by score, which two scorers can share."""
    from inspect_ai._display.core.display import TaskDisplayMetric
    from inspect_ai._display.textual.widgets.task_detail import TaskDetail

    detail = TaskDetail()
    detail.update_metrics(
        [
            TaskDisplayMetric(
                scorer="quality", scorer_name=grader, name="mean", value=value
            )
            for grader, value in (("grader_a", 0.1), ("grader_b", 0.9))
        ]
    )

    groups = detail.by_reducer[None]
    assert len(groups) == 2
    assert {group.scorer for group in groups} == {"grader_a", "grader_b"}
    assert all(len(metrics) == 1 for metrics in groups.values())


def test_progress_display_leads_with_headline() -> None:
    """`task_metric()` renders `metrics[0]`, so the headline must sort first."""
    from inspect_ai._display.core.display import TaskDisplayMetric
    from inspect_ai._display.core.results import task_metric
    from inspect_ai._eval.task.run import update_metrics_display_fn
    from inspect_ai.scorer._metric import SampleScore, Score

    captured: list[list[TaskDisplayMetric]] = []
    compute = update_metrics_display_fn(
        captured.append, headline_metric=HeadlineMetric(metric="accuracy")
    )
    compute(
        2,
        [
            {"includes": SampleScore(score=Score(value=1.0), sample_id=i)}
            for i in (1, 2)
        ],
        [includes()],
        ["includes"],
        None,
        METRICS,
    )

    assert captured, "metrics were never computed"
    names = [m.name for m in captured[-1]]
    assert names[0] == "accuracy"
    # the non-headline metrics keep their declared relative order
    assert names[1:] == ["stderr"]
    assert task_metric(captured[-1]).startswith("accuracy:")


def test_progress_display_distinguishes_colliding_dict_scorers() -> None:
    """Two dict-valued scorers share a score name; only the scorer separates them.

    `TaskDisplayMetric` flattens away the `EvalScore`, so matching the headline
    after the fact picked whichever score came first.
    """
    from inspect_ai._display.core.display import TaskDisplayMetric
    from inspect_ai._display.core.results import task_metric
    from inspect_ai._eval.task.run import update_metrics_display_fn
    from inspect_ai.scorer._metric import SampleScore

    captured: list[list[TaskDisplayMetric]] = []
    compute = update_metrics_display_fn(
        captured.append,
        headline_metric=HeadlineMetric(scorer="grader_b", score="quality"),
    )
    compute(
        1,
        [
            {
                "grader_a": SampleScore(
                    score=Score(value={"quality": 0.1}), sample_id=1
                ),
                "grader_b": SampleScore(
                    score=Score(value={"quality": 0.9}), sample_id=1
                ),
            }
        ],
        [dict_scorer("grader_a", 0.1), dict_scorer("grader_b", 0.9)],
        ["grader_a", "grader_b"],
        None,
        None,
    )

    assert captured, "metrics were never computed"
    assert captured[-1][0].value == 0.9
    assert captured[-1][0].scorer_name == "grader_b"
    assert task_metric(captured[-1]).endswith("0.90")


def test_progress_display_marks_only_the_first_of_two_identical_scores() -> None:
    """A scorer can emit two scores alike in every field a reference names.

    `metrics=[mean(), {"dup": [mean()]}]` on a scorer named `dup` yields two
    scores with the same scorer, name, reducer *and* metric key. The resolver
    takes the first; marking the last would reorder the progress line for a
    task that declared nothing.
    """
    from inspect_ai._display.core.display import TaskDisplayMetric
    from inspect_ai._display.core.results import task_metric
    from inspect_ai._eval.task.run import update_metrics_display_fn
    from inspect_ai.scorer._metric import SampleScore

    @scorer(name="dup", metrics=[mean(), {"dup": [mean()]}])
    def dup() -> Scorer:
        async def score(state: TaskState, target: Target) -> Score:
            return Score(value={"dup": 1.0})

        return score

    captured: list[list[TaskDisplayMetric]] = []
    compute = update_metrics_display_fn(captured.append, headline_metric=None)
    compute(
        1,
        [{"dup": SampleScore(score=Score(value={"dup": 1.0}), sample_id=1)}],
        [dup()],
        ["dup"],
        None,
        [mean(), {"dup": [mean()]}],
    )

    assert captured, "metrics were never computed"
    metrics = captured[-1]
    assert [m.name for m in metrics] == ["mean", "mean"]
    assert [m.headline for m in metrics] == [True, False]
    # undeclared, so the order must be exactly what it was before headlines
    assert [m.value for m in metrics] == [0.0, 1.0]
    assert task_metric(metrics) == "mean: 0.00"


def test_headline_survives_recompute_and_rescore() -> None:
    """Metric recomputation and rescoring re-resolve from the declaration."""
    log = run(HeadlineMetric(metric="accuracy"))

    expected = HeadlineMetric(
        scorer="includes", score="includes", metric="accuracy", reducer=None
    )

    recompute_metrics(log)
    assert log.results.headline == expected

    rescored = score(log, includes(), action="overwrite", display="none")
    assert rescored.results is not None
    assert rescored.results.headline == expected


def test_append_rescoring_resolves_against_the_combined_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`action="append"` extends the existing scores after metrics are computed.

    Resolving the headline inside that computation saw only the newly added
    scorers, so a headline naming a pre-existing one warned spuriously and left
    a declaration that only the append satisfies unresolved.
    """
    from inspect_ai.log import _headline

    log = run(HeadlineMetric(scorer="includes", metric="accuracy"))

    warnings: list[str] = []
    monkeypatch.setattr(_headline.logger, "warning", lambda msg: warnings.append(msg))
    monkeypatch.setattr("inspect_ai._util.logger._warned", [])

    appended = score(log, match(), action="append", display="none")

    assert appended.results is not None
    assert [s.scorer for s in appended.results.scores] == ["includes", "match"]
    assert appended.results.headline == HeadlineMetric(
        scorer="includes", score="includes", metric="accuracy", reducer=None
    )
    assert not warnings, warnings


def test_append_rescoring_can_satisfy_a_previously_unresolvable_headline() -> None:
    """A headline naming a scorer only added by the append now resolves."""
    log = run(HeadlineMetric(scorer="match", metric="accuracy"))
    # nothing named "match" existed at eval time, so it fell back
    assert log.results.headline is not None
    assert log.results.headline.scorer == "includes"

    appended = score(log, match(), action="append", display="none")
    assert appended.results is not None
    assert appended.results.headline is not None
    assert appended.results.headline.scorer == "match"


def test_empty_metric_key_is_a_real_key() -> None:
    """Mapping-valued metrics contribute their keys verbatim, and "" is legal."""
    results = EvalResults(scores=[eval_score("s", {"": 0.5})])
    resolved = resolve_headline_metric(results, None)
    assert resolved is not None
    assert (resolved.name, resolved.metric.value) == ("", 0.5)


def test_legacy_log_without_headline_fields_resolves_by_convention() -> None:
    """Logs written before headline metrics existed keep their old behavior."""
    log = run()
    log.results.headline = None
    log.eval.headline_metric = None

    resolved = headline_metric(log)
    assert resolved is not None
    assert (resolved.score.name, resolved.name) == ("includes", "stderr")
    assert to_overview(log).primary_metric is not None
