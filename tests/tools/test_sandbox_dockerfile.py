import pytest
from pydantic import BaseModel
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_dockerfile():
    sandbox = SandboxEnvironmentSpec(
        "docker", "tests/tools/docker-compose-context/Dockerfile"
    )
    log = eval(Task(sandbox=sandbox, model="mockllm/model"))[0]
    assert log.status == "success"
    assert log.eval.sandbox == sandbox


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_dockerfile_raises_for_unsupported_config():
    class MyConfig(BaseModel, frozen=True):
        pass

    # a setup error ends the task with its error log
    sandbox = SandboxEnvironmentSpec("docker", MyConfig())
    log = eval(Task(sandbox=sandbox), model="mockllm/model")[0]
    assert log.status == "error"
    assert log.error is not None
    assert "Unsupported config type" in log.error.message
