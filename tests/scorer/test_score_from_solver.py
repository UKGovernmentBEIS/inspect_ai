from inspect_ai import Task, eval
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.scorer import Score, mean
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.solver._solver import Solver


@solver
def no_scorer_solver_dict() -> Solver:
    async def run(state: TaskState, generate: Generate) -> TaskState:
        state.scores = {} if state.scores is None else state.scores
        state.scores["simple"] = Score(value={"base_val": 1, "other_val": 2})
        return state

    return run


def test_solver_dict_score():
    task = Task(
        dataset=MemoryDataset([Sample(input="")]),
        solver=no_scorer_solver_dict(),
        metrics={"*": [mean()]},
    )
    eval_log = eval(tasks=task, model="mockllm/model")[0]
    assert eval_log.results.scores[0].name == "base_val"
    assert eval_log.results.scores[1].name == "other_val"
    assert len(eval_log.results.scores[0].metrics) == 1
    assert len(eval_log.results.scores[1].metrics) == 1
    assert eval_log.results.scores[0].metrics["mean"].value == 1
    assert eval_log.results.scores[1].metrics["mean"].value == 2


@solver
def no_scorer_solver_simple() -> Solver:
    async def run(state: TaskState, generate: Generate) -> TaskState:
        state.scores = {} if state.scores is None else state.scores
        state.scores["simple"] = Score(value=1)
        return state

    return run


def test_solver_simple_score():
    task = Task(
        dataset=MemoryDataset([Sample(input="")]),
        solver=no_scorer_solver_simple(),
        metrics=[mean()],
    )
    eval_log = eval(tasks=task, model="mockllm/model")[0]
    assert eval_log.results.scores[0].name == "simple"
    assert len(eval_log.results.scores[0].metrics) == 1
    assert eval_log.results.scores[0].metrics["mean"].value == 1.0
