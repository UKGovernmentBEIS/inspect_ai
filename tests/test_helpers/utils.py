import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

from inspect_ai import eval
from inspect_ai.model import ChatMessage, ModelName, ModelOutput
from inspect_ai.solver import Generate, TaskState, solver


def skip_if_env_var(var: str, exists=True):
    """
    Pytest mark to skip the test if the var environment variable is not defined.

    Use in combination with `pytest.mark.api` if the environment variable in
    question corresponds to a paid API. For example, see `skip_if_no_openai`.
    """
    condition = (var in os.environ.keys()) if exists else (var not in os.environ.keys())
    return pytest.mark.skipif(
        condition,
        reason=f"Test doesn't work without {var} environment variable defined.",
    )


def skip_if_no_groq(func):
    return pytest.mark.api(skip_if_env_var("GROQ_API_KEY", exists=False)(func))


def skip_if_no_package(package):
    return pytest.mark.skipif(
        importlib.util.find_spec(package) is None,
        reason=f"Test doesn't work without package {package} installed",
    )


def skip_if_no_vllm(func):
    return skip_if_no_package("vllm")(func)


def skip_if_no_transformers(func):
    return skip_if_no_package("transformers")(func)


def skip_if_no_accelerate(func):
    return skip_if_no_package("accelerate")(func)


def skip_if_no_openai(func):
    return pytest.mark.api(skip_if_env_var("OPENAI_API_KEY", exists=False)(func))


def skip_if_no_anthropic(func):
    return pytest.mark.api(skip_if_env_var("ANTHROPIC_API_KEY", exists=False)(func))


def skip_if_no_google(func):
    return pytest.mark.api(skip_if_env_var("GOOGLE_API_KEY", exists=False)(func))


def skip_if_no_mistral(func):
    return pytest.mark.api(skip_if_env_var("MISTRAL_API_KEY", exists=False)(func))


def skip_if_no_cloudflare(func):
    return pytest.mark.api(skip_if_env_var("CLOUDFLARE_API_TOKEN", exists=False)(func))


def skip_if_no_together(func):
    return pytest.mark.api(skip_if_env_var("TOGETHER_API_KEY", exists=False)(func))


def skip_if_no_azureai(func):
    return pytest.mark.api(skip_if_env_var("AZURE_API_KEY", exists=False)(func))


def skip_if_no_vertex(func):
    return pytest.mark.api(skip_if_env_var("ENABLE_VERTEX_TESTS", exists=False)(func))


def skip_if_github_action(func):
    return skip_if_env_var("GITHUB_ACTIONS", exists=True)(func)


def skip_if_no_docker(func):
    try:
        is_docker_installed = (
            subprocess.run(
                ["docker", "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).returncode
            == 0
        )
    except FileNotFoundError:
        is_docker_installed = False

    return pytest.mark.skipif(
        not is_docker_installed, reason="Test doesn't work without Docker installed."
    )(func)


def run_example(example: str, model: str):
    example_file = os.path.join("examples", example)
    return eval(example_file, model=model, limit=1)


# The intention of this `simple_task_state` helper is to remove some of the
# boiler plate of creating a task for use in solver checks where we just need
# "some" state. Over time this will likely expand and need to be extracted into
# its own helper file with multiple options.
def simple_task_state(
    choices: list[str] = [],
    messages: list[ChatMessage] = [],
    model_output: str = "",
) -> TaskState:
    return TaskState(
        choices=choices,
        epoch=0,
        input=[],
        messages=messages,
        model=ModelName(model="fake/model"),
        output=ModelOutput.from_content(model="model", content=model_output),
        sample_id=0,
    )


@solver
def file_check(file: str):
    async def solve(state: TaskState, generate: Generate):
        if not Path(file).exists():
            raise ValueError(f"File {file} does not exist.")

        return state

    return solve
