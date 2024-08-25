import pytest

from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment


@pytest.mark.asyncio
async def test_docker_sandbox_exec():
    sandbox = DockerSandboxEnvironment(service="default", project=None)
    result = await sandbox.exec(["echo", "hello"])
    # Check the result
    assert result.success
    assert result.stdout.strip() == "hello"
