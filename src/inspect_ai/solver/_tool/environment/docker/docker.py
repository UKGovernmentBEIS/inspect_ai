import os
import tempfile
from logging import getLogger
from pathlib import Path
from typing import Literal, Union, cast, overload

import aiofiles
from typing_extensions import override

from inspect_ai.solver._tool.tool import ToolError
from inspect_ai.util._context.subprocess import ExecResult

from ..environment import ToolEnvironment
from ..registry import toolenv
from .cleanup import (
    cli_cleanup,
    project_cleanup,
    project_cleanup_shutdown,
    project_cleanup_startup,
    project_startup,
)
from .compose import (
    compose_build,
    compose_check_running,
    compose_cleanup_images,
    compose_cp,
    compose_exec,
    compose_pull,
    compose_services,
    compose_up,
)
from .prereqs import validate_prereqs
from .util import ComposeProject, task_project_name, tools_log

logger = getLogger(__name__)


@toolenv(name="docker")
class DockerToolEnvironment(ToolEnvironment):
    @classmethod
    async def task_init(cls, task_name: str, config: str | None) -> None:
        # validate prereqs
        await validate_prereqs()

        # intialize project cleanup
        project_cleanup_startup()

        try:
            # create project
            project = await ComposeProject.create(
                name=task_project_name(task_name), config=config
            )

            # build containers which are out of date
            await compose_build(project)

            # cleanup images created during build
            await compose_cleanup_images(project)

            # pull any remote images
            services = await compose_services(project)
            for name, service in services.items():
                if (
                    service.get("build", None) is None
                    and service.get("x-local", None) is None
                ):
                    pull_result = await compose_pull(name, project)
                    if not pull_result.success:
                        image = service.get("image", "(unknown)")
                        logger.error(
                            f"Failed to pull docker image '{image}' from remote registry. If this is a locally built image add 'x-local: true' to the the service definition to prevent this error."
                        )

            # provide some space above task display
            print("")

        except BaseException as ex:
            await project_cleanup_shutdown(True)
            raise ex

    @override
    @classmethod
    async def sample_init(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> dict[str, ToolEnvironment]:
        tools_log("setup")

        # create environment variables for sample metadata
        env: dict[str, str] = {}
        for key, value in metadata.items():
            env[f"SAMPLE_METADATA_{key.replace(' ', '_').upper()}"] = str(value)

        # create project
        project = await ComposeProject.create(
            name=task_project_name(task_name), config=config, env=env
        )

        # enumerate the services that will be created
        services = await compose_services(project)

        # start the services
        await compose_up(project)

        # note that the project is running
        project_startup(project)

        # check to ensure that the services are running
        await compose_check_running(list(services.keys()), project=project)

        # create tool environments
        environments: dict[str, ToolEnvironment] = {}
        for service, service_info in services.items():
            # update the project w/ the working directory
            project.working_dir = await container_working_dir(service, project)

            # create the docker tool environemnt
            docker_env = DockerToolEnvironment(service, project)

            # save reference to environment (mark as default if requested)
            is_default = service_info.get("x-default", False) is True
            key = "default" if is_default else service
            environments[key] = docker_env

        # confirm that we have a 'default' environemnt
        if environments.get("default", None) is None:
            raise RuntimeError(
                "No 'default' service found in Docker compose file. "
                + "You should either name a service 'default' or add "
                + "'x-default: true' to one of your service definitions."
            )

        return environments

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: str | None,
        environments: dict[str, ToolEnvironment],
        interrupted: bool,
    ) -> None:
        # if we were interrupted then wait unil the end of the task to cleanup
        # (this enables us to show output for the cleanup operation)
        if not interrupted:
            # extract project from first environment
            project = cast(
                DockerToolEnvironment, next(iter(environments.values()))
            )._project
            # cleanup the project
            await project_cleanup(project=project, quiet=True)

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: str | None, cleanup: bool
    ) -> None:
        await project_cleanup_shutdown(cleanup)

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        await cli_cleanup(id)

    def __init__(self, service: str, project: ComposeProject) -> None:
        super().__init__()
        self._service = service
        self._project = project

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
        timeout: int | None = None,
    ) -> ExecResult[str]:
        # Forward environment commands to docker compose exec so they
        # will be available to the bash command
        env_args = []
        if len(env.items()) > 0:
            for key, value in env.items():
                env_args.append("--env")
                env_args.append(f"{key}={value}")

        try:
            result = await compose_exec(
                env_args + [self._service] + cmd,
                project=self._project,
                timeout=timeout,
                input=input,
            )
        except UnicodeDecodeError:
            raise ToolError(
                "Unicode decoding error reading command output (it is likely binary rather than text)"
            )
        return result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        tools_log(f"write_file: {file}")

        # Write the contents to a temp file
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            src_file = os.path.join(temp_dir, os.path.basename(file))
            if isinstance(contents, str):
                async with aiofiles.open(src_file, "w", encoding="utf-8") as f:
                    await f.write(contents)
            else:
                async with aiofiles.open(src_file, "wb") as f:
                    await f.write(contents)

            # resolve relative file paths
            file = container_file(self._project, file)

            # ensure that the directory exists
            parent = Path(file).parent.as_posix()
            if parent != ".":
                result = await self.exec(["mkdir", "-p", parent])
                if not result.success:
                    msg = f"Failed to create container directory {parent}: {result.stderr}"
                    raise RuntimeError(msg)

            # use the cp command to copy the file
            await compose_cp(
                src=os.path.basename(src_file),
                dest=f"{self._service}:{file}",
                project=self._project,
                cwd=os.path.dirname(src_file),
            )

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        tools_log(f"read_file: {file}")

        # Write the contents to a temp file
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            # resolve relative file paths
            file = container_file(self._project, file)

            # copy the file
            dest_file = os.path.join(temp_dir, os.path.basename(file))
            try:
                await compose_cp(
                    src=f"{self._service}:{file}",
                    dest=os.path.basename(dest_file),
                    project=self._project,
                    cwd=os.path.dirname(dest_file),
                )
            except RuntimeError as ex:
                if "could not find" in str(ex).lower():
                    raise FileNotFoundError(str(ex))
                else:
                    raise ex

            # read and return w/ appropriate encoding
            if text:
                async with aiofiles.open(dest_file, "r", encoding="utf-8") as f:
                    return await f.read()
            else:
                async with aiofiles.open(dest_file, "rb") as f:
                    return await f.read()


async def container_working_dir(
    service: str, project: ComposeProject, default: str = "/"
) -> str:
    result = await compose_exec([service, "bash", "-c", "pwd"], project)
    if result.success:
        return result.stdout.strip()
    else:
        logger.warning(
            f"Failed to get working directory for docker container '{service}': "
            + f"{result.stderr}"
        )
        return default


def container_file(project: ComposeProject, file: str) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = Path(project.working_dir) / path
    return path.as_posix()
