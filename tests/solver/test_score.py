from inspect_ai import Task, eval, task
from inspect_ai._eval.task.task import task_with
from inspect_ai.dataset import Sample
from inspect_ai.log._log import EvalLog
from inspect_ai.scorer import Score, includes
from inspect_ai.solver import Generate, TaskState, solver


@solver
def solver_with_score(score_name: str, score_value: float):
    async def solve(state: TaskState, _generate: Generate):
        state.scores = {score_name: Score(value=score_value)}
        return state

    return solve


@task
def scoring_task():
    return Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=solver_with_score("foo", 0.6),
    )


def check_scoring_log(log: EvalLog, scores: dict[str, float]):
    assert log.status == "success"
    assert log.results
    for scorer, value in scores.items():
        eval_score = next(
            (es for es in log.results.scores if es.scorer == scorer), None
        )
        assert eval_score
        assert eval_score.metrics["accuracy"].value == value


def test_solver_scoring():
    log = eval(scoring_task(), model="mockllm/model")[0]
    check_scoring_log(log, {"foo": 0.6})


def test_solver_scoring_ammend():
    task = task_with(scoring_task(), scorer=includes())
    log = eval(task, model="mockllm/model")[0]
    check_scoring_log(log, {"foo": 0.6, "includes": 0})
