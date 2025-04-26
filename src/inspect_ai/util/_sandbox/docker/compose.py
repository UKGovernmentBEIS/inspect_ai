import json
import os
import shlex
from logging import getLogger
from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.trace import trace_message
from inspect_ai.util._display import display_type
from inspect_ai.util._subprocess import ExecResult, subprocess

from .prereqs import (
    DOCKER_COMPOSE_REQUIRED_VERSION_PULL_POLICY,
    validate_docker_compose,
)
from .service import ComposeService, services_healthcheck_time
from .util import ComposeProject, is_inspect_project

logger = getLogger(__name__)

# How long to wait for compose environment to pass a health check
COMPOSE_WAIT = 120


async def compose_up(
    project: ComposeProject, services: dict[str, ComposeService]
) -> ExecResult[str]:
    # compute the maximum amount of time we will
    up_command = ["up", "--detach", "--wait"]

    # are there healthchecks in the service definitions? if so then peg our timeout
    # at the maximum total wait time. otherwise, pick a reasonable default
    healthcheck_time = services_healthcheck_time(services)
    if healthcheck_time > 0:
        timeout: int = healthcheck_time
        trace_message(logger, "Docker", "Docker services heathcheck timeout: {timeout}")
    else:
        timeout = COMPOSE_WAIT

    # align global wait timeout to maximum healthcheck timeout
    up_command.extend(["--wait-timeout", str(timeout + 1)])

    # Start the environment. Note that we don't check the result because docker will
    # return a non-zero exit code for services that exit (even successfully) when
    # passing the --wait flag (see https://github.com/docker/compose/issues/10596).
    # In practice, we will catch any errors when calling compose_check_running()
    # immediately after we call compose_up().
    result = await compose_command(up_command, project=project, timeout=timeout)
    return result


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
    src: str,
    dest: str,
    project: ComposeProject,
    cwd: str | Path | None = None,
    output_limit: int | None = None,
) -> None:
    result = await compose_command(
        ["cp", "-L", "--", src, dest],
        project=project,
        timeout=120,  # 2-minute timeout for file copies
        cwd=cwd,
        output_limit=output_limit,
    )
    if not result.success:
        msg = f"Failed to copy file from '{src}' to '{dest}': {result.stderr}"
        raise RuntimeError(msg)


async def compose_check_running(
    services: list[str], project: ComposeProject
) -> list[str]:
    # Check to ensure that the status of containers is healthy
    running_services = await compose_ps(project=project, status="running")
    exited_services = await compose_ps(project=project, status="exited")
    successful_services = running_services + [
        service for service in exited_services if service["ExitCode"] == 0
    ]

    if len(successful_services) > 0:
        if len(successful_services) != len(services):
            unhealthy_services = services
            for successful_service in successful_services:
                unhealthy_services.remove(successful_service["Service"])
            return []
    else:
        return []

    return [service["Service"] for service in running_services]


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
    result = await compose_command(command, project=project, timeout=60)
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
        timeout=None,  # no timeout for build
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
        timeout=None,  # no timeout for pull
        capture_output=capture_output,
    )


async def compose_exec(
    command: list[str],
    *,
    project: ComposeProject,
    timeout: int | None,
    timeout_retry: bool = True,
    input: str | bytes | None = None,
    output_limit: int | None = None,
) -> ExecResult[str]:
    return await compose_command(
        ["exec"] + command,
        project=project,
        timeout=timeout,
        timeout_retry=timeout_retry,
        input=input,
        forward_env=False,
        output_limit=output_limit,
    )


async def compose_services(project: ComposeProject) -> dict[str, ComposeService]:
    result = await compose_command(["config"], project=project, timeout=60)
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
    *,
    cwd: str | None = None,
    timeout: int | None,
) -> None:
    # List the images that would be created for this compose
    images_result = await compose_command(
        ["config", "--images"], project=project, timeout=timeout, cwd=cwd
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
    *,
    project: ComposeProject,
    timeout: int | None,
    timeout_retry: bool = True,
    input: str | bytes | None = None,
    cwd: str | Path | None = None,
    forward_env: bool = True,
    capture_output: bool = True,
    output_limit: int | None = None,
    ansi: Literal["never", "always", "auto"] | None = None,
) -> ExecResult[str]:
    # The base docker compose command
    compose_command = ["docker", "compose"]

    # env to forward
    env = project.env if (project.env and forward_env) else {}

    # ansi (apply global override)
    if display_type() == "plain":
        ansi = "never"
    if ansi:
        compose_command = compose_command + ["--ansi", ansi]

    # quiet if display is none
    if display_type() == "none":
        compose_command = compose_command + ["--progress", "quiet"]

    # add project scope
    compose_command = compose_command + ["--project-name", project.name]

    # add config file if specified
    if project.config:
        compose_command = compose_command + ["-f", project.config]

    # build final command
    compose_command = compose_command + command

    # function to run command
    async def run_command(command_timeout: int | None) -> ExecResult[str]:
        result = await subprocess(
            compose_command,
            input=input,
            cwd=cwd,
            env=env,
            timeout=command_timeout,
            capture_output=capture_output,
            output_limit=output_limit,
        )
        return result

    # we have observed underlying unreliability in docker compose in some linux
    # environments on EC2 -- this exhibits in very simple commands (e.g. compose config)
    # simply never returning. this tends to happen when we know there is a large
    # number of commands in flight (task/sample init) so could be some sort of
    # timing issue / race condition in the docker daemon. we've also observed that
    # these same commands succeed if you just retry them. therefore, we add some
    # extra resiliance by retrying commands with a timeout once. we were observing
    # commands hanging at a rate of ~ 1/1000, so we retry up to twice (tweaking the
    # retry time down) to make the odds of hanging vanishingly small

    if timeout is not None:
        MAX_RETRIES = 2
        retries = 0
        while True:
            try:
                command_timeout = max(
                    timeout if retries == 0 else (min(timeout, 60) // retries), 1
                )
                return await run_command(command_timeout)
            except TimeoutError:
                retries += 1
                if timeout_retry and (retries <= MAX_RETRIES):
                    logger.info(
                        f"Retrying docker compose command: {shlex.join(compose_command)}"
                    )
                else:
                    raise

    else:
        return await run_command(timeout)
