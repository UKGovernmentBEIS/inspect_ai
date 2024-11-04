import abc
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, NamedTuple, Union, overload

from .._subprocess import ExecResult

TaskInit = Callable[[str, str | None], Awaitable[None]]
TaskCleanup = Callable[[str, str | None, bool], Awaitable[None]]

SampleInit = Callable[
    [str, str | None, dict[str, str]], Awaitable[dict[str, "SandboxEnvironment"]]
]
SampleCleanup = Callable[
    [str, str | None, dict[str, "SandboxEnvironment"], bool], Awaitable[None]
]


class SandboxEnvironment(abc.ABC):
    """Environment for executing arbitrary code from tools.

    Sandbox environments provide both an execution environment as well as a per-sample
    filesystem context to copy samples files into and resolve relative paths to.
    """

    @classmethod
    def config_files(cls) -> list[str]:
        """Standard config files for this provider (used for automatic discovery)"""
        return []

    @classmethod
    async def task_init(cls, task_name: str, config: str | None) -> None:
        """Called at task startup initialize resources.

        Args:
          task_name (str): Name of task using the sandbox environment.
          config (str): Implementation defined configuration file (optional).
        """
        pass

    @classmethod
    async def sample_init(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> dict[str, "SandboxEnvironment"]:
        """Initialize sandbox environments for a sample.

        Args:
          task_name (str): Name of task using the sandbox environment.
          config (str): Implementation defined configuration file (optional).
          metadata (dict[str,str]): Sample `metadata` field

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
        config: str | None,
        environments: dict[str, "SandboxEnvironment"],
        interrupted: bool,
    ) -> None:
        """Cleanup sandbox environments.

        Args:
          task_name (str): Name of task using the sandbox environment.
          config (str): Implementation defined configuration file (optional).
          environments (dict[str,SandboxEnvironment]): Sandbox environments created for this sample.
          interrupted (bool): Was the task interrupted by an error or cancellation
        """
        ...

    @classmethod
    async def task_cleanup(
        cls, task_name: str, config: str | None, cleanup: bool
    ) -> None:
        """Called at task exit as a last chance to cleanup resources.

        Args:
          task_name (str): Name of task using the sandbox environment.
          config (str): Implementation defined configuration file (optional).
          cleanup (bool): Whether to actually cleanup environment resources
            (False if `--no-sandbox-cleanup` was specified)
        """
        pass

    @classmethod
    async def cli_cleanup(cls, id: str | None) -> None:
        """Handle a cleanup invoked from the CLI (e.g. inspect sandbox cleanup).

        Args:
          id (str | None): Optional ID to limit scope of cleanup.
        """
        pass

    @abc.abstractmethod
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
    ) -> ExecResult[str]:
        """Execute a command within a sandbox environment.

        The current working directory for execution will be the per-sample
        filesystem context.

        Each output stream (stdout and stderr) is limited to 1 MiB. If exceeded, an
        `OutputLimitExceededError` will be raised.

        Args:
          cmd (str | list[str]): Command or command and arguments to execute.
          input (str | bytes | None): Standard input (optional).
          cwd (str | None): Current working dir (optional). If relative, will be relative to the per-sample filesystem context.
          env (dict[str,str]): Environment variables for execution.
          user (str | None): Optional username or UID to run the command as.
          timeout (int | None): Optional execution timeout (seconds).

        Returns:
          Execution result (status code, stderr/stdout, etc.)

        Raises:
          TimeoutError: If the specified `timeout` expires.
          UnicodeDecodeError: If an error occurs while
            decoding the command output.
          PermissionError: If the user does not have
            permission to execute the command.
          OutputLimitExceededError: If an output stream
            exceeds the 1 MiB limit.
        """
        ...

    @abc.abstractmethod
    async def write_file(self, file: str, contents: str | bytes) -> None:
        """Write a file into the sandbox environment.

        If the parent directories of the file path do not exist they
        should be automatically created.

        Args:
          file (str): Path to file (relative file paths will resolve to the
            per-sample working directory).
          contents (str | bytes): Text or binary file contents.

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

        Args:
          file (str): Path to file (relative file paths will resolve to the
            per-sample working directory).
          text (bool): Read as a utf-8 encoded text file.

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


@dataclass
class SandboxEnvironments:
    """Collection of sandbox environments used for an evaluation."""

    environments: dict[str, SandboxEnvironment]
    """Sandbox environments by name."""

    cleanup: Callable[[bool], Awaitable[None]] | None = field(default=None)
    """Optional global cleanup function.

    Called with a boolean indicating whether the sample was cancelled.
    """


class SandboxEnvironmentSpec(NamedTuple):
    """Specification of a SandboxEnvironment."""

    type: str
    config: str | None = None


SandboxEnvironmentType = SandboxEnvironmentSpec | str | tuple[str, str]
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
