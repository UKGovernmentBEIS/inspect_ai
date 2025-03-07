from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.model import Model, get_model


def check_task_model(task):
    log = eval(task)[0]
    assert log.status == "success"
    assert log.eval.model == "mockllm/model"
    return log


def test_task_model():
    task = Task(model="mockllm/model")
    check_task_model(task)


@task
def dynamic_model(model: str | Model):
    return Task(model=model)


def check_task_model_arg(model):
    task = dynamic_model(model)
    log = check_task_model(task)
    log = eval_retry(log)[0]
    assert log.status == "success"
    assert log.eval.model == "mockllm/model"
    return log


def test_task_model_str_arg():
    check_task_model_arg("mockllm/model")


def test_task_model_object_arg():
    check_task_model_arg(get_model("mockllm/model"))


def test_task_model_object_arg_with_args():
    log = check_task_model_arg(
        get_model("mockllm/model", base_url="https://example.com", foo="bar")
    )
    assert log.eval.model_base_url == "https://example.com"
    assert log.eval.model_args["foo"] == "bar"
