import json
import os
import shlex
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, TypedDict, cast

import yaml
from pydantic import BaseModel

from inspect_ai._util.ansi import no_ansi
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult, subprocess

from .prereqs import (
    DOCKER_COMPOSE_REQUIRED_VERSION_PULL_POLICY,
    validate_docker_compose,
)
from .util import ComposeProject, is_inspect_project, sandbox_log

logger = getLogger(__name__)

# How long to wait for compose environment to pass a health check
COMPOSE_WAIT = "120"


async def compose_up(project: ComposeProject) -> None:
    # Start the environment
    result = await compose_command(
        ["up", "--detach", "--wait", "--wait-timeout", COMPOSE_WAIT],
        project=project,
    )
    if not result.success:
        msg = f"Failed to start docker services {result.stderr}"
        raise RuntimeError(msg)


async def compose_down(project: ComposeProject, quiet: bool = True) -> None:
    # set cwd to config file directory
    cwd = os.path.dirname(project.config) if project.config else None

    # shut down docker containers. default internal timeout is 10 seconds
    # but we've seen reports of this handing, so add a proess timeout
    # of 60 seconds for belt and suspenders
    TIMEOUT = 60
    try:
        result = await compose_command(
            ["down", "--volumes"],
            project=project,
            cwd=cwd,
            timeout=TIMEOUT,
            capture_output=quiet,
            ansi="never",
        )

        if not result.success:
            msg = f"Failed to stop docker service {result.stderr}"
            logger.warning(msg)

    except TimeoutError:
        logger.warning(
            f"Docker compose down for project '{project.name}' timed out after {TIMEOUT} seconds."
        )

    try:
        await compose_cleanup_images(project=project, cwd=cwd, timeout=TIMEOUT)
    except TimeoutError:
        logger.warning(
            f"Docker image cleanup for project '{project.name}' timed out after {TIMEOUT} seconds."
        )


async def compose_cp(
    src: str, dest: str, project: ComposeProject, cwd: str | Path | None = None
) -> None:
    result = await compose_command(["cp", "--", src, dest], project=project, cwd=cwd)
    if not result.success:
        msg = f"Failed to copy file from '{src}' to '{dest}': {result.stderr}"
        raise RuntimeError(msg)


async def compose_check_running(services: list[str], project: ComposeProject) -> None:
    # Check to ensure that the status of containers is healthy
    running_services = await compose_ps(project=project, status="running")
    if len(running_services) > 0:
        if len(running_services) != len(services):
            unhealthy_services = services
            for running_service in running_services:
                unhealthy_services.remove(running_service["Service"])

            msg = f"One or more docker containers failed to start {','.join(unhealthy_services)}"
            raise RuntimeError(msg)
    else:
        raise RuntimeError("No services started")


async def compose_ps(
    project: ComposeProject,
    status: Literal[
        "paused", "restarting", "removing", "running", "dead", "created", "exited"
    ]
    | None = None,
    all: bool = False,
) -> list[dict[str, Any]]:
    command = ["ps", "--format", "json"]
    if all:
        command.append("--all")
    if status:
        command = command + ["--status", status]
    result = await compose_command(command, project=project)
    if not result.success:
        msg = f"Error querying for running services: {result.stderr}"
        raise RuntimeError(msg)

    output = result.stdout.strip()
    if len(output) > 0:
        return [
            cast(dict[str, Any], json.loads(service)) for service in output.split("\n")
        ]
    else:
        return []


async def compose_build(project: ComposeProject, capture_output: bool = False) -> None:
    result = await compose_command(
        ["build"],
        project=project,
        capture_output=capture_output,
    )
    if not result.success:
        msg = "Failed to build docker containers"
        raise PrerequisiteError(msg)


async def compose_pull(
    service: str, project: ComposeProject, capture_output: bool = False
) -> ExecResult[str]:
    await validate_docker_compose(DOCKER_COMPOSE_REQUIRED_VERSION_PULL_POLICY)

    return await compose_command(
        ["pull", "--ignore-buildable", "--policy", "missing", service],
        project=project,
        capture_output=capture_output,
    )


async def compose_exec(
    command: list[str],
    project: ComposeProject,
    timeout: int | None = None,
    input: str | bytes | None = None,
) -> ExecResult[str]:
    return await compose_command(
        ["exec"] + command,
        project=project,
        timeout=timeout,
        input=input,
        forward_env=False,
    )


ComposeService = TypedDict(
    "ComposeService",
    {
        "image": str | None,
        "build": str | None,
        "x-default": bool | None,
        "x-local": bool | None,
    },
)


async def compose_services(project: ComposeProject) -> dict[str, ComposeService]:
    result = await compose_command(["config"], project=project)
    if not result.success:
        raise RuntimeError(f"Error reading docker config: {result.stderr}")
    return cast(dict[str, ComposeService], yaml.safe_load(result.stdout)["services"])


class Project(BaseModel):
    Name: str
    Status: str
    ConfigFiles: str | None


async def compose_ls() -> list[Project]:
    result = await subprocess(["docker", "compose", "ls", "--all", "--format", "json"])
    if result.success:
        projects: list[dict[str, Any]] = json.loads(result.stdout)
        projects = list(filter(lambda p: is_inspect_project(p["Name"]), projects))
        return [Project(**project) for project in projects]
    else:
        raise RuntimeError(result.stderr)


async def compose_cleanup_images(
    project: ComposeProject,
    cwd: str | None = None,
    timeout: int | None = None,
) -> None:
    sandbox_log("Removing images")
    # List the images that would be created for this compose
    images_result = await compose_command(
        ["config", "--images"], project=project, cwd=cwd
    )

    # Remove those images explicitly
    if images_result.success:
        for image in images_result.stdout.strip().split("\n"):
            # See if this image was created by
            # inspect directly
            if image.startswith(project.name):
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


async def compose_command(
    command: list[str],
    project: ComposeProject,
    timeout: int | None = None,
    input: str | bytes | None = None,
    cwd: str | Path | None = None,
    forward_env: bool = True,
    capture_output: bool = True,
    ansi: Literal["never", "always", "auto"] | None = None,
) -> ExecResult[str]:
    # The base docker compose command
    compose_command = ["docker", "compose"]

    # env to forward
    env = project.env if (project.env and forward_env) else {}

    # ansi (apply global override)
    if no_ansi():
        ansi = "never"
    if ansi:
        compose_command = compose_command + ["--ansi", ansi]

    # add project scope
    compose_command = compose_command + ["--project-name", project.name]

    # add config file if specified
    if project.config:
        compose_command = compose_command + ["-f", project.config]

    # build final command
    compose_command = compose_command + command

    # Execute the command
    sandbox_log(f"compose command: {shlex.join(compose_command)}")
    result = await subprocess(
        compose_command,
        input=input,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=capture_output,
    )
    return result
