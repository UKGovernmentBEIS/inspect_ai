import abc
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Union, overload

from inspect_ai.util import ExecResult


class ToolEnvironment(abc.ABC):
    """Environment for executing arbitrary code from tools.

    Tool environments provide both an execution environment as well as a per-sample
    filesystem context to copy samples files into and resolve relative paths to.
    """

    @classmethod
    async def startup(cls, task_name: str, config: str | None) -> None:
        """Called at task startup time to initialize resources required by enviroments.

        Args:
          task_name (str): Name of task using the tool environment.
          config (str): Implementation defined configuration file (optional).
        """
        pass

    @classmethod
    @abc.abstractmethod
    async def setup(
        cls, task_name: str, config: str | None, metadata: dict[str, str]
    ) -> "ToolEnvironments":
        """Setup tool environments.

        Args:
          task_name (str): Name of task using the tool environment.
          config (str): Implementation defined configuration file (optional).
          metadata (dict[str,str]): `metadata` field from Sample.

        Returns:
          ToolEnvironments with named environments and optional cleanup function.
        """
        ...

    @abc.abstractmethod
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        env: dict[str, str] = {},
        timeout: int | None = None,
    ) -> ExecResult[str]:
        """Execute a command within a tool environment.

        The current working directory for execution will be the per-sample
        filesystem context.

        Args:
          cmd (str | list[str]): Command or command and arguments to execute.
          input (str | bytes | None): Standard input (optional).
          env (dict[str,str]): Environment variables for execution.
          timeout (int | None): Optional execution timeout (seconds).

        Returns:
          Execution result (status code, stderr/stdout, etc.)
        """
        ...

    @abc.abstractmethod
    async def write_file(self, file: str, contents: str | bytes) -> None:
        """Write a file into the tool environment.

        Args:
          file (str): Path to file (relative file paths will resolve to the
            per-sample working directory).
          contents (str | bytes): Text or binary file contents.
        """
        ...

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    @abc.abstractmethod
    async def read_file(self, file: str, text: bool = True) -> Union[str | bytes]:
        """Read a file into the tool environment.

        Args:
          file (str): Path to file (relative file paths will resolve to the
            per-sample working directory).
          text (bool): Read as a utf-8 encoded text file.

        Returns:
          Contents of file (as str or bytes for binary files)
        """
        ...


@dataclass
class ToolEnvironments:
    """Collection of tool environments used for an evaluation."""

    environments: dict[str, ToolEnvironment]
    """Tool environments by name."""

    cleanup: Callable[[], Awaitable[None]] | None = field(default=None)
    """Optional global cleanup function."""


ToolEnvironmentSpec = str | tuple[str, str | None]
"""Specification of a ToolEnvironment (type or tuple with type and config file)."""
