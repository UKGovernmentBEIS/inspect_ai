from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.self_check import get_test_functions, self_check


@pytest.fixture(scope="module")
async def local_sandbox(request):
    task_name = f"{__name__}_{request.node.name}_local"
    await LocalSandboxEnvironment.task_init(task_name=task_name, config=None)
    envs_dict = await LocalSandboxEnvironment.sample_init(
        task_name=task_name, config=None, metadata={}
    )
    yield envs_dict["default"]
    await envs_dict["default"].sample_cleanup(
        task_name=task_name,
        config=None,
        environments=envs_dict,
        interrupted=False,
    )
    await envs_dict["default"].task_cleanup(
        task_name=task_name, config=None, cleanup=True
    )


@pytest.fixture(scope="module")
async def docker_nonroot_sandbox(request):
    task_name = f"{__name__}_{request.node.name}_docker_nonroot"
    config_file = str(Path(__file__).parent / "test_sandbox_compose.yaml")
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config_file)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config_file, metadata={}
    )
    yield envs_dict["default"]
    await envs_dict["default"].sample_cleanup(
        task_name=task_name,
        config=config_file,
        environments=envs_dict,
        interrupted=False,
    )
    await envs_dict["default"].task_cleanup(
        task_name=task_name, config=config_file, cleanup=True
    )


@pytest.fixture(scope="module")
async def docker_root_sandbox(request):
    task_name = f"{__name__}_{request.node.name}_docker_root"
    await DockerSandboxEnvironment.task_init(task_name=task_name, config=None)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=None, metadata={}
    )
    yield envs_dict["default"]
    await envs_dict["default"].sample_cleanup(
        task_name=task_name,
        config=None,
        environments=envs_dict,
        interrupted=False,
    )
    await envs_dict["default"].task_cleanup(
        task_name=task_name, config=None, cleanup=True
    )


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", get_test_functions())
async def test_local_sandbox(local_sandbox, test_fn):
    result = await self_check(local_sandbox, test_fn)
    assert result, f"Test {test_fn.__name__} failed in local sandbox: {result}"


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", get_test_functions())
async def test_docker_nonroot_sandbox(docker_nonroot_sandbox, test_fn):
    result = await self_check(docker_nonroot_sandbox, test_fn)
    assert (
        result
    ), f"Test {test_fn.__name__} failed in docker non-root sandbox: {result}"


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", get_test_functions())
async def test_docker_root_sandbox(docker_root_sandbox, test_fn):
    result = await self_check(docker_root_sandbox, test_fn)
    if test_fn.__name__ == "test_write_file_without_permissions":
        assert (
            result
        ), f"Expected {test_fn.__name__} to fail in docker root sandbox, but it passed"
    else:
        assert (
            result
        ), f"Test {test_fn.__name__} failed in docker root sandbox: {result}"
