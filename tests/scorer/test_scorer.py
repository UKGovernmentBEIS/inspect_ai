# type: ignore

from copy import deepcopy

import pytest
from test_helpers.utils import ensure_test_package_installed, run_example

from inspect_ai import Task, eval, score
from inspect_ai._eval.score import ScoreAction
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, recompute_metrics
from inspect_ai.scorer import Score, Scorer, Target, accuracy, includes, scorer
from inspect_ai.scorer._scorer import scorer_create
from inspect_ai.solver import TaskState


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


@scorer(metrics=[accuracy()])
def first_scorer(threshold: float = 0.5) -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1.0, answer="first")

    return score


@scorer(metrics=[accuracy()])
def second_scorer() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=0.0, answer="second")

    return score


def _three_sample_log() -> EvalLog:
    task = Task(
        dataset=[Sample(input=f"Question {id}", target="x", id=id) for id in (1, 2, 3)],
        scorer=first_scorer(threshold=0.9),
    )
    return eval(tasks=task, model="mockllm/model", display="none")[0]


@pytest.mark.parametrize("action", ["overwrite", "append"])
def test_score_sample_ids_leaves_other_samples_untouched(action: ScoreAction) -> None:
    log = _three_sample_log()
    assert log.samples is not None
    before = {sample.id: deepcopy(sample.scores) for sample in log.samples}

    rescored = score(log, second_scorer(), action=action, sample_ids=[2])

    assert rescored.samples is not None
    by_id = {sample.id: sample for sample in rescored.samples}
    assert by_id[1].scores == before[1]
    assert by_id[3].scores == before[3]
    assert by_id[2].scores is not None
    if action == "overwrite":
        assert [*by_id[2].scores] == ["second_scorer"]
    else:
        assert [*by_id[2].scores] == ["first_scorer", "second_scorer"]
    assert by_id[2].scores["second_scorer"].answer == "second"

    # results describe the whole log, not only the rescored sample, and the
    # header still describes the scorer whose scores survive on the others
    assert rescored.results is not None
    results = {score.name: score for score in rescored.results.scores}
    assert results["second_scorer"].metrics["accuracy"].value == 0.0
    assert results["first_scorer"].metrics["accuracy"].value == 1.0
    assert results["first_scorer"].params == {"threshold": 0.9}
    assert rescored.results.total_samples == 3
    assert rescored.results.completed_samples == 3
    assert rescored.eval.scorers is not None
    header = {s.name: s for s in rescored.eval.scorers}
    assert set(header) == {"first_scorer", "second_scorer"}
    assert header["first_scorer"].options == {"threshold": 0.9}


def test_score_sample_ids_same_scorer_keeps_one_result() -> None:
    """Regrading a few samples with the task's own scorer is the common case."""
    log = _three_sample_log()
    rescored = score(
        log, first_scorer(threshold=0.9), action="overwrite", sample_ids=[2]
    )
    assert rescored.results is not None
    assert [s.name for s in rescored.results.scores] == ["first_scorer"]
    assert rescored.results.scores[0].metrics["accuracy"].value == 1.0
    assert rescored.reductions is not None
    assert len(rescored.reductions[0].samples) == 3
    assert rescored.eval.scorers is not None
    assert [s.name for s in rescored.eval.scorers] == ["first_scorer"]


def test_score_sample_ids_glob_pattern() -> None:
    task = Task(
        dataset=[Sample(input="q", target="x", id=id) for id in ("a-1", "a-2", "b-1")],
        scorer=first_scorer(),
    )
    log = eval(tasks=task, model="mockllm/model", display="none")[0]
    rescored = score(log, second_scorer(), action="overwrite", sample_ids="a-*")
    assert rescored.samples is not None
    by_id = {sample.id: [*sample.scores] for sample in rescored.samples}
    assert by_id == {
        "a-1": ["second_scorer"],
        "a-2": ["second_scorer"],
        "b-1": ["first_scorer"],
    }


def test_score_sample_ids_unknown_id_raises() -> None:
    log = _three_sample_log()
    with pytest.raises(ValueError, match="42"):
        score(log, second_scorer(), action="overwrite", sample_ids=[2, 42])
    with pytest.raises(ValueError, match="empty"):
        score(log, second_scorer(), action="overwrite", sample_ids=[])
