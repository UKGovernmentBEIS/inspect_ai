import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.util._sandbox.environment import SandboxEnvironmentSpec


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_dockerfile():
    sandbox = SandboxEnvironmentSpec(
        "docker", "tests/tools/docker-compose-context/Dockerfile"
    )
    log = eval(Task(sandbox=sandbox))[0]
    assert log.status == "success"
    assert log.eval.sandbox == sandbox
