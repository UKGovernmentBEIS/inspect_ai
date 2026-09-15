"""Tests for ComposeConfig support in Docker sandbox."""

import os
from pathlib import Path

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util import ComposeConfig, ComposeService
from inspect_ai.util._sandbox.docker import cleanup as cleanup_module
from inspect_ai.util._sandbox.docker import config as docker_config
from inspect_ai.util._sandbox.docker.compose import Project
from inspect_ai.util._sandbox.docker.config import (
    auto_compose_dir,
    is_auto_compose_file,
)
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
        # Auto-compose files are now stored in the central directory
        assert is_auto_compose_file(project.config)
        assert Path(project.config).parent == auto_compose_dir()
        assert project.config.endswith(".yaml")
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


async def test_retained_project_preserves_config_until_exact_cleanup(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    """A retained project keeps its network config for later project-scoped cleanup."""
    project_name = "inspect-retained-iabcdef"
    other_project_name = "inspect-other-ighijkl"
    config_path = tmp_path / f"{project_name}.yaml"
    other_config_path = tmp_path / f"{other_project_name}.yaml"
    config_path.write_text(
        "services:\n  default:\n    image: python:3.12-bookworm\n"
        "networks:\n  retained-network:\n    internal: true\n",
        encoding="utf-8",
    )
    other_config_path.write_text("services: {}\n", encoding="utf-8")
    project = ComposeProject(
        name=project_name,
        config=config_path.as_posix(),
        sample_id=0,
        epoch=0,
        env=None,
    )
    compose_down_configs: list[str] = []

    async def fake_compose_ps(
        _project: ComposeProject, *, all: bool = False
    ) -> list[dict[str, str]]:
        return []

    async def fake_compose_ls() -> list[Project]:
        return [
            Project(
                Name=project_name,
                Status="running",
                ConfigFiles=config_path.as_posix(),
            ),
            Project(
                Name=other_project_name,
                Status="running",
                ConfigFiles=other_config_path.as_posix(),
            ),
        ]

    async def fake_compose_down(cleanup_project: ComposeProject, _quiet: bool) -> None:
        assert cleanup_project.config is not None
        compose_down_configs.append(
            Path(cleanup_project.config).read_text(encoding="utf-8")
        )

    monkeypatch.setattr(cleanup_module, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(docker_config, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(cleanup_module, "compose_ps", fake_compose_ps)
    monkeypatch.setattr(cleanup_module, "compose_ls", fake_compose_ls)
    monkeypatch.setattr(cleanup_module, "compose_down", fake_compose_down)

    cleanup_module.project_cleanup_startup()
    cleanup_module.project_startup(project)
    await cleanup_module.project_cleanup_shutdown(cleanup=False)

    assert config_path.exists()
    assert "retained-network" in config_path.read_text(encoding="utf-8")
    assert (
        "Cleanup single environment: inspect sandbox cleanup docker <project-name>"
        in capsys.readouterr().out
    )

    await cleanup_module.cli_cleanup(project_name)

    assert compose_down_configs == [
        "services:\n  default:\n    image: python:3.12-bookworm\n"
        "networks:\n  retained-network:\n    internal: true\n"
    ]
    assert not config_path.exists()
    assert other_config_path.exists()


async def test_full_cleanup_removes_auto_compose_config(
    monkeypatch, tmp_path: Path
) -> None:
    """Full cleanup removes the auto-compose config after bringing the project down."""
    project_name = "inspect-cleanup-iabcdef"
    config_path = tmp_path / f"{project_name}.yaml"
    config_path.write_text("services: {}\n", encoding="utf-8")
    project = ComposeProject(
        name=project_name,
        config=config_path.as_posix(),
        sample_id=0,
        epoch=0,
        env=None,
    )

    async def fake_compose_down(cleanup_project: ComposeProject, _quiet: bool) -> None:
        assert cleanup_project == project

    monkeypatch.setattr(cleanup_module, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(docker_config, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(cleanup_module, "compose_down", fake_compose_down)

    cleanup_module.project_cleanup_startup()
    cleanup_module.project_startup(project)
    await cleanup_module.project_cleanup_shutdown(cleanup=True)

    assert not config_path.exists()


async def test_cli_cleanup_removes_orphaned_auto_compose_config(
    monkeypatch, tmp_path: Path
) -> None:
    """CLI cleanup removes a config whose inspect project is no longer running."""
    config_path = tmp_path / "inspect-orphan-iabcdef.yaml"
    config_path.write_text("services: {}\n", encoding="utf-8")

    async def fake_compose_ls() -> list[Project]:
        return []

    monkeypatch.setattr(cleanup_module, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(docker_config, "auto_compose_dir", lambda: tmp_path)
    monkeypatch.setattr(cleanup_module, "compose_ls", fake_compose_ls)

    await cleanup_module.cli_cleanup(None)

    assert not config_path.exists()
