from utils import run_example, skip_if_no_openai

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


@skip_if_no_openai
def test_no_scorer():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
    )
    log = eval(task)[0]
    assert log.samples[0].score is None


@skip_if_no_openai
def test_score_function():
    log = run_example("popularity.py", "openai/gpt-4")
    log = score(log[0], includes())
    assert log.samples[0].score.value
