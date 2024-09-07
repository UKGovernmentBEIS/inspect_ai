from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.self_check import sandbox_test_functions


async def setup_and_teardown_sandbox(request, sandbox_class, sandbox_type, config=None):
    task_name = f"{__name__}_{request.node.name}_{sandbox_type}"

    if config and isinstance(config, str):
        config_file = str(Path(__file__).parent / config)
    else:
        config_file = config

    await sandbox_class.task_init(task_name=task_name, config=config_file)
    envs_dict = await sandbox_class.sample_init(
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
async def local_sandbox(request):
    async for sandbox in setup_and_teardown_sandbox(
        request, LocalSandboxEnvironment, "local"
    ):
        yield sandbox


@pytest.fixture(scope="module")
async def docker_nonroot_sandbox(request):
    async for sandbox in setup_and_teardown_sandbox(
        request, DockerSandboxEnvironment, "docker_nonroot", "test_sandbox_compose.yaml"
    ):
        yield sandbox


@pytest.fixture(scope="module")
async def docker_root_sandbox(request):
    async for sandbox in setup_and_teardown_sandbox(
        request, DockerSandboxEnvironment, "docker_root"
    ):
        yield sandbox


# The test functions remain unchanged
@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_local_sandbox(local_sandbox, test_fn):
    await test_fn(local_sandbox)


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_docker_nonroot_sandbox(docker_nonroot_sandbox, test_fn):
    await test_fn(docker_nonroot_sandbox)


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_docker_root_sandbox(docker_root_sandbox, test_fn):
    if test_fn.__name__ == "test_write_file_without_permissions":
        pytest.skip("Root user always has write permissions")

    await test_fn(docker_root_sandbox)
