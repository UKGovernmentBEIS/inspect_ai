from inspect_ai import Task, eval, score, task
from inspect_ai.scorer import Score, Target, mean, scorer
from inspect_ai.solver import TaskState


@task
def my_task():
    return Task()


@scorer(metrics=[mean()])
def my_scorer(existing_uuid: str):
    async def _scorer(state: TaskState, target: Target):
        return Score(value=1 if existing_uuid == state.uuid else 0)

    return _scorer


def test_score_edit_event_span_integration():
    eval_logs = eval(
        tasks=[my_task],
        model="mockllm/model",
    )

    assert len(eval_logs) == 1

    eval_log = eval_logs[0]

    assert eval_log.samples is not None
    assert len(eval_log.samples) == 1

    sample = eval_log.samples[0]
    eval_log = score(eval_log, scorers=[my_scorer(sample.uuid)])

    assert eval_log.samples[0].scores is not None
    assert "my_scorer" in eval_log.samples[0].scores
    assert eval_log.samples[0].scores["my_scorer"].value == 1
