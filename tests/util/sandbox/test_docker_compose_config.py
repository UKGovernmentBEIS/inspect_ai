"""Tests for ComposeConfig support in Docker sandbox."""

import os

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util import ComposeConfig, ComposeService
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.util import ComposeProject


@skip_if_no_docker
async def test_compose_project_create_with_compose_config(request) -> None:
    """Test that ComposeProject.create() accepts ComposeConfig objects."""
    task_name = f"{__name__}_{request.node.name}"

    config = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    project = await ComposeProject.create(
        name=task_name,
        config=config,
    )

    try:
        # Verify the project was created with a valid config path
        assert project.config is not None
        assert project.config.endswith(".compose.yaml")
        assert os.path.exists(project.config)

        # Verify the generated YAML contains expected content
        with open(project.config, "r") as f:
            content = f.read()
            assert "python:3.12-bookworm" in content
            assert "tail -f /dev/null" in content
    finally:
        # Clean up the auto-generated compose file
        if project.config and os.path.exists(project.config):
            os.unlink(project.config)


@skip_if_no_docker
@pytest.mark.slow
async def test_docker_sandbox_with_compose_config(request) -> None:
    """Test that DockerSandboxEnvironment works with ComposeConfig objects."""
    task_name = f"{__name__}_{request.node.name}"

    config = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    await DockerSandboxEnvironment.task_init(task_name=task_name, config=config)
    envs_dict = await DockerSandboxEnvironment.sample_init(
        task_name=task_name, config=config, metadata={}
    )

    try:
        sandbox_env = envs_dict["default"]

        # Verify we can execute commands in the sandbox
        result = await sandbox_env.exec(["echo", "hello"])
        assert result.success
        assert result.stdout.strip() == "hello"
    finally:
        await DockerSandboxEnvironment.sample_cleanup(
            task_name=task_name,
            config=config,
            environments=envs_dict,
            interrupted=False,
        )
        await DockerSandboxEnvironment.task_cleanup(
            task_name=task_name, config=config, cleanup=True
        )


@skip_if_no_docker
async def test_compose_config_hashable():
    """Test that ComposeConfig is hashable and can be used in sets."""
    config1 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    config2 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.12-bookworm",
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    config3 = ComposeConfig(
        services={
            "default": ComposeService(
                image="python:3.13-bookworm",  # Different image
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )

    # Test hashability
    hash1 = hash(config1)
    hash2 = hash(config2)
    hash3 = hash(config3)

    # Same content should have same hash
    assert hash1 == hash2
    # Different content should have different hash
    assert hash1 != hash3

    # Test equality
    assert config1 == config2
    assert config1 != config3

    # Test use in set
    config_set = {config1, config2, config3}
    assert len(config_set) == 2  # config1 and config2 are equal


@skip_if_no_docker
async def test_compose_config_with_extensions(request) -> None:
    """Test that ComposeConfig preserves x- extension fields."""
    task_name = f"{__name__}_{request.node.name}"

    # Create a ComposeService with x-default extension
    service = ComposeService(
        image="python:3.12-bookworm",
        init=True,
        command="tail -f /dev/null",
        network_mode="none",
        **{"x-default": True},  # type: ignore
    )

    config = ComposeConfig(services={"myservice": service})
    project = await ComposeProject.create(name=task_name, config=config)

    try:
        # Verify the generated YAML contains the x-default extension
        # The field is serialized with its alias "x-default" due to by_alias=True
        with open(project.config, "r") as f:  # type: ignore
            content = f.read()
            # Check that x-default is present
            assert "x-default: true" in content
    finally:
        if project.config and os.path.exists(project.config):
            os.unlink(project.config)
