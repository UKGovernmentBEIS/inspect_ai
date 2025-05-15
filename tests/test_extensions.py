import importlib

import pytest
from pydantic_core import to_jsonable_python
from test_helpers.tools import list_files
from test_helpers.utils import ensure_test_package_installed, skip_if_trio

from inspect_ai import Task, eval_async
from inspect_ai.dataset import Sample
from inspect_ai.model import get_model
from inspect_ai.scorer import includes
from inspect_ai.solver import generate, use_tools
from inspect_ai.util import SandboxEnvironmentSpec


@pytest.mark.asyncio
@skip_if_trio
async def test_extension_model():
    # ensure the package is installed
    ensure_test_package_installed()

    # call the model
    mdl = get_model("custom/gpt7")
    result = await mdl.generate([{"role": "user", "content": "hello"}], [], "none", {})
    assert result.completion == "Hello from gpt7"


@pytest.mark.anyio
async def test_extension_sandboxenv():
    # ensure the package is installed
    ensure_test_package_installed()

    # run a task using the sandboxenv
    task = Task(
        dataset=[
            Sample(
                input="Please use the list_files tool to list the files in the current directory"
            )
        ],
        solver=[use_tools(list_files()), generate()],
        scorer=includes(),
        sandbox="podman",
    )
    await eval_async(task, model="mockllm/model")


@pytest.mark.slow
@pytest.mark.anyio
async def test_extension_sandboxenv_with_specialised_config():
    # ensure the package is installed
    ensure_test_package_installed()
    module = importlib.import_module("inspect_package.sandboxenv.podman")
    PodmanSandboxEnvironmentConfig = module.PodmanSandboxEnvironmentConfig

    # run a task using the sandboxenv
    task = Task(
        dataset=[
            Sample(
                input="Please use the list_files tool to list the files in the current directory"
            )
        ],
        solver=[use_tools(list_files()), generate()],
        scorer=includes(),
        sandbox=SandboxEnvironmentSpec(
            "podman", PodmanSandboxEnvironmentConfig(socket_path="/path/to/socket")
        ),
    )
    logs = await eval_async(task, model="mockllm/model")

    # Ensure that the PodmanSandboxEnvironmentConfig object is serializable.
    to_jsonable_python(logs[0].eval, exclude_none=True, fallback=lambda _x: None)


def test_can_roundtrip_specialised_config():
    ensure_test_package_installed()
    module = importlib.import_module("inspect_package.sandboxenv.podman")
    PodmanSandboxEnvironmentConfig = module.PodmanSandboxEnvironmentConfig

    # Historical issue: the SandboxEnvironmentSpec type was unable to determine which
    # sandbox-specific config Pydantic model to instantiate when deserializing from
    # JSON.
    spec = SandboxEnvironmentSpec(
        type="podman",
        config=PodmanSandboxEnvironmentConfig(socket_path="/path/to/socket"),
    )
    json_str = spec.model_dump_json()
    recreated = SandboxEnvironmentSpec.model_validate_json(json_str)

    assert recreated == spec
    assert recreated.config == spec.config
    assert isinstance(recreated.config, PodmanSandboxEnvironmentConfig)


def test_can_load_log_file_for_unavailable_sandbox_environment():
    json_str = """{"type":"unavailable","config":{"key":"value"}}"""

    recreated = SandboxEnvironmentSpec.model_validate_json(json_str)

    assert isinstance(recreated.config, dict)


def test_supports_str_config():
    spec = SandboxEnvironmentSpec(type="podman", config="/path/to/socket")
    json_str = spec.model_dump_json()
    recreated = SandboxEnvironmentSpec.model_validate_json(json_str)

    assert recreated == spec
    assert recreated.config == spec.config
    assert isinstance(recreated.config, str)
