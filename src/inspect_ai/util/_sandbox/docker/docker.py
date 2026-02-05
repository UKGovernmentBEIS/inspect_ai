import base64
import errno
import json
import os
import shlex
import tempfile
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple, Union, overload

from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult, subprocess

from ..compose import COMPOSE_FILES, DOCKERFILE, ComposeConfig
from ..environment import (
    HostMapping,
    PortMapping,
    SandboxConnection,
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from ..limits import (
    SandboxEnvironmentLimits,
    verify_exec_result_size,
    verify_read_file_size,
)
from ..registry import sandboxenv
from .cleanup import (
    cli_cleanup,
    project_cleanup,
    project_cleanup_shutdown,
    project_cleanup_startup,
    project_record_auto_compose,
    project_startup,
)
from .compose import (
    compose_build,
    compose_check_running,
    compose_cleanup_images,
    compose_cp,
    compose_exec,
    compose_ps,
    compose_pull,
    compose_services,
    compose_up,
)
from .internal import build_internal_image, is_internal_image
from .prereqs import validate_prereqs
from .util import ComposeProject, task_project_name

logger = getLogger(__name__)


@sandboxenv(name="docker")
class DockerSandboxEnvironment(SandboxEnvironment):
    @classmethod
    def config_files(cls) -> list[str]:
        return COMPOSE_FILES + [DOCKERFILE]

    @classmethod
    def is_docker_compatible(cls) -> bool:
        return True

    @classmethod
    def default_concurrency(cls) -> int | None:
        count = os.cpu_count() or 1
        return 2 * count

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        # validate prereqs
        await validate_prereqs()

        # intialize project cleanup
        project_cleanup_startup()

        try:
            # create project
            project = await ComposeProject.create(
                name=task_project_name(task_name), config=config
            )

            # record auto compose
            project_record_auto_compose(project)

            # build containers which are out of date
            await compose_build(project)

            # cleanup images created during build
            await compose_cleanup_images(project, timeout=60)

            services = await compose_services(project)
            for name, service in services.items():
                # if the service has an explicit container_name then
                # error (as this won't work w/ epochs > 1)
                container_name = service.get("container_name", None)
                if container_name:
                    raise PrerequisiteError(
                        f"ERROR: Docker service '{name}' includes an explicitly configured container_name ('{container_name}'). This is not permitted, as container names should be provisioned by Docker compose and an explicit container_name will not work with epochs > 1."
                    )

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
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        # get interpolated environment variables and underlying config path and text
        resolved = resolve_config_environment(config, metadata)

        # don't even consider sample-specific environment if there are no sample metadata refs
        if resolved and len(resolved.env) > 0:
            # resolve images using our env vars
            result = await subprocess(
                ["docker", "compose", "-f", resolved.config_file, "config", "--images"],
                env=resolved.env,
            )
            if result.success:
                # look through the images, if one of them doesn't apper in the the
                # config text then this compose file requires its own sample specific
                # environment for resolution
                images = result.stdout.strip().splitlines()
                for image in images:
                    if image not in resolved.config_text:
                        return resolved.env
            else:
                logger.warning(
                    f"Unexpected error reading compose file '{resolved.config_file}': {result.stderr}"
                )

        # no per-sample environment required
        return {}

    @override
    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, SandboxEnvironment]:
        # create environment variables for sample metadata
        resolved = resolve_config_environment(config, metadata)
        env = resolved.env if resolved is not None else {}

        # create project
        from inspect_ai.log._samples import sample_active

        sample = sample_active()
        project = await ComposeProject.create(
            name=task_project_name(task_name),
            config=config,
            sample_id=sample.sample.id if sample is not None else None,
            epoch=sample.epoch if sample is not None else None,
            env=env,
        )

        # note that the project is running
        project_startup(project)

        try:
            # enumerate the services that will be created
            services = await compose_services(project)

            # start the services
            result = await compose_up(project, services)

            # check to ensure that the services are running
            running_services = await compose_check_running(
                list(services.keys()), project=project
            )

            if not running_services:
                raise RuntimeError(
                    f"No services started.\nCompose up stderr: {result.stderr}"
                )

            # create sandbox environments for all running services
            default_service: str | None = None
            environments: dict[str, SandboxEnvironment] = {}
            for service, service_info in services.items():
                if service in running_services:
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
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        # if we were interrupted then wait unil the end of the task to cleanup
        # (this enables us to show output for the cleanup operation)
        if not interrupted:
            # extract project from first environment
            project = (
                next(iter(environments.values()))
                .as_type(DockerSandboxEnvironment)
                ._project
            )
            # cleanup the project
            await project_cleanup(project=project, quiet=True)

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
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
        env: dict[str, str] | None = None,
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
        concurrency: bool = True,
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
        if env:
            for key, value in env.items():
                args.append("--env")
                args.append(f"{key}={value}")

        exec_result = await compose_exec(
            args + [self._service] + cmd,
            project=self._project,
            timeout=timeout,
            timeout_retry=timeout_retry,
            input=input,
            output_limit=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
            concurrency=concurrency,
        )
        verify_exec_result_size(exec_result)
        if exec_result.returncode == 126 and "permission denied" in exec_result.stdout:
            raise PermissionError(f"Permission denied executing command: {exec_result}")

        return exec_result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        # defualt timeout for write_file operations
        TIMEOUT = 180

        # resolve relative file paths
        file = self.container_file(file)

        # ensure that the directory exists
        parent = Path(file).parent.as_posix()
        if parent != ".":
            result = await self.exec(["mkdir", "-p", parent])
            if not result.success:
                msg = f"Failed to create container directory {parent}: {result.stderr}"
                raise RuntimeError(msg)

        # write the file
        if isinstance(contents, str):
            result = await self.exec(
                [
                    "sh",
                    "-e",
                    "-c",
                    'tee -- "$1" > /dev/null',
                    "write_file_script",
                    file,
                ],
                input=contents,
                timeout=TIMEOUT,
            )
        else:
            base64_contents = base64.b64encode(contents).decode("US-ASCII")
            result = await self.exec(
                [
                    "sh",
                    "-e",
                    "-c",
                    'base64 -d | tee -- "$1" > /dev/null',
                    "write_file_script",
                    file,
                ],
                input=base64_contents,
                timeout=TIMEOUT,
            )
        if result.returncode != 0:
            if "permission denied" in result.stderr.casefold():
                ls_result = await self.exec(["ls", "-la", "."])
                error_string = f"Permission was denied. Error details: {result.stderr}; ls -la: {ls_result.stdout}"
                raise PermissionError(error_string)
            elif (
                "cannot overwrite directory" in result.stderr.casefold()
                or "is a directory" in result.stderr.casefold()
            ):
                raise IsADirectoryError(
                    f"Failed to write file: {file} because it is a directory already"
                )
            else:
                raise RuntimeError(f"failed to copy during write_file: {result}")

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
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
                    output_limit=SandboxEnvironmentLimits.MAX_READ_FILE_SIZE,
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
                with open(dest_file, "r", newline="", encoding="utf-8") as f:
                    return f.read()
            else:
                with open(dest_file, "rb") as f:
                    return f.read()

    @override
    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        # find container for service
        services = await compose_ps(project=self._project)
        container = next(
            (
                service["Name"]
                for service in services
                if service["Service"] == self._service
            ),
            None,
        )

        # vscode doesn't support attaching to a container as a specific user,
        # so don't include the vscode command if a user is specified
        vscode_command = (
            [
                "remote-containers.attachToRunningContainer",
                container,
            ]
            if user is None
            else None
        )

        # return container connection
        if container:
            return SandboxConnection(
                type="docker",
                command=shlex.join(
                    [
                        "docker",
                        "exec",
                        "-it",
                        *(["--user", user] if user else []),
                        container,
                        "bash",
                        "-l",
                    ]
                ),
                vscode_command=vscode_command,
                ports=await get_ports_info(container),
                container=container,
            )
        # error (not currently running)
        else:
            raise ConnectionError(
                f"Service '{self._service} is not currently running.'"
            )

    def default_polling_interval(self) -> float:
        return 0.2

    def container_file(self, file: str) -> str:
        path = Path(file)
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        return path.as_posix()


async def container_working_dir(
    service: str, project: ComposeProject, default: str = "/"
) -> str:
    result = await compose_exec(
        [service, "sh", "-c", "pwd"], timeout=60, project=project
    )
    if result.success:
        return result.stdout.strip()
    else:
        logger.warning(
            f"Failed to get working directory for docker container '{service}': "
            + f"{result.stderr}"
        )
        return default


async def get_ports_info(container: str) -> list[PortMapping] | None:
    try:
        result = await subprocess(
            [
                "docker",
                "inspect",
                container,
                "--format",
                "{{json .NetworkSettings.Ports}}",
            ],
            timeout=60,
        )

        if not result.success:
            raise RuntimeError(result.stderr)

        return parse_docker_inspect_ports(result.stdout)

    # It's currently a policy decision to let docker timeouts to be silent.
    except TimeoutError:
        return None


def parse_docker_inspect_ports(json_str: str) -> list[PortMapping] | None:
    """
    Parses the JSON output from `docker inspect {container_name} --format='{{json .NetworkSettings.Ports}}'` to extract port mappings.

    Args:
        json_str (str): A JSON string representing the `NetworkSettings.Ports` output of `docker inspect`. e.g.
          ```
          {
              "5900/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54023"}],
              "8080/tcp": [{"HostIp": "0.0.0.0", "HostPort": "54024"}]
          }
          ```

    Returns:
        list[PortMapping] | None: A list of PortMapping objects if any port mappings are found,
                                   otherwise None.
    """
    data = json.loads(json_str)
    port_mappings = []
    for port_protocol, mappings in data.items():
        if mappings is None:
            continue
        container_port, protocol = port_protocol.split("/")
        host_mappings = [
            HostMapping(host_ip=mapping["HostIp"], host_port=int(mapping["HostPort"]))
            for mapping in mappings
        ]
        port_mapping = PortMapping(
            container_port=int(container_port),
            protocol=protocol,
            mappings=host_mappings,
        )
        port_mappings.append(port_mapping)
    return port_mappings if port_mappings else None


class ConfigEnvironment(NamedTuple):
    config_file: str
    config_text: str
    env: dict[str, str]


def resolve_config_environment(
    config: SandboxEnvironmentConfigType | None,
    metadata: dict[str, str],
) -> ConfigEnvironment | None:
    # create environment variables for sample metadata
    if isinstance(config, str) and Path(config).exists():
        # read the config file
        config_file = config
        with open(config, "r") as f:
            config_text = f.read()

        # only add metadata files if the key is in the file
        env: dict[str, str] = {}
        for key, value in metadata.items():
            key = f"SAMPLE_METADATA_{key.replace(' ', '_').upper()}"
            if key in config_text:
                env[key] = str(value)

        # return resolved
        return ConfigEnvironment(config_file, config_text, env)
    elif isinstance(config, ComposeConfig):
        # ComposeConfig objects don't support metadata interpolation
        # (they are already fully resolved)
        return None
    else:
        return None
