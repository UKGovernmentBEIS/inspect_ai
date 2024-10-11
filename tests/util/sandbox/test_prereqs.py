import pytest
from inspect_ai.util._sandbox.docker.prereqs import validate_docker_engine, validate_docker_compose


@pytest.mark.asyncio
async def test_validate_docker_engine():
    # This test will pass if Docker is installed and meets the version requirement
    await validate_docker_engine()

@pytest.mark.asyncio
async def test_validate_docker_compose():
    # This test will pass if Docker Compose is installed and meets the version requirement
    await validate_docker_compose()