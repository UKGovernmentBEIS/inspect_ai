import contextlib
import importlib.util
import os
import signal
import subprocess
import sys
from pathlib import Path
from random import random
from types import FrameType
from typing import Generator, Sequence

import anyio
import pytest

from inspect_ai import Task, eval, task
from inspect_ai._util._async import configured_async_backend
from inspect_ai.dataset import Sample
from inspect_ai.model import ChatMessage, ModelName, ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import Generate, TaskState, generate, solver


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


def skip_if_no_mcp_package(func):
    return skip_if_no_package("mcp")(func)


def skip_if_no_mcp_fetch_package(func):
    return skip_if_no_package("mcp_server_fetch")(func)


def skip_if_no_mcp_git_package(func):
    return skip_if_no_package("mcp_server_git")(func)


def skip_if_no_vllm(func):
    return skip_if_no_package("vllm")(func)


def skip_if_no_transformers(func):
    return skip_if_no_package("transformers")(func)


def skip_if_no_accelerate(func):
    return skip_if_no_package("accelerate")(func)


def skip_if_no_openai(func):
    return pytest.mark.api(
        pytest.mark.skipif(
            importlib.util.find_spec("openai") is None
            or os.environ.get("OPENAI_API_KEY") is None,
            reason="Test requires both OpenAI package and OPENAI_API_KEY environment variable",
        )(func)
    )


def skip_if_no_openai_azure(func):
    return pytest.mark.skipif(
        importlib.util.find_spec("openai") is None
        or os.environ.get("AZUREAI_OPENAI_API_KEY") is None
        or os.environ.get("AZUREAI_OPENAI_BASE_URL") is None,
        reason="Test requires both OpenAI package and AZUREAI_OPENAI_API_KEY and AZUREAI_OPENAI_BASE_URL environment variables",
    )(func)


def skip_if_no_openai_package(func):
    return skip_if_no_package("openai")(func)


def skip_if_no_openai_reasoning_summaries(func):
    return pytest.mark.api(
        skip_if_env_var("ENABLE_OPENAI_REASONING_SUMMARIES", exists=False)(func)
    )


def skip_if_no_anthropic(func):
    return pytest.mark.api(skip_if_env_var("ANTHROPIC_API_KEY", exists=False)(func))


def skip_if_no_google(func):
    return pytest.mark.api(skip_if_env_var("GOOGLE_API_KEY", exists=False)(func))


def skip_if_no_mistral(func):
    return pytest.mark.api(skip_if_env_var("MISTRAL_API_KEY", exists=False)(func))


def skip_if_no_mistral_package(func):
    return skip_if_no_package("mistralai")(func)


def skip_if_no_grok(func):
    return pytest.mark.api(skip_if_env_var("GROK_API_KEY", exists=False)(func))


def skip_if_no_cloudflare(func):
    return pytest.mark.api(skip_if_env_var("CLOUDFLARE_API_KEY", exists=False)(func))


def skip_if_no_together(func):
    return pytest.mark.api(skip_if_env_var("TOGETHER_API_KEY", exists=False)(func))


def skip_if_no_together_base_url(func):
    return pytest.mark.api(skip_if_env_var("TOGETHER_BASE_URL", exists=False)(func))


def skip_if_no_perplexity(func):
    missing_requirements = []
    if importlib.util.find_spec("openai") is None:
        missing_requirements.append("openai package")
    if os.environ.get("PERPLEXITY_API_KEY") is None:
        missing_requirements.append("PERPLEXITY_API_KEY environment variable")

    return pytest.mark.api(
        pytest.mark.skipif(
            len(missing_requirements) > 0,
            reason=f"Test requires: {', '.join(missing_requirements)}",
        )(func)
    )


def skip_if_no_perplexity_package(func):
    return skip_if_no_package("openai")(func)


def skip_if_no_azureai(func):
    return pytest.mark.api(skip_if_env_var("AZUREAI_API_KEY", exists=False)(func))


def skip_if_no_llama_cpp_python(func):
    return pytest.mark.api(
        skip_if_env_var("ENABLE_LLAMA_CPP_PYTHON_TESTS", exists=False)(func)
    )


def skip_if_no_bedrock(func):
    return pytest.mark.api(skip_if_env_var("ENABLE_BEDROCK_TESTS", exists=False)(func))


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


def skip_if_async_backend(backend):
    return pytest.mark.skipif(
        configured_async_backend() == backend,
        reason=f"Test not compatible with {backend} async backend.",
    )


def skip_if_trio(func):
    return skip_if_async_backend("trio")(func)


def skip_if_asyncio(func):
    return skip_if_async_backend("asyncio")(func)


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
            raise FileNotFoundError(f"File {file} does not exist.")

        return state

    return solve


@solver
def failing_solver(rate=0.5):
    async def solve(state: TaskState, generate: Generate):
        value = random()
        if value < rate:
            raise ValueError("Eval failed!")

        return state

    return solve


@task
def failing_task(rate=0.5, samples=1) -> Task:
    dataset: list[Sample] = []
    for _ in range(0, samples):
        dataset.append(Sample(input="Say hello", target="hello"))
    return Task(
        dataset=dataset,
        solver=[failing_solver(rate), generate()],
        scorer=match(),
    )


@solver
def failing_solver_deterministic(should_fail: Sequence[bool]):
    it = iter(should_fail)

    async def solve(state: TaskState, generate: Generate):
        should_fail_this_time = it.__next__()
        if should_fail_this_time:
            raise ValueError("Eval failed!")
        return state

    return solve


@task
def failing_task_deterministic(should_fail: Sequence[bool]) -> Task:
    dataset: list[Sample] = []
    for _ in range(0, len(should_fail)):
        dataset.append(Sample(input="Say hello", target="hello"))
    return Task(
        dataset=dataset,
        plan=[failing_solver_deterministic(should_fail), generate()],
        scorer=match(),
    )


@solver
def sleep_for_solver(seconds: int):
    async def solve(state: TaskState, generate: Generate):
        await anyio.sleep(seconds)
        return state

    return solve


@solver
def identity_solver():
    async def solve(state: TaskState, generate: Generate):
        return state

    return solve


def ensure_test_package_installed():
    try:
        import inspect_package  # type: ignore # noqa: F401
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--no-deps", "tests/test_package"]
        )


@contextlib.contextmanager
def keyboard_interrupt(seconds: int) -> Generator[None, None, None]:
    def handler(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    original_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(seconds)

    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, original_handler)
