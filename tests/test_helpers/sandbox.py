"""Fake ``SandboxEnvironment`` for tests that script ``exec`` results."""

from pathlib import PurePosixPath
from typing import Callable, Literal, NamedTuple, overload

from inspect_ai.util._sandbox._framework_directory import _SCRIPT, _SHELL
from inspect_ai.util._sandbox.environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfigType,
)
from inspect_ai.util._subprocess import ExecResult

ExecPolicy = Callable[[list[str], str | None], ExecResult[str]]
"""Decides the result of an ``exec`` from its argv and ``user``."""


class CannedSandbox(SandboxEnvironment):
    """Sandbox whose ``exec`` results are decided by a per-test policy.

    Every ``exec`` is recorded as ``(cmd, user)`` in ``exec_calls``, its stdin in
    ``inputs`` and its ``concurrency`` flag in ``concurrency`` (same order).
    ``write_file`` records the path in ``written`` and stores nothing; ``read_file``
    is not supported.
    """

    def __init__(self, policy: ExecPolicy) -> None:
        super().__init__()
        self.policy = policy
        self.exec_calls: list[tuple[list[str], str | None]] = []
        self.inputs: list[str | bytes | None] = []
        self.concurrency: list[bool] = []
        self.written: list[str] = []

    @classmethod
    def returning(cls, result: ExecResult[str]) -> "CannedSandbox":
        """A sandbox that returns ``result`` from every ``exec``."""
        return cls(lambda _cmd, _user: result)

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
        self.exec_calls.append((cmd, user))
        self.inputs.append(input)
        self.concurrency.append(concurrency)
        return self.policy(cmd, user)

    async def write_file(self, file: str, contents: str | bytes) -> None:
        self.written.append(file)

    @overload
    async def read_file(self, file: str, text: Literal[True] = True) -> str: ...

    @overload
    async def read_file(self, file: str, text: Literal[False]) -> bytes: ...

    async def read_file(self, file: str, text: bool = True) -> str | bytes:
        raise NotImplementedError

    @classmethod
    async def sample_cleanup(
        cls,
        task_name: str,
        config: SandboxEnvironmentConfigType | None,
        environments: dict[str, SandboxEnvironment],
        interrupted: bool,
    ) -> None:
        pass


class FrameworkDirectoryCall(NamedTuple):
    """A framework-directory helper invocation, decoded from its argv."""

    path: str
    expected_uid: str
    """Uid the script must run as ("" when unconstrained)."""
    create: bool
    repair: bool
    shared: bool
    cmd: tuple[str, ...]
    """The wrapped command (empty when only ensuring or verifying the directory)."""


def framework_directory_call(cmd: list[str]) -> FrameworkDirectoryCall | None:
    """Decode a framework-directory helper invocation; None for any other command."""
    if cmd[:3] != [_SHELL, "-c", _SCRIPT]:
        return None
    _, expected_uid, create, repair, shared, parent, leaf, *wrapped = cmd[3:]
    return FrameworkDirectoryCall(
        path=str(PurePosixPath(parent, leaf)),
        expected_uid=expected_uid,
        create=create == "1",
        repair=repair == "1",
        shared=shared == "1",
        cmd=tuple(wrapped),
    )
