import json
from logging import getLogger
from typing import Callable

import semver
from pydantic import BaseModel

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._context.subprocess import subprocess

logger = getLogger(__name__)


class DockerClientVersion(BaseModel):
    Version: str
    ApiVersion: str


class DockerVersion(BaseModel):
    Client: DockerClientVersion


async def validate_prereqs() -> None:
    await validate_docker_engine()
    await validate_docker_compose()


# Version that corresponds to Docker Desktop w/ Compose v2.22.0
# (which we require for the pull '--policy' option)
# Linux versions of Docker Engine (docker-ce) also include
# Docker Compose as a dependency as of this version
# https://docs.docker.com/engine/release-notes/24.0/#2407
async def validate_docker_engine() -> None:
    DOCKER_ENGINE_REQUIRED_VERSION = "24.0.7"

    def parse_version(stdout: str) -> semver.Version:
        version = DockerVersion(**json.loads(stdout)).Client.Version
        return semver.Version.parse(version)

    await validate_version(
        cmd=["docker", "version", "--format", "json"],
        parse_fn=parse_version,
        required_version=DOCKER_ENGINE_REQUIRED_VERSION,
        feature="Docker Engine",
    )


# We require Compose v2.22.0 for the pull '--policy' option
async def validate_docker_compose() -> None:
    DOCKER_COMPOSE_REQUIRED_VERSION = "2.22.0"

    def parse_version(stdout: str) -> semver.Version:
        version = json.loads(stdout)["version"].removeprefix("v")
        return semver.Version.parse(version)

    await validate_version(
        cmd=["docker", "compose", "version", "--format", "json"],
        parse_fn=parse_version,
        required_version=DOCKER_COMPOSE_REQUIRED_VERSION,
        feature="Docker Compose",
    )


async def validate_version(
    cmd: list[str],
    parse_fn: Callable[[str], semver.Version],
    required_version: str,
    feature: str,
) -> None:
    # attempt to read version
    try:
        version = semver.Version(0)
        result = await subprocess(cmd)
        if result.success:
            version = parse_fn(result.stdout)
    except Exception as ex:
        # we expect FileNotFoundError (when docker is not installed) however
        # other errors would be a surprise so we alert the user w/ a warning
        if not isinstance(ex, FileNotFoundError):
            logger.warning(f"Unexpected error executing docker: {ex}")

        raise PrerequisiteError(
            "ERROR: Docker tool environments require Docker Engine\n\n"
            + "Install: https://docs.docker.com/engine/install/\n"
        )

    # validate version
    if version.compare(required_version) < 0:
        raise PrerequisiteError(
            f"ERROR: Docker tool environments require {feature} >= {required_version}\n\n"
            + "Upgrade: https://docs.docker.com/engine/install/\n"
        )
