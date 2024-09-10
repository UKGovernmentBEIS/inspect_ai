from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.local import LocalSandboxEnvironment
from inspect_ai.util._sandbox.self_check import self_check


@skip_if_no_docker
@pytest.mark.slow
async def test_self_check_local(request) -> None:
    task_name = f"{__name__}_{request.node.name}_local"

    await LocalSandboxEnvironment.task_init(task_name=task_name, config=None)
    envs_dict = await LocalSandboxEnvironment.sample_init(
        task_name=task_name, config=None, metadata={}
    )

    known_failures = ["test_exec_as_user", "test_exec_as_nonexistent_user"]

    return await check_results_of_self_check(task_name, envs_dict, known_failures)


@skip_if_no_docker
@pytest.mark.slow
async def test_self_check_docker_custom_nonroot(request) -> None:
    task_name = f"{__name__}_{request.node.name}_docker_nonroot"

    # The default docker-compose used in Inspect uses the root user in the container.
    # The root user is allowed to overwrite files even if they're read-only.
    # This breaks the sematics of the sandbox, so we use a non-root user for these tests.
    config_file = str(Path(__file__) / ".." / "test_sandbox_compose.yaml")

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config_file)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config_file, metadata={}
    )

    return await check_results_of_self_check(task_name, envs_dict)


@skip_if_no_docker
@pytest.mark.slow
async def test_self_check_docker_custom_nonroot_alpine(request) -> None:
    task_name = f"{__name__}_{request.node.name}_docker_nonroot_alpine"

    # Alpine has busybox which is has a bunch of stuff "missing" if you are used to GNU.
    config_file = str(Path(__file__) / ".." / "test_sandbox_compose_alpine.yaml")

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config_file)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config_file, metadata={}
    )

    return await check_results_of_self_check(
        # alpine busybox is happy to overwrite a readonly file with cp
        task_name,
        envs_dict,
        ["test_write_file_without_permissions"],
    )


@skip_if_no_docker
@pytest.mark.slow
async def test_self_check_docker_default_root(request) -> None:
    task_name = f"{__name__}_{request.node.name}_docker_root"

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=None)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=None, metadata={}
    )

    return await check_results_of_self_check(
        task_name, envs_dict, ["test_write_file_without_permissions"]
    )


async def check_results_of_self_check(task_name, envs_dict, known_failures=[]):
    sandbox_env = envs_dict["default"]

    try:
        self_check_results = await self_check(sandbox_env)
        failures = []
        for test_name, result in self_check_results.items():
            if result is not True and test_name not in known_failures:
                failures.append(f"Test {test_name} failed: {result}")
        if failures:
            assert False, "\n".join(failures)
    finally:
        await sandbox_env.sample_cleanup(
            task_name=task_name,
            config=None,
            environments=envs_dict,
            interrupted=False,
        )
        await sandbox_env.task_cleanup(task_name=task_name, config=None, cleanup=True)
