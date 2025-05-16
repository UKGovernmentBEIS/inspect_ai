"""Firecracker sandbox implementation for executing code in micro VMs.

This module implements the SandboxEnvironment interface to provide Firecracker-based
sandboxing. It leverages Docker Compose to create rootfs images, then uses 
Firecracker micro VMs to run the images in an isolated environment.

The Firecracker sandbox supports:
1. Standard Docker Compose files (for rootfs creation)
2. Single Dockerfile (auto-generating a compose file)
3. Running with no config (using a default container)

It handles building images using Docker, creating Firecracker micro VMs, executing commands,
and cleanup of resources.
"""

import base64
import errno
import json
import os
import shlex
import tempfile
import uuid
from logging import getLogger
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Literal, NamedTuple, Optional, Union, cast, overload

import requests
from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.util._subprocess import ExecResult, subprocess

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
from .config import CONFIG_FILES, DOCKERFILE
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
from .cleanup import (
    cli_cleanup,
    project_cleanup,
    project_cleanup_shutdown,
    project_cleanup_startup,
    project_record_auto_compose,
    project_startup,
)
from .prereqs import validate_prereqs
from .util import ComposeProject, FirecrackerVM, task_project_name

logger = getLogger(__name__)


@sandboxenv(name="firecracker")
class FirecrackerSandboxEnvironment(SandboxEnvironment):
    """Firecracker-based sandbox environment for executing code in isolated micro VMs.
    
    This class implements the SandboxEnvironment interface to provide Firecracker-based 
    sandboxing. It uses Docker Compose to create rootfs images, then runs them in Firecracker
    micro VMs to provide isolation. This approach provides methods for file operations 
    and command execution within those micro VMs.
    
    The Firecracker sandbox supports:
    1. Standard Docker Compose files (for building rootfs images)
    2. Single Dockerfile (auto-generating a compose file)
    3. Running with no config (using a default container)
    
    It handles building/pulling images with Docker, creating and starting Firecracker micro VMs,
    executing commands, and cleanup of resources.
    """

    @classmethod
    def config_files(cls) -> list[str]:
        """Returns the list of configuration files supported by this provider.
        
        Returns:
            list[str]: Config filenames to look for (compose.yaml, Dockerfile, etc.)
        """
        return CONFIG_FILES + [DOCKERFILE]

    @classmethod
    def default_concurrency(cls) -> int | None:
        """Determines the default maximum number of concurrent sandboxes.
        
        Uses twice the number of CPU cores as the default concurrency limit.
        
        Returns:
            int: The recommended maximum number of concurrent Firecracker micro VMs
        """
        count = os.cpu_count() or 1
        return 2 * count

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        """Initializes Firecracker environment at task startup.
        
        This method:
        1. Validates Firecracker and Docker Compose prerequisites
        2. Sets up project tracking for cleanup
        3. Creates a Docker Compose project for rootfs creation
        4. Builds or pulls necessary images
        5. Validates service configuration
        
        Args:
            task_name: Name of the task using this sandbox
            config: Path to Docker configuration file or config object
            
        Raises:
            PrerequisiteError: If prerequisites aren't met or services are misconfigured
        """
        # validate prereqs
        await validate_prereqs()

        # initialize project cleanup
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

                # Pull any remote images needed
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
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        """Determines if sample-specific environments are needed for task initialization.
        
        This method checks if the Docker Compose configuration contains references to 
        sample metadata that would require environment variables to be set during task_init.
        This is particularly important for configurations that reference environment variables
        for image tags or other dynamic values.
        
        Args:
            config: Docker configuration (path or config object)
            metadata: Sample metadata fields
            
        Returns:
            dict[str, str]: Environment variables required for task_init for this sample,
                           or empty dict if no sample-specific environment is needed
        """
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
                # look through the images, if one of them doesn't appear in the the
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
        """Initializes Firecracker sandbox environments for a specific sample.
        
        This method:
        1. Creates a Docker Compose project with sample-specific metadata for rootfs
        2. Starts containers using docker-compose up to verify the services
        3. Creates Firecracker micro VMs using the Docker rootfs
        4. Creates sandbox environments for each running service
        
        Args:
            task_name: Name of the task using this sandbox
            config: Docker configuration (path or config object)
            metadata: Sample metadata fields
            
        Returns:
            dict[str, SandboxEnvironment]: Dictionary of service name to sandbox environment
            
        Raises:
            RuntimeError: If no services start successfully or no default service is found
        """
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

            # start the services to verify they work correctly
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
                    # Create a unique ID for this Firecracker VM
                    vm_id = f"{project.name}-{service}-{uuid.uuid4()}"
                    
                    # Get container rootfs path from Docker
                    # In a real implementation, you'd need to extract this from the Docker container
                    # For this example, we'll assume a simple path
                    rootfs_path = f"/tmp/firecracker/{vm_id}/rootfs"
                    kernel_path = "/usr/local/bin/vmlinux" # Example path to kernel
                    
                    # Create Firecracker VM
                    vm = FirecrackerVM(vm_id, rootfs_path, kernel_path)
                    
                    # update the project w/ the working directory
                    working_dir = await container_working_dir(service, project)

                    # create the firecracker sandbox environment
                    fc_env = FirecrackerSandboxEnvironment(service, project, working_dir, vm)

                    # save reference to default service if requested
                    if service_info.get("x-default", False):
                        default_service = service

                    # record service => environment
                    environments[service] = fc_env

            # confirm that we have a 'default' environment
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
        """Cleans up Firecracker environment resources.
        
        Args:
            task_name: Name of the task using this sandbox
            config: Configuration for the Firecracker environment
            environments: Dictionary of all sandbox environments created
            interrupted: Whether the cleanup was triggered by an interruption
        """
        # if we were interrupted then wait until the end of the task to cleanup
        # (this enables us to show output for the cleanup operation)
        if not interrupted:
            # extract project from first environment
            project = (
                next(iter(environments.values()))
                .as_type(FirecrackerSandboxEnvironment)
                ._project
            )
            
            # Cleanup all Firecracker VMs
            for env in environments.values():
                fc_env = env.as_type(FirecrackerSandboxEnvironment)
                await fc_env._vm.stop()
                
            # cleanup the Docker project
            await project_cleanup(project=project, quiet=True)

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        """Final cleanup after task completion.
        
        Args:
            task_name: Name of the task using this sandbox
            config: Configuration for the Firecracker environment
            cleanup: Whether to perform cleanup operations
        """
        await project_cleanup_shutdown(cleanup)

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        """Handles cleanup initiated from CLI.
        
        Args:
            id: Optional ID to limit the scope of cleanup
        """
        await cli_cleanup(id)

    def __init__(
        self, 
        service: str, 
        project: ComposeProject, 
        working_dir: str,
        vm: FirecrackerVM
    ) -> None:
        """Initializes a Firecracker sandbox environment.
        
        Args:
            service: Service name in the Docker Compose file
            project: ComposeProject reference for rootfs creation
            working_dir: Working directory inside the VM
            vm: FirecrackerVM instance for this sandbox
        """
        super().__init__()
        self._service = service
        self._project = project
        self._working_dir = working_dir
        self._vm = vm

    @override
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True,
    ) -> ExecResult[str]:
        """Executes a command in the Firecracker VM.
        
        This method runs a command inside the Firecracker VM. It handles setting the 
        working directory, user, and environment variables for the command execution.
        
        Args:
            cmd: Command and arguments to execute
            input: Optional stdin input for the command
            cwd: Working directory for command execution (relative to container working dir)
            env: Environment variables to pass to the command
            user: User to run the command as
            timeout: Command execution timeout in seconds
            timeout_retry: Whether to retry on timeout
            
        Returns:
            ExecResult: Execution result containing stdout, stderr, and return code
            
        Raises:
            PermissionError: If permission is denied executing the command
            TimeoutError: If the command times out and retry is disabled or fails
            OutputLimitExceededError: If command output exceeds size limits
        """
        # additional args
        args = []

        final_cwd = PurePosixPath(self._working_dir if cwd is None else cwd)
        if not final_cwd.is_absolute():
            final_cwd = PurePosixPath(self._working_dir) / final_cwd

        # The actual implementation would use the Firecracker API to execute the command
        # For simplicity, we'll use a placeholder implementation
        result = await self._vm.exec_command(
            cmd=cmd,
            input=input,
            cwd=str(final_cwd),
            env=env,
            user=user,
            timeout=timeout,
            output_limit=SandboxEnvironmentLimits.MAX_EXEC_OUTPUT_SIZE,
        )
        
        verify_exec_result_size(result)
        if result.returncode == 126 and "permission denied" in result.stdout:
            raise PermissionError(f"Permission denied executing command: {result}")

        return result

    @override
    async def write_file(self, file: str, contents: str | bytes) -> None:
        """Writes a file to the Firecracker VM.
        
        This method creates the parent directory if needed and writes either text or
        binary content to a file in the VM.
        
        Args:
            file: Path to the file (absolute or relative to container working directory)
            contents: Text or binary content to write
            
        Raises:
            PermissionError: If permission is denied to write the file
            IsADirectoryError: If the destination path exists but is a directory
            RuntimeError: If writing fails for another reason
        """
        # resolve relative file paths
        file = self.container_file(file)

        # ensure that the directory exists
        parent = Path(file).parent.as_posix()
        if parent != ".":
            result = await self.exec(["mkdir", "-p", parent])
            if not result.success:
                msg = f"Failed to create container directory {parent}: {result.stderr}"
                raise RuntimeError(msg)

        # In a real implementation, this would transfer the file to the VM
        # For now, we use a simplified approach
        try:
            await self._vm.write_file(file, contents)
        except Exception as e:
            if "permission denied" in str(e).casefold():
                raise PermissionError(f"Permission denied writing file: {file}")
            elif "cannot overwrite directory" in str(e).casefold() or "is a directory" in str(e).casefold():
                raise IsADirectoryError(f"Failed to write file: {file} because it is a directory already")
            else:
                raise RuntimeError(f"Failed to write file: {file}, error: {e}")

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @override
    async def read_file(self, file: str, text: bool = True) -> Union[str, bytes]:
        """Reads a file from the Firecracker VM.
        
        This method reads a file from the VM. It handles both text and binary files.
        
        Args:
            file: Path to the file (absolute or relative to container working directory)
            text: If True, read as text (UTF-8); if False, read as binary
            
        Returns:
            str | bytes: File contents as text or binary data
            
        Raises:
            FileNotFoundError: If the file doesn't exist in the VM
            PermissionError: If permission is denied to read the file
            OutputLimitExceededError: If the file exceeds size limits
        """
        # resolve relative file paths
        original_file = file
        file = self.container_file(file)

        try:
            # In a real implementation, this would retrieve the file from the VM
            # For now, we use a simplified approach
            contents = await self._vm.read_file(file)
            verify_read_file_size(file)  # This would need adaptation for actual implementation
            
            if text:
                if isinstance(contents, bytes):
                    return contents.decode('utf-8')
                return contents
            else:
                if isinstance(contents, str):
                    return contents.encode('utf-8')
                return contents
                
        except Exception as e:
            error_msg = str(e).lower()
            if "no such file" in error_msg or "not found" in error_msg:
                raise FileNotFoundError(errno.ENOENT, "No such file or directory.", original_file)
            elif "permission denied" in error_msg:
                raise PermissionError(errno.EACCES, "Permission denied.", original_file)
            else:
                raise e

    @override
    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        """Provides connection information for the Firecracker VM.
        
        This method returns information needed to connect to the VM.
        
        Args:
            user: Optional user to connect as
            
        Returns:
            SandboxConnection: Connection information for the VM
            
        Raises:
            ConnectionError: If the VM is not currently running
        """
        if not await self._vm.is_running():
            raise ConnectionError(f"Service '{self._service}' is not currently running")
            
        # In a real implementation, return actual connection information
        # For this example, we'll return placeholder data
        return SandboxConnection(
            type="firecracker",
            command=f"ssh user@{self._vm.ip_address}",
            ports=None,
            container=self._vm.id,
        )

    def container_file(self, file: str) -> str:
        """Converts a file path to an absolute path inside the VM.
        
        If the path is not absolute, it is resolved relative to the VM's working directory.
        
        Args:
            file: File path (absolute or relative)
            
        Returns:
            str: Absolute path in the VM's file system
        """
        path = Path(file)
        if not path.is_absolute():
            path = Path(self._working_dir) / path
        return path.as_posix()


async def container_working_dir(
    service: str, project: ComposeProject, default: str = "/"
) -> str:
    """Determines the working directory inside a VM.
    
    Executes 'pwd' command to get the current working directory.
    
    Args:
        service: Service name in the Docker Compose file
        project: ComposeProject reference
        default: Default working directory if command fails
        
    Returns:
        str: VM's working directory or default if command fails
    """
    result = await compose_exec(
        [service, "sh", "-c", "pwd"], timeout=60, project=project
    )
    if result.success:
        return result.stdout.strip()
    else:
        logger.warning(
            f"Failed to get working directory for service '{service}': "
            + f"{result.stderr}"
        )
        return default


class ConfigEnvironment(NamedTuple):
    config_file: str
    config_text: str
    env: dict[str, str]


def resolve_config_environment(
    config: SandboxEnvironmentConfigType | None,
    metadata: dict[str, str],
) -> ConfigEnvironment | None:
    """Resolves environment variables for configuration files.
    
    This helper function reads a configuration file and builds a set of
    environment variables from sample metadata.
    
    Args:
        config: Configuration file path or object
        metadata: Sample metadata fields
        
    Returns:
        ConfigEnvironment | None: Configuration environment information or None
    """
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
    else:
        return None