import tempfile

from test_helpers.utils import failing_task

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, retryable_eval_logs
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


def test_eval_retry():
    # run eval with a solver that fails 2/3 times
    log = eval(failing_task, limit=1, model="mockllm/model")[0]

    # note the task id so we can be certain it remains the same
    task_id = log.eval.task_id

    # retry until we succeed (confirming the task_id is stable)
    while log.status != "success":
        log = eval_retry(log)[0]
        assert log.eval.task_id == task_id


def test_eval_retryable():
    with tempfile.TemporaryDirectory() as log_dir:
        # run eval with a solver that fails 2/3 of the time
        log = eval(tasks=failing_task, limit=1, model="mockllm/model", log_dir=log_dir)[
            0
        ]

        # note the task id so we can be certain it remains the same
        task_id = log.eval.task_id

        # retry until we succeed (confirming the task_id is stable)
        retryable = retryable_eval_logs(list_eval_logs(log_dir))
        while len(retryable) > 0:
            assert len(retryable) == 1
            assert retryable[0].task_id == task_id
            eval_retry(retryable, log_dir=log_dir)
            retryable = retryable_eval_logs(list_eval_logs(log_dir))


@task
def mytask():
    return Task(name="custom-task-name", solver=[])


def test_eval_retry_with_task_name():
    log = eval(mytask())[0]
    log = eval_retry(log)[0]


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[generate()],
        scorer=exact(),
    )


def test_eval_retry_with_model_generate_config():
    generate_config = GenerateConfig(
        seed=42,
        temperature=0.7,
        top_p=0.95,
        max_connections=1,
    )
    model = get_model(
        model="mockllm/model",
        config=generate_config,
    )

    log = eval(
        model=model,
        tasks=hello_world(),
    )[0]

    assert log.status == "success"
    assert log.eval.model_generate_config == generate_config

    log = eval_retry(log)[0]
    assert log.status == "success"
    assert log.eval.model_generate_config == generate_config
