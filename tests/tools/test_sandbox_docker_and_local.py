from pathlib import Path
from typing import AsyncGenerator, Optional, Type

import pytest
from pytest import FixtureRequest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.self_check import sandbox_test_functions


async def setup_sandbox(
    sandbox_class: Type[SandboxEnvironment],
    sandbox_type: str,
    config: Optional[str] = None,
) -> SandboxEnvironment:
    await sandbox_class.task_init(task_name=sandbox_type, config=config)
    envs_dict = await sandbox_class.sample_init(
        task_name=sandbox_type, config=config, metadata={}
    )
    return envs_dict["default"]


async def teardown_sandbox(
    sandbox: SandboxEnvironment,
    request: FixtureRequest,
    sandbox_type: str,
    config: Optional[str] = None,
) -> None:
    task_name = f"{__name__}_{request.node.name}_{sandbox_type}"
    await sandbox.sample_cleanup(
        task_name=task_name,
        config=config,
        environments={"default": sandbox},
        interrupted=False,
    )
    await sandbox.task_cleanup(task_name=task_name, config=config, cleanup=True)


@pytest.fixture(scope="module")
async def local_sandbox(
    request: FixtureRequest,
) -> AsyncGenerator[SandboxEnvironment, None]:
    sandbox = await setup_sandbox(LocalSandboxEnvironment, "local")
    yield sandbox
    await teardown_sandbox(sandbox, request, "local")


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
    sandbox = await setup_sandbox(
        DockerSandboxEnvironment, "docker_nonroot", config_file
    )
    yield sandbox
    await teardown_sandbox(sandbox, request, "docker_nonroot", config_file)


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
    sandbox = await setup_sandbox(DockerSandboxEnvironment, "docker_root")
    yield sandbox
    await teardown_sandbox(sandbox, request, "docker_root")


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("test_fn", sandbox_test_functions())
async def test_docker_root_sandbox(docker_root_sandbox: SandboxEnvironment, test_fn):
    if test_fn.__name__ == "test_write_file_without_permissions":
        pytest.skip("Root user always has write permissions.")

    await test_fn(docker_root_sandbox)
