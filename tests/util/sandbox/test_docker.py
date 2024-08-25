import asyncio
import pytest
from inspect_ai.util._sandbox.docker.util import ComposeProject

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment


@pytest.mark.asyncio
async def test_docker_sandbox_exec():
    # Create a temporary ComposeProject
    project = await ComposeProject.create(name="test_project", config=None)

    # Initialize the DockerSandboxEnvironment
    sandbox = DockerSandboxEnvironment(service="default", project=project)
    result = await sandbox.exec(["echo", "hello"])
    # Check the result
    assert result.success
    assert result.stdout.strip() == "hello"
