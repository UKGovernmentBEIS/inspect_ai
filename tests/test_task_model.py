import tempfile

import pytest

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessage,
    GenerateConfig,
    Model,
    ModelAPI,
    ModelOutput,
    get_model,
    modelapi,
)
from inspect_ai.solver import generate
from inspect_ai.tool import ToolChoice, ToolInfo


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


class _NameMutatingAPI(ModelAPI):
    """Mimics vLLM: rewrites a ``base:adapter`` name to ``base`` on generate()."""

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        super().__init__(model_name, base_url, api_key, [], config)

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # the rewrite that broke str(model)-keyed balancing
        self.model_name = self.model_name.split(":")[0]
        return ModelOutput.from_content(self.model_name, "ok")


@modelapi(name="namemut")
def namemut():
    return _NameMutatingAPI


@pytest.mark.parametrize("task_retry_attempts", [0, 1])
def test_dispatch_survives_model_name_mutation(task_retry_attempts: int) -> None:
    """Balancing dispatch must survive a provider rewriting its name mid-run.

    The vLLM provider resolves a ``base:adapter`` LoRA spec down to ``base`` on
    the first ``generate()``. The dispatchers in ``_eval/run.py`` track in-flight
    tasks per model, incrementing at dispatch and decrementing at completion.
    Keying that count by ``str(model)`` meant the decrement targeted a different
    key than the increment once the name changed, raising ``KeyError`` at
    finalisation (e.g. ``"namemut/base"``). ``task_retry_attempts==0`` routes
    through ``run_multiple``, ``>0`` through ``run_task_retry_attempts``.
    """
    with tempfile.TemporaryDirectory() as log_dir:
        logs = eval(
            Task(
                dataset=[Sample(input="x", target="y")],
                solver=generate(),
                name="name_mutation_task",
            ),
            model="namemut/base:adapter",
            log_dir=log_dir,
            task_retry_attempts=task_retry_attempts,
        )

    assert logs[0].status == "success"
