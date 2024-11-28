from dataclasses import dataclass

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironmentConfig,
    SandboxEnvironmentSpec,
)


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_dockerfile():
    sandbox = SandboxEnvironmentSpec(
        "docker", "tests/tools/docker-compose-context/Dockerfile"
    )
    log = eval(Task(sandbox=sandbox))[0]
    assert log.status == "success"
    assert log.eval.sandbox == sandbox


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_dockerfile_raises_for_unsupported_config():
    @dataclass(frozen=True)
    class MyConfig(SandboxEnvironmentConfig):
        pass

    sandbox = SandboxEnvironmentSpec("docker", MyConfig())
    with pytest.raises(ValueError) as e_info:
        eval(Task(sandbox=sandbox))[0]
    assert "Unsupported config type" in str(e_info.value)
