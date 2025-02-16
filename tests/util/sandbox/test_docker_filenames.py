import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval, task
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


@task
def docker_config_file(config_file: str | None):
    return Task(sandbox=SandboxEnvironmentSpec(type="docker", config=config_file))


def check_docker_config_file(config_file: str | None) -> None:
    log = eval(docker_config_file(config_file), model="mockllm/model")[0]
    assert log.status == "success"


@pytest.mark.slow
@skip_if_no_docker
def test_dockerfile_none():
    check_docker_config_file(None)


@pytest.mark.slow
@skip_if_no_docker
def test_dockerfile_standard():
    check_docker_config_file("Dockerfile")


@pytest.mark.slow
@skip_if_no_docker
def test_dockerfile_stem():
    check_docker_config_file("debug.Dockerfile")


@pytest.mark.slow
@skip_if_no_docker
def test_dockerfile_extension():
    check_docker_config_file("Dockerfile.debug")
