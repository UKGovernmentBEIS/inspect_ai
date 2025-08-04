from inspect_ai import eval
from inspect_ai._eval.score import score
from inspect_ai._eval.task.task import Task
from inspect_ai.scorer._metric import Score
from inspect_ai.scorer._metrics.accuracy import accuracy
from inspect_ai.scorer._scorer import scorer
from inspect_ai.solver._solver import solver
from inspect_ai.util._store import store


def test_score_store_access():
    @solver
    def store_writer():
        async def solve(state, generate):
            state.store.set("answer", 42)
            return state

        return solve

    log = eval(Task(solver=store_writer(), model="mockllm/model"))[0]

    @scorer(metrics=[accuracy()])
    def store_reader():
        async def score(state, target):
            return Score(
                value=state.store.get("answer") == 42 and store().get("answer") == 42
            )

        return score

    log = score(log, store_reader())
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1
