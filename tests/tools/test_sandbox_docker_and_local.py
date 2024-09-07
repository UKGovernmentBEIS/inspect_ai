from pathlib import Path
from typing import AsyncGenerator, Optional, Type

import pytest
from pytest import FixtureRequest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.self_check import sandbox_test_functions


async def setup_and_teardown_sandbox(
    request: FixtureRequest,
    sandbox_class: Type[SandboxEnvironment],
    sandbox_type: str,
    config: Optional[str] = None,
) -> AsyncGenerator[SandboxEnvironment, None]:
    task_name = f"{__name__}_{request.node.name}_{sandbox_type}"

    await sandbox_class.task_init(task_name=task_name, config=config)
    envs_dict = await sandbox_class.sample_init(
        task_name=task_name, config=config, metadata={}
    )
    yield envs_dict["default"]
    await envs_dict["default"].sample_cleanup(
        task_name=task_name,
        config=config,
        environments=envs_dict,
        interrupted=False,
    )
    await envs_dict["default"].task_cleanup(
        task_name=task_name, config=config, cleanup=True
    )


@pytest.fixture(scope="module")
async def local_sandbox(
    request: FixtureRequest,
) -> AsyncGenerator[SandboxEnvironment, None]:
    async for sandbox in setup_and_teardown_sandbox(
        request, LocalSandboxEnvironment, "local"
    ):
        yield sandbox


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_local_sandbox(local_sandbox: SandboxEnvironment, test_fn):
    await test_fn(local_sandbox)


@pytest.fixture(scope="module")
async def docker_nonroot_sandbox(
    request: FixtureRequest,
) -> AsyncGenerator[SandboxEnvironment, None]:
    config_file = str(Path(__file__).parent / "test_sandbox_compose.yaml")
    async for sandbox in setup_and_teardown_sandbox(
        request, DockerSandboxEnvironment, "docker_nonroot", config_file
    ):
        yield sandbox


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_docker_nonroot_sandbox(
    docker_nonroot_sandbox: SandboxEnvironment, test_fn
):
    await test_fn(docker_nonroot_sandbox)


@pytest.fixture(scope="module")
async def docker_root_sandbox(
    request: FixtureRequest,
) -> AsyncGenerator[SandboxEnvironment, None]:
    async for sandbox in setup_and_teardown_sandbox(
        request, DockerSandboxEnvironment, "docker_root"
    ):
        yield sandbox


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_docker_root_sandbox(docker_root_sandbox: SandboxEnvironment, test_fn):
    if test_fn.__name__ == "test_write_file_without_permissions":
        pytest.skip("Root user always has write permissions.")

    await test_fn(docker_root_sandbox)
