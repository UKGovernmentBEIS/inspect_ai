"""Track Docker projects across checkpoint tests' killed child processes."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import inspect_ai.util._sandbox.docker.docker as docker_provider
from inspect_ai.util._sandbox.docker.util import ComposeProject, is_inspect_project

PROJECTS_DIR_ENV = "INSPECT_TEST_CHECKPOINT_PROJECTS_DIR"


class DockerProjects:
    """Projects created by one test body, including all samples and attempts."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def container_ids(self) -> list[str]:
        """Return this test's containers, including stopped containers."""
        ids: list[str] = []
        for record in sorted(self.directory.iterdir()):
            name = record.name
            if not is_inspect_project(name):
                raise ValueError(f"Invalid checkpoint test project record: {record}")
            result = subprocess.run(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"label=com.docker.compose.project={name}",
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
            ids.extend(result.stdout.split())
        return ids

    def cleanup(self) -> None:
        """Remove only containers belonging to this test's recorded projects."""
        ids = self.container_ids()
        if ids:
            subprocess.run(
                ["docker", "rm", "-f", *ids],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )


@contextmanager
def record_docker_projects() -> Iterator[None]:
    """Record projects before startup when a parent test requests tracking.

    One empty file per exact project name survives SIGKILL without buffered
    writes or concurrent appends. Recording before startup also covers failed
    hydration and sibling samples that never reach the harness's crash tool.
    Cleanup belongs to the parent test, which outlives every child attempt.
    """
    directory = os.environ.get(PROJECTS_DIR_ENV)
    if directory is None:
        yield
        return

    startup: Callable[[ComposeProject], None] = getattr(
        docker_provider, "project_startup"
    )

    def record(project: ComposeProject) -> None:
        (Path(directory) / project.name).touch()
        startup(project)

    with patch.object(docker_provider, "project_startup", record):
        yield


@contextmanager
def checkpoint_docker_projects(tmp_path: Path) -> Iterator[DockerProjects]:
    """Track and clean all sandboxes created during one checkpoint test attempt.

    Enter inside the test body so flaky-retry attempts each get a fresh scope.
    Child harnesses inherit the directory and install their own recorder.
    """
    with TemporaryDirectory(prefix="docker-projects-", dir=tmp_path) as directory:
        projects = DockerProjects(Path(directory))
        with (
            patch.dict(os.environ, {PROJECTS_DIR_ENV: directory}),
            record_docker_projects(),
        ):
            try:
                yield projects
            finally:
                projects.cleanup()
