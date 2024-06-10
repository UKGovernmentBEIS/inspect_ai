import json
from logging import getLogger
from typing import Any, Literal, cast

import yaml

from inspect_ai.util._context.subprocess import ExecResult, subprocess

from .util import tools_log

logger = getLogger(__name__)

# How long to wait for compose environment to pass a health check
COMPOSE_WAIT = "120"


async def compose_up(project: str, config: str | None) -> None:
    # Start the environment
    result = await compose_command(
        ["up", "--detach", "--wait", "--wait-timeout", COMPOSE_WAIT],
        project=project,
        config=config,
    )
    if not result.success:
        msg = f"Failed to start docker services {result.stderr}"
        raise RuntimeError(msg)


async def compose_down(project: str, config: str | None, cancelled: bool) -> None:
    # shut down docker containers
    result = await compose_command(
        ["down", "--volumes"],
        project=project,
        config=config,
        capture_output=not cancelled,
        ansi="never" if cancelled else "auto",
    )
    if not result.success:
        msg = f"Failed to stop docker service {result.stderr}"
        logger.warning(msg)

    await compose_cleanup_images(project=project, config=config)


async def compose_cp(src: str, dest: str, project: str, config: str | None) -> None:
    result = await compose_command(
        ["cp", src, dest],
        project=project,
        config=config,
    )
    if not result.success:
        msg = f"Failed to copy file from '{src}' to '{dest}'"
        raise RuntimeError(msg)


async def compose_check_running(
    services: list[str], project: str, config: str | None
) -> None:
    # Check to ensure that the status of containers is healthy
    running_services = await compose_ps("running", project=project, config=config)
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
    status: Literal[
        "paused", "restarting", "removing", "running", "dead", "created", "exited"
    ],
    project: str,
    config: str | None,
) -> list[dict[str, Any]]:
    result = await compose_command(
        ["ps", "--status", status, "--format", "json"],
        project=project,
        config=config,
    )
    if not result.success:
        msg = f"Error querying for running services: {result.stderr}"
        raise RuntimeError(msg)

    return [
        cast(dict[str, Any], json.loads(service))
        for service in result.stdout.strip().split("\n")
    ]


async def compose_build(
    project: str, config: str | None, capture_output: bool = False
) -> None:
    result = await compose_command(
        ["build"],
        project=project,
        config=config,
        capture_output=capture_output,
    )
    if not result.success:
        msg = "Failed to build docker containers"
        raise RuntimeError(msg)


async def compose_pull(
    project: str, config: str | None, capture_output: bool = False
) -> ExecResult[str]:
    return await compose_command(
        ["pull", "--ignore-buildable", "--policy", "missing"],
        project=project,
        config=config,
        capture_output=capture_output,
    )


async def compose_exec(
    command: list[str],
    project: str,
    config: str | None = None,
    timeout: int | None = None,
    input: str | bytes | None = None,
) -> ExecResult[str]:
    return await compose_command(
        ["exec"] + command, project=project, config=config, timeout=timeout, input=input
    )


async def compose_mkdir(
    dir: str, service: str, project: str, config: str | None = None
) -> None:
    # create working dir
    result = await compose_exec(
        [service, "bash", "-c", f"mkdir -p {dir}"],
        project=project,
        config=config,
    )
    if not result.success:
        msg = f"Failed to create directory '{dir}': {result.stderr}"
        raise RuntimeError(msg)


async def compose_services(
    project: str, config: str | None = None
) -> dict[str, dict[str, str]]:
    result = await compose_command(["config"], project=project, config=config)
    if not result.success:
        raise RuntimeError("Error reading docker config: {result.stderr}")
    return cast(dict[str, dict[str, str]], yaml.safe_load(result.stdout)["services"])


async def compose_cleanup_images(
    project: str,
    config: str | None = None,
    timeout: int | None = None,
) -> None:
    tools_log("Removing images")
    # List the images that would be created for this compose
    images_result = await compose_command(
        ["config", "--images"], project=project, config=config
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


async def compose_command(
    command: list[str],
    project: str,
    config: str | None = None,
    timeout: int | None = None,
    input: str | bytes | None = None,
    capture_output: bool = True,
    ansi: Literal["never", "always", "auto"] | None = None,
) -> ExecResult[str]:
    # The base docker compose command
    compose_command = ["docker", "compose"]

    # ansi
    if ansi:
        compose_command = compose_command + ["--ansi", ansi]

    # If an explicit project is provided, use that
    if project:
        compose_command = compose_command + ["--project-name", project]

    # If an explicit configuration file is provided, use that
    if config:
        compose_command = compose_command + ["-f", config]
    compose_command = compose_command + command

    # Execute the command
    tools_log(f"compose command: {compose_command}")
    result = await subprocess(
        compose_command,
        input=input,
        timeout=timeout,
        capture_output=capture_output,
    )
    tools_log(f"compose command (completed): {compose_command}")
    return result
