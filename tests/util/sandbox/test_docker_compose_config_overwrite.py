"""Tests for auto-compose file uniqueness.

These tests verify that when multiple samples use different ComposeConfig
objects or different Dockerfiles in the same directory, they each get their
own unique auto-compose file in the central directory, avoiding overwrites
and race conditions.
"""

import asyncio
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import pytest

from inspect_ai.util import ComposeConfig, ComposeService
from inspect_ai.util._sandbox.docker.util import ComposeProject


@contextmanager
def temp_working_directory() -> Generator[Path, None, None]:
    """Context manager that creates a temp directory and changes to it."""
    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as temp_dir:
        os.chdir(temp_dir)
        try:
            yield Path(temp_dir)
        finally:
            os.chdir(original_cwd)


def make_config(image: str) -> ComposeConfig:
    """Create a simple ComposeConfig with the given image."""
    return ComposeConfig(
        services={
            "default": ComposeService(
                image=image,
                init=True,
                command="tail -f /dev/null",
                network_mode="none",
            )
        }
    )


async def test_compose_config_sequential_no_overwrite() -> None:
    """Verify that sequential ComposeProject.create() calls don't overwrite.

    Each project should get its own unique auto-compose file in the central
    directory, so creating project B should not affect project A's config.
    """
    with temp_working_directory():
        # Create first config with alpine image
        config_a = make_config("alpine:3.18")
        project_a = await ComposeProject.create(name="project-a", config=config_a)

        # Verify project A's config was written correctly
        assert project_a.config is not None
        with open(project_a.config, "r") as f:
            content_a_before = f.read()
        assert "alpine:3.18" in content_a_before

        # Create second config with python image
        config_b = make_config("python:3.12")
        project_b = await ComposeProject.create(name="project-b", config=config_b)

        # Each project should have its own unique file
        assert project_a.config != project_b.config

        # Re-read project A's config file - should be unchanged
        with open(project_a.config, "r") as f:
            content_a_after = f.read()

        # Project A's config should still have alpine
        assert "alpine:3.18" in content_a_after, (
            "Project A's config was overwritten by project B!"
        )

        # Project B's config should have python
        with open(project_b.config, "r") as f:
            content_b = f.read()
        assert "python:3.12" in content_b


async def test_compose_config_concurrent_no_overwrite() -> None:
    """Verify no race condition with concurrent ComposeProject.create() calls.

    Each project should get its own unique auto-compose file, so all
    configurations should be preserved even when created concurrently.
    """
    with temp_working_directory():
        # Create multiple configs with distinct images
        configs = [
            ("project-a", make_config("alpine:3.18")),
            ("project-b", make_config("python:3.12")),
            ("project-c", make_config("ubuntu:22.04")),
        ]

        # Create all projects concurrently
        projects = await asyncio.gather(
            *[
                ComposeProject.create(name=name, config=config)
                for name, config in configs
            ]
        )

        # Each project should have its own unique file
        config_paths = [p.config for p in projects]
        assert len(set(config_paths)) == 3, "Each project should have its own config file"

        # Each file should contain its respective image
        images = ["alpine:3.18", "python:3.12", "ubuntu:22.04"]
        for project, expected_image in zip(projects, images):
            with open(project.config, "r") as f:
                content = f.read()
            assert expected_image in content, (
                f"Project config should contain {expected_image}"
            )


async def test_compose_config_unique_files() -> None:
    """Verify each ComposeConfig gets a unique file.

    Each project should have:
    1. A unique config file path (not sharing .compose.yaml)
    2. A config file containing only its own configuration
    """
    with temp_working_directory():
        config_a = make_config("alpine:3.18")
        config_b = make_config("python:3.12")

        project_a = await ComposeProject.create(name="project-a", config=config_a)
        project_b = await ComposeProject.create(name="project-b", config=config_b)

        # Each project should have unique file
        assert project_a.config != project_b.config, (
            "Each ComposeConfig should have its own unique auto-compose file"
        )

        # Each file should contain only its config
        with open(project_a.config, "r") as f:
            content_a = f.read()
        with open(project_b.config, "r") as f:
            content_b = f.read()

        assert "alpine:3.18" in content_a and "python:3.12" not in content_a
        assert "python:3.12" in content_b and "alpine:3.18" not in content_b


async def test_dockerfile_sequential_no_overwrite() -> None:
    """Verify different Dockerfiles in same directory don't overwrite.

    When samples use different Dockerfiles (e.g., Dockerfile.alpine vs
    Dockerfile.python) in the same directory, each should get its own
    unique auto-compose file in the central directory.
    """
    with temp_working_directory() as temp_dir:
        # Create two different Dockerfiles in the same directory
        dockerfile_a = temp_dir / "Dockerfile.alpine"
        dockerfile_a.write_text("FROM alpine:3.18\n")

        dockerfile_b = temp_dir / "Dockerfile.python"
        dockerfile_b.write_text("FROM python:3.12\n")

        # Create project A with Dockerfile.alpine
        project_a = await ComposeProject.create(
            name="project-a", config=str(dockerfile_a)
        )

        # Verify project A's auto-compose was written correctly
        assert project_a.config is not None
        with open(project_a.config, "r") as f:
            content_a_before = f.read()
        assert "Dockerfile.alpine" in content_a_before

        # Create project B with Dockerfile.python
        project_b = await ComposeProject.create(
            name="project-b", config=str(dockerfile_b)
        )

        # Each project should have its own unique file
        assert project_a.config != project_b.config

        # Re-read project A's config file - should be unchanged
        with open(project_a.config, "r") as f:
            content_a_after = f.read()

        # Project A's config should still reference Dockerfile.alpine
        assert "Dockerfile.alpine" in content_a_after, (
            "Project A's config was overwritten by project B!"
        )

        # Project B's config should reference Dockerfile.python
        with open(project_b.config, "r") as f:
            content_b = f.read()
        assert "Dockerfile.python" in content_b


async def test_dockerfile_unique_files() -> None:
    """Verify each Dockerfile gets a unique auto-compose file.

    Projects using different Dockerfiles in the same directory
    should each have their own unique auto-compose file.
    """
    with temp_working_directory() as temp_dir:
        # Create two different Dockerfiles in the same directory
        dockerfile_a = temp_dir / "Dockerfile.alpine"
        dockerfile_a.write_text("FROM alpine:3.18\n")

        dockerfile_b = temp_dir / "Dockerfile.python"
        dockerfile_b.write_text("FROM python:3.12\n")

        project_a = await ComposeProject.create(
            name="project-a", config=str(dockerfile_a)
        )
        project_b = await ComposeProject.create(
            name="project-b", config=str(dockerfile_b)
        )

        # Each project should have unique file
        assert project_a.config != project_b.config, (
            "Each Dockerfile should have its own unique auto-compose file"
        )

        # Each file references its Dockerfile
        with open(project_a.config, "r") as f:
            content_a = f.read()
        with open(project_b.config, "r") as f:
            content_b = f.read()

        assert "Dockerfile.alpine" in content_a and "Dockerfile.python" not in content_a
        assert "Dockerfile.python" in content_b and "Dockerfile.alpine" not in content_b
