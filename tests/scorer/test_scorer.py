import pytest
from test_helpers.utils import run_example

from inspect_ai import Task, eval, score
from inspect_ai.dataset import Sample
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
