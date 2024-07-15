import random

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import Score, Target, mean, scorer, stderr
from inspect_ai.solver import TaskState


@scorer(metrics=[mean(), stderr()])
def rand_score():
    async def score(state: TaskState, target: Target):
        answer = state.output.completion
        return Score(value=random.randint(1, 100), answer=answer)

    return score


@scorer(metrics=[mean(), stderr()])
def another_rand_score():
    async def score(state: TaskState, target: Target):
        answer = state.output.completion
        return Score(value=random.randint(1, 100), answer=answer)

    return score


@scorer(metrics={"a_count": [mean(), stderr()], "e_count": [mean(), stderr()]})
def letter_count():
    async def score(state: TaskState, target: Target):
        answer = state.output.completion
        a_count = answer.count("a")
        e_count = answer.count("e")
        return Score(value={"a_count": a_count, "e_count": e_count}, answer=answer)

    return score


def check_log(log, scorers, metrics):
    # core checks
    assert log.results
    assert log.results.scores
    assert len(log.results.scores) == len(scorers)

    scorer_names = [scorer.name for scorer in log.results.scores]
    assert all(scorer in scorer_names for scorer in scorers)
    assert all(
        all(metric in scorer.metrics for metric in metrics)
        for scorer in log.results.scores
    )

    # test deprecated fields for now
    assert log.results.scorer is not None
    assert log.results.metrics is not None


# test a single scorer
def test_single_scorer() -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=rand_score(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log, ["rand_score"], ["mean", "stderr"])


# test two scorers
def test_multi_scorer() -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=[rand_score(), another_rand_score()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log, ["rand_score", "another_rand_score"], ["mean", "stderr"])


# test dictionary scorer
def test_dict_scorer() -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=letter_count(),
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log, ["a_count", "e_count"], ["mean", "stderr"])


# test blend of dictionary and simple scorers
def test_blend_scorer() -> None:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        scorer=[letter_count(), rand_score()],
    )

    # normal eval
    log = eval(tasks=task, model="mockllm/model")[0]
    check_log(log, ["a_count", "e_count", "rand_score"], ["mean", "stderr"])
