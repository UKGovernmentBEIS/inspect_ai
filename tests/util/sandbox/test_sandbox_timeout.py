from typing import Union

import pytest

from inspect_ai.util import ExecResult
from inspect_ai.util._sandbox import SandboxTimeoutError
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.events import SandboxEnvironmentProxy


class TimeoutSandbox(SandboxEnvironment):
    """Mock sandbox that raises TimeoutError from all operations."""

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
        raise TimeoutError("exec timed out")

    async def write_file(self, file: str, contents: str | bytes) -> None:
        raise TimeoutError("write timed out")

    async def read_file(  # type: ignore[override]
        self, file: str, text: bool = True
    ) -> Union[str, bytes]:
        raise TimeoutError("read timed out")

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: object,
        environments: dict[str, "SandboxEnvironment"],
        interrupted: bool,
    ) -> None:
        pass


def test_sandbox_timeout_is_timeout_subclass() -> None:
    assert issubclass(SandboxTimeoutError, TimeoutError)


async def test_exec_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.exec(["cmd"])


async def test_write_file_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.write_file("test.txt", "content")


async def test_read_file_timeout_converted() -> None:
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(SandboxTimeoutError):
        await proxy.read_file("test.txt")


async def test_sandbox_timeout_caught_by_timeout_error() -> None:
    """SandboxTimeoutError should be catchable as TimeoutError."""
    proxy = SandboxEnvironmentProxy(TimeoutSandbox())
    with pytest.raises(TimeoutError):
        await proxy.exec(["cmd"])
