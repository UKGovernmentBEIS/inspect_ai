from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import (
    Annotated,
    Any,
    Awaitable,
    Callable,
    Literal,
    Type,
    TypeVar,
    Union,
    cast,
    overload,
)

from pydantic import BaseModel, Field, model_validator

from inspect_ai._util.logger import warn_once

from .._subprocess import ExecResult
from .exec_remote import (
    ExecRemoteAwaitableOptions,
    ExecRemoteProcess,
    ExecRemoteStreamingOptions,
    exec_remote_awaitable,
    exec_remote_streaming,
)

logger = logging.getLogger(__name__)

ST = TypeVar("ST", bound="SandboxEnvironment")

TaskInit = Callable[[str, Union["SandboxEnvironmentConfigType", None]], Awaitable[None]]
TaskInitEnvironment = Callable[
    [Union["SandboxEnvironmentConfigType", None], dict[str, str]],
    Awaitable[dict[str, str]],
]
TaskCleanup = Callable[
    [str, Union["SandboxEnvironmentConfigType", None], bool], Awaitable[None]
]

SampleInit = Callable[
    [str, Union["SandboxEnvironmentConfigType", None], dict[str, str]],
    Awaitable[dict[str, "SandboxEnvironment"]],
]
SampleCleanup = Callable[
    [
        str,
        Union["SandboxEnvironmentConfigType", None],
        dict[str, "SandboxEnvironment"],
        bool,
    ],
    Awaitable[None],
]
ConfigDeserialize = Callable[[dict[str, Any]], BaseModel]


class HostMapping(BaseModel):
    host_ip: str
    host_port: int


class PortMapping(BaseModel):
    container_port: int
    protocol: Literal["tcp", "udp"]
    mappings: list[HostMapping]


class SandboxConnection(BaseModel):
    """Information required to connect to sandbox."""

    type: str
    """Sandbox type name (e.g. 'docker', 'local', etc.)"""

    command: str
    """Shell command to connect to sandbox."""

    vscode_command: list[Any] | None = Field(default=None)
    """Optional vscode command (+args) to connect to sandbox."""

    ports: list[PortMapping] | None = Field(default=None)
    """Optional list of port mappings into container"""

    container: str | None = Field(default=None)
    """Optional container name (does not apply to all sandboxes)."""


class SandboxEnvironment(abc.ABC):
    """Environment for executing arbitrary code from tools.

    Sandbox environments provide both an execution environment as well as a per-sample
    filesystem context to copy samples files into and resolve relative paths to.
    """

    @abc.abstractmethod
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
        """Execute a command within a sandbox environment.

        The current working directory for execution will be the per-sample
        filesystem context.

        Each output stream (stdout and stderr) is limited to 10 MiB. If exceeded, an
        `OutputLimitExceededError` will be raised.

        Args:
          cmd: Command or command and arguments to execute.
          input: Standard input (optional).
          cwd: Current working dir (optional). If relative, will be relative to the per-sample filesystem context.
          env: Environment variables for execution.
          user: Optional username or UID to run the command as.
          timeout: Optional execution timeout (seconds).
          timeout_retry: Retry the command in the case that it times out.
            Commands will be retried up to twice, with a timeout of no greater
            than 60 seconds for the first retry and 30 for the second.
          concurrency: For sandboxes that run locally, request that the `concurrency()`
            function be used to throttle concurrent subprocesses.

        Returns:
          Execution result (status code, stderr/stdout, etc.)

        Raises:
          TimeoutError: If the specified `timeout` expires
            (and `timeout_retry` attempts also timeout).
          UnicodeDecodeError: If an error occurs while
            decoding the command output.
          PermissionError: If the user does not have
            permission to execute the command.
          OutputLimitExceededError: If an output stream
            exceeds the 10 MiB limit.
        """
        ...

    @abc.abstractmethod
    async def write_file(self, file: str, contents: str | bytes) -> None:
        """Write a file into the sandbox environment.

        If the parent directories of the file path do not exist they
        should be automatically created.

        Args:
          file: Path to file (relative file paths will resolve to the
            per-sample working directory).
          contents: Text or binary file contents.

        Raises:
          PermissionError: If the current user does not have permission to
            write to the specified path.
          IsADirectoryError: If the file exists already and
            is a directory.
        """
        ...

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @abc.abstractmethod
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        """Read a file from the sandbox environment.

        File size is limited to 100 MiB.

        When reading text files, implementations should preserve newline constructs
        (e.g. crlf should be preserved not converted to lf). This is equivalent
        to specifying `newline=""` in a call to the Python `open()` function.

        Args:
          file: Path to file (relative file paths will resolve to the
            per-sample working directory).
          text: Read as a utf-8 encoded text file.

        Returns:
          Contents of file (as str or bytes for binary files)

        Raises:
          FileNotFoundError: If the file does not exist.
          UnicodeDecodeError: If an encoding error occurs
            while reading the file.
            (only applicable when `text = True`)
          PermissionError: If the user does not have
            permission to read from the specified path.
          IsADirectoryError: If the file is a directory.
          OutputLimitExceededError: If the file size
            exceeds the 100 MiB limit.
        """
        ...

    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        """Information required to connect to sandbox environment.

        Args:
          user: User to login as.

        Returns:
           SandboxConnection: connection information.

        Raises:
           NotImplementedError: For sandboxes that don't provide connections
           ConnectionError: If sandbox is not currently running.
        """
        raise NotImplementedError("connection not implemented")

    @overload
    async def exec_remote(
        self,
        cmd: list[str],
        options: ExecRemoteStreamingOptions | None = None,
        *,
        stream: Literal[True] = True,
    ) -> ExecRemoteProcess: ...

    @overload
    async def exec_remote(
        self,
        cmd: list[str],
        options: ExecRemoteAwaitableOptions | None = None,
        *,
        stream: Literal[False],
    ) -> ExecResult[str]: ...

    async def exec_remote(
        self,
        cmd: list[str],
        options: ExecRemoteStreamingOptions | ExecRemoteAwaitableOptions | None = None,
        *,
        stream: bool = True,
    ) -> ExecRemoteProcess | ExecResult[str]:
        """Start a command and return a process handle or result.

        In streaming mode (stream=True), the function returns only after the
        process has been successfully launched in the sandbox. The returned
        ExecRemoteProcess handle can then be iterated for output events or
        killed later.

        Both modes support automatic cleanup on cancellation: if the calling
        task is cancelled (e.g., via task group cancellation), the subprocess
        is automatically killed before the cancellation exception propagates.

        Usage patterns:

        1. Streaming (stream=True, default): iterate over events
           ```python
           proc = await sandbox.exec_remote(["pytest", "-v"])
           async for event in proc:
               match event:
                   case ExecRemoteEvent.Stdout(data=data): print(data, end="")
                   case ExecRemoteEvent.Stderr(data=data): print(data, end="", file=sys.stderr)
                   case ExecRemoteEvent.Completed(exit_code=code): print(f"Done: {code}")
           ```

        2. Fire-and-forget with explicit kill:
           ```python
           proxy = await sandbox.exec_remote(["./model-proxy"])
           # ... do other work ...
           await proxy.kill()  # terminate when done
           ```

        3. Simple await (stream=False): get result without streaming
           ```python
           result = await sandbox.exec_remote(["pytest", "-v"], stream=False)
           if result.success:
               print(result.stdout)
           ```

        4. Long-running process with automatic cleanup via task cancellation:
           ```python
           async with anyio.create_task_group() as tg:
               tg.start_soon(run_server)  # uses exec_remote(..., stream=False)
               yield  # do work while server runs
               tg.cancel_scope.cancel()  # server killed automatically
           ```

        Args:
            cmd: Command and arguments to execute.
            options: Execution options (see ExecRemoteOptions).
            stream: If True (default), returns ExecRemoteProcess for streaming.
                If False, returns ExecResult[str] directly.

        Returns:
            If stream=True: ExecRemoteProcess handle with events iterator and kill() method.
                The process is guaranteed to have been started in the sandbox when this returns.
            If stream=False: ExecResult[str] with success, returncode, stdout, and stderr.

        Raises:
            TimeoutError: If `timeout` is specified in ExecRemoteAwaitableOptions and the command exceeds it (only applicable when `stream=False`).
        """
        return await (exec_remote_streaming if stream else exec_remote_awaitable)(
            self, cmd, self.default_polling_interval(), options
        )

    def as_type(self, sandbox_cls: Type[ST]) -> ST:
        """Verify and return a reference to a subclass of SandboxEnvironment.

        Args:
           sandbox_cls: Class of sandbox (subclass of SandboxEnvironment)

        Returns:
           Reference to the sandbox using the requested type.

        Raises:
           TypeError: If the sandbox is not of the requested type.
        """
        if isinstance(self, sandbox_cls):
            return self
        else:
            raise TypeError(
                f"Expected instance of {sandbox_cls.__name__}, got {type(self).__name__}"
            )

    def default_polling_interval(self) -> float:
        """Polling interval for sandbox service requests."""
        return 2

    @classmethod
    def default_concurrency(cls) -> int | None:
        """Default max_sandboxes for this provider (`None` means no maximum)"""
        return None

    @classmethod
    async def task_init(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None
    ) -> None:
        """Called at task startup initialize resources.

        Args:
          task_name: Name of task using the sandbox environment.
          config: Implementation defined configuration (optional).
        """
        pass

    @classmethod
    async def task_init_environment(
        cls, config: SandboxEnvironmentConfigType | None, metadata: dict[str, str]
    ) -> dict[str, str]:
        """Called at task startup to identify environment variables required by task_init for a sample.

        Return 1 or more environment variables to request a dedicated call to task_init
        for samples that have exactly these environment variables (by default there is
        only one call to task_init for all of the samples in a task if they share a
        sandbox configuration).

        This is useful for situations where config files are dynamic (e.g. through
        sample metadata variable interpolation) and end up yielding different images
        that need their own init (e.g. 'docker pull').

        Args:
            config: Implementation defined configuration (optional).
            metadata: metadata: Sample `metadata` field

        Returns:
            Environment variables to set for call to task_init.
        """
        return {}

    @classmethod
    async def sample_init(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        metadata: dict[str, str],
    ) -> dict[str, "SandboxEnvironment"]:
        """Initialize sandbox environments for a sample.

        Args:
          task_name: Name of task using the sandbox environment.
          config: Implementation defined configuration (optional).
          metadata: Sample `metadata` field

        Returns:
          Dictionary of named sandbox environments. The environment which represents
          the default environment (resolved by `sandbox("default")` or `sandbox()`) must
          be the first key/value pair in the dictionary.
        """
        return {}

    @classmethod
    @abc.abstractmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, "SandboxEnvironment"],
        interrupted: bool,
    ) -> None:
        """Cleanup sandbox environments.

        Args:
          task_name: Name of task using the sandbox environment.
          config: Implementation defined configuration (optional).
          environments: Sandbox environments created for this sample.
          interrupted: Was the task interrupted by an error or cancellation
        """
        ...

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: SandboxEnvironmentConfigType | None, cleanup: bool
    ) -> None:
        """Called at task exit as a last chance to cleanup resources.

        Args:
          task_name: Name of task using the sandbox environment.
          config: Implementation defined configuration (optional).
          cleanup: Whether to actually cleanup environment resources
            (False if `--no-sandbox-cleanup` was specified)
        """
        pass

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        """Handle a cleanup invoked from the CLI (e.g. inspect sandbox cleanup).

        Args:
          id: Optional ID to limit scope of cleanup.
        """
        pass

    @classmethod
    def config_files(cls) -> list[str]:
        """Standard config files for this provider (used for automatic discovery)"""
        return []

    @classmethod
    def is_docker_compatible(cls) -> bool:
        """Is the provider docker compatible (accepts Dockerfile and compose.yaml)"""
        return any(["compose.yaml" in f for f in cls.config_files()])

    @classmethod
    def config_deserialize(cls, config: dict[str, Any]) -> BaseModel:
        """Deserialize a sandbox-specific configuration model from a dict.

        Override this method if you support a custom configuration model.

        A basic implementation would be: `return MySandboxEnvironmentConfig(**config)`

        Args:
          config: Configuration dictionary produced by serializing the configuration
            model.

        Returns:
          The sandbox-specific configuration model.
        """
        raise NotImplementedError(
            "The SandboxEnvironment provider has not implemented config_deserialize."
        )


@dataclass
class SandboxEnvironments:
    """Collection of sandbox environments used for an evaluation."""

    environments: dict[str, SandboxEnvironment]
    """Sandbox environments by name."""

    cleanup: Callable[[bool], Awaitable[None]] | None = field(default=None)
    """Optional global cleanup function.

    Called with a boolean indicating whether the sample was cancelled.
    """


class SandboxEnvironmentSpec(BaseModel, frozen=True):
    """Specification of a SandboxEnvironment."""

    type: str
    """Sandbox type (e.g. 'local', 'docker')"""

    # Any is used to prevent Pydantic from trying to initialise a BaseModel.
    config: Annotated[Any, "BaseModel, str or None"] = None
    """Sandbox configuration (filename or config object)."""

    def __init__(self, type: str, config: BaseModel | str | None = None):
        super().__init__(type=type, config=config)

    @model_validator(mode="before")
    @classmethod
    def load_config_model(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        type = data["type"]
        config = data.get("config")
        # Pydantic won't know what concrete type to instantiate for config, so
        # ask the relevant sandbox environment to deserialize it.
        if isinstance(config, dict) and len(config) > 0:
            data["config"] = deserialize_sandbox_specific_config(type, config)
        return data


SandboxEnvironmentConfigType = BaseModel | str

SandboxEnvironmentType = str | tuple[str, str] | SandboxEnvironmentSpec
"""SandboxEnvironmentSpec and str and tuple shorthands for it.

A plain str, e.g. "docker", is equivalent to SandboxEnvironmentSpec("docker")
A tuple, e.g. ("docker", "compose.yaml"), is equivalent to SandboxEnvironmentSpec("docker", "compose.yaml")
"""


def resolve_sandbox_environment(
    sandbox: SandboxEnvironmentType | None,
) -> SandboxEnvironmentSpec | None:
    # do the resolution
    if isinstance(sandbox, str):
        return SandboxEnvironmentSpec(type=sandbox)
    elif isinstance(sandbox, SandboxEnvironmentSpec):
        return sandbox
    elif isinstance(sandbox, tuple):
        return SandboxEnvironmentSpec(sandbox[0], sandbox[1])
    else:
        return None


def deserialize_sandbox_specific_config(
    type: str, config: dict[str, Any]
) -> BaseModel | dict[str, Any]:
    # Avoid circular import
    from inspect_ai.util._sandbox.registry import registry_find_sandboxenv

    try:
        sandboxenv_type = registry_find_sandboxenv(type)
    except ValueError:
        warn_once(
            logger,
            f"Could not find sandbox environment plugin for type '{type}'. "
            "Ensure the plugin is installed in your environment.",
        )
        return config
    # If the provider is docker compatible and the config is a valid
    # ComposeConfig, deserialize it automatically so providers don't
    # need to handle this case in config_deserialize.
    is_docker_compatible_fn = cast(
        Callable[..., bool], getattr(sandboxenv_type, "is_docker_compatible")
    )
    if is_docker_compatible_fn():
        from pydantic import ValidationError

        from inspect_ai.util._sandbox.compose import ComposeConfig

        try:
            return ComposeConfig.model_validate(config)
        except ValidationError:
            pass

    config_deserialize = cast(
        ConfigDeserialize, getattr(sandboxenv_type, "config_deserialize")
    )
    return config_deserialize(config)
