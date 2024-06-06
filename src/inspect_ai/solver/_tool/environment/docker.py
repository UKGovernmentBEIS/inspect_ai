import json
import os
import shlex
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, Union, cast, overload

import aiofiles
from shortuuid import uuid
from typing_extensions import override

from inspect_ai._util.constants import TOOLS
from inspect_ai.solver._tool.environment.environment import (
    ToolEnvironment,
    ToolEnvironments,
)
from inspect_ai.solver._tool.environment.registry import toolenv
from inspect_ai.util._context.subprocess import ExecResult, subprocess

logger = getLogger(__name__)

# How long to wait for compose environment to pass a health check
_COMPOSE_WAIT = "120"

# directory where copy sample specific files to
_SAMPLE_DIR = "/tmp/sample"


@toolenv(name="docker")
class DockerToolEnvironment(ToolEnvironment):
    @classmethod
    async def startup(cls, task_name: str, config: str | None) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            # unique project name for provisioning
            project = _to_project(task_name)

            # synthesize config if necessary
            config = config if config else await _auto_config(temp_dir)

            build_result = await _compose_command(
                ["build"],
                project=project,
                file=config,
                capture_output=False,
            )
            if not build_result.success:
                msg = "Failed to build docker containers"
                raise RuntimeError(msg)

            await _remove_images(project=project, config=config)

            pull_result = await _compose_command(
                ["pull", "--ignore-buildable", "--policy", "missing"],
                project=project,
                file=config,
                capture_output=False,
            )
            if not pull_result.success:
                msg = "Failed to pull docker images"
                raise RuntimeError(msg)

            print("")

    @override
    @classmethod
    async def setup(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> ToolEnvironments:
        _debug_msg("setup")

        # Provide a temporary directory that is available during setup
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

        # Create a unique project name to disambiguate different instances
        # of the docker compositions
        project = _to_project(task_name)

        # confirm that there is a docker compose file in the working directory
        # otherwise synthesize a default compose file
        config = config if config else await _auto_config(temp_dir.name)

        # Create an environment for each of the services defined
        # in the compose configuration
        environments: dict[str, ToolEnvironment] = {}
        service_result = await _compose_command(
            ["config", "--services"], project=project, file=config
        )
        if service_result.success:
            for service in service_result.stdout.strip().split("\n"):
                environments[service] = DockerToolEnvironment(service, config, project)
        else:
            msg = f"Failed to enumerate docker services {service_result.stderr}"
            raise RuntimeError(msg)

        # Start the environment
        await _compose_up_command(project, config)

        # Check to ensure that the status of containers is healthy
        health_result = await _compose_command(
            ["ps", "--status", "running", "--format", "json"],
            project=project,
            file=config,
        )
        if health_result.success:
            json_response = health_result.stdout
            if json_response.strip():
                services_raw = json_response.strip().split("\n")
                if len(services_raw) != len(environments):
                    unhealthy_environments = list(environments.keys())
                    for service_raw in services_raw:
                        service_record = cast(dict[str, Any], json.loads(service_raw))
                        unhealthy_environments.remove(service_record["Service"])

                    msg = f"One or more docker containers failed to start {','.join(unhealthy_environments)}"
                    raise RuntimeError(msg)
            else:
                raise RuntimeError("No services started")

        # create working dir in environments
        for env in environments.values():
            docker_env = cast(DockerToolEnvironment, env)
            result = await _compose_command(
                ["exec"]
                + [docker_env._service, "bash", "-c", f"mkdir -p {_SAMPLE_DIR}"],
                file=docker_env._config,
                project=docker_env._project,
            )
            if not result.success:
                msg = f"Failed to create working directory {result.stderr}"
                raise RuntimeError(msg)

        async def cleanup() -> None:
            await _compose_down_command(project=project, config=config)

            # cleanup the temp directory
            temp_dir.cleanup()

        return ToolEnvironments(environments=environments, cleanup=cleanup)

    def __init__(self, service: str, config: str | None, project: str | None) -> None:
        super().__init__()
        self._config = config
        self._service = service
        self._project = project

    @override
    async def exec(
        self,
        cmd: str | list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
        timeout: int | None = None,
    ) -> ExecResult[str]:
        # Forward environment commands to docker compose exec so they
        # will be available to the bash command
        env_args = []
        if len(env.items()) > 0:
            env_args = [f"--env {key}={value}" for key, value in env.items()]

        if isinstance(cmd, list):
            cmd = " ".join([shlex.quote(arg) for arg in cmd])

        result = await _compose_command(
            ["exec", "--workdir", _SAMPLE_DIR]
            + env_args
            + [self._service, "bash", "-c", cmd],
            file=self._config,
            project=self._project,
            timeout=timeout,
            input=input,
        )
        return result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        _debug_msg(f"write_file: {file}")

        # Write the contents to a temp file
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            if isinstance(contents, str):
                async with aiofiles.open(temp_file.name, "w", encoding="utf-8") as f:
                    await f.write(contents)
            else:
                async with aiofiles.open(temp_file.name, "wb") as f:
                    await f.write(contents)

            # resolve relative file paths to sample dir
            file = _container_file(file)

            # ensure that the directory exists
            parent = Path(file).parent.as_posix()
            if parent != ".":
                result = await self.exec(["mkdir", "-p", parent])
                if not result.success:
                    msg = f"Failed to create container directory {parent}: {result.stderr}"
                    raise RuntimeError(msg)

            # use the cp command to copy the file
            result = await _compose_command(
                ["cp", temp_file.name, f"{self._service}:{file}"],
                file=self._config,
                project=self._project,
            )
            if not result.success:
                msg = f"Failed to copy file to container {file}"
                raise RuntimeError(msg)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        _debug_msg(f"read_file: {file}")

        # Write the contents to a temp file
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            # resolve relative file paths to sample dir
            file = _container_file(file)

            result = await _compose_command(
                ["cp", f"{self._service}:{file}", temp_file.name],
                file=self._config,
                project=self._project,
            )
            if not result.success:
                msg = f"Failed to read file from container {file}"
                raise RuntimeError(msg)

            if text:
                async with aiofiles.open(temp_file.name, "r", encoding="utf-8") as f:
                    return await f.read()
            else:
                async with aiofiles.open(temp_file.name, "rb") as f:
                    return await f.read()


def _debug_msg(msg: str) -> None:
    logger.log(TOOLS, f"DOCKER: {msg}")


async def _auto_config(temp_dir: str) -> str | None:
    # compose file provides all the config we need
    if _has_compose_file():
        return None

    # dockerfile just needs a compose.yaml synthesized
    elif _has_dockerfile():
        return await _dockerfile_compose(Path(), temp_dir)

    # otherwise provide a generic python container
    else:
        return await _generic_container_compose(temp_dir)


def _container_file(file: str) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = Path(_SAMPLE_DIR) / path
    return path.as_posix()


async def _remove_images(
    project: str | None = None,
    config: str | None = None,
    timeout: int | None = None,
) -> None:
    _debug_msg("Removing images")
    # List the images that would be created for this compose
    images_result = await _compose_command(
        ["config", "--images"], project=project, file=config
    )

    # Remove those images explicitly
    if images_result.success:
        for image in images_result.stdout.strip().split("\n"):
            # See if this image was created by
            # inspect directly
            if image.startswith(project if project else ""):
                # see if this image is present
                image_result = await subprocess(
                    ["docker", "images", "-q", image],
                    timeout=timeout,
                    capture_output=True,
                )

                remove_image = True
                if image_result.success:
                    remove_image = len(image_result.stdout) != 0

                # remove the image
                if remove_image:
                    result = await subprocess(
                        ["docker", "rmi", image],
                        timeout=timeout,
                        capture_output=True,
                    )
                    if not result.success:
                        msg = f"Failed to cleanup docker image {result.stderr}"
                        logger.warning(msg)


async def _compose_up_command(project: str | None, config: str | None) -> None:
    # Start the environment
    result = await _compose_command(
        ["up", "--detach", "--wait", "--wait-timeout", _COMPOSE_WAIT],
        project=project,
        file=config,
    )
    if not result.success:
        msg = f"Failed to start docker services {result.stderr}"
        raise RuntimeError(msg)


async def _compose_down_command(project: str | None, config: str | None) -> None:
    # shut down docker containers
    result = await _compose_command(
        ["down", "--volumes"],
        project=project,
        file=config,
    )
    if not result.success:
        msg = f"Failed to stop docker service {result.stderr}"
        logger.warning(msg)

    await _remove_images(project=project, config=config)


async def _compose_command(
    command: list[str],
    project: str | None = None,
    file: str | None = None,
    timeout: int | None = None,
    input: str | bytes | None = None,
    capture_output: bool = True,
) -> ExecResult[str]:
    # The base docker compose command
    compose_command = ["docker", "compose"]

    # If an explicit project is provided, use that
    if project:
        compose_command = compose_command + ["--project-name", project]

    # If an explicit configuration file is provided, use that
    if file:
        compose_command = compose_command + ["-f", file]
    compose_command = compose_command + command

    # Execute the command
    _debug_msg(f"compose command: {compose_command}")
    result = await subprocess(
        compose_command,
        input=input,
        timeout=timeout,
        capture_output=capture_output,
    )
    _debug_msg(f"compose command (completed): {compose_command}")
    return result


def _has_compose_file() -> bool:
    compose_files = [
        "compose.yaml",
        "compose.yml",
        "docker-compose.yaml",
        "docker-compose.yml",
    ]
    for file in compose_files:
        if os.path.isfile(file):
            return True
    return False


def _has_dockerfile() -> bool:
    return os.path.isfile("Dockerfile")


# Our default compose.yaml
_compose_generic_yaml = """
services:
  default:
    image: "python:3.12-bookworm"
    command: tail -f /dev/null
"""


async def _generic_container_compose(directory: str) -> str:
    return await _default_compose_file(directory, _compose_generic_yaml)


async def _dockerfile_compose(context: Path, directory: str) -> str:
    # Template for a DockerFile
    _compose_dockerfile_yaml = f"""
services:
  default:
    build:
      context: {context.resolve().as_posix()}
    command: tail -f /dev/null
    """

    return await _default_compose_file(directory, _compose_dockerfile_yaml)


# Provide the path to a default compose file
async def _default_compose_file(directory: str, contents: str) -> str:
    with tempfile.NamedTemporaryFile(
        dir=directory, suffix=".yaml", delete=False
    ) as compose_file:
        async with aiofiles.open(compose_file.name, "w", encoding="utf-8") as f:
            await f.write(contents)
        return compose_file.name


def _to_project(task: str) -> str:
    return f"inspect-{task.lower()}-{uuid().lower()}"
