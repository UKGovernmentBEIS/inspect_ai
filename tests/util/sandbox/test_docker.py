import asyncio
import pytest
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment

@pytest.mark.asyncio
async def test_docker_sandbox_exec():
    # Initialize a DockerSandboxEnvironment
    sandbox = DockerSandboxEnvironment(service="default", project=None)  # Adjust service and project as needed

    # Execute a simple command
    result = await sandbox.exec(["echo", "hello"])

    # Check the result
    assert result.success
    assert result.stdout.strip() == "hello"
