import tempfile
from logging import getLogger
from pathlib import Path
from typing import Literal, Union, overload

import aiofiles
from typing_extensions import override

from inspect_ai.solver._tool.environment.environment import (
    ToolEnvironment,
    ToolEnvironments,
)
from inspect_ai.solver._tool.environment.registry import toolenv
from inspect_ai.util._context.subprocess import ExecResult

from .compose import (
    compose_build,
    compose_check_running,
    compose_cleanup_images,
    compose_cp,
    compose_down,
    compose_exec,
    compose_mkdir,
    compose_pull,
    compose_services,
    compose_up,
)
from .config import auto_config
from .util import to_project, tools_log

logger = getLogger(__name__)


@toolenv(name="docker")
class DockerToolEnvironment(ToolEnvironment):
    @classmethod
    async def startup(cls, task_name: str, config: str | None) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            # unique project name for provisioning
            project = to_project(task_name)

            # synthesize config if necessary
            config = config if config else await auto_config(temp_dir)

            # build containers which are out of date
            await compose_build(project=project, config=config)

            # cleanup images created during pull
            await compose_cleanup_images(project=project, config=config)

            # pull any remote images
            pull_result = await compose_pull(project=project, config=config)
            if not pull_result.success:
                msg = "Failed to pull docker images"
                raise RuntimeError(msg)

            # provide some space above task display
            print("")

    @override
    @classmethod
    async def setup(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> ToolEnvironments:
        tools_log("setup")

        # Provide a temporary directory that is available during setup
        temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)

        # Create a unique project name to disambiguate different instances
        # of the docker compositions
        project = to_project(task_name)

        # confirm that there is a docker compose file in the working directory
        # otherwise synthesize a default compose file
        config = config if config else await auto_config(temp_dir.name)

        # enumerate the services that will be created
        services = await compose_services(project=project, config=config)

        # start the services
        await compose_up(project, config)

        # check to ensure that the services are running
        await compose_check_running(
            list(services.keys()), project=project, config=config
        )

        # create tool environments
        environments: dict[str, ToolEnvironment] = {}
        for name, service in services.items():
            # create the docker tool environemnt
            docker_env = DockerToolEnvironment(name, project, config)

            # save reference to enviroinment (mark as default if requested)
            is_default = service.get("x-default", False) is True
            key = "default" if is_default else name
            environments[key] = docker_env

            # create working dir
            await compose_mkdir(
                SAMPLE_DIR,
                service=docker_env._service,
                config=docker_env._config,
                project=docker_env._project,
            )

        # confirm that we have a 'default' environemnt
        if environments.get("default", None) is None:
            raise RuntimeError(
                "No 'default' service found in Docker compose file. "
                + "You should either name a service 'default' or add "
                + "'x-default: true' to one of your service definitions."
            )

        async def cleanup(cancelled: bool) -> None:
            # bring down services
            await compose_down(project=project, config=config, cancelled=cancelled)

            # cleanup the temp directory
            temp_dir.cleanup()

        return ToolEnvironments(environments=environments, cleanup=cleanup)

    def __init__(
        self,
        service: str,
        project: str,
        config: str | None,
    ) -> None:
        super().__init__()
        self._service = service
        self._project = project
        self._config = config

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
            env_args = [f"--env {key}={value}" for key, value in env.items()]

        result = await compose_exec(
            ["--workdir", SAMPLE_DIR] + env_args + [self._service] + cmd,
            config=self._config,
            project=self._project,
            timeout=timeout,
            input=input,
        )
        return result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        tools_log(f"write_file: {file}")

        # Write the contents to a temp file
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            if isinstance(contents, str):
                async with aiofiles.open(temp_file.name, "w", encoding="utf-8") as f:
                    await f.write(contents)
            else:
                async with aiofiles.open(temp_file.name, "wb") as f:
                    await f.write(contents)

            # resolve relative file paths to sample dir
            file = container_file(file)

            # ensure that the directory exists
            parent = Path(file).parent.as_posix()
            if parent != ".":
                result = await self.exec(["mkdir", "-p", parent])
                if not result.success:
                    msg = f"Failed to create container directory {parent}: {result.stderr}"
                    raise RuntimeError(msg)

            # use the cp command to copy the file
            await compose_cp(
                src=temp_file.name,
                dest=f"{self._service}:{file}",
                config=self._config,
                project=self._project,
            )

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        tools_log(f"read_file: {file}")

        # Write the contents to a temp file
        with tempfile.NamedTemporaryFile(delete=True) as temp_file:
            # resolve relative file paths to sample dir
            file = container_file(file)

            # copy the file
            await compose_cp(
                src=f"{self._service}:{file}",
                dest=temp_file.name,
                project=self._project,
                config=self._config,
            )

            # read and return w/ appropriate encoding
            if text:
                async with aiofiles.open(temp_file.name, "r", encoding="utf-8") as f:
                    return await f.read()
            else:
                async with aiofiles.open(temp_file.name, "rb") as f:
                    return await f.read()


# directory where copy sample specific files to
SAMPLE_DIR = "/tmp/sample"


def container_file(file: str) -> str:
    path = Path(file)
    if not path.is_absolute():
        path = Path(SAMPLE_DIR) / path
    return path.as_posix()
