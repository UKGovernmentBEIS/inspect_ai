import json
import shlex
from logging import getLogger
from typing import Callable

import semver
from pydantic import BaseModel

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import subprocess

logger = getLogger(__name__)


class DockerServerVersion(BaseModel):
    Version: str | None = None


class DockerVersion(BaseModel):
    Server: DockerServerVersion | None = None


async def validate_prereqs() -> None:
    await validate_docker_engine()
    await validate_docker_compose()


# Docker daemon and Docker Compose versions are checked separately.
DOCKER_ENGINE_REQUIRED_VERSION = "24.0.6"


async def validate_docker_engine(version: str = DOCKER_ENGINE_REQUIRED_VERSION) -> None:
    def parse_version(stdout: str) -> semver.Version:
        server = DockerVersion(**json.loads(stdout)).Server
        if server is None or server.Version is None:
            raise PrerequisiteError(
                "ERROR: Unable to determine the Docker Engine server version\n\n"
                + "`docker version` did not report server version metadata. Verify that "
                + "the Docker CLI is connected to a working Docker daemon."
            )
        return semver.Version.parse(server.Version)

    await validate_version(
        cmd=["docker", "version", "--format", "json"],
        parse_fn=parse_version,
        required_version=version,
        feature="Docker Engine",
    )


# We require Compose v2.21.0, however if we are going to use
# the pull '--policy' option we call this again with 2.22.0

DOCKER_COMPOSE_REQUIRED_VERSION = "2.21.0"
DOCKER_COMPOSE_REQUIRED_VERSION_PULL_POLICY = "2.22.0"
# Older Compose versions can leave mounts inside a host directory writable,
# even when the directory is mounted read-only. Compose 2.24 uses Docker API
# 1.44, which makes those nested mounts read-only too.
# https://docs.docker.com/engine/release-notes/25.0/#2504
# https://github.com/docker/compose/blob/v2.24.0/go.mod#L14-L16
DOCKER_COMPOSE_REQUIRED_VERSION_READ_ONLY = "2.24.0"


async def validate_docker_compose(
    version: str = DOCKER_COMPOSE_REQUIRED_VERSION,
    *,
    required_for: str | None = None,
) -> None:
    def parse_version(stdout: str) -> semver.Version:
        version = json.loads(stdout)["version"].removeprefix("v").split("+")[0]
        return semver.Version.parse(version)

    await validate_version(
        cmd=["docker", "compose", "version", "--format", "json"],
        parse_fn=parse_version,
        required_version=version,
        feature="Docker Compose",
        required_for=required_for,
    )


async def validate_version(
    cmd: list[str],
    parse_fn: Callable[[str], semver.Version],
    required_version: str,
    feature: str,
    required_for: str | None = None,
) -> None:
    # attempt to read version
    try:
        version = semver.Version(0)
        result = await subprocess(cmd)
        if result.success:
            version = parse_fn(result.stdout)
    except PrerequisiteError:
        raise
    except Exception as ex:
        # we expect FileNotFoundError (when docker is not installed) however
        # other errors would be a surprise so we alert the user w/ a warning
        if not isinstance(ex, FileNotFoundError):
            logger.warning(f"Unexpected error executing docker: {ex}")

        raise PrerequisiteError(
            "ERROR: Docker sandbox environments require Docker Engine\n\n"
            + "Install: https://docs.docker.com/engine/install/"
        )

    if not result.success:
        raise PrerequisiteError(
            "ERROR: Docker sandbox environments require a working Docker Engine\n\n"
            + f"{cmd[0]} exited with return code {result.returncode} when executing: {shlex.join(cmd)}\n"
            + result.stderr
        )

    # validate version
    if version.compare(required_version) < 0:
        requirement = (
            f"{required_for} requires"
            if required_for
            else "Docker sandbox environments require"
        )
        raise PrerequisiteError(
            f"ERROR: {requirement} {feature} >= {required_version} (current: {version})\n\n"
            + "Upgrade: https://docs.docker.com/engine/install/"
        )
