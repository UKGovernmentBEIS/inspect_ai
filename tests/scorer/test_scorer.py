# type: ignore

from typing import Any

import pytest
from test_helpers.utils import ensure_test_package_installed, run_example

from inspect_ai import Task, eval, score
from inspect_ai.dataset import Sample
from inspect_ai.event import ScoreEvent
from inspect_ai.log import EvalSample, recompute_metrics
from inspect_ai.scorer import (
    Score,
    Scorer,
    Target,
    accuracy,
    includes,
    mean,
    scorer,
)
from inspect_ai.scorer import score as score_conversation
from inspect_ai.scorer._scorer import scorer_create
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


@scorer(metrics=[accuracy()], name="test_match")
def match() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return (
            Score(value="C")
            if state.output.completion == target.text
            else Score(value="I")
        )

    return score


def test_scorer_lookup():
    scorer = scorer_create("test_match")
    assert scorer


@scorer(metrics=[accuracy()], name="test_match_kwargs")
def match_kwargs(**kwargs) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value="C")

    return score


def test_scorer_create_replays_name_kwarg_without_collision():
    """A `**kwargs` key named `name` must survive scorer replay from a log (#4375).

    Flat capture records such a key at the top level of EvalScore.params, so
    replaying it via scorer_create must not collide with scorer_create's own
    `name` parameter.
    """
    scorer = scorer_create("test_match_kwargs", name="demo")
    assert scorer


def test_invalid_scorers_error():
    def not_async():
        def inner(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return inner

    class NotCallable:
        async def inner(self, state: TaskState, target: Target) -> Score:
            return Score(value="C")

    class NotAsyncCallable:
        def __call__(self, state: TaskState, target: Target) -> Score:
            return Score(value="C")

    for f in [not_async, NotCallable, NotAsyncCallable]:
        with pytest.raises(TypeError):
            scorer(metrics=[accuracy()], name=f.__name__)(f)()


def test_valid_scorers_succeed():
    def is_async():
        async def inner(state: TaskState, target: Target) -> Score:
            return Score(value="C")

        return inner

    class IsAsyncCallable:
        async def __call__(self, state: TaskState, target: Target) -> Score:
            return Score(value="C")

    for f in [is_async, IsAsyncCallable]:
        scorer(metrics=[accuracy()], name=f.__name__)(f)()


def test_no_scorer():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
    )
    log = eval(tasks=task, model="mockllm/model")[0]
    assert log.samples[0].score is None


def test_score_function():
    log = run_example("popularity.py", "mockllm/model")
    log = score(log[0], includes())
    assert log.samples[0].score.value


def test_score_package_name():
    ensure_test_package_installed()
    from inspect_package import simple_score

    task = Task(
        dataset=[Sample(input="What is the capital of Kansas?", target=["Topeka"])],
        scorer=simple_score(),
    )
    eval_log = eval(tasks=task, model="mockllm/model")[0]
    assert eval_log.results.scores[0].name == "simple_score"


def test_score_unique():
    ensure_test_package_installed()
    from inspect_package import simple_score

    task = Task(
        dataset=[Sample(input="What is the capital of Kansas?", target=["Topeka"])],
        scorer=[simple_score(), simple_score(), simple_score()],
    )
    eval_log = eval(tasks=task, model="mockllm/model")[0]

    assert eval_log.results.scores[0].name == "simple_score"
    assert eval_log.results.scores[1].name == "simple_score1"
    assert eval_log.results.scores[2].name == "simple_score2"


def test_recompute_duplicate_scorer_names():
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        scorer=[match(), match()],
        epochs=2,
    )
    eval_log = eval(tasks=task, model="mockllm/model", display="none")[0]
    assert eval_log.results is not None

    before = [score.name for score in eval_log.results.scores]
    assert before == ["test_match", "test_match1"]

    recompute_metrics(eval_log)
    assert [score.name for score in eval_log.results.scores] == before


@scorer(metrics={"correct": [mean()], "concise": [mean()]})
def answer_quality() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value={"correct": 1, "concise": 0})

    return score


@solver
def interim_scoring() -> Solver:
    """Score mid-sample with the task's scorers."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        await score_conversation(state)
        return state

    return solve


def _named_task(**task_args: Any) -> Task:
    return Task(
        dataset=[
            Sample(input="Say hello.", target="Hello", id=1),
            Sample(input="Say bye.", target="Bye", id=2),
        ],
        scorer={"strict": match(), "loose": includes()},
        **task_args,
    )


def _final_score_events(sample: EvalSample) -> list[str | None]:
    return [
        event.scorer
        for event in sample.events
        if isinstance(event, ScoreEvent) and not event.intermediate
    ]


def test_task_scorer_dict_names_scores() -> None:
    """Dict keys name sample scores, score events, results, reductions and the header."""
    log = eval(_named_task(epochs=2), model="mockllm/model", display="none")[0]
    assert log.status == "success"
    assert log.samples is not None and len(log.samples) == 4
    assert log.results is not None and log.reductions is not None
    assert log.eval.scorers is not None

    for sample in log.samples:
        assert sample.scores is not None
        assert list(sample.scores) == ["strict", "loose"]
        assert _final_score_events(sample) == ["strict", "loose"]

    assert [(s.name, s.scorer) for s in log.results.scores] == [
        ("strict", "strict"),
        ("loose", "loose"),
    ]
    assert [(r.scorer, len(r.samples)) for r in log.reductions] == [
        ("strict", 2),
        ("loose", 2),
    ]
    assert [(s.name, s.score_name) for s in log.eval.scorers] == [
        ("test_match", "strict"),
        ("includes", "loose"),
    ]

    # metrics recomputed from the header and samples keep the names
    before = log.results.model_dump()
    recompute_metrics(log)
    assert log.results.model_dump() == before
    assert [r.scorer for r in log.reductions] == ["strict", "loose"]


def test_task_scorer_dict_names_one_scorer_twice() -> None:
    """The same scorer under two keys gets both names, not generated ones."""
    includes_twice = includes()
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        scorer={"first": includes_twice, "second": includes_twice},
    )
    log = eval(task, model="mockllm/model", display="none")[0]
    assert log.results is not None
    assert [s.name for s in log.results.scores] == ["first", "second"]


def test_task_scorer_list_names_are_unchanged() -> None:
    """A list of scorers still gets generated names, and the header records none."""
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        scorer=[includes(), includes()],
    )
    log = eval(task, model="mockllm/model", display="none")[0]
    assert log.samples is not None and log.results is not None
    assert log.eval.scorers is not None
    assert list(log.samples[0].scores or {}) == ["includes", "includes1"]
    assert _final_score_events(log.samples[0]) == ["includes", "includes1"]
    assert [s.name for s in log.results.scores] == ["includes", "includes1"]
    assert [s.score_name for s in log.eval.scorers] == [None, None]


def test_task_scorer_dict_names_metrics_dict_scores() -> None:
    """A scorer with a dict of metrics reports each value under the dict key."""
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        scorer={"quality": answer_quality(), "loose": includes()},
    )
    log = eval(task, model="mockllm/model", display="none")[0]
    assert log.samples is not None and log.results is not None
    assert list(log.samples[0].scores or {}) == ["quality", "loose"]
    assert [(s.name, s.scorer) for s in log.results.scores] == [
        ("correct", "quality"),
        ("concise", "quality"),
        ("loose", "loose"),
    ]


def test_task_scorer_dict_names_task_metrics() -> None:
    """Task metrics that override the scorers' metrics apply under the dict keys."""
    log = eval(_named_task(metrics=[mean()]), model="mockllm/model", display="none")[0]
    assert log.results is not None
    assert [(s.name, list(s.metrics)) for s in log.results.scores] == [
        ("strict", ["mean"]),
        ("loose", ["mean"]),
    ]


def test_task_scorer_dict_name_is_headline_scorer() -> None:
    """`headline_metric` addresses a scorer by its dict key."""
    log = eval(
        _named_task(headline_metric="loose"), model="mockllm/model", display="none"
    )[0]
    assert log.results is not None and log.results.headline is not None
    assert log.results.headline.scorer == "loose"


def test_task_scorer_dict_names_intermediate_scores() -> None:
    """`score()` called from a solver records events under the dict keys."""
    log = eval(
        _named_task(solver=[generate(), interim_scoring()]),
        model="mockllm/model",
        display="none",
    )[0]
    assert log.status == "success"
    assert log.samples is not None
    for sample in log.samples:
        intermediate = [
            event.scorer
            for event in sample.events
            if isinstance(event, ScoreEvent) and event.intermediate
        ]
        assert intermediate == ["strict", "loose"]
        assert _final_score_events(sample) == ["strict", "loose"]


def test_task_scorer_list_names_intermediate_scores() -> None:
    """`score()` called from a solver keeps generated names for a list of scorers."""
    task = Task(
        dataset=[Sample(input="Say hello.", target="Hello")],
        solver=[generate(), interim_scoring()],
        scorer=[includes(), includes()],
    )
    log = eval(task, model="mockllm/model", display="none")[0]
    assert log.samples is not None
    intermediate = [
        event.scorer
        for event in log.samples[0].events
        if isinstance(event, ScoreEvent) and event.intermediate
    ]
    assert intermediate == ["includes", "includes1"]


def test_task_scorer_dict_unscored_eval_records_names() -> None:
    """An eval run without scoring records the names for a later scoring run."""
    log = eval(_named_task(), model="mockllm/model", display="none", score=False)[0]
    assert log.results is None or log.results.scores == []
    assert log.eval.scorers is not None
    assert [s.score_name for s in log.eval.scorers] == ["strict", "loose"]


def test_task_scorer_assigned_dict_names_scores() -> None:
    """A dict assigned to `task.scorer` names scores as one passed to `Task` does."""
    task = _named_task()
    task.scorer = {"first": match(), "second": includes()}
    log = eval(task, model="mockllm/model", display="none")[0]
    assert log.status == "success"
    assert log.samples is not None and log.results is not None
    assert log.eval.scorers is not None
    assert [list(sample.scores or {}) for sample in log.samples] == [
        ["first", "second"],
        ["first", "second"],
    ]
    assert [score.name for score in log.results.scores] == ["first", "second"]
    assert [s.score_name for s in log.eval.scorers] == ["first", "second"]


def test_task_scorer_changed_in_place_is_error() -> None:
    """Names that no longer line up with `task.scorer` fail before any sample runs."""
    task = _named_task()
    assert task.scorer is not None
    task.scorer.append(includes())
    with pytest.raises(ValueError, match="3 scorers but 2 score names"):
        eval(task, model="mockllm/model", display="none")
