import errno
import os
import tempfile
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import Literal, Union, cast, overload

import aiofiles
from typing_extensions import override

from inspect_ai.util._subprocess import ExecResult

from ..environment import SandboxEnvironment
from ..limits import verify_exec_result_size, verify_read_file_size
from ..registry import sandboxenv
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
    compose_command,
    compose_cp,
    compose_exec,
    compose_pull,
    compose_services,
    compose_up,
)
from .config import CONFIG_FILES, DOCKERFILE
from .internal import build_internal_image, is_internal_image
from .prereqs import validate_prereqs
from .util import ComposeProject, sandbox_log, task_project_name

logger = getLogger(__name__)


@sandboxenv(name="docker")
class DockerSandboxEnvironment(SandboxEnvironment):
    @classmethod
    def config_files(cls) -> list[str]:
        return CONFIG_FILES + [DOCKERFILE]

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

            services = await compose_services(project)
            for name, service in services.items():
                # build internal images
                image = service.get("image", None)
                if image and is_internal_image(image):
                    await build_internal_image(image)
                # pull any remote images
                elif (
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
    ) -> dict[str, SandboxEnvironment]:
        sandbox_log("setup")

        # create environment variables for sample metadata
        env: dict[str, str] = {}
        if config and Path(config).exists():
            # read the config file
            with open(config, "r") as f:
                config_text = f.read()

            # only add metadata files if the key is in the file
            for key, value in metadata.items():
                key = f"SAMPLE_METADATA_{key.replace(' ', '_').upper()}"
                if key in config_text:
                    env[key] = str(value)

        # create project
        project = await ComposeProject.create(
            name=task_project_name(task_name), config=config, env=env
        )

        try:
            # enumerate the services that will be created
            services = await compose_services(project)

            # start the services
            await compose_up(project)

            # note that the project is running
            project_startup(project)

            # check to ensure that the services are running
            await compose_check_running(list(services.keys()), project=project)

            # create sandbox environments
            default_service: str | None = None
            environments: dict[str, SandboxEnvironment] = {}
            for service, service_info in services.items():
                # update the project w/ the working directory
                working_dir = await container_working_dir(service, project)

                # create the docker sandbox environemnt
                docker_env = DockerSandboxEnvironment(service, project, working_dir)

                # save reference to default service if requested
                if service_info.get("x-default", False):
                    default_service = service

                # record service => environment
                environments[service] = docker_env

            # confirm that we have a 'default' environemnt
            if environments.get("default", None) is None and default_service is None:
                raise RuntimeError(
                    "No 'default' service found in Docker compose file. "
                    + "You should either name a service 'default' or add "
                    + "'x-default: true' to one of your service definitions."
                )

            # ensure that the default service is first in the dictionary
            default_service = default_service or "default"
            default_environment = environments[default_service]
            del environments[default_service]
            environments = {default_service: default_environment} | environments

        except BaseException as ex:
            await project_cleanup(project, True)
            raise ex

        return environments

    @override
    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: str | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        # if we were interrupted then wait unil the end of the task to cleanup
        # (this enables us to show output for the cleanup operation)
        if not interrupted:
            # extract project from first environment
            project = cast(
                DockerSandboxEnvironment, next(iter(environments.values()))
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

    def __init__(self, service: str, project: ComposeProject, working_dir: str) -> None:
        super().__init__()
        self._service = service
        self._project = project
        self._working_dir = working_dir

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
    ) -> ExecResult[str]:
        # additional args
        args = []

        final_cwd = PurePosixPath(self._working_dir if cwd is None else cwd)
        if not final_cwd.is_absolute():
            final_cwd = self._working_dir / final_cwd

        args.append("--workdir")
        args.append(str(final_cwd))

        if user:
            args.append("--user")
            args.append(user)

        # Forward environment commands to docker compose exec so they
        # will be available to the bash command
        if len(env.items()) > 0:
            for key, value in env.items():
                args.append("--env")
                args.append(f"{key}={value}")

        exec_result = await compose_exec(
            args + [self._service] + cmd,
            project=self._project,
            timeout=timeout,
            input=input,
        )
        verify_exec_result_size(exec_result)
        if exec_result.returncode == 126 and "permission denied" in exec_result.stdout:
            raise PermissionError(f"Permission denied executing command: {exec_result}")

        return exec_result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        sandbox_log(f"write_file: {file}")

        # resolve relative file paths
        file = self.container_file(file)

        # We want to be able to write a file in the container,
        # but only if the container's user would be allowed to do that.
        # We need to avoid implicitly trusting the provided "file" string.
        # For example, it shouldn't be passed as part of a shell command,
        # because of the risk of shell injection.

        local_tmpfile = tempfile.NamedTemporaryFile()

        # write contents into a local tmp file (not in the container)
        if isinstance(contents, str):
            local_tmpfile.write(contents.encode("utf-8"))
        else:
            local_tmpfile.write(contents)

        local_tmpfile.flush()

        # Copy the local tmp file into a tmp file on the container.
        # Both tmp files have safe names as we created them ourselves

        # We write the tmp file in the default directory,
        # because of strangeness with /tmp on GitHub action runners.

        # We are reusing the generated local tmp file name within
        # the sandbox to save on a container roundtrip. There is a very slight
        # risk of collision if another write_file call happens
        # to get the same local tmp file name. But we assume tmp file
        # names have enough randomness for us to ignore that.

        container_tmpfile = (
            f".tmp_inspect_sandbox_{os.path.basename(local_tmpfile.name)}"
        )

        # compose cp will leave the file owned by root
        await compose_cp(
            src=local_tmpfile.name,
            dest=f"{self._service}:{self.container_file(container_tmpfile)}",
            project=self._project,
        )

        local_tmpfile.close()  # this will also delete the file

        if not hasattr(self, "_docker_user"):
            uid = (await self.exec(["id", "-u"])).stdout.strip()
            gid = (await self.exec(["id", "-g"])).stdout.strip()
            self._docker_user = (uid, gid)

        await compose_command(
            [
                "exec",
                "--user",
                "root",
                self._service,
                "chown",
                f"{self._docker_user[0]}:{self._docker_user[1]}",
                container_tmpfile,
            ],
            project=self._project,
        )

        parent = PurePosixPath(file).parent

        # We do these steps in a shell script for efficiency to avoid round-trips to docker.
        res_cp = await self.exec(
            [
                "sh",
                "-e",
                "-c",
                'mkdir -p -- "$1"; cp -T -- "$2" "$3"; rm -- "$2"',
                "copy_script",
                str(parent),
                container_tmpfile,
                file,
            ]
        )

        if res_cp.returncode != 0:
            if "Permission denied" in res_cp.stderr:
                ls_result = await self.exec(["ls", "-la", "."])
                error_string = f"Permission was denied. Error details: {res_cp.stderr}; ls -la: {ls_result.stdout}; {self._docker_user=}"
                raise PermissionError(error_string)
            elif (
                "cannot overwrite directory" in res_cp.stderr
                or "is a directory" in res_cp.stderr
            ):
                raise IsADirectoryError(
                    f"Failed to write file: {file} because it is a directory already"
                )
            else:
                raise RuntimeError(f"failed to copy during write_file: {res_cp}")

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        sandbox_log(f"read_file: {file}")

        # Write the contents to a temp file
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            # resolve relative file paths
            original_file = file
            file = self.container_file(file)

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
                # extract the message and normalise case
                message = str(ex).lower()

                # FileNotFoundError
                if "could not find the file" in message:
                    raise FileNotFoundError(
                        errno.ENOENT, "No such file or directory.", original_file
                    )

                # PermissionError
                elif "permission denied" in message:
                    raise PermissionError(
                        errno.EACCES, "Permission denied.", original_file
                    )
                else:
                    raise ex

            verify_read_file_size(dest_file)

            # read and return w/ appropriate encoding
            if text:
                async with aiofiles.open(dest_file, "r", encoding="utf-8") as f:
                    return await f.read()
            else:
                async with aiofiles.open(dest_file, "rb") as f:
                    return await f.read()

    def container_file(self, file: str) -> str:
        path = Path(file)
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        return path.as_posix()


async def container_working_dir(
    service: str, project: ComposeProject, default: str = "/"
) -> str:
    result = await compose_exec([service, "sh", "-c", "pwd"], project)
    if result.success:
        return result.stdout.strip()
    else:
        logger.warning(
            f"Failed to get working directory for docker container '{service}': "
            + f"{result.stderr}"
        )
        return default
